# -*- coding: utf-8 -*-

# stdlib imports

# third party imports
from fastapi.responses import JSONResponse
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.routing import APIRoute
from starlette.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

# app imports
from wlanpi_core.__version__ import __license__, __license_url__, __version__
from wlanpi_core.api.api_v1.api import api_router
from wlanpi_core.core.auth import verify_jwt_token
from wlanpi_core.core.config import endpoints, settings
from wlanpi_core.views import api

# JWT middleware to require a token on some routes
# class JWTMiddleware(BaseHTTPMiddleware):
#     async def dispatch(self, request: Request, call_next):
#         # Exclude the routes from JWT verification
#         if request.url.path not in ["/api/v1/auth/generate_token", "/docs", "/api/v1/openapi.json"]:
#             try:
#                 # Call the verification function
#                 token = request.headers.get("Authorization")
#                 if token is None:
#                     raise HTTPException(
#                         status_code=401,
#                         detail="JWT token is missing",
#                         headers={"WWW-Authenticate": "Bearer"},
#                     )
#                 verify_jwt_token(token)
#             except HTTPException as e:
#                 return JSONResponse(
#                     status_code=e.status_code,
#                     content={"detail": e.detail},
#                 )
#         # Proceed to the next middleware or route handler
#         response = await call_next(request)
#         return response

# setup logger
log_config = uvicorn.config.LOGGING_CONFIG
log_config["formatters"]["access"]["fmt"] = "%(asctime)s - %(levelname)s - %(message)s"


def create_app():
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
    
    # app.add_middleware(JWTMiddleware)

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
