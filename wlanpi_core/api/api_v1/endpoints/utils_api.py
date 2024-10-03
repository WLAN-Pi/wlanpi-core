import json
import logging

from fastapi import APIRouter, Response

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import utils
from wlanpi_core.services import utils_service

router = APIRouter()

log = logging.getLogger("uvicorn")


@router.get(
    "/reachability",
    response_model=utils.ReachabilityTest,
    response_model_exclude_none=True,
)
async def reachability():
    """
    Runs the reachability test and returns the results
    """

    try:
        reachability = utils_service.show_reachability()

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
        log.error(ex)
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
#         log.error(ex)
#         return Response(content=f"Internal Server Error {ex}", status_code=500)


@router.get("/usb", response_model=utils.Usb)
async def usb_interfaces():
    """
    Gets a list of usb interfaces and returns them.
    """

    try:
        result = utils_service.show_usb()

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
        log.error(ex)
        return Response(content=f"Internal Server Error", status_code=500)


@router.get("/ufw", response_model=utils.Ufw)
async def usb_interfaces():
    """
    Returns the UFW information.
    """

    try:
        result = utils_service.show_ufw()

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
        log.error(ex)
        return Response(content=f"Internal Server Error", status_code=500)
