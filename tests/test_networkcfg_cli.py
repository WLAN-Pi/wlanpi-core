import pytest

from wlanpi_core.cli.network_config import NetworkConfigCLI, ValidationError

PASSPHRASE_ONLY = "psk must be 8-63 printable ASCII characters"
PASSPHRASE_OR_HEX = PASSPHRASE_ONLY + " or 64 hex digits"


@pytest.mark.parametrize(
    ("security_type", "psk", "message"),
    [
        ("WPA3-PSK", "a" * 64, PASSPHRASE_ONLY),
        ("WPA2-PSK", "pässwörd1", PASSPHRASE_OR_HEX),
        ("WPA2-PSK", "short", PASSPHRASE_OR_HEX),
    ],
)
def test_validate_psk_rejects_what_the_api_rejects(security_type, psk, message):
    with pytest.raises(ValidationError) as rejected:
        NetworkConfigCLI().validate_psk(psk, security_type)

    assert str(rejected.value) == message


def test_psk_prompt_applies_the_rule_of_the_chosen_security_type(monkeypatch):
    hex_key = "a" * 64
    typed = iter([hex_key, hex_key, hex_key, "printable1"])
    monkeypatch.setattr("builtins.input", lambda prompt: "Net")
    monkeypatch.setattr("getpass.getpass", lambda prompt: next(typed))
    cli = NetworkConfigCLI()

    assert cli.prompt_security_config("WPA2-PSK")["psk"] == hex_key
    assert cli.prompt_security_config("WPA3-PSK")["psk"] == "printable1"
