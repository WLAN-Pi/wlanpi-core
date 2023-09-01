import json
import logging

from fastapi import APIRouter, Response

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.services import network_service

router = APIRouter()

log = logging.getLogger("uvicorn")


@router.get("/neighbors")  # , response_model=network.Neighbors)
async def show_neighbors():
    """
    Run `lldpcli show neighbors -f json` and relay results to consumer.

    Python psuedo code to read this from this endpoint:

    ```
    import urllib.request,json,pprint
    with urllib.request.urlopen('http://<IP:PORT>/api/v1/network/neighbors') as resp:
        data = json.loads(resp.read().decode())
    pprint.pprint(data)
    ```
    """

    try:
        resp = await network_service.get_neighbor_results()
        return json.loads(resp)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)
