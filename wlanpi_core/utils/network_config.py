import json
import logging
from pathlib import Path

from wlanpi_core.constants import CONFIG_DIR, CURRENT_CONFIG_FILE
from wlanpi_core.models.network_config_errors import ConfigActiveError
from wlanpi_core.schemas.network.network import (
    NetConfig,
    NetConfigUpdate,
)
from wlanpi_core.services.network_namespace_service import NetworkNamespaceService
from wlanpi_core.utils.general import run_command

log = logging.getLogger(__name__)

ns = NetworkNamespaceService()

cfg_dir = Path(CONFIG_DIR)
ccf = Path(CURRENT_CONFIG_FILE)


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
    """List all configuration files in the CONFIG_DIR directory."""
    configs = {}
    for cfg_file in cfg_dir.glob("*.json"):
        try:
            data = json.loads(cfg_file.read_text())
            configs[cfg_file.stem] = ccf.exists() and ccf.read_text().strip() == cfg_file.stem or False
        except Exception:
            configs[cfg_file.stem] = False
    return configs


def status():
    namespaces_output = run_command(["sudo", "ip", "netns", "list"])
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


def get_config(cfg_id: str) -> NetConfig:
    """Get a specific configuration by cfg_id."""
    path = cfg_dir / f"{cfg_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Configuration {cfg_id} not found.")
    return NetConfig(**json.loads(path.read_text()))


def is_active(cfg_id: str) -> bool:
    if get_current_config() == cfg_id:
        return True
    return False


def get_current_config() -> str:
    """Get the currently active configuration cfg_id."""
    if not ccf.exists():
        raise FileNotFoundError("No current configuration set.")
    return ccf.read_text().strip()


def add_config(config: NetConfig) -> bool:
    """Add a new configuration."""
    path = cfg_dir / f"{config.id}.json"
    if path.exists():
        raise FileExistsError(f"Configuration {config.id} already exists.")
    path.write_text(config.model_dump_json(indent=4))
    return True


def edit_config(cfg_id: str, config_update: NetConfigUpdate) -> NetConfig:
    """Edit an existing configuration."""
    path = cfg_dir / f"{cfg_id}.json"
    cfg = get_config(cfg_id)

    if is_active(cfg_id):
        raise ConfigActiveError(f"Cannot edit active configuration {cfg_id}.")

    for field, value in config_update.model_dump().items():
        if value is not None and field != "cfg_id":
            setattr(cfg, field, value)

    # Write updated config back to file
    path.write_text(cfg.model_dump_json(indent=4))

    return cfg


def delete_config(cfg_id: str, force: bool = False) -> bool:
    """Delete a configuration by cfg_id."""
    path = cfg_dir / f"{cfg_id}.json"

    if is_active(cfg_id) and not force:
        raise ConfigActiveError(f"Cannot delete active configuration {cfg_id}.")
    path.unlink()
    return True


def activate_config(cfg_id: str, override_active: bool = False) -> bool:
    """Activate a configuration by cfg_id."""

    cfg = get_config(cfg_id)
    active_cfg = get_current_config()

    if active_cfg != cfg_id and active_cfg != "default" and not override_active:
        raise ConfigActiveError(
            f"Another configuration is currently active: {active_cfg}."
        )

    if active_cfg == cfg_id and not override_active:
        raise ConfigActiveError(f"Configuration {cfg_id} is already active.")
    try:
        for ns_cfg in cfg.namespaces or []:
            log.info(
                f"Activating namespace {ns_cfg.namespace} for interface {ns_cfg.interface}"
            )
            ns.activate_config(ns_cfg)
        for root_cfg in cfg.roots or []:
            log.info(f"Activating root config for interface {root_cfg.interface}")
            ns.activate_config(root_cfg)
        ccf.write_text(cfg_id)
        return True

    except Exception as ex:
        log.error(f"Failed to activate config {cfg_id}: {ex}")
        for ns_cfg in cfg.namespaces or []:
            log.info(
                f"Stopping app {ns_cfg.autostart_app} in namespace {ns_cfg.namespace}"
            )
            ns.stop_app_in_namespace(ns_cfg.namespace)
        for root_cfg in cfg.roots or []:
            log.info(
                f"Stopping app {root_cfg.autostart_app} in root"
            )
            ns.stop_app_in_namespace(root_cfg.namespace)
        raise


def deactivate_config(cfg_id: str, override_active: bool = False) -> bool:
    """Deactivate a configuration by cfg_id."""
    path = cfg_dir / f"{cfg_id}.json"

    cfg = get_config(cfg_id)
    if not is_active(cfg_id) and not override_active:
        raise ConfigActiveError(f"Configuration {cfg_id} is not active.")

    try:
        for ns_cfg in cfg.namespaces or []:
            log.info(
                f"Deactivating namespace {ns_cfg.namespace} for interface {ns_cfg.interface}"
            )
            ns.deactivate_config(ns_cfg)
        for root_cfg in cfg.roots or []:
            log.info(f"Deactivating root config for interface {root_cfg.interface}")
            ns.deactivate_config(root_cfg)

        ccf.write_text("default")
        activate_config("default", override_active=True)
        return True

    except Exception as ex:
        log.error(f"Failed to deactivate config {cfg_id}: {ex}")
        raise
