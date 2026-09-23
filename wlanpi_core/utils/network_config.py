"""CRUD helpers for persistent network configurations."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from wlanpi_core.adapters import discovery
from wlanpi_core.constants import CONFIG_DIR, CURRENT_CONFIG_FILE, RUN_DIR
from wlanpi_core.models.network_config_errors import (
    ConfigActiveError,
    ConfigBusyError,
    ConfigMalformedError,
)
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas.network.network import (
    NamespaceConfig,
    NetConfig,
    NetConfigUpdate,
    NetSecurity,
    NetworkModeEnum,
    RootConfig,
    SecurityTypes,
)
from wlanpi_core.services.network_namespace_service import NetworkNamespaceService
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.validation import validate_config_id

log = logging.getLogger(__name__)

ns = NetworkNamespaceService()

cfg_dir = Path(CONFIG_DIR)
ccf = Path(CURRENT_CONFIG_FILE)


@contextmanager
def network_change_lock() -> Iterator[None]:
    """Hold the process-wide lock for changing adapter and namespace state.

    An flock on a file under /run, so it excludes other threads (each call
    opens its own file description) and other processes, such as an old
    gunicorn worker still finishing during a reload. Does not wait.

    Not reentrant: acquiring it again while held, even in the same thread,
    raises ConfigBusyError. Code already holding it (activate's rollback)
    must call the unlocked service methods, not deactivate_config(). The
    lock does not cover ConnectionMonitor threads, which run DHCP, routes
    and app start after the change that started them has returned.

    Raises:
        ConfigBusyError: If another activate, deactivate or revert is running
    """
    path = Path(RUN_DIR) / "netcfg.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ConfigBusyError(
                "Another network configuration change is in progress; try again."
            ) from None
        yield
    finally:
        os.close(fd)


def _atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    """Replace `path` with `text` so readers never see a partial file.

    Writes a sibling temp file with `mode` (0600 by default, since profiles
    hold PSKs), fsyncs it, then renames it over `path`.
    """
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _write_current(cfg_id: str) -> None:
    # current.txt holds no secret and may be read by other wlanpi tools.
    _atomic_write(ccf, cfg_id, mode=0o644)


# IDs that clash with the built-in default, the root namespace or the
# /network/config/status route, in any letter case.
_RESERVED_IDS = {"default", "root", "status"}


def _reject_reserved_id(cfg_id: str) -> None:
    if cfg_id.lower() in _RESERVED_IDS:
        raise ValidationError(
            f"Configuration ID {cfg_id!r} is reserved.", status_code=400
        )


def _config_path(cfg_id: str) -> Path:
    try:
        validated_id = validate_config_id(cfg_id)
    except ValueError as error:
        raise ValidationError(str(error), status_code=400) from error
    # validate_config_id already forbids "/", "." and ".."; this normpath +
    # prefix check is the confinement CodeQL's py/path-injection recognises.
    base = os.path.normpath(cfg_dir)
    path = os.path.normpath(os.path.join(base, f"{validated_id}.json"))
    if not path.startswith(base + os.sep):
        raise ValidationError("Invalid configuration ID", status_code=400)
    return Path(path)


def _legacy_default_config(cfg_id: str = "default") -> NetConfig:
    """Return the hardcoded default shipped before #202, for migration only."""
    return NetConfig(
        id=cfg_id,
        namespaces=[],
        roots=[
            RootConfig(
                mode=NetworkModeEnum.managed,
                iface_display_name="wlan0",
                phy="phy0",
                interface="wlan0",
                security=NetSecurity(
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
            ),
        ],
    )


def _is_system_monitor(name: str) -> bool:
    return name.startswith("wlanpi") and name.removeprefix("wlanpi").isdigit()


def get_default_config(cfg_id: str = "default") -> NetConfig:
    """Build the default configuration from the radios present now.

    One root entry per wireless interface in root or in a namespace Core
    created, on the phy it is really on, keeping monitor interfaces in monitor mode. No security and no
    default route: the default returns radios to root without connecting.
    The `wlanpiN` monitor interfaces that SystemManager creates at startup
    (with its own flags) are left out, as are radios in namespaces Core did
    not create: the default must not claim a user's or another tool's radio.
    """
    core_namespaces = set(ns.core_namespaces())
    roots: list[RootConfig] = []
    for live in discovery.list_interfaces_all_namespaces():
        if live.netns is not None and live.netns not in core_namespaces:
            continue
        if live.type == "monitor" and _is_system_monitor(live.name):
            continue
        if any(r.interface == live.name for r in roots):
            # The same name in root and a Core namespace is legal, but one
            # NetConfig cannot hold both; root is listed first and wins.
            log.warning(
                f"{live.name} exists in more than one namespace; leaving the "
                f"{live.netns or 'root'} one out of the default"
            )
            continue
        roots.append(
            RootConfig(
                mode=(
                    NetworkModeEnum.monitor
                    if live.type == "monitor"
                    else NetworkModeEnum.managed
                ),
                iface_display_name=live.name,
                phy=f"phy{live.phy_index}",
                interface=live.name,
                security=None,
                default_route=False,
                autostart_app=None,
            )
        )
    return NetConfig(id=cfg_id, namespaces=[], roots=roots)


def parse_iw_dev_output(output: str) -> dict[str, Any]:
    """Parse iw dev output into dict."""
    interfaces: dict[str, Any] = {}
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
    """Return the root-interface names for a configuration."""
    cfg = get_config(cfg_id)

    root = cfg.roots or []
    return [r.interface for r in root]


def list_configs() -> dict[str, bool]:
    """List all configuration files in the CONFIG_DIR directory."""
    configs = {}
    active_id = ccf.read_text().strip() if ccf.exists() else None

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
                    log.warning(
                        f"Configuration file {cfg_file.name} has invalid structure."
                    )
                    annotation = "(malformed)"
        except json.JSONDecodeError as e:
            log.warning(
                f"Configuration file {cfg_file.name} contains malformed JSON: {e}."
            )
            annotation = "(malformed)"
        except OSError as e:
            log.warning(f"Error reading configuration file {cfg_file.name}: {e}.")
            annotation = "(malformed)"

        # Annotate the key name if there's an issue
        key = f"{cfg_stem} {annotation}" if annotation else cfg_stem

        # Check if this config is active (using original stem name for comparison)
        is_active = active_id == cfg_stem
        configs[key] = is_active

    return configs


def status() -> dict[str, Any]:
    """Return the per-namespace `iw dev` adapter layout."""
    namespaces_output = run_command(["sudo", "ip", "netns", "list"])
    namespaces = []
    for line in namespaces_output.stdout.splitlines():
        namespaces.append(line.split(" ")[0])

    final_status: dict[str, Any] = {}

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
    path = _config_path(cfg_id)
    if not path.exists():
        # Only create default config if requesting the "default" config
        if cfg_id == "default":
            log.info("Default configuration file not found. Creating default config.")
            return _write_live_default()
        raise FileNotFoundError(f"Configuration {cfg_id} not found.")

    try:
        file_content = path.read_text().strip()
        if not file_content:
            log.error(f"Configuration file {cfg_id}.json is empty.")
            raise ConfigMalformedError(
                f"Configuration file {cfg_id}.json is empty or contains only whitespace.",
                cfg_id=cfg_id,
            )

        data = json.loads(file_content)
        config = NetConfig(**data)
        if cfg_id == "default" and config == _legacy_default_config():
            # Devices upgraded from before #202 still hold the hardcoded
            # default (fake WPA2 on wlan0, wlan1 on phy1); replace it.
            log.info("Replacing the legacy hardcoded default configuration.")
            return _write_live_default()
        return config
    except json.JSONDecodeError as e:
        log.error(f"Configuration file {cfg_id}.json contains malformed JSON: {e}")
        raise ConfigMalformedError(
            f"Configuration file {cfg_id}.json contains malformed JSON: {e}",
            cfg_id=cfg_id,
        ) from None
    except ConfigMalformedError:
        raise
    except (OSError, TypeError, PydanticValidationError) as e:
        log.error(f"Failed to parse configuration {cfg_id}: {e}")
        raise ConfigMalformedError(
            f"Failed to parse configuration {cfg_id}: {e}", cfg_id=cfg_id
        ) from None


def _write_live_default() -> NetConfig:
    # shortcut: default.json snapshots the radios present when it is first
    # written; an adapter plugged in later is not in it until the file is
    # deleted. Upgrade path: regenerate while the file is unedited.
    try:
        default_config = get_default_config("default")
    except Exception as e:
        # Core must start even when the live inventory cannot be read or
        # yields an invalid default; nothing is written, so the next start
        # tries again.
        log.error(f"Could not build the default configuration: {e}")
        return NetConfig(id="default", namespaces=[], roots=[])
    # A fixed name (not a caller's ID), so no user data reaches this path.
    _atomic_write(cfg_dir / "default.json", default_config.model_dump_json(indent=4))
    return default_config


def is_active(cfg_id: str) -> bool:
    """Return whether the configuration is currently active."""
    try:
        if get_current_config() == cfg_id:
            return True
    except ConfigMalformedError:
        # If current config is malformed, it's not the requested cfg_id
        pass
    return False


def _revert_current_config_to_default() -> None:
    _write_current("default")


def get_current_config() -> str:
    """Get the currently active configuration cfg_id without mutating current.txt."""
    if not ccf.exists():
        raise FileNotFoundError("No current configuration set.")

    content = ccf.read_text().strip()
    if not content:
        log.error("Current configuration file is empty or contains only whitespace.")
        raise ConfigMalformedError(
            "Current configuration file is empty or contains only whitespace.",
            cfg_id=None,
        )

    try:
        get_config(content)
    except (FileNotFoundError, ConfigMalformedError) as e:
        error_msg = getattr(e, "message", str(e))
        log.error(f"Current configuration '{content}' is invalid: {error_msg}")
        raise ConfigMalformedError(
            f"Current configuration '{content}' is invalid or malformed: {error_msg}",
            cfg_id=content,
        ) from None

    return content


def recover_current_config() -> str:
    """
    Validate current.txt and rewrite it to default when malformed.

    Used at startup and in recovery paths where a getter side-effect is required.
    """
    try:
        return get_current_config()
    except ConfigMalformedError as e:
        _revert_current_config_to_default()
        raise ConfigMalformedError(
            f"{e.message}. Reverted to 'default'.",
            cfg_id=e.cfg_id,
        ) from e


def _rollback_activated_configs(
    activated_configs: list[NamespaceConfig | RootConfig],
) -> None:
    """Deactivate entries that were applied before a failed multi-adapter activation.

    Used for UNACCEPTABLE failures (status=error or raised exceptions). Not used when
    all per-adapter outcomes are connected/provisioned — see activate_config().
    """
    for activated_cfg in activated_configs:
        try:
            ns.deactivate_config(activated_cfg)
        except Exception as e:
            log.warning(
                f"Error deactivating config for {activated_cfg.interface}: {e} (non-critical)"
            )


def add_config(config: NetConfig) -> bool:
    """Add a new configuration."""
    _reject_reserved_id(config.id)
    path = _config_path(config.id)
    if path.exists():
        raise FileExistsError(f"Configuration {config.id} already exists.")
    _atomic_write(path, config.model_dump_json(indent=4))
    return True


def _keep_stored_secrets(stored: NetConfig, updated: NetConfig) -> None:
    """Keep an entry's stored psk/password when an update omits them (#272).

    The API never returns secrets, so a client that edits and sends back an
    entry cannot include them. Entries are matched by (namespace, interface).
    """

    def by_key(cfg: NetConfig) -> dict[tuple[str | None, str], Any]:
        entries: dict[tuple[str | None, str], Any] = {}
        for ns_entry in cfg.namespaces or []:
            entries[(ns_entry.namespace, ns_entry.interface)] = ns_entry
        for root_entry in cfg.roots or []:
            entries[(None, root_entry.interface)] = root_entry
        return entries

    old_entries = by_key(stored)
    for key, entry in by_key(updated).items():
        old = old_entries.get(key)
        if old is None or old.security is None or entry.security is None:
            continue
        if entry.security.psk is None and old.security.psk:
            entry.security.psk = old.security.psk
        if entry.security.password is None and old.security.password:
            entry.security.password = old.security.password


def edit_config(cfg_id: str, config_update: NetConfigUpdate) -> NetConfig:
    """Edit an existing configuration."""
    path = _config_path(cfg_id)
    cfg = get_config(cfg_id)

    if is_active(cfg_id):
        raise ConfigActiveError(f"Cannot edit active configuration {cfg_id}.")

    stored = cfg.model_copy(deep=True)
    for field in type(config_update).model_fields:
        value = getattr(config_update, field)
        if value is not None and field != "cfg_id":
            setattr(cfg, field, value)
    # setattr skips model validation; re-run it (uniqueness across entries)
    try:
        cfg = NetConfig.model_validate(cfg.model_dump())
    except PydanticValidationError as e:
        raise ValidationError(str(e), status_code=422) from None
    _keep_stored_secrets(stored, cfg)

    # Write updated config back to file
    _atomic_write(path, cfg.model_dump_json(indent=4))

    return cfg


def delete_config(cfg_id: str, force: bool = False) -> bool:
    """Delete a configuration by cfg_id.

    The active configuration is refused unless `force`, which deactivates it
    first so current.txt never names a file that no longer exists.
    """
    path = _config_path(cfg_id)

    # Under the change lock, so no activation can make cfg_id active again
    # between the deactivate and the unlink.
    with network_change_lock():
        if is_active(cfg_id):
            if not force:
                raise ConfigActiveError(f"Cannot delete active configuration {cfg_id}.")
            _deactivate_config_locked(cfg_id, False)
        path.unlink()
    return True


def activate_config(cfg_id: str, override_active: bool = False) -> bool:
    """Activate a configuration by cfg_id.

    Multi-adapter activation has three distinct outcomes (see tests/scenarios/ACTIVATION_OUTCOMES.md):

    1. **Persist (no rollback)** — every adapter returns connected or provisioned.
       Includes tolerated cases: missing interface (provisioned skip), delayed SSID
       (provisioned + background monitor), pre-staged WPA. Writes cfg_id to current.txt.

    2. **Rollback via return False** — loop completes but any outcome is status=error
       (UNACCEPTABLE hw fault). Deactivates only entries in activated_configs; ccf unchanged.

    3. **Rollback via exception** — ns.activate_config() raises mid-loop (same severity as
       status=error). Deactivates activated_configs, re-raises; ccf unchanged.

    Provisioned-but-not-yet-connected is success path (1), not rollback.

    Raises ConfigBusyError if another change holds network_change_lock().
    """
    with network_change_lock():
        return _activate_config_locked(cfg_id, override_active)


def _activate_config_locked(cfg_id: str, override_active: bool) -> bool:
    cfg = get_config(cfg_id)
    try:
        active_cfg = get_current_config()
    except ConfigMalformedError:
        # Malformed current.txt blocks activation pre-check; repair inline (same as recover path)
        _revert_current_config_to_default()
        active_cfg = "default"
    except FileNotFoundError:
        # Treat missing current-config as default (first-run scenario)
        active_cfg = "default"

    if not override_active:
        if active_cfg != cfg_id and active_cfg != "default":
            raise ConfigActiveError(
                f"Another configuration is currently active: {active_cfg}."
            )

        if active_cfg == cfg_id:
            raise ConfigActiveError(f"Configuration {cfg_id} is already active.")

    # Tear down the active profile first so its namespaces, supplicants and
    # apps do not linger beside the new one (#271).
    _teardown_profile(active_cfg)
    if override_active:
        log.info(
            "Override active set: stopping Core's wpa_supplicants before activation"
        )
        ns.kill_all_supplicants()

    activated_configs: list[NamespaceConfig | RootConfig] = []
    try:
        outcomes = _apply_entries(cfg, activated_configs)

        # Path 1 vs 2: provisioned and connected are both acceptable — do not roll back
        # partial success (missing adapter, delayed SSID, etc.) when all outcomes qualify.
        acceptable_statuses = {"connected", "provisioned"}
        if all(status in acceptable_statuses for status in outcomes):
            # Path 1: persist active config (monitors may still be connecting WPA)
            _write_current(cfg_id)
            return True
        # Path 2: UNACCEPTABLE status=error — roll back adapters that were applied
        log.error(
            f"Activation outcomes unacceptable {outcomes}. Rolling back only successfully activated configs"
        )
        _rollback_activated_configs(activated_configs)
        _fall_back_to_default(cfg_id)
        return False

    except Exception as ex:
        # Path 3: hard failure mid-loop — same rollback as path 2, then propagate
        log.error(f"Failed to activate config {cfg_id}: {ex}")
        if activated_configs:
            log.error(
                "Rolling back successfully activated configs after activation exception"
            )
            _rollback_activated_configs(activated_configs)
        _fall_back_to_default(cfg_id)
        raise


def _apply_entries(
    cfg: NetConfig, activated: list[NamespaceConfig | RootConfig]
) -> list[str]:
    """Activate every entry of cfg, namespaces first; return per-entry statuses.

    Entries that come up connected or provisioned are appended to `activated`
    as they succeed, so a caller can roll them back after an exception.
    """
    outcomes: list[str] = []
    entries: list[NamespaceConfig | RootConfig] = [
        *(cfg.namespaces or []),
        *(cfg.roots or []),
    ]
    for entry in entries:
        where = entry.namespace if isinstance(entry, NamespaceConfig) else "root"
        log.info(f"Activating {entry.interface} in {where}")
        result = ns.activate_config(entry)
        status = getattr(result, "status", "error") if result is not None else "error"
        outcomes.append(status)
        if status in {"connected", "provisioned"}:
            activated.append(entry)
    return outcomes


def _teardown_profile(cfg_id: str) -> None:
    """Best effort: deactivate cfg_id's entries and return Core's namespaces."""
    try:
        profile: NetConfig | None = get_config(cfg_id)
    except (FileNotFoundError, ConfigMalformedError, ValidationError) as e:
        log.warning(f"Cannot read active configuration {cfg_id} to tear down: {e}")
        profile = None
    entries: list[NamespaceConfig | RootConfig] = []
    if profile is not None:
        entries = [*(profile.namespaces or []), *(profile.roots or [])]
    for entry in entries:
        try:
            ns.deactivate_config(entry)
        except Exception as e:
            log.warning(f"Error tearing down {entry.interface} from {cfg_id}: {e}")
    ns.revert_to_root(None)


def _fall_back_to_default(failed_cfg_id: str) -> None:
    """After a failed activation, record and apply `default` so state matches."""
    _write_current("default")
    if failed_cfg_id != "default":
        _apply_default()


def _apply_default() -> None:
    """Best effort: put the radios into the default configuration."""
    try:
        outcomes = _apply_entries(get_config("default"), [])
        log.info(f"Applied default configuration: {outcomes}")
    except Exception as e:
        log.warning(f"Could not apply default configuration: {e}")


def deactivate_config(cfg_id: str, override_active: bool = False) -> bool:
    """Deactivate a configuration by cfg_id.

    On per-adapter failure mid-loop, still writes current.txt to default and calls
    revert_to_root so ccf and runtime state stay consistent before re-raising.

    Raises ConfigBusyError if another change holds network_change_lock().
    """
    with network_change_lock():
        return _deactivate_config_locked(cfg_id, override_active)


def _deactivate_config_locked(cfg_id: str, override_active: bool) -> bool:
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

        _write_current("default")
        ns.revert_to_root(None)
        # current.txt now says default, so apply it (#271)
        if cfg_id != "default":
            _apply_default()
        return True

    except Exception as ex:
        log.error(f"Failed to deactivate config {cfg_id}: {ex}")
        # Ensure ccf/revert complete even when a later adapter raises (mirror activate rollback)
        try:
            _write_current("default")
            ns.revert_to_root(None)
        except Exception as cleanup_error:
            log.warning(
                f"Error completing deactivate cleanup for {cfg_id}: {cleanup_error} (non-critical)"
            )
        if cfg_id != "default":
            _apply_default()
        raise
