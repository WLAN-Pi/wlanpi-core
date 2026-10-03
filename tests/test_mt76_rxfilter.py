"""Tests for the mt7921 DROP_OTHER_UC capture workaround."""

import pytest

from wlanpi_core.streaming import mt76_rxfilter
from wlanpi_core.streaming.mt76_rxfilter import (
    DROP_OTHER_UC,
    MT7921_RFCR_BAND0,
    allow_other_unicast,
    clear_drop_other_uc,
)


@pytest.fixture
def regs(tmp_path, monkeypatch):
    """Fake a phy whose RFCR reads back what was last written."""
    (tmp_path / "phy0" / "mt76").mkdir(parents=True)
    (tmp_path / "phy0" / "mt76" / "regidx").write_text("0x0")
    values = {MT7921_RFCR_BAND0: 0x0004000A}
    monkeypatch.setattr(mt76_rxfilter, "_read_reg", lambda regs, addr: values[addr])
    monkeypatch.setattr(
        mt76_rxfilter,
        "_write_reg",
        lambda regs, addr, value: values.__setitem__(addr, value),
    )
    return tmp_path, values


def test_register_helpers_use_regidx_then_regval(tmp_path):
    regs = tmp_path / "mt76"
    regs.mkdir()
    (regs / "regval").write_text("0x0004000a\n")

    assert mt76_rxfilter._read_reg(regs, MT7921_RFCR_BAND0) == 0x0004000A
    assert (regs / "regidx").read_text() == "0x820e5000"

    mt76_rxfilter._write_reg(regs, MT7921_RFCR_BAND0, 0x0000000A)
    assert (regs / "regval").read_text() == "0x0000000a"


def test_clears_only_drop_other_uc(regs):
    root, values = regs

    assert clear_drop_other_uc("phy0", debugfs=root) == (0x0004000A, 0x0000000A)
    assert values[MT7921_RFCR_BAND0] == 0x0000000A


def test_leaves_a_clear_register_alone(regs):
    root, values = regs
    values[MT7921_RFCR_BAND0] = 0x0000000A

    assert clear_drop_other_uc("phy0", debugfs=root) == (0x0000000A, 0x0000000A)


def test_no_mt76_debugfs_returns_none(tmp_path):
    assert clear_drop_other_uc("phy9", debugfs=tmp_path) is None


def test_other_drivers_are_untouched(mocker):
    mocker.patch.object(
        mt76_rxfilter.discovery, "interface_driver", return_value="ath12k_wifi7_pci"
    )
    clear = mocker.patch.object(mt76_rxfilter, "clear_drop_other_uc")

    allow_other_unicast("wlanpi2")

    clear.assert_not_called()


def test_mt7921_phy_is_cleared(mocker):
    mocker.patch.object(
        mt76_rxfilter.discovery, "interface_driver", return_value="mt7921u"
    )
    info = mocker.patch.object(
        mt76_rxfilter, "get_interface_info", return_value={"phy": "phy1"}
    )
    clear = mocker.patch.object(
        mt76_rxfilter, "clear_drop_other_uc", return_value=(0x0004000A, 0x0000000A)
    )

    allow_other_unicast("wlanpi1", "lab")

    info.assert_called_once_with("wlanpi1", "lab")
    clear.assert_called_once_with("phy1")


def test_errors_never_escape(mocker):
    mocker.patch.object(
        mt76_rxfilter.discovery, "interface_driver", return_value="mt7921u"
    )
    mocker.patch.object(
        mt76_rxfilter, "get_interface_info", side_effect=OSError("boom")
    )

    allow_other_unicast("wlanpi0")  # must not raise


def test_bit_is_drop_other_uc():
    assert DROP_OTHER_UC == 0x40000
