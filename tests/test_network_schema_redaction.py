from wlanpi_core.schemas.network.network import (
    NetConfig,
    NamespaceConfig,
    NetSecurity,
    RootConfig,
    SecurityTypes,
)


def test_net_security_str_redacts_psk_and_password():
    security = NetSecurity(
        ssid="MyNet",
        security=SecurityTypes.wpa2,
        psk="super-secret-psk",
        password="enterprise-password",
        private_key="/path/to/key.pem",
    )
    rendered = str(security)

    assert "super-secret-psk" not in rendered
    assert "enterprise-password" not in rendered
    assert "/path/to/key.pem" not in rendered
    assert "MyNet" in rendered
    assert "***" in rendered


def test_root_config_str_redacts_nested_security():
    cfg = RootConfig(
        iface_display_name="wlan0",
        phy="phy0",
        interface="wlan0",
        security=NetSecurity(
            ssid="MyNet",
            security=SecurityTypes.wpa2,
            psk="super-secret-psk",
        ),
    )

    rendered = str(cfg)

    assert "super-secret-psk" not in rendered
    assert "wlan0" in rendered
    assert "***" in rendered


def test_namespace_config_str_redacts_security():
    cfg = NamespaceConfig(
        namespace="lab_ns",
        iface_display_name="wlan0",
        phy="phy0",
        interface="wlan0",
        security=NetSecurity(
            ssid="MyNet",
            security=SecurityTypes.wpa3,
            psk="wpa3-secret",
        ),
    )

    rendered = str(cfg)

    assert "wpa3-secret" not in rendered
    assert "lab_ns" in rendered


def test_netconfig_str_redacts_all_entries():
    cfg = NetConfig(
        id="lab_cfg",
        namespaces=[
            NamespaceConfig(
                namespace="ns_a",
                iface_display_name="wlan0",
                phy="phy0",
                interface="wlan0",
                security=NetSecurity(
                    ssid="NetA",
                    security=SecurityTypes.wpa2,
                    psk="secret-a",
                ),
            )
        ],
        roots=[
            RootConfig(
                iface_display_name="wlan1",
                phy="phy1",
                interface="wlan1",
                security=NetSecurity(
                    ssid="NetB",
                    security=SecurityTypes.wpa2,
                    psk="secret-b",
                ),
            )
        ],
    )

    rendered = str(cfg)

    assert "secret-a" not in rendered
    assert "secret-b" not in rendered
    assert "lab_cfg" in rendered
    assert "ns_a" in rendered
