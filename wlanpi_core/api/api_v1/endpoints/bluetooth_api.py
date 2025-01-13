import logging

from fastapi import APIRouter, Depends, Response

from wlanpi_core.core.auth import verify_jwt_token
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import bluetooth
from wlanpi_core.services import bluetooth_service

router = APIRouter()

log = logging.getLogger("uvicorn")


@router.get(
    "/status",
    response_model=bluetooth.BluetoothStatus,
    dependencies=[Depends(verify_jwt_token)],
)
async def btstatus():
    """
    Returns the bluetooth status
    """

    try:
        status = bluetooth_service.bluetooth_status()
        if status == False:
            return Response(content=f"Bluetooth hardware not found", status_code=503)
        return status

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content=f"Internal Server Error", status_code=500)


@router.post(
    "/power/{action}",
    response_model=bluetooth.PowerState,
    dependencies=[Depends(verify_jwt_token)],
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

        if status == False:
            return Response(
                content=f"Bluetooth failed to turn {action}", status_code=503
            )

        return {"status": "success", "action": action}

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content=f"Internal Server Error", status_code=500)
