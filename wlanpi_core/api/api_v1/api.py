from fastapi import APIRouter

from wlanpi_core.api.api_v1.endpoints import (
    bluetooth_api,
    network_api,
    network_info_api,
    system_api,
    utils_api,
)

api_router = APIRouter()

api_router.include_router(system_api.router, prefix="/system", tags=["system"])

api_router.include_router(network_api.router, prefix="/network", tags=["network"])

api_router.include_router(
    network_info_api.router, prefix="/network/info", tags=["network information"]
)

api_router.include_router(utils_api.router, prefix="/utils", tags=["device utils"])

api_router.include_router(bluetooth_api.router, prefix="/bluetooth", tags=["bluetooth"])
