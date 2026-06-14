"""WPA supplicant and iw scan primitives."""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)

_SCAN_POLL_INTERVAL_SEC = 0.5
_SCAN_POLL_ATTEMPTS = 8
_VALID_DETAIL = frozenset({"short", "full"})


class ScanNotSupportedError(Exception):
    """Active scan is not supported on this interface."""


def normalize_scan_detail(detail: str) -> str:
    detail = (detail or "short").strip().lower()
    if detail not in _VALID_DETAIL:
        raise ValueError(f"detail must be one of: {', '.join(sorted(_VALID_DETAIL))}")
    return detail


def freq_to_channel(freq_mhz: int) -> Optional[int]:
    """Map centre frequency (MHz) to 802.11 channel number."""
    if freq_mhz == 2484:
        return 14
    if 2412 <= freq_mhz <= 2484:
        return int((freq_mhz - 2412) / 5 + 1)
    if 5160 <= freq_mhz <= 5885:
        return int((freq_mhz - 5180) / 5 + 36)
    if 5955 <= freq_mhz <= 7115:
        return int((freq_mhz - 5955) / 5 + 1)
    return None


def parse_key_mgmt(flags: str) -> str:
    """Parse key management type from WPA scan-result flags."""
    if "WPA2-PSK" in flags:
        return "wpa-psk"
    if "WPA-PSK" in flags:
        return "wpa-psk"
    if "WEP" in flags:
        return "wep"
    if "[ESS]" in flags and "WPA" not in flags:
        return "open"
    return "unknown"


def parse_wpa_scan_results(
    text: str, include_hidden: bool = True
) -> list[dict[str, Any]]:
    """Parse ``wpa_cli scan_results`` tab-separated output."""
    networks: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}

    for line in text.splitlines()[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) == 4:
            parts.append("")
        if len(parts) < 5:
            continue
        bssid, freq_str, signal_str, flags, ssid = parts[:5]
        if not include_hidden and not ssid:
            continue
        try:
            freq = int(freq_str)
            signal = int(signal_str)
        except ValueError:
            continue

        entry = {
            "ssid": ssid,
            "bssid": bssid.lower(),
            "signal": signal,
            "freq": freq,
            "key_mgmt": parse_key_mgmt(flags),
            "minrate": 1_000_000,
            "flags": flags,
            "primaryChannel": freq_to_channel(freq),
            "channelWidth": None,
            "secondaryChannelOffset": None,
            "bssLoad": None,
            "amendments": [],
        }
        existing = seen.get(entry["bssid"])
        if existing is None or entry["signal"] > existing["signal"]:
            seen[entry["bssid"]] = entry

    networks.extend(seen.values())
    networks.sort(key=lambda n: n["signal"], reverse=True)
    return networks


def split_iw_bss_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("BSS "):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _parse_secondary_channel_offset(block: str) -> Optional[str]:
    """Parse HT secondary channel offset from an iw BSS block."""
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("* secondary channel offset:"):
            raw = stripped.split(":", 1)[1].strip().lower()
            if raw == "no secondary":
                return "none"
            if raw == "above control channel":
                return "above"
            if raw == "below control channel":
                return "below"
            return raw
    return None


def _parse_channel_width(block: str) -> Optional[int]:
    for line in block.splitlines():
        stripped = line.strip()
        match = re.search(r"channel width:\s*(\d+)\s*MHz", stripped, re.I)
        if match:
            return int(match.group(1))
    if re.search(r"HT operation:", block, re.I) and not re.search(
        r"secondary channel offset: no secondary", block, re.I
    ):
        return 40
    return None


