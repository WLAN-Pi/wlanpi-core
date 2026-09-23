"""DHCP via dhcpcd and default routes (#279, #261).

Trixie ships dhcpcd, not dhclient. dhcpcd keeps its pidfile, control socket
and leases under fixed paths that every netns shares, so Core runs each one
in a private mount namespace. A missing DHCP server or gateway must never
produce a gatewayless default route.
"""

from __future__ import annotations

import signal
from unittest.mock import patch

import pytest

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.utils import network_management as nm


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(nm, "RUN_DIR", str(tmp_path))
    return tmp_path


def _started_argv(ns_exec) -> list[str]:
    return ns_exec.call_args_list[-1].args[0]


def test_dhcpcd_runs_isolated_without_link_local(run_dir):
    with patch.object(nm, "ns_exec") as ns_exec:
        nm.restart_dhcp_with_timeout("sta0", "ns_a", timeout=20)
    argv = _started_argv(ns_exec)
    state = run_dir / "dhcpcd" / "ns_a" / "sta0"
    assert argv[:4] == ["unshare", "--mount", "--propagation", "private"]
    assert argv[argv.index("dhcpcd-wlanpi") + 1 : argv.index("dhcpcd-wlanpi") + 3] == [
        str(state / "run"),
        str(state / "lib"),
    ]
    assert "-L" in argv and argv[argv.index("-t") + 1] == "20"
    assert argv[-1] == "sta0"
    assert ns_exec.call_args_list[-1].kwargs["namespace"] == "ns_a"
    assert (state / "run").is_dir() and (state / "lib").is_dir()


def test_dhcpcd_default_route_only_when_asked(run_dir):
    with patch.object(nm, "ns_exec") as ns_exec:
        nm.restart_dhcp_with_timeout("wlan0", None)
        without = _started_argv(ns_exec)
        nm.restart_dhcp_with_timeout("wlan0", None, default_route=True)
        with_route = _started_argv(ns_exec)
    assert "-G" in without and "-m" not in without
    assert "-G" not in with_route
    assert with_route[with_route.index("-m") + 1] == "200"


def test_dhcpcd_hooks_never_touch_hostname_or_root_dns(run_dir):
    with patch.object(nm, "ns_exec") as ns_exec:
        nm.restart_dhcp_with_timeout("wlan0", None)
        root = _started_argv(ns_exec)
        nm.restart_dhcp_with_timeout("sta0", "ns_a")
        namespaced = _started_argv(ns_exec)

    def disabled(argv):
        return {argv[i + 1] for i, arg in enumerate(argv) if arg == "-C"}

    assert disabled(root) == {"hostname", "timesyncd", "resolv.conf"}
    # In a namespace resolv.conf goes to /etc/netns/<ns>/resolv.conf.
    assert disabled(namespaced) == {"hostname", "timesyncd"}


class _Procs:
    def __init__(self, procs):
        self.procs = dict(procs)
        self.signals: list[tuple[int, int]] = []

    def cmdline(self, pid):
        return self.procs.get(pid, [])

    def kill(self, pid, sig):
        if pid not in self.procs:
            raise ProcessLookupError(pid)
        self.signals.append((pid, sig))
        del self.procs[pid]


def _pidfile(run_dir, ns, iface, pid):
    path = run_dir / "dhcpcd" / (ns or "@root") / iface / "run" / f"{iface}-4.pid"
    path.parent.mkdir(parents=True)
    path.write_text(f"{pid}\n")


def test_stop_dhcp_releases_only_its_own_dhcpcd(run_dir):
    procs = _Procs(
        {
            10: ["dhcpcd: sta0 [ip4]"],
            11: ["dhcpcd: sta0 [ip4]"],  # same iface name, other namespace
            12: ["/usr/bin/python3", "x"],
        }
    )
    _pidfile(run_dir, "ns_a", "sta0", 10)
    _pidfile(run_dir, "ns_b", "sta0", 11)
    _pidfile(run_dir, "ns_c", "sta0", 12)  # PID reused by something else
    with patch.object(nm, "_read_cmdline", side_effect=procs.cmdline):
        with patch.object(nm.os, "kill", side_effect=procs.kill):
            nm.stop_dhcp("sta0", "ns_a")
            nm.stop_dhcp("sta0", "ns_c")
    assert procs.signals == [(10, signal.SIGHUP)]


def test_stop_namespace_dhcp_covers_every_iface(run_dir):
    procs = _Procs(
        {1: ["dhcpcd: a [ip4]"], 2: ["dhcpcd: b [ip4]"], 3: ["dhcpcd: a [ip4]"]}
    )
    _pidfile(run_dir, "ns_a", "a", 1)
    _pidfile(run_dir, "ns_a", "b", 2)
    _pidfile(run_dir, "ns_b", "a", 3)
    with patch.object(nm, "_read_cmdline", side_effect=procs.cmdline):
        with patch.object(nm.os, "kill", side_effect=procs.kill):
            nm.stop_namespace_dhcp("ns_a")
    assert sorted(pid for pid, _sig in procs.signals) == [1, 2]


def _route_ns_exec(show_output: str):
    calls: list[list[str]] = []

    def fake(cmd, namespace=None, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["ip", "-4", "route"]:
            return CommandResult(stdout=show_output, stderr="", return_code=0)
        return CommandResult(stdout="", stderr="", return_code=0)

    return fake, calls


def test_default_route_never_gatewayless():
    fake, calls = _route_ns_exec("")
    with patch.object(nm, "ns_exec", side_effect=fake):
        nm.set_default_route("wlan0", None)
    assert not [c for c in calls if "replace" in c]


def test_default_route_goes_via_the_dhcp_router():
    fake, calls = _route_ns_exec(
        "default via 10.10.0.254 proto dhcp src 10.10.0.80 metric 3002\n"
    )
    with patch.object(nm, "ns_exec", side_effect=fake):
        nm.set_default_route("sta0", "ns_a")
    assert calls[-1] == [
        "ip",
        "route",
        "replace",
        "default",
        "via",
        "10.10.0.254",
        "dev",
        "sta0",
        "metric",
        "200",
    ]
