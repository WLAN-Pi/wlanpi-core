"""Wireless association information via ``iw link``."""

from __future__ import annotations

import logging
import re
import subprocess
from typing import Any

from wlanpi_core.constants import IW_FILE
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec
from wlanpi_core.utils.validation import validate_interface_name

log = logging.getLogger(__name__)

_MLO_LINK = re.compile(r"Link (\d+) BSSID ([0-9a-fA-F:]{17})")
_INFO_LINK = re.compile(r"- link ID\s+(\d+)(?: link addr ([0-9a-fA-F:]{17}))?")
_INFO_CHANNEL = re.compile(r"channel \d+ \((\d+(?:\.\d+)?) MHz\)")
# iw names some widths with a suffix, e.g. "20 MHz (no HT)".
_INFO_WIDTH = re.compile(r"width: (\d+) MHz[^,]*(?:, center1: (\d+) MHz)?")
_DBM = re.compile(r"(-?\d+(?:\.\d+)?)")


def _parse_iw_link(stdout: str) -> dict[str, Any]:
    """Parse ``iw dev <iface> link`` output into structured fields.

    For MLO, ``iw link`` lists every set-up link (``Link N BSSID`` plus a
    ``freq:`` line each), active or not, in kernel BSS-list order. Those go
    into ``links``; the top-level ``freq_mhz`` is only taken from a non-MLO
    ``freq:`` line.
    """
    text = stdout.strip()
    # iw prints "Not connected." whenever no link is associated, including
    # after an "Authenticated with ..." line.
    if not text or re.search(r"^Not connected", text, re.M):
        return {"connected": False}

    parsed: dict[str, Any] = {"connected": True, "links": []}

    # Status lines start at column 0; the SSID is indented, so an SSID that
    # contains these words cannot match.
    bssid = re.search(r"^Connected to ([0-9a-fA-F:]{17})", text, re.M)
    if bssid:
        parsed["bssid"] = bssid.group(1)
        parsed["managed"] = True

    link: dict[str, Any] | None = None
    for line in text.splitlines():
        line = line.strip()
        mlo = _MLO_LINK.match(line)
        if mlo:
            link = {"link_id": int(mlo.group(1)), "bssid": mlo.group(2)}
            parsed["links"].append(link)
        elif line.startswith("SSID:"):
            parsed["ssid"] = line.split(":", 1)[1].strip()
        elif line.startswith("freq:"):
            try:
                freq = float(line.split(":", 1)[1].strip())
            except ValueError:
                continue
            if link is not None:
                link["freq_mhz"] = freq
            else:
                parsed["freq_mhz"] = freq
        elif line.startswith("MLD ") and line.endswith("stats:"):
            link = None
        elif line.startswith("signal:"):
            match = _DBM.search(line)
            if match:
                parsed["signal_dbm"] = float(match.group(1))
        elif line.startswith("rx bitrate:"):
            parsed["rx_bitrate"] = line.split(":", 1)[1].strip()
        elif line.startswith("tx bitrate:"):
            parsed["tx_bitrate"] = line.split(":", 1)[1].strip()
        elif line.startswith("RX:"):
            match = re.search(r"(\d+) bytes", line)
            if match:
                parsed["rx_bytes"] = int(match.group(1))
        elif line.startswith("TX:"):
            match = re.search(r"(\d+) bytes", line)
            if match:
                parsed["tx_bytes"] = int(match.group(1))
    return parsed


def _parse_active_links(stdout: str) -> dict[int, float]:
    """Map link ID to operating frequency for the active MLO links.

    ``iw dev <iface> info`` prints a channel only under links that hold a
    channel context, which mac80211 assigns to active links only.
    """
    active: dict[int, float] = {}
    link_id: int | None = None
    for line in stdout.splitlines():
        match = _INFO_LINK.search(line)
        if match:
            link_id = int(match.group(1))
            continue
        match = _INFO_CHANNEL.search(line)
        if match and link_id is not None:
            active[link_id] = float(match.group(1))
    return active


