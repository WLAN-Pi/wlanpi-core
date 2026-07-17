from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas.network.network import (
    NetConfig,
    NetSecurity,
    NamespaceConfig,
    NetworkModeEnum,
    RootConfig,
    SecurityTypes,
)
from wlanpi_core.utils import network_config
from wlanpi_core.utils.namespace_execution import ns_exec
from wlanpi_core.utils.validation import validate_vlan_id
from wlanpi_core.wpa.config import generate_network_block
from wlanpi_core.network.link_stats import get_link_stats
from wlanpi_core.services import network_ethernet_service, utils_service


def _root_config(**overrides):
    values = {
        "mode": NetworkModeEnum.managed,
        "iface_display_name": "wlan0",
        "phy": "phy0",
        "interface": "wlan0",
    }
    values.update(overrides)
    return RootConfig(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("interface", "--help"),
        ("interface", "wlan0/../../x"),
        ("iface_display_name", "../wlan0"),
        ("phy", "phy0;reboot"),
    ],
)
def test_root_config_rejects_unsafe_device_names(field, value):
    with pytest.raises(PydanticValidationError):
        _root_config(**{field: value})


def test_namespace_config_rejects_path_syntax():
    with pytest.raises(PydanticValidationError):
        NamespaceConfig(
            **_root_config().model_dump(),
            namespace="../../root",
        )


def test_network_config_id_rejects_path_traversal():
    with pytest.raises(PydanticValidationError):
        NetConfig(id="../../etc/shadow")


def test_config_lookup_cannot_escape_config_directory(mocker, tmp_path):
    mocker.patch.object(network_config, "cfg_dir", Path(tmp_path))

    with pytest.raises(ValidationError) as error:
        network_config.get_config("../../etc/passwd")

    assert error.value.status_code == 400


@pytest.mark.parametrize("ssid", ["bad\nnetwork", "💻" * 9])
def test_security_rejects_unsafe_ssids(ssid):
    with pytest.raises(PydanticValidationError):
        NetSecurity(ssid=ssid, security=SecurityTypes.wpa2)


def test_wpa_values_are_quoted_without_config_injection():
    security = NetSecurity(
        ssid='Cafe "Guest"\\5G',
        security=SecurityTypes.wpa2,
        psk='safe"pass\\word',
    )
    block = generate_network_block(_root_config(security=security))

    assert 'ssid="Cafe \\"Guest\\"\\\\5G"' in block
    assert 'psk="safe\\"pass\\\\word"' in block


def test_namespace_execution_rejects_path_syntax_before_command(mocker):
    run_command = mocker.patch(
        "wlanpi_core.utils.namespace_execution.run_command"
    )

    with pytest.raises(ValueError):
        ns_exec(["ip", "addr"], namespace="../../root")

    run_command.assert_not_called()


def test_link_stats_rejects_option_like_interface_before_command(mocker):
    execute = mocker.patch("wlanpi_core.network.link_stats.ns_exec")

    with pytest.raises(ValueError):
        get_link_stats("--help")

    execute.assert_not_called()


@pytest.mark.parametrize("value", [0, 4095, "1.5", "1;reboot", True])
def test_vlan_id_rejects_values_outside_kernel_range(value):
    with pytest.raises(ValueError):
        validate_vlan_id(value)


@pytest.mark.asyncio
async def test_vlan_service_rejects_input_before_mutation(mocker):
    create_vlan = mocker.patch.object(
        network_ethernet_service.LiveVLANs,
        "create_vlan",
    )

    with pytest.raises(ValidationError) as error:
        await network_ethernet_service.create_vlan("eth0", "1;reboot", [])

    assert error.value.status_code == 400
    create_vlan.assert_not_called()


def test_blinker_rejects_interface_before_starting_process(mocker):
    popen = mocker.patch.object(utils_service.subprocess, "Popen")

    with pytest.raises(ValueError):
        utils_service.start_port_blinker("--help")

    popen.assert_not_called()
