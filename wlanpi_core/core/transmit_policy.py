"""Transmit refusal facts shared by the gate and the OpenAPI responses."""

GO_MODEL: str = "Go"
GO_DETAIL: str = "transmit is disabled on the WLAN Pi Go"
UNKNOWN_DETAIL: str = "transmit is disabled because the WLAN Pi model is unknown"

TRANSMIT_UNITS: frozenset[str] = frozenset(
    {
        "hostapd",
        "wpa_supplicant",
        "wpa_supplicant@wlan0",
        "bt-agent",
        "bt-network",
    }
)
