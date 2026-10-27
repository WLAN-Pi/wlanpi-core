"""Transmit refusal facts shared by the gate and the OpenAPI responses."""

GO_MODEL: str = "Go"
GO_DETAIL: str = "transmit is disabled on the WLAN Pi Go"
UNKNOWN_DETAIL: str = "transmit is disabled because the WLAN Pi model is unknown"

TRANSMIT_ALLOWED_MODELS: frozenset[str] = frozenset({"M4", "M4+", "R4", "R5", "Pro"})

TRANSMIT_UNITS: frozenset[str] = frozenset(
    {
        "hostapd",
        "wpa_supplicant",
        "wpa_supplicant@wlan0",
        "bt-agent",
        "bt-network",
    }
)


def is_go_token(value: str) -> bool:
    """Return whether `value` is `Go` or a `Go` plus digits, any case."""
    if value == GO_MODEL:
        return True
    folded = value.lower()
    if not folded.startswith("go"):
        return False
    suffix = folded[2:]
    return suffix == "" or suffix.isdigit()


def refusal_detail(model: str) -> str | None:
    """Return the 403 detail, or None when this model may transmit."""
    if is_go_token(model):
        return GO_DETAIL
    if model in TRANSMIT_ALLOWED_MODELS:
        return None
    return UNKNOWN_DETAIL
