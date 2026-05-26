from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException

from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.models.network_config_errors import ConfigActiveError, ConfigMalformedError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas.network.network import (
    NetConfig,
    NetConfigUpdate,
)
from wlanpi_core.utils import network_config

router = APIRouter()

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


@router.get(
    "/status",
    response_model=dict,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def get_status():
    """
    Get the status of network configurations.
    """
    try:
        status = network_config.status()
        log.info("Network configuration status retrieved successfully")
        return status
    except Exception as ex:
        log.error(f"Error retrieving network configuration status: {ex}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get(
    "/",
    response_model=dict[str, bool],
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def get_configs():
    """
    Get all network configuration ids.
    """
    try:

        configs = network_config.list_configs()
        log.info("Retrieved all configurations")
        return configs
    except ValidationError as ve:
        raise HTTPException(status_code=ve.status_code, detail=ve.error_msg)
    except Exception as ex:
        log.error(ex)
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get(
    "/{id}",
    response_model=NetConfig,
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def get_config_by_id(id: str):
    """
    Get a specific network configuration by ID.
    """
    try:
        config = network_config.get_config(id)
        log.info(f"Retrieved configuration: {config.id}")
        return config
    except FileNotFoundError as e:
        log.error(f"Configuration not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ConfigMalformedError as cme:
        log.error(f"Configuration is malformed: {cme}")
        raise HTTPException(status_code=422, detail=cme.message)
    except ValidationError as ve:
        raise HTTPException(status_code=ve.status_code, detail=ve.error_msg)
    except Exception as ex:
        log.error(ex)
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post(
    "/",
    response_model=dict[str, str],
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def create_config(config: NetConfig):
    """
    Create a new network configuration.
    """
    try:
        if config.id in ["root", "default"]:
            raise ValidationError(
                status_code=400,
                error_msg="Configuration ID cannot be 'root' or 'default'.",
            )
        success = network_config.add_config(config)
        if not success:
            log.error(f"Failed to add configuration: {config.id}")
            raise HTTPException(status_code=500, detail="Failed to add configuration")
        log.info(f"Configuration added: {config.id}")
        return {"id": config.id, "message": "Configuration added successfully"}
    except FileExistsError as e:
        log.error(f"Configuration already exists: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as ve:
        raise HTTPException(status_code=ve.status_code, detail=ve.error_msg)
    except Exception as ex:
        log.error(ex)
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.patch(
    "/{id}",
    response_model=dict[str, Union[NetConfig, str]],
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def update_config(id: str, config_update: NetConfigUpdate):
    """
    Update an existing network configuration.
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
            "config": config,
        }
    except FileNotFoundError as e:
        log.error(f"Configuration not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ConfigActiveError as cae:
        log.error(f"Active configuration cannot be updated: {cae}")
        raise HTTPException(status_code=409, detail=str(cae))
    except ValidationError as ve:
        raise HTTPException(status_code=ve.status_code, detail=ve.error_msg)
    except Exception as ex:
        log.error(ex)
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.delete(
    "/{id}",
    response_model=dict[str, str],
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def delete_config(id: str, force: Optional[bool] = False):
    """
    Delete a network configuration by ID.
    """
    try:
        success = network_config.delete_config(id, force)
        if not success:
            log.error(f"Failed to delete configuration: {id}")
            raise HTTPException(
                status_code=400, detail="Failed to delete configuration"
            )
        log.info(f"Configuration deleted: {id}")
        return {"id": id, "message": "Configuration deleted successfully"}
    except ConfigActiveError as cae:
        log.error(f"Active configuration cannot be deleted: {cae}")
        raise HTTPException(status_code=409, detail=str(cae))
    except FileNotFoundError as e:
        log.error(f"Configuration not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as ve:
        raise HTTPException(status_code=ve.status_code, detail=ve.error_msg)
    except Exception as ex:
        log.error(ex)
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post(
    "/activate/{id}",
    response_model=dict[str, str],
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def activate_config(id: str, override_active: Optional[bool] = False):
    """
    Activate a network configuration by ID.
    """
    try:
        success = network_config.activate_config(id, override_active)
        if not success:
            log.error(f"Failed to activate configuration: {id}")
            raise HTTPException(
                status_code=500, detail="Failed to activate configuration"
            )
        log.info(f"Configuration activated: {id}")
        return {"id": id, "message": "Configuration activated successfully"}
    except ConfigActiveError as cae:
        log.error(f"Configuration already active: {cae}")
        raise HTTPException(status_code=409, detail=str(cae))
    except ConfigMalformedError as cme:
        log.error(f"Configuration is malformed: {cme}")
        raise HTTPException(status_code=422, detail=cme.message)
    except FileNotFoundError as e:
        log.error(f"Configuration not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as ve:
        raise HTTPException(status_code=ve.status_code, detail=ve.error_msg)
    except Exception as ex:
        log.error(ex)
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post(
    "/deactivate/{id}",
    response_model=dict[str, str],
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def deactivate_config(id: str, override_active: Optional[bool] = False):
    """
    Deactivate a network configuration by ID.
    """
    try:
        success = network_config.deactivate_config(
            id, override_active=override_active if override_active else False
        )
        if not success:
            log.error(f"Failed to deactivate configuration: {id}")
            raise HTTPException(
                status_code=500, detail="Failed to deactivate configuration"
            )
        log.info(f"Configuration deactivated: {id}")
        return {"id": id, "message": "Configuration deactivated successfully"}
    except ConfigActiveError as cae:
        log.error(f"Configuration not active: {cae}")
        raise HTTPException(status_code=409, detail=str(cae))
    except FileNotFoundError as e:
        log.error(f"Configuration not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as ve:
        raise HTTPException(status_code=ve.status_code, detail=ve.error_msg)
    except Exception as ex:
        log.error(ex)
        raise HTTPException(status_code=500, detail="Internal Server Error")
