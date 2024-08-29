import json
import os
import socket
import re
import subprocess
from dbus import Interface, SystemBus
from dbus.exceptions import DBusException

from wlanpi_core.models.validation_error import ValidationError

from .helpers import run_command

def show_reachability():
    '''
    Check if default gateway, internet and DNS are reachable and working
    '''
    
    output = {"results": {}}
    

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
    try:
        ping_google_rtt = re.search(r'rtt min/avg/max/mdev = \S+/(\S+)/\S+/\S+ ms', ping_google)
        output["results"]["Ping Google"] = f"{ping_google_rtt.group(1)}ms" if ping_google_rtt else None
    except:
        output["results"]["Ping Google"] = "FAIL"
    

    # Browse Google.com
    browse_google = run_command("timeout 2 curl -s -L www.google.com | grep 'google.com'")
    output["results"]["Browse Google"] = "OK" if browse_google is not None else "FAIL"

    # Ping default gateway
    ping_gateway = run_command(f"ping -c1 -W2 -q {default_gateway}")
    try:
        ping_gateway_rtt = re.search(r'rtt min/avg/max/mdev = \S+/(\S+)/\S+/\S+ ms', ping_gateway)
        output["results"]["Ping Gateway"] = f"{ping_gateway_rtt.group(1)}ms" if ping_gateway_rtt else None
    except:
        output["results"]["Ping Gateway"] = "FAIL"

    # DNS resolution checks
    for i, dns in enumerate(dns_servers[:3], start=1):
        dns_res = run_command(f"dig +short +time=2 +tries=1 @{dns} NS google.com")
        if dns_res:
            output["results"][f"DNS Server {i} Resolution"] = "OK"

    # ARPing default gateway
    arping_gateway = run_command(f"timeout 2 arping -c1 -w2 -I {dg_interface} {default_gateway} 2>/dev/null")
    arping_rtt = re.search(r'\d+ms', arping_gateway)
    output["results"]["Arping Gateway"] = arping_rtt.group(0) if arping_rtt else "FAIL"
    
    return output


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
        "ip_address": r"Testing from .*\(([\d\.]+)\)",
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


def show_usb():
    '''
    Return a list of non-Linux USB interfaces found with the lsusb command
    '''

    lsusb = r'/usr/bin/lsusb | /bin/grep -v Linux | /usr/bin/cut -d\  -f7-'
    lsusb_info = []
    
    interfaces = {"error": {}, "interfaces": []}

    try:
        lsusb_output = subprocess.check_output(lsusb, shell=True).decode()
        lsusb_info = lsusb_output.split('\n')
    except subprocess.CalledProcessError as exc:
        output = exc.output.decode()
        #error_descr = "Issue getting usb info using lsusb command"
        interfaces["error"] = {"lsusb error": str(output)}
        return interfaces

    for result in (result for result in lsusb_info if result != ""):
        interfaces["interfaces"].append(result)

    if len(interfaces) == 0:
        interfaces["interfaces"].append("No devices detected")

    return interfaces


def show_ufw():
    '''
    Return a list ufw ports
    '''
    ufw_file = UFW_FILE
    ufw_info = []

    # check ufw is available
    if not os.path.isfile(ufw_file):

        self.alert_obj.display_alert_error(g_vars, "UFW is not installed.")

        g_vars['display_state'] = 'page'
        return

    # If no cached ufw data from previous screen paint, run ufw status
    if g_vars['result_cache'] == False:

        try:
            ufw_output = subprocess.check_output(
                "sudo {} status".format(ufw_file), shell=True).decode()
            ufw_info = ufw_output.split('\n')
            g_vars['result_cache'] = ufw_info  # cache results
        except Exception as ex:
            error_descr = "Issue getting ufw info using ufw command"
            interfaces = ["Err: ufw error", error_descr, str(ex)]
            self.simple_table_obj.display_simple_table(g_vars, interfaces)
            return
    else:
        # we must have cached results from last time
        ufw_info = g_vars['result_cache']

    port_entries = []

    # Add in status line
    port_entries.append(ufw_info[0])

    port_entries.append("Ports:")

    # lose top 4 & last 2 lines of output
    ufw_info = ufw_info[4:-2]

    for result in ufw_info:

        # tidy/compress the output
        result = result.strip()
        result_list = result.split()

        final_result = ' '.join(result_list)

        port_entries.append(final_result)

    if len(port_entries) == 0:
        port_entries.append("No UF info detected")

    # final check no-one pressed a button before we render page
    if g_vars['display_state'] == 'menu':
        return

    self.paged_table_obj.display_list_as_paged_table(g_vars, port_entries, title='UFW Ports')

    return