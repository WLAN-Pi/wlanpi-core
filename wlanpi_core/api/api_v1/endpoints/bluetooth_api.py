from fastapi import APIRouter, Depends, Response

from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import bluetooth
from wlanpi_core.services import bluetooth_service

router = APIRouter()

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


@router.get(
    "/status",
    response_model=bluetooth.BluetoothStatus,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def btstatus():
    """
    Returns the bluetooth status
    """

    try:
        status = bluetooth_service.bluetooth_status()
        if status is False:
            return Response(content="Bluetooth hardware not found", status_code=503)
        return status

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.exception("Error getting bluetooth status")
        return Response(content="Internal Server Error", status_code=500)


@router.post(
    "/power/{action}",
    response_model=bluetooth.PowerState,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def bt_power(action: str):
    """
    Turns on bluetooth

    - action: "on" or "off"
    """

    # Validate action parameter
    if action not in ["on", "off"]:
        return Response(content="Invalid action. Use 'on' or 'off'.", status_code=400)

    # Convert action to Boolean
    state = action == "on"

    if not bluetooth_service.bluetooth_present():
        return Response(content=f"Bluetooth hardware not found", status_code=503)

    try:
        status = bluetooth_service.bluetooth_set_power(state)

        if status is False:
            return Response(
                content=f"Bluetooth failed to turn {action}", status_code=503
            )

        return {"status": "success", "action": action}

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception:
        log.exception("Error toggling bluetooth state")
        return Response(content="Internal Server Error", status_code=500)
