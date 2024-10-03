# -*- coding: utf-8 -*-

# stdlib imports
import logging
import os

# third party imports
import uvicorn
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.staticfiles import StaticFiles

# app imports
from wlanpi_core.__version__ import __license__, __license_url__, __version__
from wlanpi_core.api.api_v1.api import api_router
from wlanpi_core.core.config import endpoints, settings
from wlanpi_core.views import api


def configure_logging():
    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["formatters"]["access"][
        "fmt"
    ] = "%(asctime)s - %(levelname)s - %(message)s"
    log_config["formatters"]["default"][
        "fmt"
    ] = "%(asctime)s - %(levelname)s - %(message)s"
    log_level = logging.DEBUG if settings.DEBUGGING else logging.INFO
    logging.config.dictConfig(log_config)
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.setLevel(log_level)
    return log_config


def create_app():
    if "WLANPI_CORE_DEBUGGING" in os.environ:
        level = os.environ["WLANPI_CORE_DEBUGGING"]
        if level == "1":
            settings.DEBUGGING = True
    print(f"create_app settings.DEBUGGING: {settings.DEBUGGING}")

    log_config = configure_logging()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.PROJECT_DESCRIPTION,
        version=__version__,
        license_info={"name": __license__, "url": __license_url__},
        docs_url="/docs",
        redoc_url=None,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        openapi_tags=settings.TAGS_METADATA,
        log_config=log_config,
    )

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
    app.include_router(api.router)

    return app
