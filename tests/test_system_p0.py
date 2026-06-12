"""Tests for P0 system API additions."""
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.services import system_service


@pytest.mark.asyncio
async def test_restart_systemd_service_allowed(mocker):
    mocker.patch.object(system_service, "is_allowed_service", return_value=True)
    mocker.patch.object(system_service, "restart_service", return_value=True)

    result = await system_service.restart_systemd_service("orb")

    assert result == {"name": "orb", "active": True}


@pytest.mark.asyncio
async def test_restart_systemd_service_denied():
    with pytest.raises(ValidationError) as exc:
        await system_service.restart_systemd_service("evil-service")

    assert exc.value.status_code == 400


def test_get_datetime_from_date_command(mocker):
    mocker.patch.object(
        system_service,
        "run_command",
        side_effect=[
            MagicMock(stdout="2026-06-07T21:32:12+01:00\n"),
            MagicMock(stdout="Sun  7 Jun 21:32:12 BST 2026\n"),
        ],
    )
    mocker.patch.object(system_service, "_resolve_timezone", return_value="Europe/London")

    result = system_service.get_datetime()

    assert result["datetime"] == "2026-06-07T21:32:12+01:00"
    assert result["timezone"] == "Europe/London"
    assert result["source"] == "date"
    assert result["display"] is not None


def test_resolve_timezone_from_etc_timezone(tmp_path, monkeypatch):
    tz_file = tmp_path / "timezone"
    tz_file.write_text("Europe/London\n")
    real_path = Path

    def path_factory(value):
        if value == "/etc/timezone":
            return tz_file
        return real_path(value)

    monkeypatch.setattr(system_service, "Path", path_factory)

    assert system_service._resolve_timezone() == "Europe/London"


def test_get_timezone(mocker):
    mocker.patch.object(
        system_service,
        "run_command",
        return_value=MagicMock(stdout="Europe/London\n"),
    )

    assert system_service.get_timezone() == {"timezone": "Europe/London"}


def test_set_timezone_uses_script_when_present(mocker, tmp_path):
    script = tmp_path / "wlanpi-timezone"
    script.write_text("#!/bin/sh\n")
    mocker.patch.object(system_service, "TIME_ZONE_FILE", str(script))
    run = mocker.patch.object(system_service, "run_command")
    mocker.patch.object(
        system_service, "get_timezone", return_value={"timezone": "Europe/London"}
    )

    result = system_service.set_timezone("Europe/London")

    run.assert_called_once_with([str(script), "set", "Europe/London"], raise_on_fail=True)
    assert result["timezone"] == "Europe/London"


def test_get_reg_domain_from_wlanpi_script(mocker):
    def fake_exists(self):
        return str(self) == system_service.REG_DOMAIN_FILE

    mocker.patch.object(Path, "exists", fake_exists)
    mocker.patch.object(
        system_service,
        "run_command",
        return_value=MagicMock(stdout="GB\n", stderr="", return_code=0),
    )

    result = system_service.get_reg_domain()

    assert result["country"] == "GB"
    assert result["raw"] == "GB"
    assert result["source"] == "wlanpi-reg-domain"


def test_get_reg_domain_parses_iw(mocker):
    mocker.patch.object(Path, "exists", return_value=False)
    mocker.patch.object(
        system_service,
        "run_command",
        return_value=MagicMock(stdout="global\ncountry GB: DFS-ETSI\n"),
    )

    result = system_service.get_reg_domain()

    assert result["country"] == "GB"
    assert result["source"] == "iw"
    assert "GB" in result["raw"]


def test_get_reg_domain_falls_back_to_iw_when_script_invalid(mocker):
    def fake_exists(self):
        return str(self) == system_service.REG_DOMAIN_FILE

    mocker.patch.object(Path, "exists", fake_exists)
    mocker.patch.object(
        system_service,
        "run_command",
        side_effect=[
            MagicMock(stdout="Error: Invalid option\n", stderr="", return_code=1),
            MagicMock(stdout="global\ncountry US: DFS-FCC\n"),
        ],
    )

    result = system_service.get_reg_domain()

    assert result["country"] == "US"
    assert result["source"] == "iw"


def test_parse_reg_country():
    assert system_service._parse_reg_country("GB") == "GB"
    assert system_service._parse_reg_country("country US: DFS-FCC") == "US"
    assert system_service._parse_reg_country("no country here") == "unknown"


def test_set_reg_domain_invalid_country():
    with pytest.raises(ValidationError) as exc:
        system_service.set_reg_domain("GBR")

    assert exc.value.status_code == 400


def test_set_reg_domain_unsupported_country():
    with pytest.raises(ValidationError) as exc:
        system_service.set_reg_domain("ZZ")

    assert exc.value.status_code == 400


def test_list_reg_domains():
    result = system_service.list_reg_domains()

    assert len(result["countries"]) == 9
    codes = {entry["code"] for entry in result["countries"]}
    assert codes == {"US", "CA", "GB", "BR", "FR", "CZ", "NL", "DE", "NO"}
    gb = next(c for c in result["countries"] if c["code"] == "GB")
    assert gb["name"] == "United Kingdom"


def test_get_platform_missing_wlanpi_model(mocker):
    mocker.patch.object(
        system_service,
        "run_command",
        side_effect=FileNotFoundError(2, "No such file or directory: 'wlanpi-model'"),
    )

    assert system_service.get_platform() == "Unknown"
    assert system_service.get_model() == "Unknown"


def _path_factory(supply_root):
    real_path = Path

    def factory(value):
        if value == "/sys/class/power_supply":
            return supply_root
        return real_path(value)

    return factory


def test_get_battery_present(tmp_path, monkeypatch):
    supply_root = tmp_path / "power_supply"
    bat = supply_root / "BAT0"
    bat.mkdir(parents=True)
    (bat / "type").write_text("Battery\n")
    (bat / "capacity").write_text("85\n")
    (bat / "status").write_text("Discharging\n")
    monkeypatch.setattr(system_service, "Path", _path_factory(supply_root))

    result = system_service.get_battery()

    assert result["present"] is True
    assert result["capacity_percent"] == 85
    assert result["status"] == "Discharging"
    assert result["source"] == "BAT0"


def test_get_battery_absent(tmp_path, monkeypatch):
    supply_root = tmp_path / "power_supply"
    supply_root.mkdir()
    monkeypatch.setattr(system_service, "Path", _path_factory(supply_root))

    assert system_service.get_battery() == {"present": False}
