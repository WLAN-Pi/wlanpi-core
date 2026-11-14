import json
import logging

import pytest

from wlanpi_core.core import logging as core_logging

DEBUG_TMPFS_BYTES = 25 * 1024 * 1024


@pytest.fixture
def restore_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)


def test_debug_log_budget_fits_tmpfs():
    total = core_logging.DEBUG_LOG_MAX_BYTES * (core_logging.DEBUG_LOG_BACKUP_COUNT + 1)
    assert total + core_logging.DEBUG_LOG_MAX_BYTES <= DEBUG_TMPFS_BYTES


def test_debug_log_rotates_and_keeps_writing(
    tmp_path, monkeypatch, restore_root_logger
):
    monkeypatch.setattr(core_logging, "LOG_DIR", tmp_path)
    monkeypatch.setattr(core_logging, "DEBUG_LOG_MAX_BYTES", 2000)
    core_logging.configure_logging()
    log = logging.getLogger("wlanpi_core.test")

    for i in range(200):
        log.debug("filler %d %s", i, "x" * 100)
    log.debug("last record")

    debug_dir = tmp_path / "debug"
    files = sorted(p.name for p in debug_dir.iterdir())
    assert files == [
        "debug.log",
        *(f"debug.log.{n}" for n in range(1, core_logging.DEBUG_LOG_BACKUP_COUNT + 1)),
    ]
    assert "last record" in (debug_dir / "debug.log").read_text()
    for path in debug_dir.iterdir():
        assert path.stat().st_size <= 2000
    assert "filler" not in (tmp_path / "app.log").read_text()


def test_json_record_carries_the_call_site_line_and_no_source_fields():
    record = logging.LogRecord(
        "wlanpi_core.test", logging.INFO, "/x/mod.py", 42, "hello", None, None, "fn"
    )

    data = json.loads(core_logging.JsonFormatter().format(record))

    assert data["line"] == "42"
    assert data["function"] == "fn"
    assert "source_file" not in data
    assert "source_function" not in data
