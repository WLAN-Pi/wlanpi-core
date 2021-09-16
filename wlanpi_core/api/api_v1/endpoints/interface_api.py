import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/interfaces")
async def show_interfaces_list():
    """
    Return a list of phy80211 compatible interfaces
    """
    interfaces = []
    path = "/sys/class/net"
    for net, ifaces, files in os.walk(path):
        for iface in ifaces:
            for dirpath, dirnames, filenames in os.walk(os.path.join(path, iface)):
                if "phy80211" in dirnames:
                    interfaces.append(iface)
    return JSONResponse(interfaces, status_code=200)
