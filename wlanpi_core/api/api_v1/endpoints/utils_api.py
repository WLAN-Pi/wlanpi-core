import json
import logging

from fastapi import APIRouter, Response

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import utils
from wlanpi_core.schemas.utils.utils import TracerouteResponse
from wlanpi_core.services import utils_service

router = APIRouter()

log = logging.getLogger("uvicorn")


@router.get(
    "/reachability",
    response_model=utils.ReachabilityTest,
    response_model_exclude_none=True,
)
async def check_reachability():
    """
    Runs the reachability test and returns the results
    """

    try:
        reachability = await utils_service.show_reachability()

        if reachability.get("error"):
            return Response(
                content=json.dumps(reachability),
                status_code=503,
                media_type="application/json",
            )

        return reachability["results"]

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex, exc_info=ex)
        return Response(content=f"Internal Server Error", status_code=500)


# @router.post("/port_blinker/{action}", response_model=utils.PortBlinkerState)
# async def port_blinker(action: str):
#     """
#     Turns on bluetooth

#     - action: "on" or "off"
#     """

#     # Validate action parameter
#     if action not in ["on", "off"]:
#         return Response(content="Invalid action. Use 'on' or 'off'.", status_code=400)

#     # Convert action to Boolean
#     state = action == "on"

#     try:
#         status = utils_service.port_blinker_state(state)

#         if status == False:
#             return Response(content=f"Port blinker failed to turn {action}", status_code=503)

#         return {"status": "success", "action": action}

#     except ValidationError as ve:
#         return Response(content=ve.error_msg, status_code=ve.status_code)
#     except Exception as ex:
#         log.error(ex, exc_info=ex)
#         return Response(content=f"Internal Server Error {ex}", status_code=500)


@router.get("/usb", response_model=utils.Usb)
async def usb_interfaces():
    """
    Gets a list of usb interfaces and returns them.
    """

    try:
        result = await utils_service.show_usb()

        if result.get("error"):
            return Response(
                content=json.dumps(result["error"]),
                status_code=503,
                media_type="application/json",
            )

        return result

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex, exc_info=ex)
        return Response(content=f"Internal Server Error", status_code=500)


@router.get("/ufw", response_model=utils.Ufw)
async def ufw_information():
    """
    Returns the UFW information.
    """

    try:
        result = await utils_service.show_ufw()

        if result.get("error"):
            return Response(
                content=json.dumps(result["error"]),
                status_code=503,
                media_type="application/json",
            )

        return result

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex, exc_info=ex)
        return Response(content=f"Internal Server Error", status_code=500)


@router.post("/ping", response_model=utils.PingResult)
async def execute_ping(request: utils.PingRequest):
    """
    Pings a target and returns the results
    """

    try:
        result = await utils_service.ping(
            request.host,
            request.count,
            request.interval,
            request.ttl,
            request.interface,
        )
        return result

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex, exc_info=ex)
        return Response(content=f"Internal Server Error: {ex}", status_code=500)


@router.post("/iperf2/client", response_model=utils.Iperf2Result)
async def execute_iperf(request: utils.Iperf2ClientRequest):
    """
    Runs iperf2 against a target and returns the results
    """

    try:
        return await utils_service.run_iperf2_client(**request.__dict__)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex, exc_info=ex)
        return Response(content=f"Internal Server Error: {ex}", status_code=500)


@router.post("/iperf3/client", response_model=None)
async def execute_iperf3_client(request: utils.Iperf3ClientRequest):
    """
    Runs iperf3 against a target and returns the results
    """

    try:
        return await utils_service.run_iperf3_client(**request.__dict__)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex, exc_info=ex)
        return Response(content=f"Internal Server Error: {ex}", status_code=500)


@router.post("/traceroute", response_model=TracerouteResponse)
async def execute_traceroute(request: utils.TracerouteRequest):
    """
    Run traceroute and return the results
    """
    try:
        return await utils_service.run_traceroute(**request.__dict__)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex, exc_info=ex)
        return Response(content=f"Internal Server Error: {ex}", status_code=500)


@router.post("/dhcp/test", response_model=utils.DhcpTestResponse)
async def execute_dhcp_test(request: utils.DhcpTestRequest):
    """
    Run a dhcpcd test and return the results
    """
    try:
        return await utils_service.run_dhcp_test(**request.__dict__)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex, exc_info=ex)
        return Response(content=f"Internal Server Error: {ex}", status_code=500)


@router.post("/dns/dig", response_model=list[utils.DigResponse])
async def execute_dig(request: utils.DigRequest):
    """
    Run a dhcpcd test and return the results
    """
    try:
        return await utils_service.dig(**request.__dict__)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex, exc_info=ex)
        return Response(content=f"Internal Server Error: {ex}", status_code=500)
