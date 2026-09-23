"""Signs that another tool is using a wireless netdev (wlanpi_core.adapters.usage)."""

import os
from unittest.mock import patch

import pytest

from wlanpi_core.adapters import usage
from wlanpi_core.models.command_result import CommandResult


@pytest.fixture
def fake_proc(tmp_path, monkeypatch):
    """Build a /proc with pid 1 in the root netns and a named netns `ns_a`."""
    proc = tmp_path / "proc"
    netns_dir = tmp_path / "netns"
    netns_dir.mkdir()
    root_ns = tmp_path / "root-ns"
    root_ns.write_text("")
    (netns_dir / "ns_a").write_text("")
    monkeypatch.setattr(usage, "PROC", proc)
    monkeypatch.setattr(usage, "NETNS_RUN_DIR", str(netns_dir))
    monkeypatch.setattr(usage, "RUN_DIR", "/run/wlanpi-core")

    def add(pid: int, argv: list[str], netns: str | None = None, files=None):
        d = proc / str(pid)
        (d / "ns").mkdir(parents=True)
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        # Same inode as the netns it runs in, like /proc/<pid>/ns/net.
        os.link(root_ns if netns is None else netns_dir / netns, d / "ns" / "net")
        for path, text in (files or {}).items():
            target = d / "root" / path.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)

    add(1, ["/sbin/init"])
    return add


def test_foreign_supplicant_is_reported(fake_proc):
    fake_proc(40, ["wpa_supplicant", "-B", "-i", "wlan2", "-c", "/etc/x.conf"])
    assert usage.foreign_users("wlan2", None) == ["wpa_supplicant (pid 40)"]
    assert usage.foreign_users("wlan1", None) == []


def test_cores_own_supplicant_is_not_foreign(fake_proc):
    fake_proc(
        41,
        [
            "wpa_supplicant",
            "-B",
            "-iwlan2",
            "-P",
            "/run/wlanpi-core/wpa/@root/wlan2.pid",
        ],
    )
    assert usage.foreign_users("wlan2", None) == []


def test_hostapd_found_through_its_config(fake_proc):
    conf = "/tmp/profiler/hostapd.conf"
    fake_proc(
        42,
        ["hostapd", "-B", conf],
        files={conf: "ctrl_interface=/run/hostapd\ninterface=wlan2\nchannel=36\n"},
    )
    assert usage.foreign_users("wlan2", None) == ["hostapd (pid 42)"]


def test_same_name_in_another_netns_is_not_this_iface(fake_proc):
    fake_proc(43, ["wpa_supplicant", "-i", "wlan2"], netns="ns_a")
    assert usage.foreign_users("wlan2", None) == []
    assert usage.foreign_users("wlan2", "ns_a") == ["wpa_supplicant (pid 43)"]


def test_up_links_reads_the_admin_up_flag():
    out = (
        "1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536\n"
        "7: wlan2: <NO-CARRIER,BROADCAST,MULTICAST,UP> mtu 1500\n"
        "8: wlan2profiler: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 2304\n"
        "9: wlanpi2: <BROADCAST,MULTICAST> mtu 1500\n"
    )
    result = CommandResult(stdout=out, stderr="", return_code=0)
    with patch.object(usage, "ns_exec", return_value=result):
        assert usage.up_links(None) == {"lo", "wlan2", "wlan2profiler"}
