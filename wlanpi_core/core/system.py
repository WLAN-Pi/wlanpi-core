import subprocess
import time
from threading import Thread
from typing import Any, Optional

from wlanpi_core.constants import ETHTOOL_FILE, IP_FILE, IW_FILE
from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)
_SYSTEM_COMMAND_TIMEOUT_SEC = 10


class SystemManager:
    def __init__(self, iface_name: str = "wlanpi", exclusions: list[str] = []) -> None:
        self.iface_name = iface_name
        self.exclusions = exclusions
        self.sync_monitor_interfaces()

    def _run(
        self,
        cmd: list[str],
        capture_output: bool = False,
        suppress_output: bool = False,
    ) -> Optional[Any]:
        try:
            if capture_output:
                return (
                    subprocess.check_output(
                        cmd,
                        stderr=subprocess.DEVNULL,
                        timeout=_SYSTEM_COMMAND_TIMEOUT_SEC,
                    )
                    .decode()
                    .strip()
                )
            elif suppress_output:
                subprocess.check_call(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=_SYSTEM_COMMAND_TIMEOUT_SEC,
                )
            else:
                subprocess.check_call(cmd, timeout=_SYSTEM_COMMAND_TIMEOUT_SEC)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            if isinstance(error, subprocess.TimeoutExpired):
                log.warning("System command timed out")
            return None if capture_output else False

    def _iface_up(self, name: str) -> Optional[Any]:
        return self._run([IP_FILE, "link", "set", name, "up"])

    def _iface_down(self, name: str) -> Optional[Any]:
        return self._run([IP_FILE, "link", "set", name, "down"])

    def _get_driver(self, name: str) -> Optional[str]:
        output = self._run([ETHTOOL_FILE, "-i", name], capture_output=True)
        if output:
            for line in output.splitlines():
                if line.lower().startswith("driver:"):
                    return line.split(":")[1].strip()
        return None

    def _get_wiphy_index(self, name: str) -> Optional[str]:
        output = self._run([IW_FILE, "dev", name, "info"], capture_output=True)
        if output:
            for line in output.splitlines():
                if "wiphy" in line:
                    return "".join(filter(str.isdigit, line))
        return None

    def _get_interfaces_by_type(self) -> dict[str, str]:
        output = self._run([IW_FILE, "dev"], capture_output=True)
        interfaces: dict[str, str] = {}
        current_iface: Optional[str] = None
        if not output:
            return interfaces

        for line in output.splitlines():
            if line.strip().startswith("Interface"):
                current_iface = line.strip().split()[1]
            elif "type" in line and current_iface:
                iface_type = line.strip().split()[1]
                if current_iface not in self.exclusions:
                    interfaces[current_iface] = iface_type
                    current_iface = None

        return interfaces

    def _create_monitor(self, name: str, index: str) -> Optional[str]:
        mon = f"{self.iface_name}{index}"
        self._run(
            [
                IW_FILE,
                name,
                "interface",
                "add",
                mon,
                "type",
                "monitor",
                "flags",
                "control",
                "otherbss",
            ]
        )
        if self._iface_up(mon):
            return mon
        else:
            log.error(f"Failed to create monitor interface {mon}")
            return None

    def sync_monitor_interfaces(self) -> None:
        interfaces = self._get_interfaces_by_type()
        managed: dict[str, str] = {}
        for name, typ in interfaces.items():
            if typ == "managed":
                index = self._get_wiphy_index(name)
                if index is not None:
                    managed[name] = index
        monitor: dict[str, str] = {}
        for name, typ in interfaces.items():
            if typ == "monitor":
                index = self._get_wiphy_index(name)
                if index is not None:
                    monitor[name] = index

        # Delete orphan <iface_name><index> interfaces
        for mon_name, mon_index in monitor.items():
            if (
                mon_name.startswith(self.iface_name)
                and mon_index not in managed.values()
            ):
                log.info(f"Deleting unused monitor interface: {mon_name}")
                self._run([IW_FILE, "dev", mon_name, "del"], suppress_output=True)

        # Create missing <iface_name><index> interfaces
        for iface, index in managed.items():
            expected_mon = f"{self.iface_name}{index}"
            if expected_mon not in monitor:
                log.info(f"Creating monitor interface for {iface} → {expected_mon}")
                self._iface_up(iface)
                self._create_monitor(iface, index)
                driver = self._get_driver(iface)
                if driver == "iwlwifi":
                    self._iface_up(expected_mon)
                    log.info(f"Bringing up and scanning on {iface}...")

                    def background_scan_with_timeout() -> None:
                        time.sleep(1)
                        try:
                            subprocess.run(
                                [IW_FILE, iface, "scan"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                timeout=10,
                            )
                            log.info(f"Scan on {iface} done")

                            self._iface_down(iface)
                        except subprocess.TimeoutExpired:
                            log.warning(f"Scan on {iface} timed out after 10s")

                    Thread(target=background_scan_with_timeout, daemon=True).start()
                else:
                    self._iface_down(iface)
