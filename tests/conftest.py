"""Shared fixtures for namespace matrix tests."""

from __future__ import annotations

import subprocess
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from wlanpi_core.adapters.discovery import LiveInterface
from wlanpi_core.connection.monitor import ConnectionMonitor
from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.services.network_namespace_service import NetworkNamespaceService

_REAL_CONNECTION_MONITOR_START = ConnectionMonitor.start_monitor


@pytest.fixture(scope="session", autouse=True)
def mock_wlanpi_group():
    """Prevent startup readiness failures when the wlanpi group is absent in CI."""
    mock_group = MagicMock()
    mock_group.gr_gid = 1000
    mock_group.gr_name = "wlanpi"

    with patch("grp.getgrnam", return_value=mock_group):
        yield


@pytest.fixture(autouse=True)
def mock_app_initialization(monkeypatch):
    """Bypass filesystem-dependent startup in CI and local pytest."""

    async def _mock_initialize_components(self):
        self.initialized = True
        return True

    monkeypatch.setattr(
        "wlanpi_core.app.InitializationManager.initialize_components",
        _mock_initialize_components,
    )
    monkeypatch.setattr(
        "wlanpi_core.services.system_service.get_mode",
        lambda: "classic",
    )


_DEFAULT_WPA_STATUS = {
    "wpa_status": {
        "wpa_state": "COMPLETED",
        "ssid": "test",
        "bssid": "00:11:22:33:44:55",
    },
    "ip_info": "",
    "connected_scan": {
        "ssid": "test",
        "bssid": "00:11:22:33:44:55",
        "key_mgmt": "open",
        "freq": 2412,
        "signal": 0,
        "minrate": 1000000,
    },
}


def _mock_namespace_run_command(cmd, raise_on_fail=True, **kwargs):
    """Avoid real sudo/ip netns/wpa_cli execution in CI and local pytest."""
    joined = " ".join(str(part) for part in cmd)
    if "wpa_cli" in joined and "status" in joined:
        stdout = "wpa_state=COMPLETED\nssid=test\nbssid=00:11:22:33:44:55\n"
    elif "wpa_cli" in joined and "scan_results" in joined:
        stdout = "bssid / frequency / signal level / flags / ssid\n"
    elif " iw " in f" {joined} " and " phy" in joined:
        stdout = "phy0\nphy1\n"
    else:
        stdout = ""
    return CommandResult(stdout=stdout, stderr="", return_code=0)


