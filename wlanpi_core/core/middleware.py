from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from wlanpi_core.core.logging import get_logger
from wlanpi_core.core.repositories import TokenRepository

log = get_logger(__name__)


class ActivityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        token = None
        if "Authorization" in request.headers:
            auth = request.headers["Authorization"]
            if auth.startswith("Bearer "):
                token = auth.split(" ")[1]

        response = await call_next(request)

        if token and hasattr(request.app.state, "activity_manager"):
            try:
                async with request.app.state.db_manager.session() as session:
                    token_repo = TokenRepository(session)
                    token_obj = await token_repo.get_token_by_value(token)

                    if token_obj and not token_obj.revoked:
                        await request.app.state.activity_manager.record_activity(
                            token=token,
                            endpoint=str(request.url.path),
                            status_code=response.status_code,
                        )
                    else:
                        log.warning(
                            "Skipping activity recording for invalid token",
                            extra={
                                "component": "middleware",
                                "action": "skip_recording",
                                "path": str(request.url.path),
                            },
                        )

            except Exception as e:
                log.error(
                    "Failed to record activity",
                    extra={
                        "error": str(e),
                        "component": "middleware",
                        "action": "record_error",
                        "path": str(request.url.path),
                    },
                )

        return response
