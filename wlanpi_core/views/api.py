# stdlib imports
import logging

# third party imports
import fastapi
from starlette.requests import Request
from starlette.templating import Jinja2Templates

# app imports
from wlanpi_core.settings import ENDPOINTS
from wlanpi_core.core.config import settings

log = logging.getLogger("uvicorn")

templates = Jinja2Templates(settings.Config.base_dir / "templates")
router = fastapi.APIRouter()

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
