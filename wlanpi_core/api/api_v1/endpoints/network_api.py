import json
import logging

from fastapi import APIRouter, Response

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import network
from wlanpi_core.services import network_service

router = APIRouter()

log = logging.getLogger("uvicorn")


@router.get("/neighbors")  # , response_model=network.Neighbors)
async def show_neighbors():
    """
    Run `lldpcli show neighbors -f json` and return results

    Test psuedo code:

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


# @router.get("/interface/ip_config")
# def get_interface_ip_config(interface: str):
#    return "TBD"


# @router.get("/interface/vlan")
# def get_interface_vlan(interface: str):
#    return "TBD"
