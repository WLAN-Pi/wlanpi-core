import os


def get_status():
    running = profiler_beaconing()
    ssid = profiler_beaconing_ssid()

    return {"running": running, "ssid": ssid, "passphrase": "12345678"}


def profiler_beaconing():
    """
    Checks the presence of /var/run/wlanpi-profiler.ssid to determine whether
    or not the Profiler is beaconing
    """
    ssid_file = "/var/run/wlanpi-profiler.ssid"
    if os.path.exists(ssid_file):
        return True
    else:
        return False


def profiler_beaconing_ssid():
    """
    Returns the SSID currently in used by the Profiler
    """
    ssid_file = "/var/run/wlanpi-profiler.ssid"
    if os.path.exists(ssid_file):
        with open(ssid_file, "r") as f:
            return f.read()
    return None
