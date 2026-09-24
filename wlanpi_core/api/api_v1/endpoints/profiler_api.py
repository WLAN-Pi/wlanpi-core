"""Profiler status and control endpoints."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Response

import wlanpi_core.profiler.cli as cli
import wlanpi_core.profiler.models as models
import wlanpi_core.profiler.schemas as schemas
import wlanpi_core.profiler.service as service
from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.core.logging import get_logger
from wlanpi_core.models.validation_error import ValidationError

router = APIRouter()

log = get_logger(__name__)


@router.get(
    "/status",
    response_model=schemas.Status,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def profiler_status() -> Any:
    """Return the profiler status."""

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
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def start_profiler(args: models.Start) -> Any:
    """Start the profiler and wait (up to about 25 s) until it runs or fails.

    `success` is false when the profiler did not start; `reason` and `message`
    say why:

    - the profiler's own exit reason when it exited during startup, for example
      `country_code_detection` (no reg domain set) or `interface_validation`
      (unknown interface), or `exited` if it gave none
    - `already_running` when a profiler started by Core is still running
    - `spawn_failed` when the profiler could not be launched

    If it is still starting when the wait ends, `success` is true with
    `reason` `starting`. In AP mode, poll `GET /profiler/status` until
    `running` is true.
    """

    try:
        return await cli.start_profiler(args)

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
async def stop_profiler() -> Any:
    """Stop the profiler."""

    try:
        result = await cli.stop_profiler()

        return {"success": result}

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.post(
    "/purge",
    response_model=schemas.Purge,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def purge_profiler() -> Any:
    """Delete all profiler client profiles, captures and session reports.

    Removes everything inside `/var/www/html/profiler/clients` and
    `/var/www/html/profiler/reports`; the two directories stay. Symlinks are
    removed, never followed. This cannot be undone.

    Returns `409` while the profiler is running or starting; stop it first.
    """

    try:
        return await asyncio.to_thread(service.purge_data)

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)
