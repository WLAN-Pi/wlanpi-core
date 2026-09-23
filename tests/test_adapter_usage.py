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


def test_in_netns_matches_the_exact_namespace(fake_proc):
    fake_proc(50, ["dhcpcd: wlan1 [ip4]"], netns="ns_a")
    assert usage.in_netns(50, "ns_a") and not usage.in_netns(50, None)
    assert not usage.in_netns(1, "ns_a") and usage.in_netns(1, None)
    assert not usage.in_netns(99, None)  # gone
    assert not usage.in_netns(50, "ns_missing")


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


def test_capturing_links_reads_packet_sockets():
    # wlan2profiler (8) has sockets; ifindex 0 is "any interface", not a link.
    out = (
        "sk       RefCnt Type Proto  Iface R Rmem   User   Inode\n"
        "00000000 3      3    0003   8     1 0      0      1001\n"
        "00000000 3      3    0003   8     1 0      0      1002\n"
        "00000000 3      2    0003   0     1 0      0      1003\n"
        "00000000 3      3    888e   7     1 0      0      1004\n"
    )
    result = CommandResult(stdout=out, stderr="", return_code=0)
    with patch.object(usage, "ns_exec", return_value=result) as run:
        assert usage.capturing_links("ns_a") == {7, 8}
    assert run.call_args.kwargs["namespace"] == "ns_a"
