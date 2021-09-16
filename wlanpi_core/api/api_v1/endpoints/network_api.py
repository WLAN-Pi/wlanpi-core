import json
import logging
import socket

from fastapi import APIRouter, Response

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
def get_local_ip():
    """
    Return the determined primary local IP address. 

    TODO: Test get_local_ip() when Pi has no connectivity. Abstract out to a service.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # does not have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return {'ip': IP}