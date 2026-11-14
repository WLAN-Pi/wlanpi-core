from wlanpi_core.cli.network_config import SECURITY_TYPES
from wlanpi_core.schemas.network.network import SecurityTypes


def test_menu_offers_only_the_security_types_the_api_accepts():
    assert set(SECURITY_TYPES) == {security.value for security in SecurityTypes}
