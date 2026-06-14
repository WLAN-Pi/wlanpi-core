import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import utils
from wlanpi_core.services import utils_service
from wlanpi_core.wlan.scan import NoScanAdapterError, wlan_scan

router = APIRouter()

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


@router.get(
    "/reachability",
    response_model=utils.ReachabilityTest,
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def reachability():
    """
    Runs the reachability test and returns the results
    """

    try:
        reachability = await utils_service.show_reachability()

        if reachability.get("error"):
            return Response(
                content=json.dumps(reachability),
                status_code=503,
                media_type="application/json",
            )

        return reachability["results"]

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content=f"Internal Server Error", status_code=500)


# @router.post("/port_blinker/{action}", response_model=utils.PortBlinkerState)
# async def port_blinker(action: str):
#     """
#     Turns on bluetooth

#     - action: "on" or "off"
#     """

#     # Validate action parameter
#     if action not in ["on", "off"]:
#         return Response(content="Invalid action. Use 'on' or 'off'.", status_code=400)

#     # Convert action to Boolean
#     state = action == "on"

#     try:
#         status = utils_service.port_blinker_state(state)

#         if status == False:
#             return Response(content=f"Port blinker failed to turn {action}", status_code=503)

#         return {"status": "success", "action": action}

#     except ValidationError as ve:
#         return Response(content=ve.error_msg, status_code=ve.status_code)
#     except Exception as ex:
#         log.error(ex)
#         return Response(content=f"Internal Server Error {ex}", status_code=500)


@router.get(
    "/wlan/scan",
    response_model=utils.WlanScanResponse,
    response_model_exclude_none=True,
    responses={
        422: {
            "model": utils.WlanScanErrorResponse,
            "description": "No suitable scan adapter",
        }
    },
    dependencies=[Depends(verify_auth_wrapper)],
)
async def wlan_scan_endpoint(
    iface: Optional[str] = None,
    namespace: Optional[str] = None,
    hidden: bool = True,
):
    """
    Namespace-aware WLAN scan with automatic monitor adapter selection.

    When multiple monitor adapters exist and ``iface`` is omitted, returns
    ``needsSelection`` with candidates instead of scanning.
    """
    try:
        return await asyncio.to_thread(
            wlan_scan, iface=iface, namespace=namespace, hidden=hidden
        )
    except NoScanAdapterError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": "NO_SCAN_ADAPTER",
                "candidates": exc.candidates,
            },
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to complete WLAN scan", status_code=503)


@router.get(
    "/usb", response_model=utils.Usb, dependencies=[Depends(verify_auth_wrapper)]
)
async def usb_interfaces():
    """
    Gets a list of usb interfaces and returns them.
    """

    try:
        result = await utils_service.show_usb()

        if result.get("error"):
            return Response(
                content=json.dumps(result["error"]),
                status_code=503,
                media_type="application/json",
            )

        return result

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content=f"Internal Server Error", status_code=500)


@router.get(
    "/ufw", response_model=utils.Ufw, dependencies=[Depends(verify_auth_wrapper)]
)
async def ufw_information():
    """
    Returns the UFW information.
    """

    try:
        result = await utils_service.show_ufw()

        if result.get("error"):
            return Response(
                content=json.dumps(result["error"]),
                status_code=503,
                media_type="application/json",
            )

        return result

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content=f"Internal Server Error", status_code=500)
