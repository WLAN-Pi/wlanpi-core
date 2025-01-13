from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

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
                await request.app.state.activity_manager.record_activity(
                    token=token,
                    endpoint=str(request.url.path),
                    status_code=response.status_code
                )
            except Exception as e:
                request.app.logger.error(f"Failed to record activity: {e}")

        return response