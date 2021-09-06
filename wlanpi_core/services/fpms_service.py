import json
import socket

from .helpers import run_cli_async


async def get_system_summary() -> dict:
    """
    Returns device status information:

    - IP address
    - CPU utilization
    - Memory usage
    - Disk utilization
    - Device temperature
    """
    ip = ""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # does not have to be reachable
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except:
        ip = "127.0.0.1"
    finally:
        s.close()

    # determine CPU load
    cmd = "top -bn1 | grep load | awk '{printf \"%.2f\", $(NF-2)}'"
    try:
        cpu = await run_cli_async(cmd)
    except:
        cpu = "unknown"

    # determine memory usage
    cmd = "free -m | awk 'NR==2{printf \"%s/%sMB %.2f%%\", $3,$2,$3*100/$2 }'"
    try:
        mem_usage = await run_cli_async(cmd)
    except:
        mem_usage = "unknown"

    # determine disk utilization
    cmd = 'df -h | awk \'$NF=="/"{printf "%d/%dGB %s", $3,$2,$5}\''
    try:
        disk = await run_cli_async(cmd)
    except:
        disk = "unknown"

    # determine temp
    temp = ""

    try:
        temp_int = int(open("/sys/class/thermal/thermal_zone0/temp", "r").read())
    except:
        temp_int = None

    if temp_int:
        if temp_int > 1000:
            temp_int = temp_int / 1000
        temp = f"{temp_int:.2f}C"

    system_summary = {
        "ip": str(ip),
        "cpu_util": str(cpu),
        "mem_usage": str(mem_usage),
        "disk_util": str(disk),
        "temp": temp,
    }
    return json.dumps(system_summary)
