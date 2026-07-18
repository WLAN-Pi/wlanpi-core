import pytest
from pydantic import ValidationError

from wlanpi_core.schemas.network.network import IPInterfaceAddress


def test_dynamic_address_keeps_real_ip():
    # Regression for issue #147: `ip -j addr` marks DHCP-assigned addresses
    # with dynamic=true; the validator must not clobber the parsed address.
    addr = IPInterfaceAddress.model_validate(
        {
            "family": "inet",
            "local": "10.254.102.42",
            "prefixlen": 24,
            "broadcast": "10.254.102.255",
            "scope": "global",
            "dynamic": True,
            "label": "eth0",
            "valid_life_time": 3600,
            "preferred_life_time": 3600,
        }
    )

    assert addr.local == "10.254.102.42"
    assert addr.prefixlen == 24


def test_dynamic_address_keeps_non_24_prefixlen():
    addr = IPInterfaceAddress.model_validate(
        {
            "family": "inet",
            "local": "172.16.5.9",
            "prefixlen": 16,
            "dynamic": True,
        }
    )

    assert addr.local == "172.16.5.9"
    assert addr.prefixlen == 16


def test_dynamic_request_without_address_gets_placeholders():
    # VLAN creation requests may omit local/prefixlen when asking for DHCP
    addr = IPInterfaceAddress.model_validate({"family": "inet", "dynamic": True})

    assert addr.local == "0.0.0.0"
    assert addr.prefixlen == 24


@pytest.mark.parametrize(
    "payload",
    [
        {"family": "inet", "local": "10.0.0.1"},
        {"family": "inet", "prefixlen": 24},
    ],
)
def test_static_address_requires_local_and_prefixlen(payload):
    with pytest.raises(ValidationError):
        IPInterfaceAddress.model_validate(payload)
