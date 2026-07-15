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
from wlanpi_core.wpa.config import generate_network_block


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
