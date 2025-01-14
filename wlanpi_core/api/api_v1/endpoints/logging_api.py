from fastapi import APIRouter, Depends
from pydantic import BaseModel

from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.core.logging import get_logger, set_log_level

router = APIRouter()
log = get_logger(__name__)


class LogLevel(BaseModel):
    level: str


@router.post("/level", dependencies=[Depends(verify_auth_wrapper)])
async def change_log_level(level: LogLevel):
    """Change the application log level

    Available levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
    """
    try:
        set_log_level(level.level)
        log.info("Log level changed to %s", level.level)
        return {"status": "success", "level": level.level}
    except ValueError as e:
        return {"status": "error", "message": str(e)}
