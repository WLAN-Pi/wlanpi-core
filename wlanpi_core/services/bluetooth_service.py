import json
import os
import socket
import subprocess
import re
from dbus import Interface, SystemBus
from dbus.exceptions import DBusException

from wlanpi_core.models.validation_error import ValidationError

from .helpers import run_command

BT_ADAPTER = "hci0"

def bluetooth_present():
    '''
    We want to use hciconfig here as it works OK when no devices are present
    '''
    return run_command(f"hciconfig | grep {BT_ADAPTER}")

def bluetooth_name():
    cmd = f"bt-adapter -a {BT_ADAPTER} -i" + "| grep Name | awk '{ print $2 }'"
    return run_command(cmd)

def bluetooth_alias():
    cmd = f"bt-adapter -a {BT_ADAPTER} -i" + "| grep Alias | awk '{ print $2 }'"
    return run_command(cmd)

def bluetooth_address():
    cmd = f"bt-adapter -a {BT_ADAPTER} -i" + "| grep Address | awk '{ print $2 }'"
    return run_command(cmd)

def bluetooth_power():
    '''
    We want to use hciconfig here as it works OK when no devices are present
    '''
    cmd = f"hciconfig {BT_ADAPTER} | grep -E '^\s+UP'"
    return run_command(cmd)

def bluetooth_set_power(power):
    bluetooth_is_on = bluetooth_power()
    
    if power:
        if bluetooth_is_on:
            return True
        cmd = f"bt-adapter -a {BT_ADAPTER} --set Powered 1 && echo 1 > /etc/wlanpi-bluetooth/state"
    else:
        if not bluetooth_is_on:
            return True
        cmd = f"bt-adapter -a {BT_ADAPTER} --set Powered 0 && echo 0 > /etc/wlanpi-bluetooth/state"
    result = run_command(cmd)
    
    if result:
        return True
    else:
        return False

def bluetooth_paired_devices():
    '''
    Returns a dictionary of paired devices, indexed by MAC address
    '''

    if not bluetooth_present():
        return None
    
    cmd = "bluetoothctl -- paired-devices | grep -iv 'no default controller'"
    output = run_command(cmd)
    if len(output) > 0:
        output = re.sub("Device *", "", output).split('\n')
        return dict([line.split(" ", 1) for line in output])
    else:
        return None

def bluetooth_status():
    status = {}

    if not bluetooth_present():
        return False

    status["name"] = bluetooth_name()
    status["alias"] = bluetooth_alias()
    status["addr"] = bluetooth_address()

    if bluetooth_power():
        status["power"] = "On"
    else:
        status["power"] = "Off"

    paired_devices = bluetooth_paired_devices()

    if paired_devices != None:
        status["paired_devices"] = []
        for mac in paired_devices:
            status["paired_devices"].append({"name": paired_devices[mac], "addr": mac})
            
    return status


def bluetooth_pair():
    if not bluetooth_present():
        return False

    ok = False
    if bluetooth_set_power(True):
        if not bluetooth_paired_devices() == {}:
            # Unpair existing paired devices
            paired_devices = bluetooth_paired_devices()
            '''
            For some reason removing devices isn't working immediately in Bullseye,
            so we need to keep trying until all devices are removed.
            Give up after 30 seconds.
            '''
            timeout = 30
            elapsed_time = 0
            while paired_devices != None and elapsed_time < timeout:
                for dev in paired_devices:
                    try:
                        cmd = f"bluetoothctl -- remove {dev}"
                        subprocess.run(cmd, shell=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
                    except:
                        pass
                paired_devices = bluetooth_paired_devices()
                time.sleep(1)
                elapsed_time += 1
                
        else:
            paired_devices = bluetooth_paired_devices()
            if paired_devices != None:
                for dev in paired_devices:
                    return {True: paired_devices[dev]}
            else:
                alias = bluetooth_alias()
                try:
                    cmd = "systemctl start bt-timedpair"
                    subprocess.run(cmd, shell=True).check_returncode()
                    return True
                except subprocess.CalledProcessError as exc:
                    return False

    else:
        return False
