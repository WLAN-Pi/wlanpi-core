from fastapi import APIRouter

from wlanpi_core.api.api_v1.endpoints import system_api

api_router = APIRouter()

api_router.include_router(system_api.router, prefix="/system", tags=["system"])
