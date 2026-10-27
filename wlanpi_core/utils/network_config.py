"""CRUD helpers for persistent network configurations."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from wlanpi_core.adapters import discovery
from wlanpi_core.constants import CONFIG_DIR, CURRENT_CONFIG_FILE, RUN_DIR
from wlanpi_core.core.transmit_policy import refusal_detail
from wlanpi_core.models.network_config_errors import (
    ConfigActiveError,
    ConfigBusyError,
    ConfigMalformedError,
)
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas.network.network import (
    AdapterOutcome,
    LeftAlone,
    NamespaceConfig,
    NamespaceResetResult,
    NetConfig,
    NetConfigUpdate,
    NetSecurity,
    NetworkModeEnum,
    RootConfig,
    SecurityTypes,
)
from wlanpi_core.services.network_namespace_service import NetworkNamespaceService
from wlanpi_core.services.platform_cache import resolve_model
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


# IDs that clash with the built-in default, the root namespace or /network/config/* routes, in any case.
_RESERVED_IDS = {"default", "root", "status", "leftovers", "reset"}


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

    One root entry, with no security or default route, per wireless interface in
    root or a Core namespace, on its real phy and keeping monitor mode.
    SystemManager's `wlanpiN` monitors and radios in others' namespaces are left out.
    """
    core_namespaces = set(ns.core_namespaces())
    roots: list[RootConfig] = []
    for live in discovery.list_interfaces_all_namespaces():
        if live.netns is not None and live.netns not in core_namespaces:
            continue
        if live.type == "monitor" and _is_system_monitor(live.name):
            continue
        if any(r.interface == live.name for r in roots):
            # One NetConfig cannot hold a name twice; root, listed first, wins.
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
    current_wiphy = None
    skip_table_block = False

    for line in output.splitlines():
        line = line.rstrip()
        if not line.strip():
            skip_table_block = False
            continue

        # `iw dev` names the PHY only in its unindented "phy#N" header; it
        # also ends the previous interface's block (and any table in it).
        if line.startswith("phy#"):
            current_wiphy = line[len("phy#") :]
            current_iface = None
            skip_table_block = False
            continue

        if line.lstrip().startswith("Interface "):
            current_iface = line.strip().split()[1]
            interfaces[current_iface] = (
                {} if current_wiphy is None else {"wiphy": current_wiphy}
            )
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

        key = f"{cfg_stem} {annotation}" if annotation else cfg_stem

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
            log.warning(
                f"Failed to get status for namespace '{ns_name}': {e}. "
                f"This namespace may be corrupted or invalid. Skipping."
            )
            final_status[ns_name] = {"error": str(e)}
        except Exception as e:
            log.warning(
                f"Unexpected error getting status for namespace '{ns_name}': {e}. Skipping."
            )
            final_status[ns_name] = {"error": str(e)}

    return final_status


def get_config(cfg_id: str) -> NetConfig:
    """Get a specific configuration by cfg_id."""
    path = _config_path(cfg_id)
    if not path.exists():
        if cfg_id == "default":
            log.info("Default configuration file not found. Creating default config.")
            return _write_live_default()
        raise FileNotFoundError(f"Configuration {cfg_id} not found.")

    try:
        return _read_config(cfg_id, path)
    except ConfigMalformedError as e:
        if cfg_id != "default":
            raise
        # Core activates default.json at boot; a broken one would fail every start.
        bad = path.with_name(f"default.json.bad-{time.strftime('%Y%m%dT%H%M%S')}")
        path.replace(bad)
        log.error(
            f"Default configuration is unusable ({e.message}); moved it to {bad.name} and regenerating it."
        )
        return _write_live_default()


def _read_config(cfg_id: str, path: Path) -> NetConfig:
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
            # Devices upgraded from before #202 still hold it.
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
    # ponytail: snapshots radios at first write; a later adapter needs the file
    # deleted. Upgrade: regenerate while the file is unedited.
    try:
        default_config = get_default_config("default")
    except Exception as e:
        # Core must start anyway; nothing is written, so the next start retries.
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
    """Deactivate entries applied before a failed activation, best effort."""
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

    _atomic_write(path, cfg.model_dump_json(indent=4))

    return cfg


def delete_config(cfg_id: str, force: bool = False) -> bool:
    """Delete a configuration by cfg_id.

    The active configuration is refused unless `force`, which deactivates it
    first so current.txt never names a file that no longer exists.
    """
    path = _config_path(cfg_id)

    # Locked so no activation can make cfg_id active between deactivate and unlink.
    with network_change_lock():
        if is_active(cfg_id):
            if not force:
                raise ConfigActiveError(f"Cannot delete active configuration {cfg_id}.")
            _deactivate_config_locked(cfg_id, False)
        path.unlink()
    return True


