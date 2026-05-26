import json
import logging
from pathlib import Path

from wlanpi_core.constants import CONFIG_DIR, CURRENT_CONFIG_FILE
from wlanpi_core.models.network_config_errors import ConfigActiveError, ConfigMalformedError
from wlanpi_core.schemas.network.network import (
    NetConfig,
    NetConfigUpdate,
    NamespaceConfig,
    RootConfig,
    NetSecurity,
    SecurityTypes,
    NetworkModeEnum,
)
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.services.network_namespace_service import NetworkNamespaceService
from wlanpi_core.utils.general import run_command

log = logging.getLogger(__name__)

ns = NetworkNamespaceService()

cfg_dir = Path(CONFIG_DIR)
ccf = Path(CURRENT_CONFIG_FILE)


def get_default_config(cfg_id: str = "default") -> NetConfig:
    """Get the default configuration structure."""
    return NetConfig(
        id=cfg_id,
        namespaces=[],
        roots=[
            RootConfig(
                mode=NetworkModeEnum.managed,
                iface_display_name="wlan0",
                phy="phy0",
                interface="wlan0",
                security = NetSecurity(
                    ssid="wlan0",
                    security=SecurityTypes.wpa2,
                ),
                default_route=True,
                autostart_app=None,
            ),
            RootConfig(
                mode=NetworkModeEnum.managed,
                iface_display_name="wlan1",
                phy="phy1",
                interface="wlan1",
                default_route=True,
                autostart_app=None,
            )
        ],
    )


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

        # Prefer splitting on the first whitespace to get the key token, then
        # treat a leading ':' in the remainder as a key:value separator.
        parts = stripped.split(None, 1)
        if len(parts) == 2:
            key, remainder = parts[0], parts[1]
        else:
            key, remainder = parts[0], ""

        value = remainder[1:].strip() if remainder.startswith(":") else remainder

        key = key.replace(" ", "_")
        interfaces[current_iface][key] = value

    return interfaces

def interfaces_in_root(cfg_id: str) -> list[str]:
    cfg = get_config(cfg_id)
    
    root = cfg.roots or []
    return [r.interface for r in root]

def list_configs() -> dict[str, bool]:
    """List all configuration files in the CONFIG_DIR directory."""
    configs = {}
    for cfg_file in cfg_dir.glob("*.json"):
        cfg_stem = cfg_file.stem
        annotation = None
        
        try:
            file_content = cfg_file.read_text().strip()
            if not file_content:
                log.warning(f"Configuration file {cfg_file.name} is empty.")
                annotation = "(empty)"
            else:
                data = json.loads(file_content)
                # Validate that it's a valid NetConfig structure (at least has 'id')
                if not isinstance(data, dict) or "id" not in data:
                    log.warning(f"Configuration file {cfg_file.name} has invalid structure.")
                    annotation = "(malformed)"
        except json.JSONDecodeError as e:
            log.warning(f"Configuration file {cfg_file.name} contains malformed JSON: {e}.")
            annotation = "(malformed)"
        except Exception as e:
            log.warning(f"Error reading configuration file {cfg_file.name}: {e}.")
            annotation = "(malformed)"
        
        # Annotate the key name if there's an issue
        key = f"{cfg_stem} {annotation}" if annotation else cfg_stem
        
        # Check if this config is active (using original stem name for comparison)
        is_active = ccf.exists() and ccf.read_text().strip() == cfg_stem
        configs[key] = is_active
    
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
        try:
            output = run_command(["sudo", "ip", "netns", "exec", ns_name, "iw", "dev"])
            ns_status = parse_iw_dev_output(output.stdout)
            final_status[ns_name] = ns_status
        except RunCommandError as e:
            # Namespace may be in a corrupted/invalid state (e.g., after forced termination)
            # Log warning but continue processing other namespaces
            log.warning(
                f"Failed to get status for namespace '{ns_name}': {e}. "
                f"This namespace may be corrupted or invalid. Skipping."
            )
            # Add error indicator to status so caller knows this namespace failed
            final_status[ns_name] = {"error": str(e)}
        except Exception as e:
            # Catch any other unexpected errors for this namespace
            log.warning(
                f"Unexpected error getting status for namespace '{ns_name}': {e}. Skipping."
            )
            final_status[ns_name] = {"error": str(e)}

    return final_status


