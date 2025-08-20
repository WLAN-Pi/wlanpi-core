import subprocess

from wlanpi_core.constants import ETHTOOL_FILE, IP_FILE, IW_FILE
from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


class SystemManager:
    def __init__(self, iface_name: str = "wlanpi"):
        self.iface_name = iface_name
        self.sync_monitor_interfaces()

    def _run(self, cmd, capture_output=False, suppress_output=False):
        try:
            if capture_output:
                return (
                    subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
                    .decode()
                    .strip()
                )
            elif suppress_output:
                subprocess.check_call(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            else:
                subprocess.check_call(cmd)
            return True
        except subprocess.CalledProcessError:
            return None if capture_output else False

    def _iface_up(self, name):
        return self._run([IP_FILE, "link", "set", name, "up"])

    def _iface_down(self, name):
        return self._run([IP_FILE, "link", "set", name, "down"])

    def _iface_scan(self, name):
        log.info(f"Bringing up and scanning on {name}...")
        self._iface_up(name)
        self._run([IW_FILE, name, "scan"], suppress_output=True)

    def _get_driver(self, name):
        output = self._run([ETHTOOL_FILE, "-i", name], capture_output=True)
        if output:
            for line in output.splitlines():
                if line.lower().startswith("driver:"):
                    return line.split(":")[1].strip()
        return None

    def _get_wiphy_index(self, name):
        output = self._run([IW_FILE, "dev", name, "info"], capture_output=True)
        if output:
            for line in output.splitlines():
                if "wiphy" in line:
                    return "".join(filter(str.isdigit, line))
        return None

    def _get_interfaces_by_type(self):
        output = self._run([IW_FILE, "dev"], capture_output=True)
        interfaces = {}
        current_iface = None
        if not output:
            return interfaces

        for line in output.splitlines():
            if line.strip().startswith("Interface"):
                current_iface = line.strip().split()[1]
            elif "type" in line and current_iface:
                iface_type = line.strip().split()[1]
                interfaces[current_iface] = iface_type
                current_iface = None
        return interfaces

    def _create_monitor(self, name, index):
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

    def sync_monitor_interfaces(self):
        interfaces = self._get_interfaces_by_type()
        managed = {
            name: self._get_wiphy_index(name)
            for name, typ in interfaces.items()
            if typ == "managed"
        }
        monitor = {
            name: self._get_wiphy_index(name)
            for name, typ in interfaces.items()
            if typ == "monitor"
        }

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
                self._create_monitor(iface, index)
                driver = self._get_driver(iface)
                if driver == "iwlwifi":
                    self._iface_scan(iface)
                self._iface_down(iface)
