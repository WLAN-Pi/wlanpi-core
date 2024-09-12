from fastapi import APIRouter

from wlanpi_core.api.api_v1.endpoints import network_api, system_api

api_router = APIRouter()

api_router.include_router(system_api.router, prefix="/system", tags=["system"])

api_router.include_router(
    network_api.router, prefix="/network", tags=["network information", "network_configuration"]
)