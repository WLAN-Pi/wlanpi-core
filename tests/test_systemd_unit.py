from pathlib import Path


def test_only_gunicorn_main_process_can_notify_systemd() -> None:
    unit = Path("debian/wlanpi-core.service").read_text()

    assert "Type=notify" in unit
    assert "NotifyAccess=main" in unit
    assert "NotifyAccess=all" not in unit
