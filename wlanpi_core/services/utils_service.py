import os
import re
import subprocess

from .helpers import run_command

UFW_FILE = "/usr/sbin/ufw"


def show_reachability():
    """
    Check if default gateway, internet and DNS are reachable and working
    """

    output = {"results": {}}

    # --- Variables ---
    try:
        default_gateway = (
            subprocess.check_output(
                "ip route | grep 'default' | grep -E -o '([0-9]{1,3}[\\.]){3}[0-9]{1,3}' | head -n1",
                shell=True,
            )
            .decode()
            .strip()
        )

        dg_interface = (
            subprocess.check_output(
                "ip route | grep 'default' | head -n1 | cut -d ' ' -f5", shell=True
            )
            .decode()
            .strip()
        )

        dns_servers = [
            line.split()[1]
            for line in open("/etc/resolv.conf")
            if line.startswith("nameserver")
        ]
    except subprocess.CalledProcessError:
        return {"error": "Failed to determine network configuration"}

    # --- Checks ---
    if not default_gateway:
        return {"error": "No default gateway"}

    # Ping Google
    ping_google = run_command("ping -c1 -W2 -q google.com")
    try:
        ping_google_rtt = re.search(
            r"rtt min/avg/max/mdev = \S+/(\S+)/\S+/\S+ ms", ping_google
        )
        output["results"]["Ping Google"] = (
            f"{ping_google_rtt.group(1)}ms" if ping_google_rtt else None
        )
    except:
        output["results"]["Ping Google"] = "FAIL"

    # Browse Google.com
    browse_google = run_command(
        "timeout 2 curl -s -L www.google.com | grep 'google.com'"
    )
    output["results"]["Browse Google"] = "OK" if browse_google is not None else "FAIL"

    # Ping default gateway
    ping_gateway = run_command(f"ping -c1 -W2 -q {default_gateway}")
    try:
        ping_gateway_rtt = re.search(
            r"rtt min/avg/max/mdev = \S+/(\S+)/\S+/\S+ ms", ping_gateway
        )
        output["results"]["Ping Gateway"] = (
            f"{ping_gateway_rtt.group(1)}ms" if ping_gateway_rtt else None
        )
    except:
        output["results"]["Ping Gateway"] = "FAIL"

    # DNS resolution checks
    for i, dns in enumerate(dns_servers[:3], start=1):
        dns_res = run_command(f"dig +short +time=2 +tries=1 @{dns} NS google.com")
        if dns_res:
            output["results"][f"DNS Server {i} Resolution"] = "OK"

    # ARPing default gateway
    arping_gateway = run_command(
        f"timeout 2 arping -c1 -w2 -I {dg_interface} {default_gateway} 2>/dev/null"
    )
    arping_rtt = re.search(r"\d+ms", arping_gateway)
    output["results"]["Arping Gateway"] = arping_rtt.group(0) if arping_rtt else "FAIL"

    return output


def show_speedtest():
    """
    Run speedtest.net speed test
    """

    # Command to execute speedtest-cli and process its output
    speedtest_cmd = "/opt/wlanpi/pipx/bin/speedtest-cli --secure"

    # Run the command
    speedtest_info = run_command(speedtest_cmd)

    if not speedtest_info:
        return {"error": "Failed to run speedtest"}

    # Define regex patterns to extract parts from the output
    patterns = {
        "ip_address": r"Testing from .*\(([\d\.]+)\)",
        "download_speed": r"Download:\s+([\d\.]+)\s*Mbit/s",
        "upload_speed": r"Upload:\s+([\d\.]+)\s*Mbit/s",
    }

    # Extract information using regex
    results = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, speedtest_info)
        if match:
            # Extract the number and format it
            number = match.group(1)
            if key in ["download_speed", "upload_speed"]:
                results[key] = f"{number} Mbps"
            else:
                results[key] = number

    return results


def show_usb():
    """
    Return a list of non-Linux USB interfaces found with the lsusb command
    """

    lsusb = r"/usr/bin/lsusb | /bin/grep -v Linux | /usr/bin/cut -d\  -f7-"
    lsusb_info = []

    interfaces = {}

    try:
        lsusb_output = subprocess.check_output(lsusb, shell=True).decode()
        lsusb_info = lsusb_output.split("\n")
    except subprocess.CalledProcessError as exc:
        output = exc.output.decode()
        # error_descr = "Issue getting usb info using lsusb command"
        interfaces["error"] = {"lsusb error": str(output)}
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
    status = status_line.split(":")[1].strip()  # Extract status value after "Status:"

    # Check if there are at least 4 lines (status + headers + at least one rule)
    if len(lines) <= 4:
        # No rules present in the output
        parsed_rules = ["No UF info detected"]
    else:
        # Skip the first 4 lines as they are headers or status
        rules = lines[4:]

        parsed_rules = []

        for rule in rules:
            parts = rule.split()

            # Check if the line is long enough to be a rule and not malformed
            if len(parts) >= 3:
                if parts[1] == "ALLOW" or parts[1] == "DENY":
                    # Correctly formatted rule (e.g., "22/tcp ALLOW Anywhere")
                    to = parts[0]
                    action = parts[1]
                    from_ = " ".join(
                        parts[2:]
                    )  # Join remaining parts in case "From" has multiple words
                else:
                    # Special rule format (e.g., "Anywhere on pan0 ALLOW Anywhere")
                    to = " ".join(parts[:3])  # Combine first two parts for 'To'
                    action = parts[3]
                    from_ = " ".join(parts[4:])  # Remaining parts for 'From'

                parsed_rules.append({"To": to, "Action": action, "From": from_})

    final_output = {"status": status, "ports": parsed_rules}
    return final_output


def show_ufw():
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
        ufw_output = subprocess.check_output(
            "sudo {} status".format(ufw_file), shell=True
        ).decode()
        ufw_info = parse_ufw(ufw_output)

    except Exception as ex:
        error_descr = "Issue getting ufw info using ufw command"
        response["error"] = {"error": error_descr + str(ex)}
        return

    # Add in status line

    response = ufw_info

    return response
