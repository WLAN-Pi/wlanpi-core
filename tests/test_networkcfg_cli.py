import pytest

from wlanpi_core.cli.network_config import NetworkConfigCLI, ValidationError


@pytest.mark.parametrize(
    ("security_type", "psk"),
    [("WPA3-PSK", "a" * 64), ("WPA2-PSK", "pässwörd1"), ("WPA2-PSK", "short")],
)
def test_validate_psk_rejects_what_the_api_rejects(security_type, psk):
    with pytest.raises(ValidationError, match="psk must be 8-63 printable ASCII"):
        NetworkConfigCLI().validate_psk(psk, security_type)


def test_psk_prompt_applies_the_rule_of_the_chosen_security_type(monkeypatch):
    hex_key = "a" * 64
    monkeypatch.setattr("builtins.input", lambda prompt: "Net")
    monkeypatch.setattr("getpass.getpass", lambda prompt: hex_key)
    cli = NetworkConfigCLI()

    assert cli.prompt_security_config("WPA2-PSK")["psk"] == hex_key
    assert cli.prompt_security_config("WPA3-PSK")["psk"] == ""
