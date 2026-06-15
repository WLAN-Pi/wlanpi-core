import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse

from wlanpi_core.api.openapi_docs import RESPONSES_API_ERROR
from wlanpi_core.constants import SPEEDTEST_TIMEOUT_SEC
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
    responses={**RESPONSES_API_ERROR},
    dependencies=[Depends(verify_auth_wrapper)],
)
async def reachability(
    targets: Optional[list[str]] = Query(
        default=None,
        description=(
            "Optional hostnames or IPs to ping. Repeat the parameter or use "
            "comma-separated values, e.g. targets=8.8.8.8&targets=1.1.1.1"
        ),
    ),
):
    """
    Runs reachability checks for gateway, internet, DNS, and optional custom targets.
    """

    try:
        reachability_result = await utils_service.show_reachability(targets=targets)

        if reachability_result.get("error"):
            message = reachability_result["error"]
            status_code = 400 if "invalid" in message.lower() or "at most" in message.lower() else 503
            return Response(
                content=json.dumps({"error": message}),
                status_code=status_code,
                media_type="application/json",
            )

        return reachability_result["results"]

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content=f"Internal Server Error", status_code=500)


@router.get(
    "/speedtest",
    response_model=utils.SpeedTest,
    response_model_exclude_none=True,
    summary="Internet speed test (slow)",
    responses={
        503: {
            "model": utils.SpeedTestErrorResponse,
            "description": "LibreSpeed failed or timed out (default server-side timeout 120s)",
        },
    },
    dependencies=[Depends(verify_auth_wrapper)],
)
async def speedtest():
    """
    Run LibreSpeed CLI (typically **30–90 seconds**).

    Use a client HTTP timeout of at least **120 seconds**. UI platforms should
  wrap as a job with `freshnessSec` deduplication rather than blocking the UI thread.

    On success returns `downloadSpeed`, `uploadSpeed`, `pingMs`, `ipAddress`, `server`.
    """
    try:
        result = await asyncio.wait_for(
            utils_service.show_speedtest(),
            timeout=SPEEDTEST_TIMEOUT_SEC,
        )
        if result.get("error"):
            return Response(
                content=json.dumps({"error": result["error"]}),
                status_code=503,
                media_type="application/json",
            )
        return result["results"]
    except asyncio.TimeoutError:
        return Response(
            content=json.dumps({"error": "speedtest timed out"}),
            status_code=503,
            media_type="application/json",
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to complete speedtest", status_code=503)


# @router.post("/port_blinker/{action}", response_model=utils.PortBlinkerState)
# async def port_blinker(action: str):
#     ...

@router.post(
    "/blinker/start",
    response_model=utils.BlinkerActionResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def start_blinker(interface: str = "eth0"):
    """Start the Ethernet port blinker (cable finder)."""
    try:
        return await asyncio.to_thread(utils_service.start_port_blinker, interface)
    except FileNotFoundError:
        return Response(content="Port blinker script not found", status_code=503)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to start port blinker", status_code=503)


@router.post(
    "/blinker/stop",
    response_model=utils.BlinkerActionResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def stop_blinker():
    """Stop the Ethernet port blinker."""
    try:
        return await asyncio.to_thread(utils_service.stop_port_blinker)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to stop port blinker", status_code=503)


@router.get(
    "/blinker/status",
    response_model=utils.BlinkerStatus,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def blinker_status():
    """Return whether the port blinker is running."""
    try:
        return await asyncio.to_thread(utils_service.port_blinker_status)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to read port blinker status", status_code=503)


@router.get(
    "/wlan/scan",
    response_model=utils.WlanScanResponse,
    response_model_exclude_none=True,
    summary="WLAN scan (canonical)",
    responses={
        400: RESPONSES_API_ERROR[400],
        422: {
            "model": utils.WlanScanErrorResponse,
            "description": "No suitable scan adapter",
        },
        503: RESPONSES_API_ERROR[503],
    },
    dependencies=[Depends(verify_auth_wrapper)],
)
async def wlan_scan_endpoint(
    iface: Optional[str] = None,
    namespace: Optional[str] = None,
    hidden: bool = True,
    detail: str = "short",
):
    """
    Namespace-aware WLAN scan with automatic monitor adapter selection.

    When multiple monitor adapters exist and ``iface`` is omitted, returns
    ``needsSelection`` with candidates instead of scanning.

    ``detail=short`` (default) returns list-friendly fields plus RF extensions.
    ``detail=full`` adds a per-BSS ``raw`` iw dump blob (uses ``iw scan``).
    """
    try:
        result = await asyncio.to_thread(
            wlan_scan,
            iface=iface,
            namespace=namespace,
            hidden=hidden,
            detail=detail,
        )
        if result.get("error"):
            return Response(
                content=json.dumps({"error": result["error"]}),
                status_code=503,
                media_type="application/json",
            )
        return result
    except ValueError as exc:
        return Response(content=str(exc), status_code=400)
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
