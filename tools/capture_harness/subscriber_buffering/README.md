# Capture subscriber buffering

How much buffering and send time a pcapng stream subscriber can absorb before
wlanpi-core evicts it with WebSocket close code 1013. These tools measure the
two knobs in `wlanpi_core/streaming/connection_manager.py`:

- `_SUBSCRIBER_QUEUE_BLOCKS`: per-subscriber pcapng block queue depth.
- `_SUBSCRIBER_SEND_TIMEOUT_SEC`: how long a single WebSocket send may stall.

The current budget is 1024 blocks and 5.0 s. The previous budget was 128 blocks
and 1.0 s.

## Mechanism

`_broadcast_chunk` frames dumpcap output into pcapng blocks and calls
`put_nowait` for each subscriber queue. The owner is awaited first, so a slow
subscriber never blocks the owner. A subscriber is evicted by one of two
paths:

1. Queue overflow. `put_nowait` raises `QueueFull`, the subscriber is dropped
   and the queue is drained and replaced with a 1013 close.
2. Send stall. A single `send_bytes` exceeds `_SUBSCRIBER_SEND_TIMEOUT_SEC`,
   which also closes 1013.

Both paths only trigger once the transport is backpressured. Kernel socket
buffers absorb short stalls, so a fast local link masks the difference until
the stall is long enough to fill those buffers too.

## Method A: deterministic (budget_test.py)

Drives `_broadcast_chunk` in-process at a fixed block rate with a subscriber
whose first send stalls for a controlled duration. Runs the same cases twice,
monkeypatching the constants to the old and new values. No device, no
WebSocket.

```bash
python tools/capture_harness/subscriber_buffering/budget_test.py
```

Effective feed rate was about 800 blocks/s (`asyncio.sleep` overhead, not the
nominal 2000). Results on a WLAN Pi running 2.1.20-1:

| case | stall | OLD (128, 1.0 s) | NEW (1024, 5.0 s) |
|------|-------|------------------|-------------------|
| 1 | 0.3 s | EVICT, 130 blocks | SURVIVE, 3023 blocks |
| 2 | 3.0 s | EVICT at 1.01 s (send timeout) | SURVIVE |
| 3 | 10 s | EVICT, 130 blocks | EVICT, 1026 blocks (about 8x) |
| 4 | 0.6 s | EVICT, 130 blocks | SURVIVE |

`owner_sent == fed` in every case: the owner never blocks under either build.

## Method B: device (run_on_device.py, slow_subscriber.py)

Starts a real owner capture with `capture_harness.py`, then a subscriber that
reads normally, stops reading for a set stall, and resumes. A small
`SO_RCVBUF` and `max_queue` on the client make the server block quickly.

```bash
python tools/capture_harness/subscriber_buffering/run_on_device.py \
    --url wss://wlanpi.local:31415/api/v1/streaming/capture \
    --ca-cert /etc/nginx/ssl/self-signed-wlanpi.cert \
    --token-file /tmp/token --config /tmp/ch6.json \
    --host wlanpi.local --build OLD --stalls 0 3 5 10
```

Use `capture_harness.py config` to build the owner config, and stop Kismet and
create the monitor vif first if the channel must hold (see the parent README).

### Channel rates measured

`dumpcap` on `wlanpi0`, bytes/s:

| channel | frequency | rate | packets/s |
|---------|-----------|------|-----------|
| 40 | 5200 MHz | about 1.9 to 2.0 MB/s | about 2800 |
| 48 | 5240 MHz | about 212 KB/s | about 140 |
| 6 | 2437 MHz | about 143 KB/s | about 450 |

At 1024 blocks that is about 0.37 s on channel 40 and about 2.3 s on channel 6.
The old 128 blocks was about 46 ms on channel 40 and about 0.28 s on channel 6.

### Results

10 s stall, four trials per build, channel 6 (about 450 blocks/s):

| build | result |
|-------|--------|
| OLD (128, 1.0 s) | 4 of 4 EVICT (1013) |
| NEW (1024, 5.0 s) | 4 of 4 SURVIVE |

NEW also survived 12 s and 15 s stalls. OLD was noisy at 7 s (one evict, one
survive) and 9 s (survive), as expected on a shared RF channel.

## Conclusion

The larger queue and timeout measurably extend how long a stalled subscriber
survives before eviction (NEW survived 15 s, OLD reliably failed at 10 s). The
change is owner-neutral and still evicts a permanently stalled subscriber.

Caveats:

- Short stalls survive under both budgets because socket buffers absorb them.
  The difference appears under sustained backpressure.
- One gunicorn worker serves the whole API, so the real ceiling on a busy
  channel is the single event loop, not the queue size. On channel 40 a Python
  subscriber could not keep up at all and would be evicted under either budget.
- Worst case memory per stalled subscriber is `_SUBSCRIBER_QUEUE_BLOCKS` times
  the block size, about 1.5 MB at 1024 blocks, which is why concurrent
  subscribers per session are capped.