def _parse_bss_load(block: str) -> Optional[dict[str, int]]:
    stations = None
    utilization = None
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("* station count:"):
            try:
                stations = int(stripped.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif stripped.startswith("* channel utilisation:"):
            raw = stripped.split(":", 1)[1].strip()
            try:
                if "/" in raw:
                    utilization = int(raw.split("/", 1)[0].strip())
                else:
                    utilization = int(raw)
            except ValueError:
                pass
    if stations is None and utilization is None:
        return None
    return {"stations": stations, "utilization": utilization}


def _parse_iw_flags(block: str) -> Optional[str]:
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("capability:"):
            return stripped.split(":", 1)[1].strip()
    return None


def _detect_amendments(block: str) -> list[str]:
    amendments: list[str] = []
    if re.search(r"HT capabilities:", block, re.I):
        amendments.append("n")
    if re.search(r"VHT ", block, re.I):
        amendments.append("ac")
    if re.search(r"HE ", block, re.I):
        amendments.append("ax")
    if re.search(r"EHT ", block, re.I):
        amendments.append("be")
    if re.search(r"RM enabled|Radio Measurement", block, re.I):
        amendments.append("k")
    if re.search(r"WNM|BSS Transition", block, re.I):
        amendments.append("v")
    if re.search(r"\bFT\b|FT over", block, re.I):
        amendments.append("r")
    return amendments


def _parse_primary_channel(block: str, freq: int) -> Optional[int]:
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("* primary channel:"):
            try:
                return int(stripped.split(":", 1)[1].strip())
            except ValueError:
                break
    return freq_to_channel(freq)


def parse_iw_bss_block(
    block: str, include_hidden: bool = True, detail: str = "short"
) -> Optional[dict[str, Any]]:
    """Parse one ``iw dev <iface> scan`` BSS block."""
    match = re.match(r"BSS ([0-9a-f:]+)", block, re.IGNORECASE)
    if not match:
        return None

    bssid = match.group(1).lower()
    ssid = ""
    signal = 0
    freq = 0
    key_mgmt = "unknown"

    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("SSID:"):
            ssid = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("signal:"):
            try:
                signal = int(float(stripped.split()[1]))
            except (IndexError, ValueError):
                pass
        elif stripped.startswith("freq:"):
            try:
                freq = int(stripped.split()[1])
            except (IndexError, ValueError):
                pass
        elif stripped.startswith("RSN:") or stripped.startswith("WPA:"):
            key_mgmt = "wpa-psk"

    if not include_hidden and not ssid:
        return None

    entry: dict[str, Any] = {
        "ssid": ssid,
        "bssid": bssid,
        "signal": signal,
        "freq": freq,
        "key_mgmt": key_mgmt,
        "minrate": 1_000_000,
        "flags": _parse_iw_flags(block),
        "primaryChannel": _parse_primary_channel(block, freq),
        "channelWidth": _parse_channel_width(block),
        "secondaryChannelOffset": _parse_secondary_channel_offset(block),
        "bssLoad": _parse_bss_load(block),
        "amendments": _detect_amendments(block),
    }
    if detail == "full":
        entry["raw"] = block
    return entry


def finalize_network_entry(entry: dict[str, Any], detail: str) -> dict[str, Any]:
    """Drop fields not requested by ``detail`` level."""
    if detail != "full":
        entry.pop("raw", None)
    return entry


def parse_iw_scan_output(
    text: str,
    include_hidden: bool = True,
    detail: str = "short",
) -> list[dict[str, Any]]:
    """Parse ``iw dev <iface> scan`` BSS block output."""
    detail = normalize_scan_detail(detail)
    networks: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}

    for block in split_iw_bss_blocks(text):
        entry = parse_iw_bss_block(block, include_hidden=include_hidden, detail=detail)
        if not entry:
            continue
        finalize_network_entry(entry, detail)
        existing = seen.get(entry["bssid"])
        if existing is None or entry["signal"] > existing["signal"]:
            seen[entry["bssid"]] = entry

    networks.extend(seen.values())
    networks.sort(key=lambda n: n["signal"], reverse=True)
    return networks


def fetch_scan_results(iface: str, namespace: Optional[str] = None) -> str:
    """Read cached ``wpa_cli scan_results`` without triggering a new scan."""
    return ns_exec(
        ["wpa_cli", "-i", iface, "scan_results"],
        namespace=namespace,
    ).stdout.strip()


