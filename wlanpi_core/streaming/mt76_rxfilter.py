"""Let mt7921 monitor interfaces receive other stations' unicast frames.

A scan on an MT7921 radio (mt7921u/e/s) leaves firmware ``DROP_OTHER_UC``
(bit 18 of band-0 RFCR, 0x820e5000) set, so its monitor drops unicast frames
not addressed to it. Retuning or down/up does not clear it and the driver
never does, so captures and scans clear it through mt76 debugfs (#364).
"""

from __future__ import annotations

from pathlib import Path

from wlanpi_core.adapters import discovery
from wlanpi_core.adapters.interface import get_interface_info
from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)

DEBUGFS_IEEE80211 = Path("/sys/kernel/debug/ieee80211")
MT7921_DRIVERS = frozenset({"mt7921u", "mt7921e", "mt7921s"})
MT7921_RFCR_BAND0 = 0x820E5000
DROP_OTHER_UC = 1 << 18


def _read_reg(regs: Path, addr: int) -> int:
    """Read one register through mt76's debugfs regidx/regval pair."""
    (regs / "regidx").write_text(f"0x{addr:08x}")
    return int((regs / "regval").read_text().strip(), 16)


def _write_reg(regs: Path, addr: int, value: int) -> None:
    """Write one register through mt76's debugfs regidx/regval pair."""
    (regs / "regidx").write_text(f"0x{addr:08x}")
    (regs / "regval").write_text(f"0x{value:08x}")


def clear_drop_other_uc(
    phy: str, debugfs: Path = DEBUGFS_IEEE80211
) -> tuple[int, int] | None:
    """Clear DROP_OTHER_UC in ``phy``'s RX filter register.

    Returns the register value before and after, or None when the phy has no
    mt76 debugfs register interface. Raises OSError when the read fails.
    """
    regs = debugfs / phy / "mt76"
    if not (regs / "regidx").exists():
        return None
    before = _read_reg(regs, MT7921_RFCR_BAND0)
    # mt76 returns ~0 for a failed bus read; writing that back sets every drop bit.
    if before == 0xFFFFFFFF:
        raise OSError(f"RFCR read failed on {phy}")
    if not before & DROP_OTHER_UC:
        return before, before
    _write_reg(regs, MT7921_RFCR_BAND0, before & ~DROP_OTHER_UC)
    return before, _read_reg(regs, MT7921_RFCR_BAND0)


def allow_other_unicast(iface: str, namespace: str | None = None) -> None:
    """Make ``iface``'s mt7921 radio pass other stations' unicast frames.

    Does nothing for other drivers. Never raises: a capture or scan must not
    fail because of this workaround.
    """
    try:
        driver = discovery.interface_driver(iface, namespace)
        if driver not in MT7921_DRIVERS:
            return
        info = get_interface_info(iface, namespace) or {}
        phy = info.get("phy")
        if not phy:
            return
        result = clear_drop_other_uc(str(phy))
        if result and result[0] != result[1]:
            log.info(
                "Cleared mt7921 DROP_OTHER_UC on %s (%s, %s): RFCR 0x%08x -> 0x%08x",
                iface,
                phy,
                driver,
                result[0],
                result[1],
            )
    except Exception as e:
        log.warning("mt7921 unicast filter workaround skipped for %s: %r", iface, e)
