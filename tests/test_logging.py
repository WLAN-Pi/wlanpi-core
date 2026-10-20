"""Tests for wlanpi_core.core.logging file handlers."""

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
