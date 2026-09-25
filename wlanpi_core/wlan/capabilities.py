"""Wi-Fi PHY capability queries."""

from __future__ import annotations

import logging
from typing import Any

from wlanpi_core.adapters.phy import list_phys
from wlanpi_core.constants import IW_FILE
from wlanpi_core.models.network.namespace.namespace_errors import (
    NetworkNamespaceError,
)
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.namespaces.namespace import list_namespaces
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


def get_wifi_capabilities() -> dict[str, Any]:
    """Return ``iw phy <n> info`` for each PHY in root and in every named netns.

    A phy moved into a namespace is only visible from inside it, so each
    namespace is listed there. One failing namespace is logged and skipped.
    """
    # ponytail: uncached (by design) and unserialised, so each call runs
    # 1 + namespaces + phys commands; add a lock like the driver inventory's
    # if many namespaces or tight polling make that costly.
    try:
        phys_by_ns: list[tuple[str | None, list[str]]] = [
            (None, list_phys(namespace=None))
        ]
    except RunCommandError as exc:
        raise ValidationError(
            f"Unable to list wireless PHY devices: {exc}", status_code=503
        ) from exc

    try:
        namespaces = list_namespaces()
    except NetworkNamespaceError as exc:
        log.warning("Could not list namespaces; root PHYs only: %r", exc)
        namespaces = []
    for netns in namespaces:
        try:
            phys_by_ns.append((netns, list_phys(namespace=netns)))
        except (RunCommandError, ValueError) as exc:
            log.warning("Could not list PHYs in %s: %r", netns, exc)

    adapters: list[dict[str, Any]] = []
    for netns, phys in phys_by_ns:
        for phy in phys:
            cmd = [IW_FILE, "phy", phy, "info"]
            try:
                if netns is None:
                    raw = run_command(cmd, raise_on_fail=True).stdout
                else:
                    raw = ns_exec(cmd, namespace=netns, no_output=True).stdout
            except RunCommandError as exc:
                adapters.append({"phy": phy, "namespace": netns, "error": str(exc)})
                continue
            adapters.append({"phy": phy, "namespace": netns, "info": raw})

    return {"adapters": adapters}
