import logging
import os

from fastapi import APIRouter, Response

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import utils
from wlanpi_core.services import utils_service

import subprocess

router = APIRouter()

log = logging.getLogger("uvicorn")


@router.get("/reachability", response_model=utils.ReachabilityTest)
async def reachability():
    """
    Runs the reachability test and returns the results
    """

    try:
        reachability = utils_service.show_reachability()
        
        return {"reachability": reachability}
        
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)
