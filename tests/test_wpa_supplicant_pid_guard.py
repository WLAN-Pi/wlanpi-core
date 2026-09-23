"""Supplicant stop guards from the review of #283.

Same-named supplicants in two namespaces are normal, so a stale pidfile must
only ever stop the supplicant Core started with that pidfile, and a
supplicant that ignores SIGTERM must not get a second one started beside it.
"""

from __future__ import annotations

import signal
from pathlib import Path
from unittest.mock import patch

import pytest

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.wpa import supplicant


class _Clock:
    """Stand-in for the module's `time`: sleep returns at once (AGENTS.md rule 7)."""

    @staticmethod
    def sleep(_seconds: float) -> None:
        return None


class _Procs:
    def __init__(self, procs, stubborn=()):
        self.procs = dict(procs)
        self.stubborn = set(stubborn)  # ignore SIGTERM
        self.signals: list[tuple[int, int]] = []

    def cmdline(self, pid):
        return self.procs.get(pid, [])

    def kill(self, pid, sig):
        if pid not in self.procs:
            raise ProcessLookupError(pid)
        self.signals.append((pid, sig))
        if sig == signal.SIGKILL or pid not in self.stubborn:
            del self.procs[pid]


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(supplicant, "RUN_DIR", str(tmp_path))
    return tmp_path


def _argv(iface: str, pidfile: Path) -> list[str]:
    return ["wpa_supplicant", "-B", "-i", iface, "-c", "x.conf", "-P", str(pidfile)]


def _patched(procs):
    return (
        patch.object(supplicant, "_read_cmdline", side_effect=procs.cmdline),
        patch.object(supplicant.os, "kill", side_effect=procs.kill),
        patch.object(supplicant, "time", _Clock),
    )


def test_stale_pidfile_does_not_stop_same_iface_in_another_namespace(run_dir):
    mine = supplicant.pidfile_path("wlan1", "ns_a")
    other = supplicant.pidfile_path("wlan1", "ns_b")
    mine.parent.mkdir(parents=True)
    # ns_a's supplicant died; its PID now belongs to ns_b's wlan1 supplicant.
    mine.write_text("100\n")
    procs = _Procs({100: _argv("wlan1", other)})
    a, b, c = _patched(procs)
    with a, b, c:
        assert supplicant.stop_supplicant("wlan1", "ns_a") is True
    assert procs.signals == []
    assert 100 in procs.procs


def test_supplicant_ignoring_sigterm_gets_sigkill(run_dir):
    path = supplicant.pidfile_path("wlan1", None)
    path.parent.mkdir(parents=True)
    path.write_text("100\n")
    procs = _Procs({100: _argv("wlan1", path)}, stubborn={100})
    a, b, c = _patched(procs)
    with a, b, c:
        assert supplicant.stop_supplicant("wlan1", None) is True
    assert procs.signals == [(100, signal.SIGTERM), (100, signal.SIGKILL)]
    assert not path.exists()


def test_restart_aborts_when_the_old_supplicant_survives(run_dir):
    path = supplicant.pidfile_path("wlan1", None)
    path.parent.mkdir(parents=True)
    path.write_text("100\n")
    procs = _Procs({100: _argv("wlan1", path)})
    unkillable = patch.object(supplicant.os, "kill")  # signals have no effect
    with (
        patch.object(supplicant, "_read_cmdline", side_effect=procs.cmdline),
        unkillable,
        patch.object(supplicant, "time", _Clock),
        patch.object(supplicant, "ns_exec") as ns_exec,
    ):
        with pytest.raises(RunCommandError):
            supplicant.start_or_restart_supplicant("wlan1", None, Path("/tmp/x.conf"))
    ns_exec.assert_not_called()
    assert path.exists()
