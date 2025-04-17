# -*- coding: utf-8 -*-

# stdlib imports
import asyncio
import grp
import time
from pathlib import Path

# third party imports
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import text
from starlette.staticfiles import StaticFiles

# app imports
from wlanpi_core.__version__ import __license__, __license_url__, __version__
from wlanpi_core.api.api_v1.api import api_router
from wlanpi_core.constants import SECRETS_DIR
from wlanpi_core.core.config import endpoints, settings
from wlanpi_core.core.database import DatabaseError, DatabaseManager
from wlanpi_core.core.logging import configure_logging, get_logger
from wlanpi_core.core.middleware import ActivityMiddleware
from wlanpi_core.core.security import SecurityInitError, SecurityManager
from wlanpi_core.core.token import TokenManager
from wlanpi_core.views.api import router as views_router


class ApplicationHealthManager:
    """
    Manager for monitoring and recovering application health
    """

    def __init__(self, app):
        self.app = app
        self.log = get_logger(__name__)
        self.health_check_interval = 300
        self._health_check_task = None
        self._lock = asyncio.Lock()

    async def start_health_checks(self):
        """Start the health check loop"""
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        self.log.debug("Application health monitoring started")

    async def stop_health_checks(self):
        """Stop the health check loop"""
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        self.log.debug("Application health monitoring stopped")

    async def _health_check_loop(self):
        """Periodically check application health and recover if needed"""
        while True:
            try:
                await asyncio.sleep(self.health_check_interval)
                await self._check_application_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error(f"Health check failed: {e}")

    def _invalidate_caches(self):
        """Invalidate auth caches after database reset"""
        self.log.info("Invalidating caches after database reset")
        try:
            from wlanpi_core.core.token import SKeyCache

            key_cache = SKeyCache()
            key_cache.clear()
            self.log.debug("Signing key cache cleared")
        except Exception as e:
            self.log.error(f"Failed to clear signing key cache: {e}")

        try:
            from wlanpi_core.core.token import TokenCache

            token_cache = TokenCache()
            token_cache.clear()
            self.log.debug("Token cache cleared")
        except Exception as e:
            self.log.error(f"Failed to clear token cache: {e}")

    async def _check_application_health(self):
        """Check health of all application components"""
        async with self._lock:
            if (
                not hasattr(self.app.state, "security_manager")
                or self.app.state.security_manager is None
            ):
                self.log.error("Security manager missing, attempting recovery")
                try:
                    self.app.state.security_manager = SecurityManager()
                    self.log.info("Security manager successfully recovered")
                except Exception as e:
                    self.log.error(
                        f"Failed to recover security manager: {e}", exc_info=True
                    )

            if hasattr(self.app.state, "db_manager"):
                try:
                    async with self.app.state.db_manager.session() as session:
                        try:
                            critical_tables = ["signing_keys", "tokens", "devices"]
                            missing_tables = []
                            for table in critical_tables:
                                result = await session.execute(
                                    text(
                                        "SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"
                                    ),
                                    {"table_name": table},
                                )
                                if not result.scalar_one_or_none():
                                    missing_tables.append(table)
                            if missing_tables:
                                self.log.error(f"Schema verification failes")
                                raise Exception(
                                    f"Required tables missing: {', '.join(missing_tables)}"
                                )
                            self.log.debug("Database schema verified - tables exist")
                        except Exception as schema_error:
                            self.log.error(
                                f"Database schema error: {schema_error}, recreating tables"
                            )
                            try:
                                self._invalidate_caches()

                                if hasattr(self.app.state, "db_manager"):
                                    try:
                                        await self.app.state.db_manager.cleanup()
                                    except Exception as cleanup_error:
                                        self.log.warning(
                                            f"Error during database cleanup: {cleanup_error}"
                                        )

                                self.log.info("Creating new database manager instance")
                                self.app.state.db_manager = DatabaseManager()

                                db_initialized = (
                                    await self.app.state.db_manager.initialize_with_retry()
                                )
                                if db_initialized:
                                    self.log.info(
                                        "Database successfully reset and initialized"
                                    )
                                    if hasattr(self.app.state, "token_manager"):
                                        self.log.info(
                                            "Recreating token manager after database reset"
                                        )
                                        self.app.state.token_manager = TokenManager(
                                            self.app.state
                                        )
                                else:
                                    self.log.error(
                                        "Database reset failed - application may be in inconsistent state"
                                    )
                            except Exception as init_error:
                                self.log.error(
                                    f"Failed to recreate database tables: {init_error}"
                                )
                                await self.app.state.db_manager.initialize_with_retry()
                    self.log.debug("Database connection healthy")
                except Exception as e:
                    self.log.error(
                        f"Database connection unhealthy: {e}, attempting recovery"
                    )
                    try:
                        await self.app.state.db_manager.initialize_with_retry()
                        self.log.info("Database connection successfully recovered")
                    except Exception as recovery_error:
                        self.log.error(
                            f"Failed to recover database connection: {recovery_error}"
                        )

            if (
                not hasattr(self.app.state, "token_manager")
                or self.app.state.token_manager is None
            ):
                if hasattr(self.app.state, "security_manager") and hasattr(
                    self.app.state, "db_manager"
                ):
                    self.log.error("Token manager missing, attempting recovery")
                    try:
                        self.app.state.token_manager = TokenManager(self.app.state)
                        self.log.info("Token manager successfully recovered")
                    except Exception as e:
                        self.log.error(f"Failed to recover token manager: {e}")


