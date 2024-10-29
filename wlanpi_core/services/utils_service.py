import os
import re

from wlanpi_core.constants import UFW_FILE

from ..models.runcommand_error import RunCommandError
from ..utils.general import run_command_async
from ..utils.network import get_default_gateways


async def show_reachability():
    """
    Check if default gateway, internet and DNS are reachable and working
    """

    output = {"results": {}}

    # --- Variables ---
    try:
        dg_interface, default_gateway = list(get_default_gateways().items())[0]

        dns_servers = [
            line.split()[1]
            for line in open("/etc/resolv.conf")
            if line.startswith("nameserver")
        ]
    except RunCommandError as err:
        return {"error": "Failed to determine network configuration: {}".format(err)}

    # --- Checks ---
    if not default_gateway:
        return {"error": "No default gateway"}

    # Start executing tests in the background
    ping_google_cr = run_command_async(
        "jc ping -c1 -W2 -q google.com", raise_on_fail=False
    )
    browse_google_result_cr = run_command_async(
        "timeout 2 curl -s -L www.google.com", raise_on_fail=False
    )
    ping_gateway_cr = run_command_async(
        f"jc ping -c1 -W2 -q {default_gateway}", raise_on_fail=False
    )
    arping_gateway_cr = run_command_async(
        f"timeout 2 arping -c1 -w2 -I {dg_interface} {default_gateway}",
        raise_on_fail=False,
    )
    dns_res_crs = [
        (
            i,
            run_command_async(
                f"dig +short +time=2 +tries=1 @{dns} NS google.com", raise_on_fail=False
            ),
        )
        for i, dns in enumerate(dns_servers[:3], start=1)
    ]

    # Ping Google
    ping_google = await ping_google_cr
    output["results"]["Ping Google"] = (
        f"{ping_google.output_from_json()['round_trip_ms_avg']}ms"
        if ping_google.success
        else "FAIL"
    )

    # Browse Google.com
    browse_google_result = await browse_google_result_cr
    output["results"]["Browse Google"] = (
        "OK"
        if (
            browse_google_result.success and "google.com" in browse_google_result.stdout
        )
        else "FAIL"
    )

    # Ping default gateway
    ping_gateway = await ping_gateway_cr
    output["results"]["Ping Gateway"] = (
        f"{ping_gateway.output_from_json()['round_trip_ms_avg']}ms"
        if ping_gateway.success
        else "FAIL"
    )

    # DNS resolution checks
    for i, cr in dns_res_crs:
        dns_res = await cr
        output["results"][f"DNS Server {i} Resolution"] = (
            "OK" if dns_res.success else "FAIL"
        )

    # ARPing default gateway
    arping_gateway = (await arping_gateway_cr).stdout
    arping_rtt = re.search(r"\d+ms", arping_gateway)
    output["results"]["Arping Gateway"] = arping_rtt.group(0) if arping_rtt else "FAIL"

    return output


async def show_usb():
    """
    Return a list of non-Linux USB interfaces found with the lsusb command
    """
    interfaces = {}

    try:
        lsusb_output = (
            await run_command_async("/usr/bin/lsusb", raise_on_fail=True)
        ).stdout.split("\n")
        lsusb_info = [
            line.split(" ", 6)[-1].strip()
            for line in lsusb_output
            if "Linux" not in line
        ]
    except RunCommandError as err:
        error_descr = "Issue getting usb info using lsusb command"
        interfaces["error"] = {"error": {error_descr + ": " + err.error_msg}}
        return interfaces

    interfaces["interfaces"] = []

    for result in (result for result in lsusb_info if result != ""):
        interfaces["interfaces"].append(result)

    if len(interfaces) == 0:
        interfaces["interfaces"].append("No devices detected")

    return interfaces


def parse_ufw(output):
    """
    Parses the output of the UFW file into readable json for the api.
    """

    lines = output.strip().split("\n")

    status_line = lines[0]
    status = status_line.split(":")[1].strip()

    # Check if there are at least 3 lines (status + headers + at least one rule)
    if len(lines) <= 3:
        # No rules present in the output
        parsed_rules = []
    else:
        rules = lines[3:]
        parsed_rules = []

        # IPv6 pattern detection: "XX (v6)" followed by "ALLOW" and "Anywhere (v6)"
        ipv6_pattern = re.compile(r"\(v6\)")

        for rule in rules:
            parts = rule.split()

            if len(parts) >= 3 and (parts[1] == "ALLOW" or parts[1] == "DENY"):
                to = parts[0]
                action = parts[1]
                from_ = " ".join(parts[2:])
            elif len(parts) >= 4 and ipv6_pattern.search(rule):
                to = " ".join(parts[0:2])
                action = parts[2]
                from_ = " ".join(parts[3:])
            else:
                continue

            parsed_rules.append({"To": to, "Action": action, "From": from_})
    final_output = {"status": status, "ports": parsed_rules}
    return final_output


async def show_ufw():
    """
    Return a list ufw ports
    """
    ufw_file = UFW_FILE
    ufw_info = []

    response = {}

    # check ufw is available
    if not os.path.isfile(ufw_file):
        response["error"] = {"error": "UFW is not installed."}

        return response

    try:
        ufw_output = (
            await run_command_async(
                "sudo {} status".format(ufw_file), raise_on_fail=True
            )
        ).stdout
        ufw_info = parse_ufw(ufw_output)

    except:
        error_descr = "Issue getting ufw info using ufw command"
        response["error"] = {"error": error_descr}
        return

    # Add in status line

    response = ufw_info

    return response
