"""wpa_supplicant runtime state and teardown (#269, #273).

Core must only stop supplicants it started: the one named in its pidfile for
a (namespace, iface), checked against /proc to survive PID reuse. A host-wide
`pkill -f wpa_supplicant` would also kill NetworkManager's supplicant. Every
runtime file (pidfile, config, log, control socket) is keyed by
(namespace, iface), because /run and /tmp are shared by every namespace.
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
    assert root == run_dir / "wpa" / "@root" / "wlan1.pid"
    assert lab == run_dir / "wpa" / "lab_ns" / "wlan1.pid"


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


def test_start_records_pidfile_and_stops_previous(run_dir, procs):
    old = supplicant.pidfile_path("wlan1", "lab_ns")
    _write_pid(old, 100)
    procs.procs[100] = _core_argv("wlan1", old)

    with patch.object(supplicant, "ns_exec") as ns_exec:
        supplicant.start_or_restart_supplicant("wlan1", "lab_ns")

    assert procs.killed == [100]
    start = ns_exec.call_args_list[-1]
    argv = start.args[0]
    runtime = run_dir / "wpa" / "lab_ns"
    assert argv[argv.index("-P") + 1] == str(runtime / "wlan1.pid")
    assert argv[argv.index("-c") + 1] == str(runtime / "wlan1.conf")
    assert argv[argv.index("-f") + 1] == str(runtime / "wlan1.log")
    assert start.kwargs["namespace"] == "lab_ns"


# --- runtime state keyed by (namespace, iface) (#273) ---


def test_runtime_paths_do_not_collide_across_namespaces(run_dir):
    paths = {
        ns: (
            supplicant.config_path("wlan1", ns),
            supplicant.log_path("wlan1", ns),
            supplicant.ctrl_dir(ns),
        )
        for ns in (None, "ns_a", "ns_b")
    }
    flat = [str(p) for triple in paths.values() for p in triple]
    assert len(flat) == len(set(flat))
    assert supplicant.ctrl_dir(None) == "/run/wpa_supplicant"


def test_wpa_cli_uses_core_ctrl_dir_only_when_core_started_the_supplicant(run_dir):
    assert supplicant.wpa_cli_command("wlan1", "ns_a", "status") == [
        "wpa_cli",
        "-p",
        "/run/wpa_supplicant",
        "-i",
        "wlan1",
        "status",
    ]
    # Core's pidfile decides, even before the control socket exists.
    pidfile = supplicant.pidfile_path("wlan1", "ns_a")
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text("100\n")
    assert supplicant.wpa_cli_command("wlan1", "ns_a", "status")[1:3] == [
        "-p",
        supplicant.ctrl_dir("ns_a"),
    ]


def test_wpa_config_holds_one_network_and_is_private(tmp_path):
    from wlanpi_core.schemas.network.network import NetSecurity, RootConfig
    from wlanpi_core.wpa.config import write_wpa_config

    def cfg(ssid):
        return RootConfig(
            mode="managed",
            iface_display_name="wlan1",
            phy="phy1",
            interface="wlan1",
            security=NetSecurity(ssid=ssid, security="WPA2-PSK", psk="secret123"),
            default_route=False,
            autostart_app=None,
        )

    path = tmp_path / "wpa" / "wlan1.conf"
    write_wpa_config(cfg("OldNet"), path, {}, "/run/x/ctrl")
    write_wpa_config(cfg("NewNet"), path, {}, "/run/x/ctrl")

    text = path.read_text()
    assert text.count("network={") == 1
    assert "NewNet" in text and "OldNet" not in text
    assert "ctrl_interface=/run/x/ctrl" in text
    assert path.stat().st_mode & 0o777 == 0o600
