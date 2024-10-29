import re

from wlanpi_core.utils.general import run_command
from wlanpi_core.constants import BT_ADAPTER


def bluetooth_present():
    """
    We want to use hciconfig here as it works OK when no devices are present
    """
    cmd = f"hciconfig"
    filtered = run_command(cmd=cmd, raise_on_fail=True).grep_stdout_for_string(BT_ADAPTER,)
    return filtered.strip() if filtered else ""


def bluetooth_name():
    cmd = f"bt-adapter -a {BT_ADAPTER} -i"
    filtered = run_command(cmd=cmd, raise_on_fail=True).grep_stdout_for_string("Name", split=True)
    return filtered[0].strip().split(" ")[1] if filtered else ""


def bluetooth_alias():
    cmd = f"bt-adapter -a {BT_ADAPTER} -i"
    filtered = run_command(cmd=cmd, raise_on_fail=True).grep_stdout_for_string("Alias", split=True)
    return filtered[0].strip().split(" ")[1] if filtered else ""


def bluetooth_address():
    cmd = f"bt-adapter -a {BT_ADAPTER} -i"
    filtered = run_command(cmd=cmd, raise_on_fail=True).grep_stdout_for_string("Address", split=True)
    return filtered[0].strip().split(" ")[1] if filtered else ""


def bluetooth_power():
    """
    We want to use hciconfig here as it works OK when no devices are present
    """
    cmd = f"hciconfig {BT_ADAPTER} "
    filtered = run_command(cmd=cmd, raise_on_fail=True).grep_stdout_for_pattern(r"^\s+UP", split=True)
    return filtered[0].strip() if filtered else ""


def bluetooth_set_power(power):
    bluetooth_is_on = bluetooth_power()

    if power:
        if bluetooth_is_on:
            return True
        cmd = f"bt-adapter -a {BT_ADAPTER} --set Powered 1"
        bt_state = 1
    else:
        if not bluetooth_is_on:
            return True
        cmd = f"bt-adapter -a {BT_ADAPTER} --set Powered 0"
        bt_state = 0
    result = run_command(cmd, shell=True, raise_on_fail=True).stdout
    with open('/etc/wlanpi-bluetooth/state', 'w') as bt_state_file:
        bt_state_file.write(str(bt_state))

    if result:
        return True
    else:
        return False


def bluetooth_paired_devices():
    """
    Returns a dictionary of paired devices, indexed by MAC address
    """
    if not bluetooth_present():
        return None

    cmd = "bluetoothctl -- paired-devices"
    output = run_command(cmd=cmd, raise_on_fail=True).grep_stdout_for_pattern(r"no default controller", flags=re.I, negate=True, split=False)
    if len(output) > 0:
        output = re.sub("Device *", "", output).split("\n")
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


# Pairing not yet implemented

# def bluetooth_pair():
#     if not bluetooth_present():
#         return False

#     ok = False
#     if bluetooth_set_power(True):
#         if not bluetooth_paired_devices() == {}:
#             # Unpair existing paired devices
#             paired_devices = bluetooth_paired_devices()
#             '''
#             For some reason removing devices isn't working immediately in Bullseye,
#             so we need to keep trying until all devices are removed.
#             Give up after 30 seconds.
#             '''
#             timeout = 30
#             elapsed_time = 0
#             while paired_devices != None and elapsed_time < timeout:
#                 for dev in paired_devices:
#                     try:
#                         cmd = f"bluetoothctl -- remove {dev}"
#                         subprocess.run(cmd, shell=True,
#                             stdout=subprocess.DEVNULL,
#                             stderr=subprocess.DEVNULL)
#                     except:
#                         pass
#                 paired_devices = bluetooth_paired_devices()
#                 time.sleep(1)
#                 elapsed_time += 1

#         else:
#             paired_devices = bluetooth_paired_devices()
#             if paired_devices != None:
#                 for dev in paired_devices:
#                     return {True: paired_devices[dev]}
#             else:
#                 alias = bluetooth_alias()
#                 try:
#                     cmd = "systemctl start bt-timedpair"
#                     subprocess.run(cmd, shell=True).check_returncode()
#                     return True
#                 except subprocess.CalledProcessError as exc:
#                     return False

#     else:
#         return False
