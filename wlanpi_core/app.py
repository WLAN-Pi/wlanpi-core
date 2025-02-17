# -*- coding: utf-8 -*-

# stdlib imports
import asyncio

# third party imports
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.staticfiles import StaticFiles

# app imports
from wlanpi_core.__version__ import __license__, __license_url__, __version__
from wlanpi_core.api.api_v1.api import api_router
from wlanpi_core.core.config import endpoints, settings
from wlanpi_core.core.database import DatabaseError, DatabaseManager
from wlanpi_core.core.logging import configure_logging, get_logger
from wlanpi_core.core.middleware import ActivityMiddleware
from wlanpi_core.core.security import SecurityManager
from wlanpi_core.core.tokenmanager import TokenManager
from wlanpi_core.views.api import router as views_router


def create_app(debug: bool = False):
    configure_logging(debug_mode=debug)
    log = get_logger(__name__)

    if debug:
        log.debug("Starting application in DEBUG mode")

    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.PROJECT_DESCRIPTION,
        version=__version__,
        license_info={"name": __license__, "url": __license_url__},
        docs_url="/docs",
        redoc_url=None,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        openapi_tags=settings.TAGS_METADATA,
        debug=debug,
    )

    @app.exception_handler(DatabaseError)
    async def database_error_handler(request: Request, exc: DatabaseError):
        log.error(f"Database error: {exc}", exc_info=True)
        return JSONResponse(
            status_code=503, content={"detail": "Service temporarily unavailable"}
        )

    # setup slowapi
    limiter = Limiter(key_func=get_remote_address, default_limits=["90/minute"])
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(ActivityMiddleware)

    # setup router
    app.include_router(api_router, prefix=settings.API_V1_STR)
    for route in app.routes:
        if isinstance(route, APIRoute):
            endpoints.append(
                {
                    "path": route.path,
                    "methods": "".join(list(route.methods)),
                    "description": route.description.split("\n")[0],
                }
            )

    app.include_router(views_router)

    app.mount(
        "/static",
        StaticFiles(directory=settings.Config.base_dir / "static"),
        name="static",
    )

    @app.on_event("startup")
    async def startup():
        app.state.security_manager = SecurityManager()
        app.state.db_manager = DatabaseManager()

        try:
            await app.state.db_manager.initialize_models()
            log.debug("Database initialization complete")
        except DatabaseError as e:
            log.error(
                "Database connection failed during startup",
                extra={
                    "component": "database",
                    "action": "startup_connection_error",
                    "error": str(e),
                    "timeout_seconds": getattr(e, "timeout_seconds", 5.0),
                },
            )

        app.state.token_manager = TokenManager(app.state)
        log.debug("Token manager initialization complete")

        asyncio.create_task(app.state.token_manager.purge_expired_tokens())

    @app.on_event("shutdown")
    async def shutdown():
        pass

    return app
