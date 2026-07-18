import asyncio

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import bluetooth
from wlanpi_core.schemas.common import ApiErrorResponse
from wlanpi_core.services import bluetooth_service

router = APIRouter()

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


def _set_power_if_present(state: bool):
    """Run the complete synchronous Bluetooth power transaction in one worker."""
    if not bluetooth_service.bluetooth_present():
        return None
    return bluetooth_service.bluetooth_set_power(state)


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
        status = await asyncio.to_thread(bluetooth_service.bluetooth_status)
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

    try:
        status = await asyncio.to_thread(_set_power_if_present, state)

        if status is None:
            return Response(content="Bluetooth hardware not found", status_code=503)

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


@router.post(
    "/pair",
    response_model=bluetooth.BluetoothPairResponse,
    responses={
        409: {
            "model": ApiErrorResponse,
            "description": "Bluetooth is already in its pairing window",
        },
        503: {
            "model": ApiErrorResponse,
            "description": "Bluetooth is unavailable or pairing could not be started",
        },
    },
    dependencies=[Depends(verify_auth_wrapper)],
)
async def bt_pair():
    """Enter Bluetooth discoverable pairing mode (starts bt-timedpair)."""
    try:
        return await bluetooth_service.bluetooth_pair()
    except bluetooth_service.BluetoothPairingInProgressError as exc:
        return JSONResponse(
            content={"error": "PAIRING_IN_PROGRESS", "message": str(exc)},
            status_code=409,
        )
    except ValueError as exc:
        return JSONResponse(
            content={"error": "BLUETOOTH_UNAVAILABLE", "message": str(exc)},
            status_code=503,
        )
    except bluetooth_service.BluetoothPairingError as exc:
        log.error(exc)
        return JSONResponse(
            content={"error": "BLUETOOTH_PAIRING_FAILED", "message": str(exc)},
            status_code=503,
        )
    except Exception as ex:
        log.error(ex)
        return JSONResponse(
            content={
                "error": "BLUETOOTH_PAIRING_FAILED",
                "message": "Unable to start Bluetooth pairing",
            },
            status_code=503,
        )