class InitializationManager:
    """
    Manager for application initialization with retry mechanisms
    """

    def __init__(self, app):
        self.app = app
        self.max_retries = 3
        self.log = get_logger(__name__)
        self.initialized = False

    async def check_system_readiness(self):
        """Check if the system is ready for application initialization"""
        try:
            wlanpi_gid = grp.getgrnam("wlanpi").gr_gid
            self.log.debug(f"Found wlanpi group with GID: {wlanpi_gid}")
        except KeyError:
            existing_groups = [g.gr_name for g in grp.getgrall()]
            self.log.error(
                f"Required group 'wlanpi' does not exist! Available groups: {', '.join(existing_groups)}"
            )
            return False

        try:
            secrets_dir = Path(SECRETS_DIR)
            parent_dir = secrets_dir.parent

            if not parent_dir.exists():
                self.log.warning(
                    f"Parent directory {parent_dir} does not exist yet - system may not be fully booted"
                )
                try:
                    parent_dir.mkdir(parents=True, exist_ok=True)
                    self.log.debug(f"Created parent directory {parent_dir}")
                except Exception as e:
                    self.log.error(f"Could not create parent directory: {e}")
                    return False

            test_file = parent_dir / f"wlanpi_boot_test_{int(time.time())}"
            try:
                test_file.write_text("test")
                test_file.unlink()
                self.log.debug(f"Filesystem check successful on {parent_dir}")
            except Exception as e:
                self.log.error(f"Filesystem not writable: {e}")
                return False

            return True
        except Exception as e:
            self.log.error(f"System readiness check failed: {e}")
            return False

    async def initialize_components(self):
        """Initialize all application components with proper sequencing and retry"""
        if not await self.check_system_readiness():
            self.log.error("System not ready for initialization")
            return False

        security_initialized = await self._initialize_security_manager()
        if not security_initialized:
            self.log.error("Security initialization failed - cannot proceed")
            return False

        database_initialized = await self._initialize_database()
        if not database_initialized:
            self.log.error(
                "Database initialization failed - cannot proceed with token management"
            )
            self.initialized = True
            return True

        token_initialized = await self._initialize_token_manager()
        if not token_initialized:
            self.log.warning(
                "Token manager initialization failed - some functionality will be limited"
            )
            self.initialized = True
            return True

        self.initialized = True
        self.log.info("All components initialized ...")
        return True

    async def _initialize_security_manager(self):
        """Initialize the security manager with retry"""
        for attempt in range(1, self.max_retries + 1):
            try:
                self.app.state.security_manager = SecurityManager()
                self.log.info("Security manager initialized successfully")
                return True
            except SecurityInitError as e:
                self.log.error(
                    f"Security manager initialization failed (attempt {attempt}/{self.max_retries}): {e}"
                )
                if attempt < self.max_retries:
                    retry_delay = self.initial_retry_delay * (2 ** (attempt - 1))
                    self.log.info(
                        f"Retrying security initialization in {retry_delay} seconds..."
                    )
                    await asyncio.sleep(retry_delay)
                else:
                    self.log.error(
                        "Security manager initialization failed after all retry attempts"
                    )
                    return False
            except Exception as e:
                self.log.error(f"Unexpected error during security initialization: {e}")
                return False
        return False

    async def _initialize_database(self):
        """Initialize the database manager with retry"""
        try:
            self.app.state.db_manager = DatabaseManager()
            db_initialized = await self.app.state.db_manager.initialize_with_retry()
            if db_initialized:
                self.log.info("Database manager initialized successfully")
                return True
            else:
                self.log.error("Database initialization failed after multiple attempts")
                return False
        except Exception as e:
            self.log.error(f"Unexpected error creating database manager: {e}")
            return False

    async def _initialize_token_manager(self):
        """Initialize the token manager"""
        try:
            self.app.state.token_manager = TokenManager(self.app.state)
            self.log.debug("Token manager initialized successfully")
            asyncio.create_task(self.app.state.token_manager.purge_expired_tokens())
            return True
        except Exception as e:
            self.log.error(f"Token manager initialization failed: {e}")
            return False


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

    @app.exception_handler(SecurityInitError)
    async def security_error_handler(request: Request, exc: SecurityInitError):
        log.error(f"Security initialization error: {exc}", exc_info=True)
        return JSONResponse(
            status_code=503, content={"detail": "Security system unavailable"}
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
        log.info("Starting application initialization")
        app.state.initialization_manager = InitializationManager(app)
        app.state.health_manager = ApplicationHealthManager(app)

        initialization_success = (
            await app.state.initialization_manager.initialize_components()
        )

        if initialization_success:
            log.info("Application successfully initialized")
            await app.state.health_manager.start_health_checks()
        else:
            log.error("Application initialization failed")

    @app.on_event("shutdown")
    async def shutdown():
        log.info("Application shutting down")
        if hasattr(app.state, "health_manager"):
            await app.state.health_manager.stop_health_checks()

        if hasattr(app.state, "db_manager"):
            try:
                await app.state.db_manager.cleanup()
                log.info("Database connections cleaned up")
            except Exception as e:
                log.error(f"Error cleaning up database connections: {e}")

    return app