def get_config(cfg_id: str) -> NetConfig:
    """Get a specific configuration by cfg_id."""
    path = cfg_dir / f"{cfg_id}.json"
    if not path.exists():
        # Only create default config if requesting the "default" config
        if cfg_id == "default":
            log.info(f"Default configuration file not found. Creating default config.")
            default_config = get_default_config("default")
            path.write_text(default_config.model_dump_json(indent=4))
            return default_config
        raise FileNotFoundError(f"Configuration {cfg_id} not found.")
    
    try:
        file_content = path.read_text().strip()
        if not file_content:
            log.error(f"Configuration file {cfg_id}.json is empty.")
            raise ConfigMalformedError(
                f"Configuration file {cfg_id}.json is empty or contains only whitespace.",
                cfg_id=cfg_id
            )
        
        data = json.loads(file_content)
        return NetConfig(**data)
    except json.JSONDecodeError as e:
        log.error(f"Configuration file {cfg_id}.json contains malformed JSON: {e}")
        raise ConfigMalformedError(
            f"Configuration file {cfg_id}.json contains malformed JSON: {e}",
            cfg_id=cfg_id
        )
    except ConfigMalformedError:
        raise
    except Exception as e:
        log.error(f"Failed to parse configuration {cfg_id}: {e}")
        raise ConfigMalformedError(
            f"Failed to parse configuration {cfg_id}: {e}",
            cfg_id=cfg_id
        )


def is_active(cfg_id: str) -> bool:
    try:
        if get_current_config() == cfg_id:
            return True
    except ConfigMalformedError:
        # If current config is malformed, it's been reverted to default
        # so the requested cfg_id is not active
        pass
    return False


def get_current_config() -> str:
    """Get the currently active configuration cfg_id."""
    if not ccf.exists():
        raise FileNotFoundError("No current configuration set.")
    
    content = ccf.read_text().strip()
    if not content:
        log.error("Current configuration file is empty or contains only whitespace.")
        # Revert to default without rewriting the file
        ccf.write_text("default")
        raise ConfigMalformedError(
            "Current configuration file is empty or contains only whitespace. Reverted to 'default'.",
            cfg_id=None
        )
    
    # Validate that the config ID exists and is valid
    try:
        # Try to get the config to validate it exists and is valid
        get_config(content)
    except (FileNotFoundError, ConfigMalformedError) as e:
        error_msg = getattr(e, 'message', str(e))
        log.error(f"Current configuration '{content}' is invalid: {error_msg}")
        # Revert to default without rewriting the malformed active config file
        ccf.write_text("default")
        raise ConfigMalformedError(
            f"Current configuration '{content}' is invalid or malformed: {error_msg}. Reverted to 'default'.",
            cfg_id=content
        )
    
    return content


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
    try:
        active_cfg = get_current_config()
    except (FileNotFoundError, ConfigMalformedError):
        # Treat missing or malformed current-config as default (first-run or error scenario)
        active_cfg = "default"

    if not override_active:
        if active_cfg != cfg_id and active_cfg != "default":
            raise ConfigActiveError(
                f"Another configuration is currently active: {active_cfg}."
            )

        if active_cfg == cfg_id:
            raise ConfigActiveError(f"Configuration {cfg_id} is already active.")
    try:
        if override_active:
            log.info("Override active set: killing all wpa_supplicant processes before activation")
            ns.kill_all_supplicants()
        outcomes: list[str] = []
        activated_configs: list[NamespaceConfig | RootConfig] = []  # Track what was actually activated

        for ns_cfg in cfg.namespaces or []:
            log.info(
                f"Activating namespace {ns_cfg.namespace} for interface {ns_cfg.interface}"
            )
            result = ns.activate_config(ns_cfg)
            status = getattr(result, "status", "error") if result is not None else "error"
            outcomes.append(status)
            # Only track as activated if it succeeded (not error, not skipped)
            if status in {"connected", "provisioned"}:
                activated_configs.append(ns_cfg)

        for root_cfg in cfg.roots or []:
            log.info(f"Activating root config for interface {root_cfg.interface}")
            result = ns.activate_config(root_cfg)
            status = getattr(result, "status", "error") if result is not None else "error"
            outcomes.append(status)
            # Only track as activated if it succeeded (not error, not skipped)
            if status in {"connected", "provisioned"}:
                activated_configs.append(root_cfg)

        # Determine if activation should be persisted
        acceptable_statuses = {"connected", "provisioned"}
        all_ok = all(status in acceptable_statuses for status in outcomes) if outcomes else True

        if all_ok:
            ccf.write_text(cfg_id)
            return True
        else:
            log.error(f"Activation outcomes unacceptable {outcomes}. Rolling back only successfully activated configs")
            # Only deactivate configs that were actually activated
            for activated_cfg in activated_configs:
                try:
                    ns.deactivate_config(activated_cfg)
                except Exception as e:
                    log.warning(f"Error deactivating config for {activated_cfg.interface}: {e} (non-critical)")
            return False

    except Exception as ex:
        # Do not roll back here; a provisioned (not connected) outcome should
        # leave the configuration active. Only report the error upward.
        log.error(f"Failed to activate config {cfg_id}: {ex}")
        raise


def deactivate_config(cfg_id: str, override_active: bool = False) -> bool:
    """Deactivate a configuration by cfg_id."""
    path = cfg_dir / f"{cfg_id}.json"

    cfg = get_config(cfg_id)
    if not override_active:
        if not is_active(cfg_id):
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
        # activate_config("default", override_active=True)
        ns.revert_to_root(None)
        return True

    except Exception as ex:
        log.error(f"Failed to deactivate config {cfg_id}: {ex}")
        raise
