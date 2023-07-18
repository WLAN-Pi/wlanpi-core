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

    Python psuedo code to read this from this endpoint:

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


@router.get("/publicipv4", response_model=network.PublicIP)
async def retrieve_public_ip_information():
    """
    publicip leverages the `ifconfig.co/json` service to retrieve public IP information.
    """
    try:
        return await network_service.get_public_ipv4()
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)


@router.get("/publicipv6", response_model=network.PublicIP)
async def retrieve_public_ip_information():
    """
    publicip leverages the `ifconfig.co/json` service to retrieve public IP information.
    """
    try:
        return await network_service.get_public_ipv6()
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)


@router.get("/localipv4")
async def get_local_ipv4():
    """
    TODO: Test get_local_ipv4() when Pi has no connectivity. Abstract out to a service.

    Return the determined primary local IPv4 address without a given interface.
    """
    try:
        return await network_service.get_local_ipv4()
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)


@router.get("/localipv6")
async def get_local_ipv6():
    """
    TODO: Test get_local_ipv6() when Pi has no connectivity. Abstract out to a service.

    Return the determined primary local IPv6 address without a given interface.
    """
    try:
        return await network_service.get_local_ipv6()
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)


@router.get("/ipv4_reachability")
async def get_ipv4_internet_reachability(host="8.8.8.8", port=53, timeout=3):
    """
    TODO: When host has IPv6 reachability. IPv6 is returned. Force IPv4.

    Get IPv4 reachability to Internet from the Pi.
    """
    try:
        if network_service.get_ipv4_internet_reachability(host, port, timeout):
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


@router.get("/ipv6_reachability")
async def get_ipv6_internet_reachability(
    host="2001:4860:4860::8888", port=53, timeout=3
):
    """
    TODO: When host only has IPv4 reachability, we get IPv4 response. Force IPv6.

    Get IPv6 reachability to Internet from the Pi.
    """
    try:
        if network_service.get_ipv6_internet_reachability(host, port, timeout):
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
