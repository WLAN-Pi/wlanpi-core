"""Let mt7921 monitor interfaces receive other stations' unicast frames.

MediaTek MT7921 radios (mt7921u/e/s) filter received frames in firmware. Once a
managed interface on the radio has been up - wlanpi-core's own scans bring the
``wlanN`` sibling of a ``wlanpiN`` monitor up and down - the firmware leaves
``DROP_OTHER_UC`` (bit 18 of the band-0 RX filter register RFCR, 0x820e5000)
set. The monitor then drops every unicast frame not addressed to itself:
authentication, association, EAPOL, ACK, RTS/CTS and Block Ack never reach the
capture, while beacons and broadcast still do. Taking the monitor down and up
or retuning it does not clear the bit, and the driver has no code path that
does (``mt7921_configure_filter`` only maps FCSFAIL, CONTROL and OTHER_BSS).

Until the driver handles it, a capture clears the bit through mt76's debugfs
register interface just before it starts. This is best effort: other drivers,
a missing debugfs, or any error leave the capture untouched.
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
    mt76 debugfs register interface.
    """
    regs = debugfs / phy / "mt76"
    if not (regs / "regidx").exists():
        return None
    before = _read_reg(regs, MT7921_RFCR_BAND0)
    if not before & DROP_OTHER_UC:
        return before, before
    _write_reg(regs, MT7921_RFCR_BAND0, before & ~DROP_OTHER_UC)
    return before, _read_reg(regs, MT7921_RFCR_BAND0)


def allow_other_unicast(iface: str, namespace: str | None = None) -> None:
    """Make ``iface``'s mt7921 radio pass other stations' unicast frames.

    Does nothing for other drivers. Never raises: a capture must not fail
    because of this workaround.
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
