import datetime
from typing import Optional

__cache = {}
lifetime_in_hours = 1.0


def get_system_summary(key) -> Optional[dict]:
    key = __create_key(key)
    data: dict = __cache.get(key)
    if not data:
        return None

    last = data["time"]
    dt = datetime.datetime.now() - last
    if dt / datetime.timedelta(minutes=60) < lifetime_in_hours:
        return data["value"]

    del __cache[key]
    return None


def set_system_summary(key, value: dict):
    key = __create_key(key)
    data = {"time": datetime.datetime.now(), "value": value}
    __cache[key] = data
    __clean_out_of_date()


def __create_key(key: str) -> str:
    if not key:
        raise Exception("Key is required")

    return key.strip().lower()


def __clean_out_of_date():
    for key, data in list(__cache.items()):
        dt = datetime.datetime.now() - data.get("time")
        if dt / datetime.timedelta(minutes=60) > lifetime_in_hours:
            del __cache[key]
