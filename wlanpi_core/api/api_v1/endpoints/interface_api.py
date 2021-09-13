from typing import Optional

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import diagnostics
from wlanpi_core.services import diagnostics_service

router = APIRouter()

# TODO