def activate_config(cfg_id: str, override_active: bool = False) -> bool:
    """Activate a configuration by cfg_id; see tests/scenarios/ACTIVATION_OUTCOMES.md.

    cfg_id is recorded when every entry is connected, provisioned, skipped or
    in_use. An invalid entry stops it before any change. A failed entry rolls
    back the applied ones and records `default`; False is returned, or the
    exception re-raised.

    Raises:
        ConfigBusyError: If another change holds network_change_lock().
    """
    return activate_config_report(cfg_id, override_active)[0]


def activate_config_report(
    cfg_id: str, override_active: bool = False
) -> tuple[bool, list[AdapterOutcome]]:
    """Activate cfg_id as activate_config does, and report each entry's outcome."""
    with network_change_lock():
        return _activate_config_locked(cfg_id, override_active)


def _activate_config_locked(
    cfg_id: str, override_active: bool
) -> tuple[bool, list[AdapterOutcome]]:
    cfg = get_config(cfg_id)
    try:
        active_cfg = get_current_config()
    except ConfigMalformedError:
        _revert_current_config_to_default()
        active_cfg = "default"
    except FileNotFoundError:
        active_cfg = "default"

    if not override_active:
        if active_cfg != cfg_id and active_cfg != "default":
            raise ConfigActiveError(
                f"Another configuration is currently active: {active_cfg}."
            )

        if active_cfg == cfg_id:
            raise ConfigActiveError(f"Configuration {cfg_id} is already active.")

    refusal = _transmit_refusal(cfg)
    if refusal is not None:
        log.error(f"Configuration {cfg_id} not activated: {refusal}")
        if active_cfg == cfg_id:
            try:
                _teardown_profile(cfg_id)
            finally:
                _fall_back_to_default(cfg_id)
        raise ValidationError(refusal, status_code=403)

    # Validate every entry before touching any radio, so an invalid entry
    # cannot cost a valid sibling its interface (#261).
    invalid_outcomes = _invalid_entries(cfg, only_core_managed=cfg_id == "default")
    if invalid_outcomes:
        log.error(
            f"Configuration {cfg_id} is invalid, nothing changed: "
            f"{[o.detail for o in invalid_outcomes]}"
        )
        if active_cfg == cfg_id:
            # The active profile went invalid: tear it down and stop claiming it.
            try:
                _teardown_profile(cfg_id)
            finally:
                _fall_back_to_default(cfg_id)
        return False, invalid_outcomes

    # The old profile must not linger beside the new one (#271).
    _teardown_profile(active_cfg)
    if override_active:
        log.info(
            "Override active set: stopping Core's wpa_supplicants before activation"
        )
        ns.kill_all_supplicants()

    activated_configs: list[NamespaceConfig | RootConfig] = []
    try:
        outcomes = _apply_entries(
            cfg, activated_configs, only_core_managed=cfg_id == "default"
        )

        acceptable_statuses = {"connected", "provisioned", "skipped", "in_use"}
        if all(outcome.status in acceptable_statuses for outcome in outcomes):
            _write_current(cfg_id)
            return True, outcomes
        log.error(
            f"Activation outcomes unacceptable {[o.status for o in outcomes]}. Rolling back only successfully activated configs"
        )
        _rollback_activated_configs(activated_configs)
        _fall_back_to_default(cfg_id)
        return False, outcomes

    except Exception as ex:
        log.error(f"Failed to activate config {cfg_id}: {ex}")
        if activated_configs:
            log.error(
                "Rolling back successfully activated configs after activation exception"
            )
            _rollback_activated_configs(activated_configs)
        _fall_back_to_default(cfg_id)
        raise


def _transmit_refusal(cfg: NetConfig) -> str | None:
    entries = [*(cfg.roots or []), *(cfg.namespaces or [])]
    if not any(entry.security or entry.autostart_app for entry in entries):
        return None
    return refusal_detail(resolve_model())


def _invalid_entries(
    cfg: NetConfig, only_core_managed: bool = False
) -> list[AdapterOutcome]:
    """Return an error outcome for every entry that fails schema validation.

    With `only_core_managed`, entries whose radio Core did not create are not
    checked: _apply_entries reports them "skipped" without touching them.
    """
    outcomes: list[AdapterOutcome] = []
    for entry in [*(cfg.namespaces or []), *(cfg.roots or [])]:
        if only_core_managed and not ns.is_core_managed(entry):
            continue
        is_valid, detail = ns.validate_config(entry)
        if not is_valid:
            outcomes.append(
                AdapterOutcome(
                    interface=entry.interface,
                    namespace=entry.namespace
                    if isinstance(entry, NamespaceConfig)
                    else None,
                    status="error",
                    detail=detail,
                    invalid=True,
                )
            )
    return outcomes


