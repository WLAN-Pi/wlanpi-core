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
