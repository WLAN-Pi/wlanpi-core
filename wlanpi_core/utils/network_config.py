import json
import logging
import subprocess
from typing import List
from pathlib import Path

from wlanpi_core.models.network_config_errors import ConfigActiveError
from wlanpi_core.schemas.network.network import NetConfig, NetConfigUpdate, NetConfigCreate
from wlanpi_core.services.network_namespace_service import NetworkNamespaceService

CONFIG_PATH = Path("/etc/wifictl/configs")
CONFIG_PATH.mkdir(parents=True, exist_ok=True)

log = logging.getLogger(__name__)

ns = NetworkNamespaceService()

def list_configs() -> List[str]:
    """List all configuration files in the CONFIG_PATH directory."""
    return [f.stem for f in CONFIG_PATH.glob("*.json")]
    
def get_config(id: str) -> NetConfig:
    """Get a specific configuration by ID."""
    path = CONFIG_PATH / f"{id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Configuration {id} not found.")
    return NetConfig(**json.loads(path.read_text()))

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

def delete_config(id: str) -> bool:
    """Delete a configuration by ID."""
    path = CONFIG_PATH / f"{id}.json"
    
    cfg = get_config(id)
    if cfg.active:
        raise ConfigActiveError(f"Cannot delete active configuration {id}.")
    path.unlink()
    return True

def activate_config(id: str) -> bool:
    """Activate a configuration by ID."""
    path = CONFIG_PATH / f"{id}.json"
    
    cfg = get_config(id)
    if cfg.active:
        raise ConfigActiveError(f"Configuration {id} is already active.")
    try:
        ns.add_network(cfg.interface, cfg, cfg.namespace, cfg.default_route)
        cfg.active = True
        path.write_text(cfg.model_dump_json(indent=4))
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
        ns.stop_app_in_namespace(cfg.namespace)
        ns.remove_network(cfg.interface, cfg.namespace)
        ns.restore_phy_to_userspace(cfg.namespace)
        cfg.active = False
        path.write_text(cfg.model_dump_json(indent=4))
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