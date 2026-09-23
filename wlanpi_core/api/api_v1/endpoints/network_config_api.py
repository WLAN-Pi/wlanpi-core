"""Network configuration CRUD and activation endpoints."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.core.logging import get_logger
from wlanpi_core.core.mode_guard import require_wlan_management_enabled
from wlanpi_core.models.network_config_errors import (
    ConfigActiveError,
    ConfigBusyError,
    ConfigMalformedError,
)
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas.network.config_status import NetworkConfigStatus
from wlanpi_core.schemas.network.network import (
    ActivationResponse,
    DeactivationResponse,
    LeftoversResponse,
    NamespaceResetRequest,
    NamespaceResetResponse,
    NetConfig,
    NetConfigPublic,
    NetConfigUpdate,
)
from wlanpi_core.utils import network_config

router = APIRouter()

log = get_logger(__name__)


@router.get(
    "/status",
    response_model=NetworkConfigStatus,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def get_status() -> Any:
    """
    Per-namespace `iw dev` adapter layout (`root` plus each netns).

    Namespace values are interface maps or `{ "error": "…" }` when a netns could
    not be queried.
    """
    try:
        status = await asyncio.to_thread(network_config.status)
        log.info("Network configuration status retrieved successfully")
        return status
    except Exception as ex:
        log.error(f"Error retrieving network configuration status: {ex}")
        raise HTTPException(status_code=500, detail="Internal Server Error") from None


@router.get(
    "/",
    response_model=dict[str, bool],
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def get_configs() -> Any:
    """Get all network configuration ids."""
    try:
        configs = await asyncio.to_thread(network_config.list_configs)
        log.info("Retrieved all configurations")
        return configs
    except ValidationError as ve:
        raise HTTPException(status_code=ve.status_code, detail=ve.error_msg) from None
    except Exception as ex:
        log.error(ex)
        raise HTTPException(status_code=500, detail="Internal Server Error") from None


@router.get(
    "/leftovers",
    response_model=LeftoversResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def get_leftovers() -> Any:
    """
    List namespaces holding radios that Core has left alone.

    That is a namespace Core created that is still present outside the
    active configuration, or any other namespace that holds wireless phys or
    interfaces. Core never clears these on its own; clear them with
    `POST /network/config/reset`.
    """
    try:
        left = await asyncio.to_thread(network_config.left_alone)
        return LeftoversResponse(left_alone=left)
    except Exception as ex:
        log.error(ex)
        raise HTTPException(status_code=500, detail="Internal Server Error") from None


@router.post(
    "/reset",
    response_model=NamespaceResetResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def reset_namespaces(request: NamespaceResetRequest) -> Any:
    """
    Return the radios in the named namespaces to root.

    Only the namespaces listed are touched, whoever created them: every phy
    in each is moved to the root namespace and the namespace is deleted once
    empty. Processes running inside are not stopped. A namespace used by the
    active configuration is refused (deactivate it first). Each result says
    what happened. Returns 409 while another network change is running.
    """
    try:
        require_wlan_management_enabled()
        results = await asyncio.to_thread(
            network_config.reset_namespaces, request.namespaces
        )
        return NamespaceResetResponse(results=results)
    except ConfigBusyError as cbe:
        raise HTTPException(status_code=409, detail=cbe.message) from None
    except ValidationError as ve:
        raise HTTPException(status_code=ve.status_code, detail=ve.error_msg) from None
    except HTTPException:
        raise
    except Exception as ex:
        log.error(ex)
        raise HTTPException(status_code=500, detail="Internal Server Error") from None


@router.get(
    "/{id}",
    response_model=NetConfigPublic,
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def get_config_by_id(id: str) -> Any:
    """
    Get a specific network configuration by ID.

    Secrets are never returned: each `security` block has `psk_set` and
    `password_set` instead of `psk` and `password`.
    """
    try:
        config = network_config.get_config(id)
        log.info(f"Retrieved configuration: {config.id}")
        return NetConfigPublic.from_config(config)
    except FileNotFoundError as e:
        log.error(f"Configuration not found: {e}")
        raise HTTPException(status_code=404, detail=str(e)) from None
    except ConfigMalformedError as cme:
        log.error(f"Configuration is malformed: {cme}")
        raise HTTPException(status_code=422, detail=cme.message) from None
    except ValidationError as ve:
        raise HTTPException(status_code=ve.status_code, detail=ve.error_msg) from None
    except Exception as ex:
        log.error(ex)
        raise HTTPException(status_code=500, detail="Internal Server Error") from None


@router.post(
    "/",
    response_model=dict[str, str],
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def create_config(config: NetConfig) -> Any:
    """
    Create a new network configuration.

    The IDs `default`, `root` and `status` are reserved in any letter case
    and return 400.
    """
    try:
        success = network_config.add_config(config)
        if not success:
            log.error(f"Failed to add configuration: {config.id}")
            raise HTTPException(status_code=500, detail="Failed to add configuration")
        log.info(f"Configuration added: {config.id}")
        return {"id": config.id, "message": "Configuration added successfully"}
    except FileExistsError as e:
        log.error(f"Configuration already exists: {e}")
        raise HTTPException(status_code=409, detail=str(e)) from None
    except ValidationError as ve:
        raise HTTPException(status_code=ve.status_code, detail=ve.error_msg) from None
    except Exception as ex:
        log.error(ex)
        raise HTTPException(status_code=500, detail="Internal Server Error") from None


@router.patch(
    "/{id}",
    response_model=dict[str, NetConfigPublic | str],
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def update_config(id: str, config_update: NetConfigUpdate) -> Any:
    """
    Update an existing network configuration.

    `roots` and `namespaces` replace the stored lists. An entry sent without
    `psk` or `password` keeps the stored secret for the same namespace and
    interface, so a configuration read with GET can be edited and sent back.
    The response omits secrets like GET does.
    """
    try:
        config = network_config.edit_config(id, config_update)
        if not config:
            log.error(f"Failed to update configuration: {id}")
            raise HTTPException(
                status_code=500, detail="Failed to update configuration"
            )
        log.info(f"Configuration updated: {id}")
        return {
            "id": id,
            "message": "Configuration updated successfully",
            "config": NetConfigPublic.from_config(config),
        }
    except FileNotFoundError as e:
        log.error(f"Configuration not found: {e}")
        raise HTTPException(status_code=404, detail=str(e)) from None
    except ConfigActiveError as cae:
        log.error(f"Active configuration cannot be updated: {cae}")
        raise HTTPException(status_code=409, detail=str(cae)) from None
    except ValidationError as ve:
        raise HTTPException(status_code=ve.status_code, detail=ve.error_msg) from None
    except Exception as ex:
        log.error(ex)
        raise HTTPException(status_code=500, detail="Internal Server Error") from None


@router.delete(
    "/{id}",
    response_model=dict[str, str],
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def delete_config(id: str, force: bool = False) -> Any:
    """
    Delete a network configuration by ID.

    Deleting the active configuration returns 409 unless `force=true`, which
    deactivates it first (the default configuration becomes active).
    """
    try:
        success = await asyncio.to_thread(network_config.delete_config, id, force)
        if not success:
            log.error(f"Failed to delete configuration: {id}")
            raise HTTPException(
                status_code=400, detail="Failed to delete configuration"
            )
        log.info(f"Configuration deleted: {id}")
        return {"id": id, "message": "Configuration deleted successfully"}
    except ConfigActiveError as cae:
        log.error(f"Active configuration cannot be deleted: {cae}")
        raise HTTPException(status_code=409, detail=str(cae)) from None
    except ConfigBusyError as cbe:
        raise HTTPException(status_code=409, detail=cbe.message) from None
    except FileNotFoundError as e:
        log.error(f"Configuration not found: {e}")
        raise HTTPException(status_code=404, detail=str(e)) from None
    except ValidationError as ve:
        raise HTTPException(status_code=ve.status_code, detail=ve.error_msg) from None
    except Exception as ex:
        log.error(ex)
        raise HTTPException(status_code=500, detail="Internal Server Error") from None


@router.post(
    "/activate/{id}",
    response_model=ActivationResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def activate_config(id: str, override_active: bool = False) -> Any:
    """
    Activate a network configuration by ID.

    The response lists one outcome per entry (`connected`, `provisioned`, or
    `error` with a `detail`). Activating `default` only touches interfaces
    Core created; the others are reported `skipped` and left alone. A radio
    another tool is using (a mode Core never sets such as AP, a
    wpa_supplicant or hostapd Core did not start, or a program capturing on
    another interface of the same radio) is never taken: its entry is reported
    `in_use` with the reason, and the rest of the configuration still runs.
    To use that radio, stop the other tool first. Every entry is validated
    before any radio is touched: if one fails, the request returns 422 with
    the invalid outcomes in `detail` and nothing has changed (a previously
    active profile keeps running). If an adapter fails during activation
    the request returns 500, `detail` holds the message and the outcomes,
    and the default configuration is active again. If an adapter command fails outright
    (for example a driver refusing to delete an interface), the 500's
    `detail` holds the message and the command's `error`. 409 means another
    change is running or the configuration is already active.
    """
    try:
        require_wlan_management_enabled()
        success, outcomes = await asyncio.to_thread(
            network_config.activate_config_report, id, override_active
        )
        if not success:
            log.error(f"Failed to activate configuration: {id}")
            invalid = any(outcome.invalid for outcome in outcomes)
            raise HTTPException(
                status_code=422 if invalid else 500,
                detail={
                    "message": "Configuration is invalid"
                    if invalid
                    else "Failed to activate configuration",
                    "outcomes": [outcome.model_dump() for outcome in outcomes],
                },
            )
        log.info(f"Configuration activated: {id}")
        return ActivationResponse(
            id=id, message="Configuration activated successfully", outcomes=outcomes
        )
    except ConfigBusyError as cbe:
        raise HTTPException(status_code=409, detail=cbe.message) from None
    except ConfigActiveError as cae:
        log.error(f"Configuration already active: {cae}")
        raise HTTPException(status_code=409, detail=str(cae)) from None
    except ConfigMalformedError as cme:
        log.error(f"Configuration is malformed: {cme}")
        raise HTTPException(status_code=422, detail=cme.message) from None
    except FileNotFoundError as e:
        log.error(f"Configuration not found: {e}")
        raise HTTPException(status_code=404, detail=str(e)) from None
    except ValidationError as ve:
        raise HTTPException(status_code=ve.status_code, detail=ve.error_msg) from None
    except HTTPException:
        raise
    except RunCommandError as rce:
        log.error(f"Adapter command failed activating {id}: {rce}")
        raise HTTPException(
            status_code=500,
            detail={"message": "An adapter command failed", "error": rce.error_msg},
        ) from None
    except Exception as ex:
        log.error(ex)
        raise HTTPException(status_code=500, detail="Internal Server Error") from None


@router.post(
    "/deactivate/{id}",
    response_model=DeactivationResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def deactivate_config(id: str, override_active: bool = False) -> Any:
    """
    Deactivate a network configuration by ID.

    `left_alone` lists namespaces still holding radios that Core did not
    clean up (another tool's, or Core's own that could not be removed).
    Clear them with `POST /network/config/reset`.
    """
    try:
        require_wlan_management_enabled()
        success = await asyncio.to_thread(
            network_config.deactivate_config,
            id,
            override_active=override_active if override_active else False,
        )
        if not success:
            log.error(f"Failed to deactivate configuration: {id}")
            raise HTTPException(
                status_code=500, detail="Failed to deactivate configuration"
            )
        log.info(f"Configuration deactivated: {id}")
        left = await asyncio.to_thread(network_config.left_alone)
        return DeactivationResponse(
            id=id, message="Configuration deactivated successfully", left_alone=left
        )
    except ConfigBusyError as cbe:
        raise HTTPException(status_code=409, detail=cbe.message) from None
    except ConfigActiveError as cae:
        log.error(f"Configuration not active: {cae}")
        raise HTTPException(status_code=409, detail=str(cae)) from None
    except FileNotFoundError as e:
        log.error(f"Configuration not found: {e}")
        raise HTTPException(status_code=404, detail=str(e)) from None
    except ValidationError as ve:
        raise HTTPException(status_code=ve.status_code, detail=ve.error_msg) from None
    except Exception as ex:
        log.error(ex)
        raise HTTPException(status_code=500, detail="Internal Server Error") from None