def _apply_entries(
    cfg: NetConfig,
    activated: list[NamespaceConfig | RootConfig],
    only_core_managed: bool = False,
) -> list[AdapterOutcome]:
    """Activate every entry of cfg, namespaces first; return per-entry outcomes.

    Entries that come up connected or provisioned are appended to `activated`
    as they succeed, so a caller can roll them back after an exception. With
    `only_core_managed` (the default configuration), an entry whose radio
    Core did not create is reported "skipped" and not touched.
    """
    outcomes: list[AdapterOutcome] = []
    for entry in _all_entries(cfg):
        where = entry.namespace if isinstance(entry, NamespaceConfig) else "root"
        if only_core_managed and not ns.is_core_managed(entry):
            log.info(f"Leaving {entry.interface} in {where} alone: not created by Core")
            outcomes.append(
                AdapterOutcome(
                    interface=entry.interface,
                    namespace=entry.namespace
                    if isinstance(entry, NamespaceConfig)
                    else None,
                    status="skipped",
                    detail="Not created by Core; left alone",
                )
            )
            continue
        log.info(f"Activating {entry.interface} in {where}")
        result = ns.activate_config(entry)
        status = getattr(result, "status", "error") if result is not None else "error"
        detail = result.response.selectErr if result is not None else ""
        outcomes.append(
            AdapterOutcome(
                interface=entry.interface,
                namespace=entry.namespace
                if isinstance(entry, NamespaceConfig)
                else None,
                status=status,
                detail=detail,
                invalid=status == "error"
                and detail.startswith("Config validation failed"),
            )
        )
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
    entries = _all_entries(profile) if profile is not None else []
    for entry in entries:
        try:
            ns.deactivate_config(entry)
        except Exception as e:
            log.warning(f"Error tearing down {entry.interface} from {cfg_id}: {e}")
    ns.revert_to_root(None)


def revert_all() -> None:
    """Return every radio Core manages to root and make `default` active.

    Tears down the active configuration, returns every namespace Core created
    to root (deleting each once empty), then records `default`.
    Backs the deprecated /wlan/revert endpoint (#274).

    Raises:
        ConfigBusyError: If another change holds network_change_lock()
    """
    with network_change_lock():
        try:
            active = get_current_config()
        except (FileNotFoundError, ConfigMalformedError):
            active = "default"
        _teardown_profile(active)
        _write_current("default")


def _all_entries(cfg: NetConfig) -> list[NamespaceConfig | RootConfig]:
    """Return cfg's entries, namespaces first."""
    return [*(cfg.namespaces or []), *(cfg.roots or [])]


def _active_namespaces() -> set[str]:
    try:
        active = get_current_config()
        if active == "default":
            return set()
        return {entry.namespace for entry in get_config(active).namespaces or []}
    except (OSError, ConfigMalformedError, ValidationError):
        return set()


def left_alone() -> list[LeftAlone]:
    """Return the namespaces holding radios that Core has left alone."""
    return [LeftAlone(**entry) for entry in ns.left_alone(_active_namespaces())]


def reset_namespaces(names: list[str]) -> list[NamespaceResetResult]:
    """Return the radios in the named namespaces to root, deleting each once empty.

    Only the namespaces named are touched, whoever created them; one used by
    the active configuration is refused (deactivate it first).

    Raises:
        ConfigBusyError: If another change holds network_change_lock()
    """
    with network_change_lock():
        existing = {entry["namespace"] for entry in ns.left_alone(set())}
        in_use = _active_namespaces()
        results = []
        for name in names:
            if name in in_use:
                detail = "In use by the active configuration; deactivate it first"
                results.append(NamespaceResetResult(namespace=name, detail=detail))
            elif name not in existing:
                detail = "No such namespace holding radios"
                results.append(NamespaceResetResult(namespace=name, detail=detail))
            else:
                results.append(NamespaceResetResult(**ns.reset_namespace(name)))
        return results


def _fall_back_to_default(failed_cfg_id: str) -> None:
    """Record `default` after a failed activation; rollback already undid what was applied."""
    _write_current("default")


def deactivate_config(cfg_id: str, override_active: bool = False) -> bool:
    """Deactivate a configuration by cfg_id.

    If an entry raises, `default` is still recorded and Core's namespaces
    reverted before re-raising.

    Raises:
        ConfigBusyError: If another change holds network_change_lock().
    """
    with network_change_lock():
        return _deactivate_config_locked(cfg_id, override_active)


def _deactivate_config_locked(cfg_id: str, override_active: bool) -> bool:
    cfg = get_config(cfg_id)
    if not override_active:
        if not is_active(cfg_id):
            raise ConfigActiveError(f"Configuration {cfg_id} is not active.")

    try:
        for entry in _all_entries(cfg):
            where = entry.namespace if isinstance(entry, NamespaceConfig) else "root"
            log.info(f"Deactivating {entry.interface} in {where}")
            ns.deactivate_config(entry)

        _write_current("default")
        ns.revert_to_root(None)
        return True

    except Exception as ex:
        log.error(f"Failed to deactivate config {cfg_id}: {ex}")
        try:
            _write_current("default")
            ns.revert_to_root(None)
        except Exception as cleanup_error:
            log.warning(
                f"Error completing deactivate cleanup for {cfg_id}: {cleanup_error} (non-critical)"
            )
        raise
