"""Tests for P0 system API additions."""
import asyncio
import threading
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from wlanpi_core.data import reg_domain_countries
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.services import system_service

_GET_MODE = system_service.get_mode


@pytest.mark.asyncio
async def test_restart_systemd_service_allowed(mocker):
    worker_thread = None

    def restart_service(_name):
        nonlocal worker_thread
        worker_thread = threading.get_ident()
        return True

    mocker.patch.object(system_service, "is_allowed_service", return_value=True)
    mocker.patch.object(system_service, "restart_service", side_effect=restart_service)

    result = await system_service.restart_systemd_service("orb")

    assert result == {"name": "orb", "active": True}
    assert worker_thread != threading.get_ident()


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


def test_get_mode_missing_file_is_read_only(tmp_path, monkeypatch):
    mode_file = tmp_path / "missing-mode"
    monkeypatch.setattr(system_service, "MODE_FILE", str(mode_file))

    assert _GET_MODE() == "classic"
    assert not mode_file.exists()


def test_get_mode_reports_unreadable_file(tmp_path, monkeypatch):
    mode_dir = tmp_path / "mode-directory"
    mode_dir.mkdir()
    monkeypatch.setattr(system_service, "MODE_FILE", str(mode_dir))

    with pytest.raises(ValidationError) as exc:
        _GET_MODE()

    assert exc.value.status_code == 503


def test_get_image_ver_ignores_non_assignment_lines(tmp_path, monkeypatch):
    release = tmp_path / "wlanpi-release"
    release.write_text("comment without equals\nVERSION=4.2=beta\n", encoding="utf-8")
    monkeypatch.setattr(system_service, "WLANPI_IMAGE_FILE", str(release))

    assert system_service.get_image_ver() == "4.2=beta"


def test_get_hostname_uses_local_domain_when_domain_lookup_fails(mocker):
    run = mocker.patch.object(
        system_service,
        "run_command",
        side_effect=[
            MagicMock(stdout="wlanpi\n"),
            RunCommandError("domain unavailable", return_code=1),
        ],
    )

    assert system_service.get_hostname() == "wlanpi.local"
    assert run.call_args_list == [
        call(["/usr/bin/hostname"]),
        call(["/usr/bin/hostname", "-d"]),
    ]


def test_get_hostname_falls_back_to_socket(mocker):
    mocker.patch.object(
        system_service,
        "run_command",
        side_effect=RunCommandError("hostname unavailable", return_code=1),
    )
    mocker.patch.object(system_service.socket, "gethostname", return_value="wlanpi.local")

    assert system_service.get_hostname() == "wlanpi.local"


def test_read_cpu_temperature_handles_missing_sensor(mocker):
    mocker.patch.object(
        system_service.Path,
        "read_text",
        side_effect=FileNotFoundError,
    )

    assert system_service._read_cpu_temperature() == "unknown"


def test_read_cpu_temperature_converts_millidegrees(mocker):
    mocker.patch.object(system_service.Path, "read_text", return_value="52123\n")

    assert system_service._read_cpu_temperature() == "52.1C"


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


def test_list_timezones_caches_names_but_returns_fresh_list(mocker):
    run = mocker.patch.object(
        system_service,
        "run_command",
        return_value=MagicMock(stdout="Europe/London\nAmerica/New_York\n"),
    )
    system_service._timezone_names.cache_clear()

    try:
        first = system_service.list_timezones()
        first["timezones"].append("mutated")
        second = system_service.list_timezones()
    finally:
        system_service._timezone_names.cache_clear()

    run.assert_called_once_with(
        ["timedatectl", "list-timezones"],
        raise_on_fail=True,
    )
    assert second == {"timezones": ["Europe/London", "America/New_York"]}


def test_set_timezone_uses_script_when_present(mocker, tmp_path):
    script = tmp_path / "wlanpi-timezone"
    script.write_text("#!/bin/sh\n")
    mocker.patch.object(system_service, "TIME_ZONE_FILE", str(script))
    mocker.patch.object(
        system_service,
        "_timezone_names",
        return_value=("Europe/London",),
    )
    run = mocker.patch.object(system_service, "run_command")
    mocker.patch.object(
        system_service, "get_timezone", return_value={"timezone": "Europe/London"}
    )

    result = system_service.set_timezone("Europe/London")

    run.assert_called_once_with([str(script), "set", "Europe/London"], raise_on_fail=True)
    assert result["timezone"] == "Europe/London"


def test_set_timezone_rejects_unknown_name_before_command(mocker):
    mocker.patch.object(
        system_service,
        "_timezone_names",
        return_value=("Europe/London",),
    )
    run = mocker.patch.object(system_service, "run_command")

    with pytest.raises(ValidationError) as exc:
        system_service.set_timezone("../../etc/passwd")

    assert exc.value.status_code == 400
    run.assert_not_called()


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
    reg_domain_countries._country_data.cache_clear()
    result = system_service.list_reg_domains()

    assert len(result["countries"]) > 9
    codes = {entry["code"] for entry in result["countries"]}
    assert {"AU", "CA", "GB", "JP", "US"}.issubset(codes)
    assert "ZZ" not in codes
    gb = next(c for c in result["countries"] if c["code"] == "GB")
    assert gb["name"] == "United Kingdom"


def test_set_reg_domain_accepts_installed_database_country(mocker):
    mocker.patch.object(
        system_service,
        "is_supported_reg_domain",
        return_value=True,
    )
    mocker.patch.object(Path, "exists", return_value=False)
    run = mocker.patch.object(system_service, "run_command")
    mocker.patch.object(
        system_service,
        "get_reg_domain",
        return_value={"country": "AU", "raw": "AU", "source": "iw"},
    )

    assert system_service.set_reg_domain("au")["country"] == "AU"
    run.assert_called_once_with(["iw", "reg", "set", "AU"], raise_on_fail=True)


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
