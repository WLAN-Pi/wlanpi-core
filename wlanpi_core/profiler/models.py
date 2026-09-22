"""Request model for the profiler start endpoint."""

from pydantic import BaseModel, Field, field_validator

from wlanpi_core.utils.validation import (
    validate_interface_name,
    validate_ssid,
    validate_wifi_frequency,
)


class Start(BaseModel):
    """Arguments accepted by the profiler start command."""

    channel: int | None = Field(default=None, ge=1, le=233)
    frequency: int | None = None
    interface: str | None = None
    ssid: str | None = None

    # config_file_path: Optional[str] = None
    # files_path: Optional[str] = None

    debug: bool | None = None
    noprep: bool | None = None
    noAP: bool | None = None
    no11r: bool | None = None
    no11ax: bool | None = None
    no11be: bool | None = None
    noprofilertlv: bool | None = None

    wpa3_personal_transition: bool | None = None
    wpa3_personal: bool | None = None
    oui_update: bool | None = None
    no_bpf_filters: bool | None = None

    model_config = {"extra": "forbid"}

    @field_validator("frequency")
    @classmethod
    def validate_frequency_field(cls, value: int | None) -> int | None:
        """Validate an optional Wi-Fi frequency value."""
        if value is None:
            return None
        return validate_wifi_frequency(value)

    @field_validator("interface")
    @classmethod
    def validate_interface_field(cls, value: str | None) -> str | None:
        """Validate an optional interface name."""
        if value is None:
            return None
        return validate_interface_name(value)

    @field_validator("ssid")
    @classmethod
    def validate_ssid_field(cls, value: str | None) -> str | None:
        """Validate an optional SSID."""
        if value is None:
            return None
        return validate_ssid(value)
