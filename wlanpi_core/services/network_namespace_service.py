from datetime import datetime
import logging    
from pathlib import Path
import time
from typing import List
from wlanpi_core.utils.general import run_command
from wlanpi_core.schemas.network.network import NetworkSetupLog, ScanItem, WlanConfig, NetworkEvent, NetworkSetupStatus
from wlanpi_core.models.runcommand_error import RunCommandError

DEFAULT_CTRL_INTERFACE = "/run/wpa_supplicant"
DEFAULT_CONFIG_DIR = "/etc/wpa_supplicant"
DEFAULT_DHCP_DIR = "/etc/network/interfaces.d"

class NetworkService:
    def __init__(self, config_dir=DEFAULT_CONFIG_DIR, ctrl_interface=DEFAULT_CTRL_INTERFACE, dhcp_dir=DEFAULT_DHCP_DIR):
        self.config_dir = Path(config_dir)
        self.ctrl_interface = ctrl_interface
        self.dhcp_dir = Path(dhcp_dir)
        self.global_settings = {
            "ctrl_interface": ctrl_interface,
            "update_config": True,
            "pmf": 2,
            "sae_pwe": True
        }
        self.networks = {}
        self.log = logging.getLogger(__name__)
        self.event_log: List[NetworkEvent] = []

    def set_global_settings(self, settings: dict):
        self.log.info("Updating global settings: %s", settings)
        self.global_settings.update(settings)
        

    def parse_wpa_log(self, timeout: int = 30):
        """
        Tails the given wpa_supplicant log file until it sees the 'Connection to ... completed'
        event, or until timeout seconds passes.

        Each line is appended to `event_log`.
        """
        start_time = time.time()

        with open("/tmp/wpa.log", "r") as f:
            # f.seek(0, 2)  # Uncomment to tail only NEW output

            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.1)  # Wait for more output
                    if time.time() - start_time > timeout:
                        raise TimeoutError("Timeout waiting for connection to complete")
                    continue

                line = line.strip()
                self._log_event(line)

                if "CTRL-EVENT-CONNECTED" in line and "completed" in line:
                    break

    def add_network(self, iface: str, net_config: WlanConfig, namespace: str, set_default_route: bool = False):
        self.log.info("Adding network on %s in namespace %s", iface, namespace)
        self.networks[iface] = net_config

        self._prepare_namespace(iface, namespace)
        self._write_config(iface)
        self._write_dhcp_config(iface)
        self._start_or_restart_supplicant(iface, namespace)
        self._restart_dhcp(iface, namespace)

        if set_default_route:
            self._set_default_route(iface, namespace)
            
        self.parse_wpa_log()
            
        status = self.get_status(iface, namespace)
        wpa: dict = status.get("wpa_status", {})
        scan: dict = status.get("connected_scan", {})

        connected = ScanItem(
            ssid=net_config.ssid,
            bssid=wpa.get("bssid", "unknown"),
            key_mgmt=wpa.get("key_mgmt", "unknown"),
            signal=scan.get("signal"),
            freq=wpa.get("freq", 0),
            minrate=1000000
        )

        log = NetworkSetupLog(selectErr="", eventLog=self.event_log)
        return NetworkSetupStatus(
            status="connected",
            response=log,
            connectedNet=connected,
            input=net_config.__str__()
        )

    def remove_network(self, iface: str, namespace: str):
        self.log.info("Removing network %s from namespace %s", iface, namespace)
        self.networks.pop(iface, None)

        self._safe_unlink(self.config_dir / f"{iface}.conf")
        self._safe_unlink(self.dhcp_dir / f"{iface}.cfg")

        self._ns_exec(["pkill", "-f", f"wpa_supplicant.*-i{iface}"], namespace)
        self._ns_exec(["rm", "-f", f"{self.ctrl_interface}/{iface}"], namespace)
        self._ns_exec(["dhclient", "-r", iface], namespace)
        
    def revert_to_root(self, iface: str, namespace: str, delete_namespace: bool = True):
        self.log.info(f"Reverting {iface} and phy0 from namespace {namespace} to root namespace.")

        # Try to delete the interface in the namespace if it exists
        try:
            self._run(["ip", "netns", "exec", namespace, "iw", "dev", iface, "del"])
            self.log.info(f"Deleted {iface} in namespace {namespace}.")
        except RunCommandError as e:
            if "No such device" in str(e):
                self.log.info(f"No {iface} found to delete in {namespace}.")
            else:
                self.log.warning(f"Failed to delete {iface} in {namespace}: {e}")

        # Try to move phy0 back to root
        try:
            phy_result = self._run(["ip", "netns", "exec", namespace, "iw", "phy"], no_output=True)
            if "phy0" in phy_result.stdout:
                self._run(["ip", "netns", "exec", namespace, "iw", "phy", "phy0", "set", "netns", "1"])
                self.log.info(f"Moved phy0 from namespace {namespace} back to root.")
            else:
                self.log.info(f"No phy0 found in {namespace}. assuming it's already in root.")
        except RunCommandError as e:
            self.log.warning(f"Could not check or move phy0 from {namespace}: {e}")

        try:
            self._run(["iw", "phy", "phy0", "interface", "add", iface, "type", "managed"])
            self.log.info(f"Created {iface} in root namespace.")
        except RunCommandError as e:
            self.log.warning(f"Could not create {iface} in root: {e}")


        try:
            self._run(["ip", "link", "set", iface, "up"])
            self.log.info(f"Brought {iface} up in root namespace.")
        except RunCommandError as e:
            self.log.warning(f"Could not bring up {iface} in root: {e}")

        # Optionally delete the namespace
        if delete_namespace:
            try:
                self._run(["ip", "netns", "delete", namespace])
                self.log.info(f"Deleted namespace {namespace}.")
            except RunCommandError as e:
                if "No such file or directory" in str(e):
                    self.log.info(f"Namespace {namespace} already deleted.")
                else:
                    self.log.warning(f"Could not delete namespace {namespace}: {e}")

    def get_status(self, iface: str, namespace: str) -> dict[dict[str, str], str]:
        try:
            wpa_status = {}
            wpa = self._ns_exec(["wpa_cli", "-i", iface, "status"], namespace).stdout.strip()
            for line in wpa.split("\n"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    wpa_status[key.strip()] = value.strip()

            connected_ssid = wpa_status.get("ssid")
            connected_bssid = wpa_status.get("bssid")

            signal = None
            freq = int(wpa_status.get("freq", 0))
            scan = self._ns_exec(["wpa_cli", "-i", iface, "scan_results"], namespace).stdout.strip()
            lines = scan.split("\n")
            if len(lines) > 1 and connected_bssid:
                for line in lines[1:]:
                    parts = line.split("\t")
                    if len(parts) < 5:
                        continue
                    bssid, freq_str, signal_str, flags, ssid = parts
                    if bssid.lower() == connected_bssid.lower():
                        self.log.info(f"found connected network: {parts}")
                        signal = int(signal_str)
                        key_mgmt = self._parse_key_mgmt(flags)
                        break

            ip = self._ns_exec(["ip", "addr", "show", iface], namespace).stdout.strip()
        

            return {
                "wpa_status": wpa_status,
                "ip_info": ip,
                "connected_scan": {
                    "ssid": connected_ssid,
                    "bssid": connected_bssid,
                    "key_mgmt": key_mgmt,
                    "freq": freq,
                    "signal": signal,
                    "minrate": 1000000  # Or some real value if you can find it
                }
            }
        
        except RunCommandError as e:
            self.log.warning("Status check failed for %s: %s", iface, e)
            return {"error": str(e)}
        
    
    def _parse_key_mgmt(self, flags: str) -> str:
        if "WPA2-PSK" in flags:
            return "wpa-psk"
        elif "WPA-PSK" in flags:
            return "wpa-psk"
        elif "WEP" in flags:
            return "wep"
        elif "[ESS]" in flags and "WPA" not in flags:
            return "open"
        return "unknown"
        
    def _prepare_namespace(self, iface: str, namespace: str):
        if not namespace:
                return

        try:
            # Make sure the namespace exists
            output = run_command(["ip", "netns", "list"]).stdout
            if namespace in output:
                self.log.info("Namespace %s already exists", namespace)
            else:
                self.log.info("Creating namespace %s", namespace)
                self._run(["sudo", "ip", "netns", "add", namespace])

            # Clean up any stale iface
            try:
                self._ns_exec(["iw", "dev", iface, "del"], namespace)
            except RunCommandError as e:
                if "No such device" in str(e):
                    self.log.info(f"No {iface} to delete in {namespace}. ignoring.")
                else:
                    raise

            # Check if phy0 is already in namespace. if yes, move it back to root first
            result = self._ns_exec(["iw", "phy"], namespace)
            if "phy0" in result.stdout:
                self.log.info("Moving phy0 back to root from namespace %s", namespace)
                self._ns_exec(["iw", "phy", "phy0", "set", "netns", "1"], namespace)
            else:
                self.log.info(f"phy0 not found in {namespace}. assume it's in root already.")

            # Attach phy0 to target namespace
            self.log.info("Attaching phy0 to namespace %s", namespace)
            self._run(["sudo", "iw", "phy", "phy0", "set", "netns", "name", namespace])

            # Create the wlan interface
            try:
                self.log.info("Creating %s in namespace %s", iface, namespace)
                self._ns_exec(["iw", "phy", "phy0", "interface", "add", iface, "type", "managed"], namespace)
            except:
                self.log.info("wlan0 already exists")

            # Bring up the new interface
            self.log.info("Bringing up %s in namespace %s", iface, namespace)
            self._ns_exec(["ip", "link", "set", iface, "up"], namespace)

        except RunCommandError as e:
            self.log.error("Namespace setup failed for %s: %s", iface, e)
            raise

    def restore_phy_to_userspace(self, namespace: str):
        try:
            self._run(["ip", "netns", "exec", namespace, "iw", "dev", "wlan0", "del"])
        except RunCommandError as e:
            if "No such device" in str(e):
                self.log.info(f"No wlan0 to delete in {namespace} - ignoring.")
            else:
                self.log.warning(f"Failed to delete wlan0 in {namespace}: {e}")

        # Check if phy0 exists in namespace
        try:
            result = self._run(["ip", "netns", "exec", namespace, "iw", "phy"], no_output=True)
            if "phy0" in result.stdout:
                # phy0 exists;  move it back
                self._run(["ip", "netns", "exec", namespace, "iw", "phy", "phy0", "set", "netns", "1"])
                self.log.info("Restored phy0 to root namespace from %s", namespace)
            else:
                self.log.info(f"No phy0 found in {namespace} - already restored or missing.")
        except RunCommandError as e:
            self.log.warning(f"Could not check phy in {namespace}: {e}")

    def _write_config(self, iface: str):
        conf_path = self.config_dir / f"{iface}.conf"
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Find max priority
        max_priority = 0
        blocks = []

        if conf_path.exists():
            with conf_path.open() as f:
                block, in_block = [], False
                for line in f:
                    line = line.strip()
                    if line.startswith("network={"):
                        in_block = True
                        block = [line]
                    elif in_block:
                        block.append(line)
                        if line == "}":
                            blocks.append("\n".join(block))
                            in_block = False

            for b in blocks:
                for l in b.splitlines():
                    if l.strip().startswith("priority="):
                        try:
                            max_priority = max(max_priority, int(l.split("=")[1]))
                        except ValueError:
                            pass

        new_block = self._generate_network_block(self.networks[iface], max_priority + 1)
        blocks = [b for b in blocks if f'ssid="{self.networks[iface].ssid}"' not in b]
        blocks.insert(0, new_block)

        with conf_path.open("w") as f:
            f.write(self._generate_global_header() + "\n\n" + "\n\n".join(blocks))

    def _write_dhcp_config(self, iface: str):
        self.dhcp_dir.mkdir(parents=True, exist_ok=True)
        dhcp_path = self.dhcp_dir / f"{iface}.cfg"
        dhcp_path.write_text(f"auto {iface}\niface {iface} inet dhcp\n")

    def _start_or_restart_supplicant(self, iface: str, namespace: str):
        self._ns_exec(["pkill", "-f", f"wpa_supplicant -B -i {iface}"], namespace)
        self._ns_exec(["rm", "-f", f"{self.ctrl_interface}/{iface}"], namespace)
        conf_path = self.config_dir / f"{iface}.conf"
        self._ns_exec([
            "wpa_supplicant", "-B",
            "-i", iface,
            "-c", str(conf_path),
            "-D", "nl80211",
            "-f" "/tmp/wpa.log"
        ], namespace)
        # self._run(["tail", "-F", "/tmp/wpa.log"])

    def _restart_dhcp(self, iface: str, namespace: str):
        self._ns_exec(["dhclient", "-r", iface], namespace)
        self._ns_exec(["dhclient", iface], namespace)

    def _set_default_route(self, iface: str, namespace: str):
        if iface not in self._ns_exec(["ip", "route", "show", "default"], namespace).stdout:
            self._ns_exec(["ip", "route", "replace", "default", "dev", iface, "metric", "200"], namespace)

    def _generate_global_header(self):
        lines = [
            f"ctrl_interface={self.global_settings['ctrl_interface']}",
            f"update_config={1 if self.global_settings.get('update_config') else 0}",
            f"pmf={self.global_settings.get('pmf', 1)}"
        ]
        if self.global_settings.get("sae_pwe"):
            lines.append("sae_pwe=1")
        return "\n".join(lines)

    def _generate_network_block(self, net: WlanConfig, priority=0):
        lines = ["network={"]
        lines.append(f"    ssid=\"{net.ssid}\"")
        lines.append(f"    priority={priority}")
        lines.append(f"    psk=\"{net.psk}\"")
        lines.append("    key_mgmt=WPA-PSK")
        lines.append("    ieee80211w=2")
        # sec = net.get("security", "OPEN").upper()

        # if sec == "OPEN":
        #     lines.append("    key_mgmt=NONE")
        # elif sec == "OWE":
        #     lines.append("    key_mgmt=OWE")
        # elif sec in ("WPA2-PSK", "WPA3-PSK"):
        #     lines.append(f"    psk=\"{net.psk}\"")
        #     lines.append("    key_mgmt=WPA-PSK")
        #     if sec == "WPA3-PSK":
        #         lines.append("    ieee80211w=2")
        #         lines.append("    sae_pwe=1")
        # elif sec == "802.1X":
        #     lines.append("    key_mgmt=WPA-EAP")
        #     lines.append(f"    identity=\"{net}\"")
        #     lines.append(f"    password=\"{net.pas}\"")
        #     lines.append(f"    ca_cert=\"{net.get('ca_cert', '/etc/ssl/certs/ca-certificates.crt')}\"")
        #     lines.append("    eap=PEAP")
        # elif sec == "OPENROAMING":
        #     lines.append("    key_mgmt=WPA-EAP")
        #     lines.append(f"    identity=\"{net['identity']}\"")
        #     lines.append(f"    client_cert=\"{net['client_cert']}\"")
        #     lines.append(f"    private_key=\"{net['private_key']}\"")
        #     lines.append(f"    ca_cert=\"{net['ca_cert']}\"")
        #     lines.append("    eap=TLS")

        # if net.get("mlo"):
        #     lines.append("    mlo=1")

        lines.append("}")
        return "\n".join(lines)

    def _run(self, cmd, no_output=False):
        self.log.info(f"Running: {' '.join(cmd)}")
        output = run_command(cmd, raise_on_fail=True)
        if not no_output:
            self.log.info(f"stdout: {output.stdout}\nstderr: {output.stderr}\ncode: {output.return_code}")
        return output

    def _ns_exec(self, cmd, namespace):
        full_cmd = ["sudo", "ip", "netns", "exec", namespace] + cmd if namespace else cmd
        self.log.info(f"Running: {' '.join(full_cmd)}")
        output = run_command(full_cmd, raise_on_fail=True)
        self.log.info(f"stdout: {output.stdout}\nstderr: {output.stderr}\ncode: {output.return_code}")
        return output

    def _safe_unlink(self, path: Path):
        if path.exists():
            path.unlink()
            
    def _log_event(self, event: str):
        now = datetime.now().isoformat()
        self.event_log.append(NetworkEvent(event=event, time=now))
        self.log.info(f"[EventLog] {event}")
    
    