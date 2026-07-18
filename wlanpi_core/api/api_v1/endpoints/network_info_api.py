import asyncio

from fastapi import APIRouter, Depends, Response

from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import network_info
from wlanpi_core.services import network_info_service

router = APIRouter()

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


@router.get(
    "/",
    response_model=network_info.NetworkInfo,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_network_info():
    """
    Returns information about network related stuff.
    """

    try:
        log.debug("GET /network/info request")
        info = await asyncio.to_thread(network_info_service.show_info)
        log.debug("GET /network/info response keys: %s", list(info.keys()))
        return info

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/publicip6",
    response_model=network_info.PublicIpInfo,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_public_ip6():
    """
    Returns public IPv6 address and related details.
    """
    try:
        return await asyncio.to_thread(network_info_service.show_publicip, ip_version=6)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)
