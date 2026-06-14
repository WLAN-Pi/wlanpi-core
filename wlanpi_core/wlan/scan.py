"""Namespace-aware WLAN scan with adapter auto-selection."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from wlanpi_core.utils import network_config
from wlanpi_core.wpa import scan as wpa_scan

log = logging.getLogger(__name__)


class NoScanAdapterError(Exception):
    """Raised when no interface is available for scanning."""

    def __init__(self, candidates: Optional[list[dict[str, Any]]] = None):
        self.candidates = candidates or []
        super().__init__("NO_SCAN_ADAPTER")


def _ns_display(namespace: Optional[str]) -> str:
    return "root" if namespace is None else namespace


def _ns_from_param(namespace: Optional[str]) -> Optional[str]:
    if not namespace:
        return None
    if namespace.strip().lower() == "root":
        return None
    return namespace.strip()


def _iface_mode(iface_info: dict[str, Any]) -> str:
    mode = iface_info.get("type") or iface_info.get("mode") or ""
    return str(mode).strip().lower()


def _adapter_label(iface: str, mode: str, namespace: Optional[str]) -> str:
    ns_label = _ns_display(namespace)
    if mode:
        return f"{iface} ({mode}, {ns_label})"
    return f"{iface} ({ns_label})"


def iter_adapters(status: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten ``network_config.status()`` into adapter records."""
    adapters: list[dict[str, Any]] = []
    for ns_name, ns_status in status.items():
        if not isinstance(ns_status, dict) or "error" in ns_status:
            continue
        namespace = None if ns_name == "root" else ns_name
        for iface, iface_info in ns_status.items():
            if not isinstance(iface_info, dict):
                continue
            mode = _iface_mode(iface_info)
            adapters.append(
                {
                    "iface": iface,
                    "namespace": namespace,
                    "namespace_display": _ns_display(namespace),
                    "mode": mode,
                    "label": _adapter_label(iface, mode, namespace),
                }
            )
    return adapters


def _adapter_response(adapter: dict[str, Any]) -> dict[str, Any]:
    return {
        "iface": adapter["iface"],
        "namespace": adapter["namespace_display"],
        "label": adapter["label"],
        "mode": adapter.get("mode") or None,
    }


def select_scan_adapter(
    status: dict[str, Any],
    iface: Optional[str] = None,
    namespace: Optional[str] = None,
) -> dict[str, Any]:
    """
    Apply P0 adapter selection rules.

    Returns either:
    - ``{"action": "scan", "adapter": {...}}``
    - ``{"action": "needs_selection", "candidates": [...]}``
    """
    adapters = iter_adapters(status)
    ns = _ns_from_param(namespace)

    if iface:
        iface = iface.strip()
        matches = [
            adapter
            for adapter in adapters
            if adapter["iface"] == iface
            and (ns is None or adapter["namespace"] == ns)
        ]
        if not matches:
            raise NoScanAdapterError()
        if ns is None:
            root_match = next((a for a in matches if a["namespace"] is None), None)
            return {"action": "scan", "adapter": root_match or matches[0]}
        return {"action": "scan", "adapter": matches[0]}

    monitors = [a for a in adapters if a["mode"] == "monitor"]
    if len(monitors) >= 2:
        return {
            "action": "needs_selection",
            "candidates": [_adapter_response(a) for a in monitors],
        }
    if len(monitors) == 1:
        return {"action": "scan", "adapter": monitors[0]}

    managed_root = [
        a for a in adapters if a["mode"] == "managed" and a["namespace"] is None
    ]
    if managed_root:
        return {"action": "scan", "adapter": managed_root[0]}

    if not adapters:
        raise NoScanAdapterError()
    raise NoScanAdapterError()


def wlan_scan(
    iface: Optional[str] = None,
    namespace: Optional[str] = None,
    hidden: bool = True,
    status: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Run namespace-aware WLAN scan with adapter selection."""
    if status is None:
        status = network_config.status()

    selection = select_scan_adapter(status, iface=iface, namespace=namespace)
    if selection["action"] == "needs_selection":
        return {
            "needsSelection": True,
            "candidates": selection["candidates"],
            "selectedAdapter": None,
            "networks": [],
            "scannedAt": None,
        }

    adapter = selection["adapter"]
    networks = wpa_scan.run_interface_scan(
        adapter["iface"],
        namespace=adapter["namespace"],
        include_hidden=hidden,
    )
    return {
        "selectedAdapter": _adapter_response(adapter),
        "networks": networks,
        "scannedAt": datetime.now(timezone.utc).replace(microsecond=0),
        "needsSelection": False,
        "candidates": [],
    }
