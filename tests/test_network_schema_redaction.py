from wlanpi_core.schemas.network.network import (
    NamespaceConfig,
    NetConfig,
    NetConfigPublic,
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


def _keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _keys(child)


def test_net_config_public_masks_secrets_in_roots_and_namespaces():
    cfg = NetConfig(
        id="lab_cfg",
        namespaces=[
            NamespaceConfig(
                namespace="ns_b",
                iface_display_name="wlan1",
                phy="phy1",
                interface="wlan1",
                security=NetSecurity(
                    ssid="NetB",
                    security=SecurityTypes.wpa2,
                    identity="lab-user",
                    password="eap-secret-pw",
                ),
            ),
            NamespaceConfig(
                namespace="ns_a",
                iface_display_name="wlan2",
                phy="phy2",
                interface="wlan2",
            ),
        ],
        roots=[
            RootConfig(
                iface_display_name="wlan0",
                phy="phy0",
                interface="wlan0",
                security=NetSecurity(
                    ssid="NetA",
                    security=SecurityTypes.wpa2,
                    psk="root-secret-psk",
                ),
            )
        ],
    )

    public = NetConfigPublic.from_config(cfg)
    dumped = public.model_dump()
    rendered = public.model_dump_json()

    for text in (rendered, str(dumped)):
        assert "root-secret-psk" not in text
        assert "eap-secret-pw" not in text
    assert {"psk", "password"}.isdisjoint(_keys(dumped))
    assert dumped["roots"][0]["security"]["psk_set"] is True
    assert dumped["namespaces"][0]["security"]["password_set"] is True
    assert dumped["namespaces"][0]["security"]["identity"] == "lab-user"
    assert [ns["namespace"] for ns in dumped["namespaces"]] == ["ns_b", "ns_a"]
    assert all(isinstance(ns, RootConfig) for ns in cfg.namespaces or [])
