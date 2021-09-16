# -*- coding: utf-8 -*-

# stdlib imports
import logging

# third party imports
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.staticfiles import StaticFiles

# app imports
from wlanpi_core.__version__ import __license__, __license_url__, __version__
from wlanpi_core.api.api_v1.api import api_router
from wlanpi_core.core.config import endpoints, settings
from wlanpi_core.views import api

log = logging.getLogger("uvicorn")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_DESCRIPTION,
    version=__version__,
    license_info={"name": __license__, "url": __license_url__},
    docs_url="/documentation",
    redoc_url=None,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    openapi_tags=settings.TAGS_METADATA,
)


def configure():
    configure_routing()
    # TODO: configure_events()
    # TODO: configure_api_keys()


def configure_routing():
    app.include_router(api_router, prefix=settings.API_V1_STR)
    for route in app.routes:
        if isinstance(route, APIRoute):
            endpoints.append({"path": route.path})

    app.mount(
        "/static",
        StaticFiles(directory=settings.Config.base_dir / "static"),
        name="static",
    )
    app.include_router(api.router)


configure()
