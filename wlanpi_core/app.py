# -*- coding: utf-8 -*-

# stdlib imports
import logging

# third party imports
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.staticfiles import StaticFiles

# app imports
from wlanpi_core.api.api_v1.api import api_router
from wlanpi_core.core.config import settings, endpoints
from wlanpi_core.views import api

log = logging.getLogger("uvicorn")

app = FastAPI(
    title=settings.PROJECT_NAME, openapi_url=f"{settings.API_V1_STR}/openapi.json"
)


def configure():
    configure_routing()
    # configure_api_keys()


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