def find_bss(
    networks: list[dict[str, Any]], bssid: str
) -> Optional[dict[str, Any]]:
    """Return the scan entry matching ``bssid``, if present."""
    target = bssid.lower()
    for network in networks:
        if network.get("bssid") == target:
            return network
    return None


def ensure_iface_up(iface: str, namespace: Optional[str] = None) -> None:
    """Bring ``iface`` up before an active scan (required on some drivers)."""
    ns_exec(
        ["ip", "link", "set", iface, "up"],
        namespace=namespace,
        raise_on_fail=False,
    )


def wpa_cli_available(iface: str, namespace: Optional[str] = None) -> bool:
    """Return True when ``wpa_cli`` can talk to a running supplicant."""
    result = ns_exec(
        ["wpa_cli", "-i", iface, "status"],
        namespace=namespace,
        raise_on_fail=False,
    )
    return result.return_code == 0 and "wpa_state" in result.stdout


def run_wpa_cli_scan(
    iface: str,
    namespace: Optional[str] = None,
    include_hidden: bool = True,
    detail: str = "short",
) -> list[dict[str, Any]]:
    """Trigger ``wpa_cli scan`` and return parsed networks."""
    normalize_scan_detail(detail)
    ns_exec(["wpa_cli", "-i", iface, "scan"], namespace=namespace)

    last_error: Optional[Exception] = None
    for _ in range(_SCAN_POLL_ATTEMPTS):
        time.sleep(_SCAN_POLL_INTERVAL_SEC)
        try:
            networks = parse_wpa_scan_results(
                fetch_scan_results(iface, namespace),
                include_hidden=include_hidden,
            )
        except RunCommandError as exc:
            last_error = exc
            continue
        if networks:
            return [finalize_network_entry(n, detail) for n in networks]

    if last_error:
        raise last_error
    return []


def run_iw_scan(
    iface: str,
    namespace: Optional[str] = None,
    include_hidden: bool = True,
    detail: str = "short",
) -> list[dict[str, Any]]:
    """Run ``iw dev <iface> scan`` and return parsed networks."""
    normalize_scan_detail(detail)
    ensure_iface_up(iface, namespace)
    result = ns_exec(
        ["iw", "dev", iface, "scan"],
        namespace=namespace,
        raise_on_fail=False,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    if result.return_code != 0:
        if "not supported" in combined.lower():
            raise ScanNotSupportedError(
                f"iw scan not supported on {iface} in {namespace or 'root'}"
            )
        raise RunCommandError(
            combined.strip() or f"iw scan failed on {iface}",
            result.return_code,
        )
    return parse_iw_scan_output(
        result.stdout,
        include_hidden=include_hidden,
        detail=detail,
    )


def run_interface_scan(
    iface: str,
    namespace: Optional[str] = None,
    include_hidden: bool = True,
    mode: Optional[str] = None,
    detail: str = "short",
) -> list[dict[str, Any]]:
    """
    Trigger an active scan on ``iface`` and return parsed networks.

    Monitor interfaces use ``iw scan``. Managed interfaces prefer ``wpa_cli``
    when a supplicant control socket is available, otherwise ``iw scan``.
    """
    detail = normalize_scan_detail(detail)
    log.debug(
        "run_interface_scan iface=%s namespace=%r mode=%r hidden=%s detail=%s",
        iface,
        namespace,
        mode,
        include_hidden,
        detail,
    )
    mode = (mode or "").lower()

    if mode == "monitor":
        return run_iw_scan(
            iface, namespace, include_hidden=include_hidden, detail=detail
        )

    ensure_iface_up(iface, namespace)
    if detail == "full":
        return run_iw_scan(
            iface, namespace, include_hidden=include_hidden, detail=detail
        )

    if wpa_cli_available(iface, namespace):
        try:
            return run_wpa_cli_scan(
                iface,
                namespace,
                include_hidden=include_hidden,
                detail=detail,
            )
        except RunCommandError as exc:
            log.warning(
                "wpa_cli scan failed for %s, falling back to iw: %r", iface, exc
            )
    return run_iw_scan(
        iface, namespace, include_hidden=include_hidden, detail=detail
    )
