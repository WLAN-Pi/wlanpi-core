import logging

import fastapi
from starlette.requests import Request
from starlette.templating import Jinja2Templates

templates = Jinja2Templates("wlanpi_core/templates")
router = fastapi.APIRouter()
from wlanpi_core.settings import ENDPOINTS

log = logging.getLogger("uvicorn")


@router.get("/", include_in_schema=False)
async def index(request: Request):
    data = {"request": request}
    return templates.TemplateResponse("home/index.html", data)


@router.get("/api", include_in_schema=False)
@router.get("/api/v1", include_in_schema=False)
async def index(request: Request):
    data = {"request": request, "endpoints": ENDPOINTS}
    return templates.TemplateResponse("home/api.html", data)


@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    return fastapi.responses.RedirectResponse(url="/static/img/favicon.ico")
