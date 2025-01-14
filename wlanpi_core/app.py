# -*- coding: utf-8 -*-

# stdlib imports
import asyncio

# third party imports
from fastapi import FastAPI
from fastapi.routing import APIRoute
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.staticfiles import StaticFiles

# app imports
from wlanpi_core.__version__ import __license__, __license_url__, __version__
from wlanpi_core.api.api_v1.api import api_router
from wlanpi_core.core.auth import TokenManager
from wlanpi_core.core.config import endpoints, settings
from wlanpi_core.core.database import DatabaseManager, RetentionManager
from wlanpi_core.core.logging import configure_logging, get_logger
from wlanpi_core.core.middleware import ActivityMiddleware
from wlanpi_core.core.migrations import run_migrations
from wlanpi_core.core.monitoring import DeviceActivityManager
from wlanpi_core.core.security import SecurityManager


def create_app():
    configure_logging()
    log = get_logger(__name__)

    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.PROJECT_DESCRIPTION,
        version=__version__,
        license_info={"name": __license__, "url": __license_url__},
        docs_url="/docs",
        redoc_url=None,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        openapi_tags=settings.TAGS_METADATA,
    )

    # setup slowapi
    limiter = Limiter(key_func=get_remote_address, default_limits=["10/minute"])
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

    app.mount(
        "/static",
        StaticFiles(directory=settings.Config.base_dir / "static"),
        name="static",
    )

    @app.on_event("startup")
    async def startup():
        app.state.security_manager = SecurityManager()

        app.state.db_manager = DatabaseManager(app.state)
        run_migrations(await app.state.db_manager.get_connection())

        await app.state.db_manager.initialize()
        log.info("Database manager initialization complete")

        app.state.retention_manager = RetentionManager(app.state)
        log.info("Retention manager initialization complete")

        app.state.token_manager = TokenManager(app.state)

        await app.state.token_manager.initialize()
        log.info("Token manager initialization complete")

        app.state.activity_manager = DeviceActivityManager(app.state)
        log.info("Activity manager initialization complete")

        asyncio.create_task(periodic_maintenance())
        asyncio.create_task(app.state.token_manager.purge_expired_tokens())

    async def periodic_maintenance():
        while True:
            try:
                await app.state.activity_manager.flush_buffers()

                await app.state.retention_manager.cleanup_old_data()

                if not app.state.db_manager.check_size():
                    log.warning("Database size exceeds limit, running vacuum")
                    app.state.db_manager.vacuum()

                await app.state.db_manager.backup()

            except Exception as e:
                log.error(f"Maintenance task failed: {e}")
            finally:
                await asyncio.sleep(3600)

    @app.on_event("shutdown")
    async def shutdown():
        await app.state.activity_manager.flush_buffers()
        await app.state.db_manager.close()

    return app
