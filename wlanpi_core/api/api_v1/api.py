from fastapi import APIRouter

from wlanpi_core.api.api_v1.endpoints import (
    auth_api,
    bluetooth_api,
    network_api,
    network_info_api,
    system_api,
    utils_api,
    profiler_api,
    streaming_api,
)

api_router = APIRouter()

api_router.include_router(auth_api.router, prefix="/auth", tags=["authentication"])

api_router.include_router(bluetooth_api.router, prefix="/bluetooth", tags=["bluetooth"])

api_router.include_router(network_api.router, prefix="/network", tags=["network"])

api_router.include_router(
    network_info_api.router, prefix="/network/info", tags=["network_information"]
)

api_router.include_router(system_api.router, prefix="/system", tags=["system"])

api_router.include_router(utils_api.router, prefix="/utils", tags=["device utils"])

api_router.include_router(profiler_api.router, prefix="/profiler", tags=["profiler"])

api_router.include_router(streaming_api.router, prefix="/streaming", tags=["streaming"])