@pytest.fixture
def mock_namespace_execution():
    """Block all namespace command execution during tests."""
    patches = [
        patch(
            "wlanpi_core.utils.namespace_execution.run_command",
            side_effect=_mock_namespace_run_command,
        ),
        patch(
            "wlanpi_core.wpa.status.get_wpa_status",
            return_value=_DEFAULT_WPA_STATUS.copy(),
        ),
        patch.object(
            NetworkNamespaceService,
            "get_status",
            return_value=_DEFAULT_WPA_STATUS.copy(),
        ),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


@pytest.fixture(autouse=True)
def _isolate_namespace_execution(mock_namespace_execution):
    """Ensure matrix and service tests never invoke real netns commands."""
    yield mock_namespace_execution


@pytest.fixture(autouse=True)
def _clean_connection_monitors():
    from wlanpi_core.connection.monitor import stop_all_connection_monitors

    stop_all_connection_monitors()
    yield
    stop_all_connection_monitors()
    if ConnectionMonitor.start_monitor is not _REAL_CONNECTION_MONITOR_START:
        ConnectionMonitor.start_monitor = _REAL_CONNECTION_MONITOR_START


@pytest.fixture
def netcfg_env(tmp_path, monkeypatch):
    """Isolated config directory and current.txt for network_config module."""
    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir()
    ccf = tmp_path / "current.txt"
    ccf.write_text("default")

    monkeypatch.setattr("wlanpi_core.utils.network_config.cfg_dir", cfg_dir)
    monkeypatch.setattr("wlanpi_core.utils.network_config.ccf", ccf)

    service = NetworkNamespaceService(
        config_dir=tmp_path / "wpa",
        dhcp_dir=tmp_path / "dhcp",
    )
    service.config_dir.mkdir(parents=True, exist_ok=True)
    service.dhcp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("wlanpi_core.utils.network_config.ns", service)

    return {"cfg_dir": cfg_dir, "ccf": ccf, "service": service, "root": tmp_path}


@pytest.fixture
def namespace_service(netcfg_env):
    return netcfg_env["service"]


def _service_side_effect_patches() -> list[Any]:
    """Patches for the non-adapter side effects of activate/deactivate.

    WPA/DHCP config writes, supplicant control, apps, and the connection
    monitor. Adapter and namespace commands are left to the caller.
    """
    return [
        patch(
            "wlanpi_core.services.network_namespace_service.wpa_config.write_wpa_config",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.write_dhcp_config",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.wpa_supplicant.start_or_restart_supplicant",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.wpa_supplicant.kill_all_supplicants",
        ),
        patch.object(
            NetworkNamespaceService,
            "_monitor_connection_async",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.apps.start_app_in_namespace",
            return_value=True,
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.apps.stop_app_in_namespace",
        ),
    ]


@contextmanager
def hardware_success_mocks(interfaces=None, phy_move_side_effect=None):
    """Mock adapter/namespace stack so activate/deactivate paths succeed in CI."""
    interfaces = interfaces or ["wlan0", "wlan1"]

    def _move_phy(phy_name, namespace):
        if phy_move_side_effect is not None:
            # Production addresses live phys by index (`phy#N`); rows fault by name.
            result = phy_move_side_effect(phy_name.replace("phy#", "phy"), namespace)
            if result is RunCommandError or isinstance(result, Exception):
                raise result
            if result is False:
                raise RunCommandError("phy move failed", 1)
        return None

    def _find_interface(names):
        # Parity layout: wlanN lives on phyN in root.
        for name in names:
            if name in interfaces:
                index = interfaces.index(name)
                if name.removeprefix("wlan").isdigit():
                    index = int(name.removeprefix("wlan"))
                return LiveInterface(name, index, None, "managed")
        return None

    patches = [
        patch(
            "wlanpi_core.services.network_namespace_service.discovery.list_interfaces",
            return_value=interfaces,
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.discovery.find_interface",
            side_effect=_find_interface,
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.ns_namespace.namespace_exists",
            return_value=False,
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.ns_namespace.create_namespace",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.ns_namespace.list_namespaces",
            return_value=[],
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.ns_namespace.delete_namespace",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.interface.delete_interface",
            return_value=True,
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.interface.create_interface",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.interface.bring_interface_up",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.phy.list_phys",
            return_value=[],
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.phy.move_phy_to_namespace",
            side_effect=_move_phy,
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.phy.move_phy_to_root",
        ),
        *_service_side_effect_patches(),
    ]

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


# Every module that binds `run_command` at import and is reached by
# activate/deactivate/revert. The inventory fake replaces each of them.
_RUN_COMMAND_SITES = (
    "wlanpi_core.utils.network_config.run_command",
    "wlanpi_core.utils.namespace_execution.run_command",
    "wlanpi_core.adapters.discovery.run_command",
    "wlanpi_core.adapters.interface.run_command",
    "wlanpi_core.adapters.phy.run_command",
    "wlanpi_core.namespaces.namespace.run_command",
)

# Commands with no inventory effect that prepare/revert issue as cleanup.
_NOOP_COMMANDS = {"pkill", "rm", "dhclient"}


@dataclass
class Iface:
    """One live wireless netdev."""

    phy: str
    netns: str | None = None
    type: str = "managed"
    # Kernel ifindex: survives a netns move; newer netdevs get higher ones.
    ifindex: int = 0


@dataclass
class InventoryRecorder:
    """Stateful fake of `iw` and `ip netns` across namespaces.

    State is phys (name -> netns, MAC) and ifaces keyed by (netns, name).
    Deleting an iface removes it, `interface add` creates it on a visible phy,
    and a phy move takes its ifaces with it, as the kernel does. Mutations
    are recorded in order so rows can assert the exact sequence.

    Output order, error strings, and move semantics were checked against
    iw 6.17 on a WLAN Pi with three radios: dumps list phys highest index
    first and a phy's ifaces newest first; deleting a netns returns its phys
    to root; a travelling iface whose name is taken is renamed `wlan%d`.
    """

    phy_netns: dict[str, str | None]
    phy_mac: dict[str, str]
    ifaces: dict[tuple[str | None, str], Iface]
    netns: set[str]
    faults: dict[tuple[str | None, tuple[str, ...]], str] = field(default_factory=dict)
    deleted: list[tuple[str, str | None]] = field(default_factory=list)
    adds: list[tuple[str, str, str | None]] = field(default_factory=list)
    phy_moves: list[tuple[str, str | None]] = field(default_factory=list)
    commands: list[tuple[str | None, list[str]]] = field(default_factory=list)
    unrecognised: list[tuple[str | None, list[str]]] = field(default_factory=list)
    next_ifindex: int = 3

    @classmethod
    def from_adapters(
        cls,
        adapters: dict[str, dict[str, str]],
        faults: dict[tuple[str | None, tuple[str, ...]], str] | None = None,
    ) -> InventoryRecorder:
        phy_netns: dict[str, str | None] = {}
        phy_mac: dict[str, str] = {}
        ifaces: dict[tuple[str | None, str], Iface] = {}
        # Adapters are created in dict order, so later entries are newer.
        for ifindex, (name, meta) in enumerate(adapters.items(), start=3):
            netns = meta.get("netns")
            phy_netns[meta["phy"]] = netns
            phy_mac[meta["phy"]] = meta["mac"]
            ifaces[(netns, name)] = Iface(
                phy=meta["phy"],
                netns=netns,
                type=meta.get("type", "managed"),
                ifindex=ifindex,
            )
        netns_set = {ns for ns in phy_netns.values() if ns is not None}
        return cls(
            phy_netns=phy_netns,
            phy_mac=phy_mac,
            ifaces=ifaces,
            netns=netns_set,
            faults=dict(faults or {}),
            next_ifindex=3 + len(adapters),
        )

    # --- views for assertions ---

    def live(self) -> dict[str, tuple[str, str | None, str]]:
        """Return {iface: (phy, netns, type)} for every live netdev."""
        return {
            name: (meta.phy, netns, meta.type)
            for (netns, name), meta in sorted(
                self.ifaces.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])
            )
        }

    def added_phy(self, iface: str) -> str | None:
        matches = [phy for phy, name, _ns in self.adds if name == iface]
        return matches[-1] if matches else None

    def last_moved_phy(self) -> str | None:
        return self.phy_moves[-1][0] if self.phy_moves else None

    # --- fake command dispatch ---

    def run_command(
        self, cmd: list[str], raise_on_fail: bool = True, **kwargs: Any
    ) -> CommandResult:
        parts = [str(item) for item in cmd]
        if parts[:1] == ["sudo"]:
            parts = parts[1:]
        netns: str | None = None
        if parts[:3] == ["ip", "netns", "exec"] and len(parts) > 4:
            netns = parts[3]
            parts = parts[4:]
            if netns not in self.netns:
                return self._fail(
                    f'Cannot open network namespace "{netns}": '
                    "No such file or directory\n",
                    255,
                    raise_on_fail,
                )
        if parts[:1] == ["/sbin/iw"]:
            parts = ["iw", *parts[1:]]
        self.commands.append((netns, parts))

        fault = self.faults.get((netns, tuple(parts)))
        if fault is not None:
            return self._fail(fault, 1, raise_on_fail)

        if parts[:1] == ["iw"]:
            return self._iw(netns, parts[1:], raise_on_fail)
        if parts[:1] == ["ip"]:
            return self._ip(netns, parts[1:], raise_on_fail)
        if parts[:1] and parts[0] in _NOOP_COMMANDS:
            return self._ok()
        return self._unrecognised(netns, parts)

    def _ok(self, stdout: str = "") -> CommandResult:
        return CommandResult(stdout=stdout, stderr="", return_code=0)

    def _fail(self, stderr: str, code: int, raise_on_fail: bool) -> CommandResult:
        if raise_on_fail:
            raise RunCommandError(stderr, code)
        return CommandResult(stdout="", stderr=stderr, return_code=code)

    def _unrecognised(self, netns: str | None, parts: list[str]) -> CommandResult:
        # Recorded as well as raised: production code wraps many calls in a
        # blind `except Exception`, so the context manager re-checks on exit.
        self.unrecognised.append((netns, parts))
        raise AssertionError(f"inventory fake: unrecognised command {parts} in {netns}")

    def _visible_phys(self, netns: str | None) -> list[str]:
        # Highest index first, as `iw dev` and `iw phy` dump them.
        return sorted(
            (phy for phy, ns in self.phy_netns.items() if ns == netns),
            key=lambda name: int(name.removeprefix("phy")),
            reverse=True,
        )

    def _netns_ifaces(self, netns: str | None) -> list[tuple[str, Iface]]:
        return sorted(
            ((name, meta) for (ns, name), meta in self.ifaces.items() if ns == netns),
            key=lambda item: item[1].ifindex,
        )

    def _iw(
        self, netns: str | None, args: list[str], raise_on_fail: bool
    ) -> CommandResult:
        no_device = "command failed: No such device (-19)\n"
        if args == ["dev"]:
            return self._ok(self._iw_dev_dump(netns))
        if len(args) == 3 and args[0] == "dev":
            name, action = args[1], args[2]
            meta = self.ifaces.get((netns, name))
            if action == "info":
                if meta is None:
                    return self._fail(no_device, 237, raise_on_fail)
                return self._ok(self._iw_dev_info(name, meta))
            if action == "del":
                if meta is None:
                    return self._fail(no_device, 237, raise_on_fail)
                del self.ifaces[(netns, name)]
                self.deleted.append((name, netns))
                return self._ok()
        if args == ["phy"]:
            stdout = "".join(
                f"Wiphy {phy}\n\twiphy index: {phy.removeprefix('phy')}\n"
                for phy in self._visible_phys(netns)
            )
            return self._ok(stdout)

        # `iw phy <name> ...` or `iw phy#<index> ...`
        if args[:1] == ["phy"] and len(args) >= 2:
            phy_name = args[1]
            rest = args[2:]
            visible = phy_name in self._visible_phys(netns)
            if not visible:
                return self._fail(
                    "command failed: No such file or directory (-2)\n",
                    254,
                    raise_on_fail,
                )
        elif args[:1] and args[0].startswith("phy#"):
            phy_name = f"phy{args[0].removeprefix('phy#')}"
            rest = args[1:]
            if phy_name not in self._visible_phys(netns):
                # Real iw filters an info dump by index, so an unknown index
                # prints nothing and exits 0; commands on it fail with ENODEV.
                if rest == ["info"]:
                    return self._ok()
                return self._fail(
                    "command failed: No such device (-19)\n", 237, raise_on_fail
                )
        else:
            return self._unrecognised(netns, ["iw", *args])

        return self._iw_phy(netns, phy_name, rest, raise_on_fail)

    def _iw_phy(
        self, netns: str | None, phy_name: str, rest: list[str], raise_on_fail: bool
    ) -> CommandResult:
        if rest == ["info"]:
            # Real `iw phy <x> info` has no `addr` line.
            index = phy_name.removeprefix("phy")
            return self._ok(f"Wiphy {phy_name}\n\twiphy index: {index}\n")
        if len(rest) == 5 and rest[:2] == ["interface", "add"] and rest[3] == "type":
            name, iface_type = rest[2], rest[4]
            if (netns, name) in self.ifaces:
                # What the kernel really returns for a taken name (ENFILE).
                return self._fail(
                    "command failed: Too many open files in system (-23)\n",
                    233,
                    raise_on_fail,
                )
            self.ifaces[(netns, name)] = Iface(
                phy=phy_name, netns=netns, type=iface_type, ifindex=self.next_ifindex
            )
            self.next_ifindex += 1
            self.adds.append((phy_name, name, netns))
            return self._ok()
        if rest[:2] == ["set", "netns"]:
            if rest[2:3] == ["name"] and len(rest) == 4:
                target: str | None = rest[3]
                if target not in self.netns:
                    return self._fail(
                        "command failed: No such file or directory (-2)\n",
                        254,
                        raise_on_fail,
                    )
            elif rest[2:] == ["1"]:
                target = None
            else:
                return self._unrecognised(netns, ["iw", "phy", phy_name, *rest])
            self._move_phy(phy_name, target)
            return self._ok()
        return self._unrecognised(netns, ["iw", "phy", phy_name, *rest])

    def _move_phy(self, phy_name: str, target: str | None) -> None:
        source = self.phy_netns[phy_name]
        travelling = sorted(
            (key for key, meta in self.ifaces.items() if meta.phy == phy_name),
            key=lambda key: self.ifaces[key].ifindex,
        )
        for key in travelling:
            meta = self.ifaces.pop(key)
            meta.netns = target
            name = key[1]
            if (target, name) in self.ifaces:
                # The kernel does not refuse the move; it renames the
                # travelling iface to the lowest free wlan%d in the target.
                index = 0
                while (target, f"wlan{index}") in self.ifaces:
                    index += 1
                name = f"wlan{index}"
            self.ifaces[(target, name)] = meta
        self.phy_netns[phy_name] = target
        if source != target:
            self.phy_moves.append((phy_name, target))

    def _iw_dev_dump(self, netns: str | None) -> str:
        # Bare `iw dev` groups by `phy#N` and prints no `wiphy N` line.
        lines: list[str] = []
        for phy_name in self._visible_phys(netns):
            # A phy's ifaces print newest first.
            on_phy = [
                (name, meta)
                for name, meta in reversed(self._netns_ifaces(netns))
                if meta.phy == phy_name
            ]
            if not on_phy:
                continue
            lines.append(f"phy#{phy_name.removeprefix('phy')}")
            for name, meta in on_phy:
                lines += [
                    f"\tInterface {name}",
                    f"\t\taddr {self.phy_mac[phy_name]}",
                    f"\t\ttype {meta.type}",
                ]
        return "\n".join(lines) + ("\n" if lines else "")

    def _iw_dev_info(self, name: str, meta: Iface) -> str:
        return (
            f"Interface {name}\n"
            f"\taddr {self.phy_mac[meta.phy]}\n"
            f"\ttype {meta.type}\n"
            f"\twiphy {meta.phy.removeprefix('phy')}\n"
        )

    def _ip(
        self, netns: str | None, args: list[str], raise_on_fail: bool
    ) -> CommandResult:
        if netns is None and args[:1] == ["netns"]:
            return self._ip_netns(args[1:], raise_on_fail)
        if args == ["-o", "link", "show"]:
            stdout = "1: lo: <LOOPBACK> mtu 65536\n" + "".join(
                f"{meta.ifindex}: {name}: <BROADCAST,MULTICAST> mtu 1500\n"
                for name, meta in self._netns_ifaces(netns)
            )
            return self._ok(stdout)
        if len(args) == 4 and args[:2] == ["link", "set"] and args[3] in {"up", "down"}:
            if (netns, args[2]) not in self.ifaces:
                return self._fail(f'Cannot find device "{args[2]}"\n', 1, raise_on_fail)
            return self._ok()
        if len(args) == 5 and args[:2] == ["link", "set"] and args[3] == "netns":
            # Wireless netdevs are netns-local; only the phy can move.
            return self._fail(
                "Error: The interface netns is immutable.\n", 2, raise_on_fail
            )
        return self._unrecognised(netns, ["ip", *args])

    def _ip_netns(self, args: list[str], raise_on_fail: bool) -> CommandResult:
        if args == ["list"]:
            stdout = "".join(
                f"{name} (id: {i})\n" for i, name in enumerate(sorted(self.netns))
            )
            return self._ok(stdout)
        if len(args) == 2 and args[0] == "add":
            if args[1] in self.netns:
                return self._fail(
                    f'Cannot create namespace file "/run/netns/{args[1]}": File exists\n',
                    1,
                    raise_on_fail,
                )
            self.netns.add(args[1])
            return self._ok()
        if len(args) == 2 and args[0] == "delete":
            name = args[1]
            if name not in self.netns:
                return self._fail(
                    f'Cannot remove namespace file "/run/netns/{name}": '
                    "No such file or directory\n",
                    1,
                    raise_on_fail,
                )
            # Destroying a netns returns its phys (and their ifaces) to root.
            for phy_name in self._visible_phys(name):
                self._move_phy(phy_name, None)
            self.netns.discard(name)
            return self._ok()
        return self._unrecognised(None, ["ip", "netns", *args])


