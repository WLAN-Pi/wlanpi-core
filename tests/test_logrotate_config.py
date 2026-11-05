from pathlib import Path


def test_logrotate_covers_root_logs_but_not_debug_tmpfs() -> None:
    config = Path("debian/wlanpi-core.logrotate").read_text()

    assert config.startswith("/var/log/wlanpi_core/*.log {")
    assert "debug" not in config
    assert "copytruncate" in config
    assert "size 10M" in config
