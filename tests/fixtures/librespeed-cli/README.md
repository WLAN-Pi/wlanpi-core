# LibreSpeed CLI fixtures

These files capture the output contract consumed by `wlanpi_core.utils.speedtest`.
Values vary by run; tests verify parsing rather than network performance.

## v1.0.10 Linux arm64

- Command: `/usr/bin/librespeed-cli --json --simple`
- Package: `wlanpi-librespeed-cli 1.0.2`
- Upstream: `librespeed/speedtest-cli` tag `v1.0.10`
- Binary SHA-256: `20be1ce7ead094f2b8f4e316b5407f5aa508486d53e5b0d879d47b8d9d58943d`
- Captured on: WLAN Pi M4+ `192.168.6.63`, 2026-09-22
- Streams were captured separately. JSON is stdout; human-readable results are stderr.
- The empty `client.ip` is the real response returned by the selected backend.

## v1.0.14 Linux arm64

- Command: `/usr/bin/librespeed-cli --json --simple`
- Package candidate: `wlanpi-librespeed-cli 1.0.14-1wlanpi1`
- Upstream: `librespeed/speedtest-cli` tag `v1.0.14`
- Binary SHA-256: `cf1959caaf18ef1fe4c92421f733797ad41682db12d1d77e6be1eee6357833b4`
- Captured on: WLAN Pi M4+ `192.168.6.63`, 2026-09-22
- Unlike v1.0.10, the human-readable lines and JSON are all on stdout;
  stderr is empty. The parser scans for the final JSON array to support both.
- The empty `client.ip` is the real response returned by the selected backend.
