from fastapi import APIRouter

from wlanpi_core.api.api_v1.endpoints import (
    diagnostics_api,
    fpms_api,
    network_api,
    profiler_api,
    speedtest_api,
    utils_api,
)

api_router = APIRouter()

api_router.include_router(
    diagnostics_api.router, prefix="/diagnostics", tags=["diagnostics"]
)
api_router.include_router(
    fpms_api.router, prefix="/fpms", tags=["front panel menu system"]
)
api_router.include_router(
    network_api.router, prefix="/network", tags=["network information"]
)
api_router.include_router(profiler_api.router, prefix="/profiler", tags=["profiler"])
api_router.include_router(speedtest_api.router, prefix="/speedtest", tags=["speedtest"])
api_router.include_router(utils_api.router, prefix="/utils", tags=["utilities"])
