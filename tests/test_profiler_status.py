"""Tests for the profiler status service."""

import pytest

from wlanpi_core.profiler import service


@pytest.fixture(autouse=True)
def no_real_profiler_files(monkeypatch):
    """Keep tests off the real profiler runtime files."""
    monkeypatch.setattr(service, "profiler_beaconing_ssid", lambda: None)


def test_get_status_reads_passphrase_from_info_file(monkeypatch):
    monkeypatch.setattr(service, "profiler_beaconing", lambda: True)
    monkeypatch.setattr(service, "_profiler_info", lambda: {"passphrase": "s3cret"})

    assert service.get_status()["passphrase"] == "s3cret"


def test_get_status_omits_passphrase_when_not_running(monkeypatch):
    monkeypatch.setattr(service, "profiler_beaconing", lambda: False)
    monkeypatch.setattr(service, "_profiler_info", lambda: {"passphrase": "s3cret"})

    assert service.get_status()["passphrase"] is None


def test_get_status_returns_none_without_info_file(monkeypatch):
    monkeypatch.setattr(service, "profiler_beaconing", lambda: True)
    monkeypatch.setattr(service, "_profiler_info", lambda: {})

    assert service.get_status()["passphrase"] is None


def test_profiler_passphrase_ignores_non_string(monkeypatch):
    monkeypatch.setattr(service, "_profiler_info", lambda: {"passphrase": 123})

    assert service._profiler_passphrase() is None


def test_profiler_info_returns_empty_on_missing_file(monkeypatch):
    monkeypatch.setattr(service, "INFO_FILE", "/nonexistent/wlanpi-profiler.info.json")

    assert service._profiler_info() == {}


def test_profiler_info_returns_empty_on_bad_json(monkeypatch, tmp_path):
    bad = tmp_path / "info.json"
    bad.write_text("not json")
    monkeypatch.setattr(service, "INFO_FILE", str(bad))

    assert service._profiler_info() == {}
