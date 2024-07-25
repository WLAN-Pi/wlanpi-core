import json
import os
import socket
import subprocess
from dbus import Interface, SystemBus
from dbus.exceptions import DBusException

from wlanpi_core.models.validation_error import ValidationError


REACHABILITY_FILE = '/opt/wlanpi-common/networkinfo/reachability.sh'


def show_reachability():
    '''
    Check if default gateway, internet and DNS are reachable and working
    '''
    
    reachability_info = []

    try:
        reachability_output = subprocess.check_output(
            REACHABILITY_FILE, shell=True).decode()
        reachability_info = reachability_output.split('\n')

        if len(reachability_info) == 0:
            reachability_info.append("Not available.")

        return reachability_info

    except subprocess.CalledProcessError as exc:
        return ["Could not get reachability."]