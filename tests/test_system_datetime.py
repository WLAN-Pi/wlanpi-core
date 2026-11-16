import os
import time

import pytest

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.services import system_service

OLD_STAMP_MTIME = 1_000_000_000


class _Result:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


@pytest.fixture
def settime_calls(monkeypatch, tmp_path):
    stamp = tmp_path / "clock"
    stamp.touch()
    os.utime(stamp, (OLD_STAMP_MTIME, OLD_STAMP_MTIME))
    calls: list[tuple[int, int]] = []

    def _settime(clock_id, target_ns):
        calls.append((clock_id, target_ns))

    monkeypatch.setattr(system_service, "TIMESYNC_CLOCK_FILE", stamp)
    monkeypatch.setattr(system_service.time, "clock_settime_ns", _settime)
    return calls


def _ntp(monkeypatch, synchronized: str) -> None:
    def _run(cmd, **_kwargs):
        assert cmd == ["timedatectl", "show", "-p", "NTPSynchronized", "--value"]
        return _Result(f"{synchronized}\n")

    monkeypatch.setattr(system_service, "run_command", _run)


def _push_client_time(
    ahead_ms: int, allow_backward: bool = False, received_ms_ago: int = 0
):
    epoch_ms = time.time_ns() // 1_000_000 + ahead_ms - received_ms_ago
    received_ns = time.monotonic_ns() - received_ms_ago * 1_000_000
    return epoch_ms, system_service.set_datetime(epoch_ms, allow_backward, received_ns)


@pytest.mark.parametrize(
    "synchronized,ahead_ms,allow_backward,outcome,steps",
    [
        ("no", 5000, False, "stepped", True),
        ("no", -5000, False, "backward_not_allowed", False),
        ("no", -5000, True, "stepped", True),
        ("no", 50, False, "within_tolerance", False),
        ("no", -50, True, "within_tolerance", False),
        ("yes", 5000, False, "ntp_synchronized", False),
        ("yes", -5000, True, "ntp_synchronized", False),
    ],
)
def test_set_datetime_decision(
    monkeypatch, settime_calls, synchronized, ahead_ms, allow_backward, outcome, steps
):
    _ntp(monkeypatch, synchronized)

    _epoch_ms, result = _push_client_time(ahead_ms, allow_backward)

    assert result["outcome"] == outcome
    assert ahead_ms - 20 <= result["offset_ms"] <= ahead_ms + 20
    assert bool(settime_calls) is steps


def test_set_datetime_steps_to_client_time_and_saves_stamp(monkeypatch, settime_calls):
    _ntp(monkeypatch, "no")

    epoch_ms, result = _push_client_time(5000)

    assert result["outcome"] == "stepped"
    [(clock_id, target_ns)] = settime_calls
    assert clock_id == time.CLOCK_REALTIME
    assert 0 <= target_ns - epoch_ms * 1_000_000 < 1_000_000_000
    assert system_service.TIMESYNC_CLOCK_FILE.stat().st_mtime > OLD_STAMP_MTIME


def test_set_datetime_adds_handling_time(monkeypatch, settime_calls):
    _ntp(monkeypatch, "no")

    _epoch_ms, result = _push_client_time(0, received_ms_ago=2000)

    assert result["outcome"] == "within_tolerance"
    assert not settime_calls


def test_set_datetime_steps_when_stamp_is_missing(monkeypatch, settime_calls):
    _ntp(monkeypatch, "no")
    system_service.TIMESYNC_CLOCK_FILE.unlink()

    _epoch_ms, result = _push_client_time(5000)

    assert result["outcome"] == "stepped"
    assert len(settime_calls) == 1


def test_set_datetime_leaves_clock_alone_when_ntp_state_is_unknown(
    monkeypatch, settime_calls
):
    def _run(cmd, **_kwargs):
        raise RunCommandError("Failed to query server", 1)

    monkeypatch.setattr(system_service, "run_command", _run)

    with pytest.raises(RunCommandError):
        _push_client_time(5000)

    assert not settime_calls
