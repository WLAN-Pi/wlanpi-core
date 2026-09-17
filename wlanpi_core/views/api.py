# stdlib imports

# third party imports
import fastapi
from starlette.requests import Request
from starlette.responses import Response
from starlette.templating import Jinja2Templates

# app imports
from wlanpi_core.core.config import endpoints, settings
from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)

templates = Jinja2Templates(settings.base_dir / "templates")
router = fastapi.APIRouter()


@router.get("/", include_in_schema=False)
async def index(request: Request) -> Response:
    return templates.TemplateResponse(request, "home/index.html", {"request": request})


@router.get("/api", include_in_schema=False)
@router.get("/api/v1", include_in_schema=False)
async def api(request: Request) -> Response:
    return templates.TemplateResponse(
        request, "api/index.html", {"request": request, "endpoints": endpoints}
    )


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> fastapi.responses.RedirectResponse:
    return fastapi.responses.RedirectResponse(url="/static/img/favicon.ico")
