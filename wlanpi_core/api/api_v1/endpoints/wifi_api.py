from typing import Optional

from fastapi import APIRouter, Depends, Response

from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.api.openapi_docs import RESPONSES_MODE_CONFLICT
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import wifi as wifi_schema
from wlanpi_core.wlan.capabilities import get_wifi_capabilities
from wlanpi_core.wlan.regulatory import get_wifi_regulatory
from wlanpi_core.wlan.stations import get_hotspot_client_link, get_hotspot_stations

router = APIRouter()

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


@router.get(
    "/capabilities",
    response_model=wifi_schema.WifiCapabilitiesResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_wifi_capabilities():
    """Return ``iw phy`` capability dumps for each PHY."""
    try:
        return get_wifi_capabilities()
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to read WiFi capabilities", status_code=503)


@router.get(
    "/regulatory",
    response_model=wifi_schema.WifiRegulatoryResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_wifi_regulatory():
    """Return WiFi regulatory domain information."""
    try:
        return get_wifi_regulatory()
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to read regulatory domain", status_code=503)


@router.get(
    "/hotspot/stations",
    response_model=wifi_schema.HotspotStationsResponse,
    summary="Hotspot AP station list",
    responses={**RESPONSES_MODE_CONFLICT},
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_hotspot_stations(iface: Optional[str] = None):
    """
    Connected stations on the hotspot AP interface.

    Returns 409 when the device is not in hotspot mode.
    """
    try:
        return get_hotspot_stations(iface=iface)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to read hotspot stations", status_code=503)


@router.get(
    "/hotspot/link",
    response_model=wifi_schema.HotspotClientLinkResponse,
    summary="Hotspot per-client link stats",
    responses={**RESPONSES_MODE_CONFLICT},
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_hotspot_client_link(iface: Optional[str] = None):
    """
    Per-station link statistics for hotspot AP clients.

    Returns 409 when the device is not in hotspot mode.
    """
    try:
        return get_hotspot_client_link(iface=iface)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to read hotspot client link stats", status_code=503)
