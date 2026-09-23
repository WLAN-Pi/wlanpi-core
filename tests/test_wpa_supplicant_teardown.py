"""Pidfile-based wpa_supplicant teardown (#269).

Core must only stop supplicants it started: the one named in its pidfile for
a (namespace, iface), checked against /proc to survive PID reuse. A host-wide
`pkill -f wpa_supplicant` would also kill NetworkManager's supplicant.
"""

from __future__ import annotations

import signal
from pathlib import Path
from unittest.mock import patch

import pytest

from wlanpi_core.wpa import supplicant


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(supplicant, "RUN_DIR", str(tmp_path))
    return tmp_path


class FakeProcs:
    """A /proc and os.kill stand-in; killed PIDs disappear."""

    def __init__(self, procs: dict[int, list[str]]):
        self.procs = dict(procs)
        self.killed: list[int] = []

    def cmdline(self, pid: int) -> list[str]:
        return self.procs.get(pid, [])

    def kill(self, pid: int, sig: int) -> None:
        assert sig == signal.SIGTERM
        if pid not in self.procs:
            raise ProcessLookupError(pid)
        self.killed.append(pid)
        del self.procs[pid]


@pytest.fixture
def procs():
    fake = FakeProcs({})
    with patch.object(supplicant, "_read_cmdline", side_effect=fake.cmdline):
        with patch.object(supplicant.os, "kill", side_effect=fake.kill):
            yield fake


def _core_argv(iface: str, pidfile: Path | None = None) -> list[str]:
    argv = [
        "wpa_supplicant",
        "-B",
        "-i",
        iface,
        "-c",
        f"/etc/wpa_supplicant/{iface}.conf",
    ]
    argv += ["-D", "nl80211", "-f", f"/tmp/wpa-{iface}.log", "-t"]
    if pidfile is not None:
        argv += ["-P", str(pidfile)]
    return argv


def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n")


def test_pidfile_is_keyed_by_namespace_and_iface(run_dir):
    root = supplicant.pidfile_path("wlan1", None)
    lab = supplicant.pidfile_path("wlan1", "lab_ns")
    assert root == run_dir / "wpa_supplicant" / "@root" / "wlan1.pid"
    assert lab == run_dir / "wpa_supplicant" / "lab_ns" / "wlan1.pid"


def test_stop_supplicant_kills_only_its_pid(run_dir, procs):
    mine = supplicant.pidfile_path("wlan1", "lab_ns")
    _write_pid(mine, 100)
    procs.procs[100] = _core_argv("wlan1", mine)
    procs.procs[200] = _core_argv("wlan1")  # same iface, other netns, no pidfile
    procs.procs[300] = [
        "/usr/sbin/wpa_supplicant",
        "-u",
        "-s",
        "-O",
        "/run/wpa_supplicant",
    ]

    supplicant.stop_supplicant("wlan1", "lab_ns")

    assert procs.killed == [100]
    assert not mine.exists()


def test_stop_supplicant_ignores_reused_pid(run_dir, procs):
    path = supplicant.pidfile_path("wlan1", None)
    _write_pid(path, 100)
    procs.procs[100] = ["/usr/bin/python3", "something_else"]

    supplicant.stop_supplicant("wlan1", None)

    assert procs.killed == []
    assert not path.exists()


def test_stop_supplicant_does_not_match_iface_prefix(run_dir, procs):
    path = supplicant.pidfile_path("wlan1", None)
    _write_pid(path, 100)
    procs.procs[100] = _core_argv("wlan10")

    supplicant.stop_supplicant("wlan1", None)

    assert procs.killed == []


def test_stop_supplicant_without_pidfile_is_a_no_op(run_dir, procs):
    procs.procs[100] = _core_argv("wlan1")
    supplicant.stop_supplicant("wlan1", None)
    assert procs.killed == []


def test_stop_namespace_supplicants_leaves_other_namespaces(run_dir, procs):
    for pid, (iface, ns) in {
        1: ("wlan1", "a"),
        2: ("wlan2", "a"),
        3: ("wlan1", "b"),
    }.items():
        path = supplicant.pidfile_path(iface, ns)
        _write_pid(path, pid)
        procs.procs[pid] = _core_argv(iface, path)

    supplicant.stop_namespace_supplicants("a")

    assert sorted(procs.killed) == [1, 2]
    assert supplicant.pidfile_path("wlan1", "b").exists()


def test_kill_all_stops_core_supplicants_only(run_dir, procs):
    path = supplicant.pidfile_path("wlan0", None)
    _write_pid(path, 10)
    procs.procs[10] = _core_argv("wlan0", path)
    procs.procs[11] = _core_argv("wlan2")  # legacy Core supplicant: no pidfile
    procs.procs[12] = [
        "/usr/sbin/wpa_supplicant",
        "-u",
        "-s",
        "-O",
        "/run/wpa_supplicant",
    ]
    procs.procs[13] = ["wpa_supplicant", "-B", "-i", "wlan3", "-c", "/etc/x.conf"]

    with patch.object(supplicant, "_proc_pids", return_value=list(procs.procs)):
        supplicant.kill_all_supplicants()

    assert sorted(procs.killed) == [10, 11]
    assert sorted(procs.procs) == [12, 13]


def test_start_records_pidfile_and_stops_previous(run_dir, procs, tmp_path):
    old = supplicant.pidfile_path("wlan1", "lab_ns")
    _write_pid(old, 100)
    procs.procs[100] = _core_argv("wlan1", old)

    with patch.object(supplicant, "ns_exec") as ns_exec:
        supplicant.start_or_restart_supplicant(
            "wlan1", "lab_ns", tmp_path / "wlan1.conf"
        )

    assert procs.killed == [100]
    start = ns_exec.call_args_list[-1]
    argv = start.args[0]
    assert argv[argv.index("-P") + 1] == str(old)
    assert start.kwargs["namespace"] == "lab_ns"
    assert old.parent.is_dir()