def _parse_link_details(stdout: str) -> dict[int, dict[str, Any]]:
    """Map link ID to this station's link address and, if active, its width.

    ``iw dev <iface> info`` lists every set-up link with the address mac80211
    gave this station on it (random per link; the frames on air use it), and
    a channel line with width and center frequency for active links only.
    """
    details: dict[int, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for line in stdout.splitlines():
        match = _INFO_LINK.search(line)
        if match:
            current = details.setdefault(int(match.group(1)), {})
            if match.group(2):
                current["local_addr"] = match.group(2).lower()
            continue
        match = _INFO_WIDTH.search(line)
        if match and current is not None and _INFO_CHANNEL.search(line):
            current["width_mhz"] = int(match.group(1))
            if match.group(2):
                current["center1_mhz"] = int(match.group(2))
    return details


def _station_signal(stdout: str, keys: tuple[str, ...]) -> float | None:
    """Return the first non-zero MLD-level value among ``keys``.

    Stops at the first per-link ``Link N:`` block, whose values belong to one
    link that may not be active.
    """
    top: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if re.match(r"Link \d+:", line):
            break
        top.append(line)
    for key in keys:
        for line in top:
            if line.startswith(key):
                match = _DBM.search(line[len(key) :])
                if match and float(match.group(1)) != 0:
                    return float(match.group(1))
    return None


def _link_set(parsed: dict[str, Any]) -> tuple[Any, ...]:
    """Identify an MLO association by its AP MLD address and links' channels."""
    links = parsed.get("links", [])
    return (
        parsed.get("bssid"),
        sorted((x["link_id"], x["bssid"], x.get("freq_mhz")) for x in links),
    )


def _iw(iface: str, namespace: str | None, *args: str) -> str | None:
    """Run a supplementary ``iw dev <iface> ...`` query; None on failure."""
    try:
        return ns_exec([IW_FILE, "dev", iface, *args], namespace=namespace).stdout
    except (RunCommandError, subprocess.TimeoutExpired) as exc:
        log.warning("iw %s failed for %s: %r", " ".join(args), iface, exc)
        return None


def get_wlan_link(iface: str, namespace: str | None = None) -> dict[str, Any]:
    """Return the wireless association for ``iface`` using ``iw link``."""
    iface = validate_interface_name(iface)
    log.debug("get_wlan_link iface=%s namespace=%r", iface, namespace)
    try:
        result = ns_exec([IW_FILE, "dev", iface, "link"], namespace=namespace)
    except RunCommandError as exc:
        log.error("iw link failed for %s: %r", iface, exc)
        raise

    parsed = _parse_iw_link(result.stdout)
    links: list[dict[str, Any]] = parsed.get("links", [])
    info = _iw(iface, namespace, "info") if links else None

    # 0 dBm is the kernel's "no frame received yet" value, not a reading.
    signal = parsed.get("signal_dbm") or None
    keys: tuple[str, ...] = ("signal avg:", "beacon signal avg:")
    if len(links) > 1:
        # cfg80211 reports the MLD signal as the max over all set-up links,
        # active or not: 0 while one never received a frame, else possibly
        # an idle link's last reading. The driver's beacon average follows
        # the primary (active) link.
        signal = None
        keys = ("beacon signal avg:", "signal avg:")
    # Station fallback only for a managed association (one peer: the AP).
    from_station = signal is None and bool(parsed.get("managed"))
    if from_station:
        # The AP (MLD address for MLO) only, not TDLS or other peers.
        sta = _iw(iface, namespace, "station", "get", parsed["bssid"])
        signal = _station_signal(sta, keys) if sta is not None else None

    freq = parsed.get("freq_mhz")
    if links:
        # iw info and iw station have no AP address, so re-read after them:
        # iw info, when the station signal follows the active link, catches an
        # active-link switch; iw link catches a reassociation, link removal or
        # channel switch. Otherwise one response would mix two states.
        same = True
        if from_station and len(links) > 1 and info is not None:
            info_again = _iw(iface, namespace, "info")
            same = info_again is not None and (
                _parse_active_links(info_again) == _parse_active_links(info)
            )
        if same:
            again = _iw(iface, namespace, "link")
            now = _parse_iw_link(again) if again is not None else {}
            same = _link_set(now) == _link_set(parsed)
        if not same:
            info = None
            if from_station:
                signal = None
        active = _parse_active_links(info) if info is not None else {}
        details = _parse_link_details(info) if info is not None else {}
        for link in links:
            # None: activity unknown because iw dev info failed, the links
            # changed during the request, or iw info doesn't list this link.
            link["active"] = (
                link["link_id"] in active if link["link_id"] in details else None
            )
            link.update(details.get(link["link_id"], {}))
        # Several active links (EMLSR, STR): iw cannot tell which carries
        # the traffic, so report no single frequency; see ``links``.
        freq = next(iter(active.values())) if len(active) == 1 else None

    return {
        "interface": iface,
        "namespace": namespace,
        "connected": parsed.get("connected", False),
        "ssid": parsed.get("ssid"),
        "bssid": parsed.get("bssid"),
        "freq_mhz": freq,
        "signal_dbm": signal,
        "links": links,
        "rx_bitrate": parsed.get("rx_bitrate"),
        "tx_bitrate": parsed.get("tx_bitrate"),
        "rx_bytes": parsed.get("rx_bytes"),
        "tx_bytes": parsed.get("tx_bytes"),
        "raw": result.stdout,
    }
