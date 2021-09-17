import json
import logging

from fastapi import APIRouter, Response
from starlette.responses import JSONResponse

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import network
from wlanpi_core.services import network_service

router = APIRouter()

log = logging.getLogger("uvicorn")


@router.get("/neighbors")  # , response_model=network.Neighbors)
async def show_neighbors():
    """
    Run `lldpcli show neighbors -f json` and relay results to consumer.

    TODO: remove test psuedo code, this is what Swagger UI is for:

    ```
    import urllib.request,json,pprint
    with urllib.request.urlopen('http://[WLANPI]/api/v1/network/neighbors') as resp:
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
        return Response(content=str(ex), status_code=500)


@router.get("/publicip", response_model=network.PublicIP)
async def retrieve_public_ip_information():
    """
    publicip leverages the `ifconfig.co/json` service to retrieve public IP information.
    """
    try:
        return await network_service.get_public_ip()
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)


@router.get("/localip")
async def get_local_ip():
    """
    Return the determined primary local IP address without a given interface.

    TODO: Test get_local_ip() when Pi has no connectivity. Abstract out to a service.
    """
    try:
        return await network_service.get_local_ip()
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)


@router.get("/reachability")
async def get_internet_reachability(host="8.8.8.8", port=53, timeout=3):
    """
    Get the reachability status of the internet from the Pi.
    """
    try:
        if network_service.get_internet(host, port, timeout):
            return JSONResponse(
                content={"reachability": True, "host": host, "port": port},
                status_code=200,
            )
        else:
            return JSONResponse(
                content={"reachability": False, "host": host, "port": port},
                status_code=404,
            )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)
