import subprocess

from fastapi import APIRouter, Depends, Response

from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.validation_error import ValidationError
import wlanpi_core.profiler.schemas as schemas
import wlanpi_core.profiler.models as models
import wlanpi_core.profiler.cli as cli
import wlanpi_core.profiler.service as service
from wlanpi_core.services import system_service
from wlanpi_core.utils.general import run_command

router = APIRouter()

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


@router.get(
    "/status",
    response_model=schemas.Status,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def profiler_status():
    """
    Returns status of profiler
    """

    try:
        status = service.get_status()

        return status

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.post(
    "/start",
    response_model=schemas.Start,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def start_profiler(args: models.Start):
    """
    Starts profiler with provided arguments
    """

    try:
        # start with args
        result = await cli.start_profiler(args)

        return {"success": result}

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.post(
    "/stop",
    response_model=schemas.Stop,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def stop_profiler():
    """
    Stops  profiler
    """

    try:
        result = cli.stop_profiler()

        return result

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)
