import glob
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas.profiler import profiler

profiler_dir = "/var/www/html/profiler/"

log = logging.getLogger("uvicorn")

_HEX = [
    "0",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "a",
    "b",
    "c",
    "d",
    "e",
    "f",
]


def _trim_separator(mac: str) -> str:
    """removes separator from MAC address"""
    return mac.translate(str.maketrans("", "", ":-."))


def _ins(source: str, insert: str, position: int) -> str:
    """inserts value at a certain position in the source"""
    return source[:position] + insert + source[position:]


def _build_mac_with_hyphen_separator(mac: str) -> str:
    """builds the type of separator used"""
    return _ins(
        _ins(
            _ins(_ins(_ins(mac, "-", 2), "-", 5), "-", 8),
            "-",
            11,
        ),
        "-",
        14,
    )


def _is_mac_address(mac: str):
    chars = [x for x in _trim_separator(mac).strip()]
    if any(str(x).lower() not in _HEX for x in chars):
        return False
    if len(_trim_separator(mac)) != 12:
        return False
    return True


def profiler_file_listing(mac: str = None) -> Dict:
    """custom file listing for profiler results"""
    _glob = glob.glob(f"{profiler_dir}**", recursive=True)
    try:
        _glob.sort(key=os.path.getmtime, reverse=True)
    except Exception:
        pass
    files = []
    for _file in _glob:
        if not os.path.isdir(_file):
            if os.path.isfile(_file):
                modifytime = datetime.fromtimestamp(os.path.getmtime(_file)).strftime(
                    "%Y-%m-%d %H:%M:%S%z"  # "%Y-%m-%d %H:%M"
                )
                if any(x in _file for x in [".json"]):
                    files.append(
                        (_file, modifytime, json.loads(Path(_file).read_text()))
                    )

    if mac:
        for file in files:
            if mac in file[0]:
                profile = profiler.Profile(**file[2])
                return profile

        raise ValidationError(status_code=404, error_msg=f"{mac} not found")
    else:
        validated_files = []
        for file in files:
            try:
                validated_files.append(profiler.Profile(**file[2]))
            except Exception:
                log.warning(f"{file[0]} failed Profile schema validation checks")
        return validated_files


async def get_profile(mac: str):
    if _is_mac_address(mac):
        mac = _trim_separator(mac)
        mac = _build_mac_with_hyphen_separator(mac)
        data = profiler_file_listing(mac)
        return data
    else:
        raise ValidationError(
            error_msg=f"{mac} is not a valid MAC address", status_code=400
        )


async def get_profiles():
    profiles = profiler_file_listing()
    return profiles
