import json
import os
import socket
import re
import subprocess
from dbus import Interface, SystemBus
from dbus.exceptions import DBusException

from wlanpi_core.models.validation_error import ValidationError

def run_command(cmd):
    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL)
        return output.decode().strip()
    except subprocess.CalledProcessError:
        return None

def show_reachability():
    '''
    Check if default gateway, internet and DNS are reachable and working
    '''
    
    results = {}

    # --- Variables ---
    try:
        default_gateway = subprocess.check_output(
            "ip route | grep 'default' | grep -E -o '([0-9]{1,3}[\\.]){3}[0-9]{1,3}' | head -n1", 
            shell=True
        ).decode().strip()
        
        dg_interface = subprocess.check_output(
            "ip route | grep 'default' | head -n1 | cut -d ' ' -f5", 
            shell=True
        ).decode().strip()
        
        dns_servers = [line.split()[1] for line in open('/etc/resolv.conf') if line.startswith('nameserver')]
    except subprocess.CalledProcessError:
        return {"error": "Failed to determine network configuration"}

    # --- Checks ---
    if not default_gateway:
        return {"error": "No default gateway"}

    # Ping Google
    ping_google = run_command("ping -c1 -W2 -q google.com")
    ping_google_rtt = re.search(r'rtt min/avg/max/mdev = \S+/(\S+)/\S+/\S+ ms', ping_google)
    results["Ping Google"] = f"{ping_google_rtt.group(1)}ms" if ping_google_rtt else None

    # Browse Google.com
    browse_google = run_command("timeout 2 curl -s -L www.google.com | grep 'google.com'")
    results["Browse Google"] = "OK" if browse_google is not None else "FAIL"

    # Ping default gateway
    ping_gateway = run_command(f"ping -c1 -W2 -q {default_gateway}")
    ping_gateway_rtt = re.search(r'rtt min/avg/max/mdev = \S+/(\S+)/\S+/\S+ ms', ping_gateway)
    results["Ping Gateway"] = f"{ping_gateway_rtt.group(1)}ms" if ping_gateway_rtt else None

    # DNS resolution checks
    for i, dns in enumerate(dns_servers[:3], start=1):
        dns_res = run_command(f"dig +short +time=2 +tries=1 @{dns} NS google.com")
        if dns_res:
            results[f"DNS Server {i} Resolution"] = "OK"

    # ARPing default gateway
    arping_gateway = run_command(f"timeout 2 arping -c1 -w2 -I {dg_interface} {default_gateway} 2>/dev/null")
    arping_rtt = re.search(r'\d+ms', arping_gateway)
    results["Arping Gateway"] = arping_rtt.group(0) if arping_rtt else "FAIL"
    
    return results


def show_speedtest():
    '''
    Run speedtest.net speed test
    '''
    
        # Command to execute speedtest-cli and process its output
    speedtest_cmd = "/opt/wlanpi/pipx/bin/speedtest-cli --secure"
    
    # Run the command
    speedtest_info = run_command(speedtest_cmd)
    
    if not speedtest_info:
        return {"error": "Failed to run speedtest"}

    # Define regex patterns to extract parts from the output
    patterns = {
        "IP_address": r"Testing from .*\(([\d\.]+)\)",
        "download_speed": r"Download:\s+([\d\.]+)\s*Mbit/s",
        "upload_speed": r"Upload:\s+([\d\.]+)\s*Mbit/s"
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