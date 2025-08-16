import json
import logging
from typing import List
from pathlib import Path

from wlanpi_core.models.network_config_errors import ConfigActiveError
from wlanpi_core.schemas.network.network import NetConfig, NetConfigUpdate, NetConfigCreate
from wlanpi_core.services.network_namespace_service import NetworkNamespaceService
from wlanpi_core.utils.general import run_command

CONFIG_PATH = Path("/etc/wifictl/configs")
CONFIG_PATH.mkdir(parents=True, exist_ok=True)
CURRENT_CONFIG_PATH = Path("/etc/wifictl/current.txt")
CURRENT_CONFIG_PATH.touch(exist_ok=True)

log = logging.getLogger(__name__)

ns = NetworkNamespaceService()

def parse_iw_dev_output(output: str) -> dict:
    """Parse iw dev output into dict"""
    interfaces = {}
    current_iface = None
    skip_table_block = False

    for line in output.splitlines():
        line = line.rstrip()
        if not line.strip():
            skip_table_block = False
            continue

        if line.lstrip().startswith("Interface "):
            current_iface = line.strip().split()[1]
            interfaces[current_iface] = {}
            skip_table_block = False
            continue

        if not current_iface:
            continue

        stripped = line.strip()

        if stripped.endswith("TXQ:") or stripped.startswith("qsz-byt"):
            skip_table_block = True
            continue
        if skip_table_block:
            continue

        if ":" in stripped and not stripped.startswith("channel "):
            key, value = map(str.strip, stripped.split(":", 1))
        else:
            parts = stripped.split(None, 1)
            if len(parts) == 2:
                key, value = parts
            else:
                key, value = parts[0], ""

        key = key.replace(" ", "_")
        interfaces[current_iface][key] = value

    return interfaces


def list_configs() -> dict[str, bool]:
    """List all configuration files in the CONFIG_PATH directory."""
    configs = {}
    for f in CONFIG_PATH.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            configs[f.stem] = data.get("active", False)
        except Exception:
            configs[f.stem] = False
    return configs

def status():
    namespaces_output = run_command(["sudo","ip", "netns", "list"])
    namespaces = []
    for line in namespaces_output.stdout.splitlines():
        namespaces.append(line.split(" ")[0])
        
    final_status = {}
        
    root_info = run_command(["sudo", "iw", "dev"])
    root_status = parse_iw_dev_output(root_info.stdout)
    final_status["root"] = root_status
    
    for ns_name in namespaces:
        output = run_command(["sudo", "ip", "netns", "exec", ns_name, "iw", "dev"])
        ns_status = parse_iw_dev_output(output.stdout)
        final_status[ns_name] = ns_status
        
    return final_status
        
    
def get_config(id: str) -> NetConfig:
    """Get a specific configuration by ID."""
    path = CONFIG_PATH / f"{id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Configuration {id} not found.")
    return NetConfig(**json.loads(path.read_text()))

def get_current_config() -> str:
    """Get the currently active configuration ID."""
    if not CURRENT_CONFIG_PATH.exists():
        raise FileNotFoundError("No current configuration set.")
    return CURRENT_CONFIG_PATH.read_text().strip()

def add_config(config: NetConfigCreate) -> bool:
    """Add a new configuration."""
    path = CONFIG_PATH / f"{config.id}.json"
    if path.exists():
        raise FileExistsError(f"Configuration {config.id} already exists.")
    path.write_text(config.model_dump_json(indent=4))
    return True

def edit_config(id: str, config_update: NetConfigUpdate) -> NetConfig:
    """Edit an existing configuration."""
    path = CONFIG_PATH / f"{id}.json"
    cfg = get_config(id)
    
    if cfg.active:
        raise ConfigActiveError(f"Cannot edit active configuration {id}.")

    for field, value in config_update.model_dump().items():
        if value is not None and field != "id":
            setattr(cfg, field, value)

    # Write updated config back to file
    path.write_text(cfg.model_dump_json(indent=4))
    
    return cfg

def delete_config(id: str, force: bool = False) -> bool:
    """Delete a configuration by ID."""
    path = CONFIG_PATH / f"{id}.json"
    
    cfg = get_config(id)
    if cfg.active and not force:
        raise ConfigActiveError(f"Cannot delete active configuration {id}.")
    path.unlink()
    return True

def activate_config(id: str, override_active: bool = False) -> bool:
    """Activate a configuration by ID."""
    path = CONFIG_PATH / f"{id}.json"
    
    cfg = get_config(id)
    if cfg.active and not override_active:
        raise ConfigActiveError(f"Configuration {id} is already active.")
    try:
        for ns_config in cfg.namespaces:
            log.info(f"Activating namespace {ns_config.namespace} for interface {ns_config.interface}")
            ns.add_network(ns_config)
        for root_config in cfg.roots:
            log.info(f"Activating root config for interface {root_config.interface}")
            ns.add_network(root_config)
        cfg.active = True
        path.write_text(cfg.model_dump_json(indent=4))
        CURRENT_CONFIG_PATH.write_text(id)
        return True

    except Exception as ex:
        log.error(f"Failed to activate config {id}: {ex}")
        raise

def deactivate_config(id: str, override_active: bool = False) -> bool:
    """Deactivate a configuration by ID."""
    path = CONFIG_PATH / f"{id}.json"
    
    cfg = get_config(id)
    if not cfg.active and not override_active:
        raise ConfigActiveError(f"Configuration {id} is not active.")

    try:
        for ns_cfg in cfg.namespaces:
            ns.stop_app_in_namespace(ns_cfg.namespace)
            ns.remove_network(ns_cfg.interface, ns_cfg.namespace)
            ns.restore_phy_to_userspace(ns_cfg)
        for root_cfg in cfg.roots:
            ns.stop_app_in_namespace("root")
            ns.remove_network(root_cfg.interface, "root")
            
        cfg.active = False
        path.write_text(cfg.model_dump_json(indent=4))
        CURRENT_CONFIG_PATH.write_text("root")
        return True

    except Exception as ex:
        log.error(f"Failed to deactivate config {id}: {ex}")
        raise

if __name__ == "__main__":
    cfg = NetConfigCreate(
        id="example",
        namespace="test",
        phy="phy0",
        interface="wlan0",
        ssid="ExampleSSID",
        security="WPA-PSK",
        psk="examplepassword",
        )
    
    add_config(cfg)
    print("Available configs:", list_configs())
    print("Config details:", get_config(cfg.id))
    activate_config(cfg.id)
    print("Activated config:", get_config(cfg.id))
    deactivate_config(cfg.id)
    print("Deactivated config:", get_config(cfg.id))
    delete_config(cfg.id)
    print("Available configs after deletion:", list_configs())
    print("Done.")