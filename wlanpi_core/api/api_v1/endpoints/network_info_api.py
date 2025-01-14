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
        # get network information
        info = network_info_service.show_info()
        return info

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)