# Josh's 3-radio boot (#236): BE200 phy0/wlan0, mt7921u phy1/wlan2, MT7612U phy2/wlan1.
JOSH_THREE_RADIO: dict[str, dict[str, str]] = {
    "wlan0": {"phy": "phy0", "mac": "00:11:22:33:44:00"},
    "wlan1": {"phy": "phy2", "mac": "00:11:22:33:44:01"},
    "wlan2": {"phy": "phy1", "mac": "00:11:22:33:44:02"},
}


@contextmanager
def live_adapter_inventory_mocks(
    adapters: dict[str, dict[str, str]] | None = None,
    faults: dict[tuple[str | None, tuple[str, ...]], str] | None = None,
):
    """Run activation against a stateful fake of the live radio inventory.

    Each adapter is `{iface: {"phy", "mac", optional "netns", optional "type"}}`.
    Every `run_command` import site on the activate/deactivate/revert path is
    routed to InventoryRecorder, so the real adapter, discovery, and namespace
    parsers run against realistic `iw`/`ip` output. `faults` maps
    `(netns, command_tuple)` to the stderr that command fails with.

    Unrecognised commands fail the test on exit even if production code
    swallowed the exception.
    """
    recorder = InventoryRecorder.from_adapters(
        adapters if adapters is not None else JOSH_THREE_RADIO, faults
    )
    patches = [
        *(patch(site, side_effect=recorder.run_command) for site in _RUN_COMMAND_SITES),
        *_service_side_effect_patches(),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield recorder
    assert not recorder.unrecognised, (
        f"inventory fake saw unrecognised commands: {recorder.unrecognised}"
    )


class _RealCommandGuard:
    """Stand-in for `subprocess` inside utils.general that refuses to spawn."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(subprocess, name)

    def Popen(self, cmd: Any, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(cmd)
        raise AssertionError(f"real command reached run_command: {cmd}")


@pytest.fixture
def no_real_run_command(monkeypatch):
    """Fail the test if anything reaches a real `utils.general.run_command`.

    Replaces only the `subprocess` name inside utils.general, so stdlib
    subprocess is untouched elsewhere. Calls are recorded as well as raised
    because production code often wraps them in a blind `except Exception`.
    """
    guard = _RealCommandGuard()
    monkeypatch.setattr("wlanpi_core.utils.general.subprocess", guard)
    yield guard
    assert not guard.calls, f"real run_command calls: {guard.calls}"


def write_json_config(cfg_dir: Path, cfg_id: str, payload: dict) -> Path:
    path = cfg_dir / f"{cfg_id}.json"
    import json

    path.write_text(json.dumps(payload, indent=4))
    return path
