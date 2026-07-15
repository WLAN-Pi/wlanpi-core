from typing import Optional

from pydantic import BaseModel, Field, field_validator

from wlanpi_core.utils.validation import (
    validate_interface_name,
    validate_ssid,
    validate_wifi_frequency,
)


class Start(BaseModel):
    channel: Optional[int] = Field(default=None, ge=1, le=233)
    frequency: Optional[int] = None
    interface: Optional[str] = None
    ssid: Optional[str] = None

    # config_file_path: Optional[str] = None
    # files_path: Optional[str] = None

    debug: Optional[bool] = None
    noprep: Optional[bool] = None
    noAP: Optional[bool] = None
    no11r: Optional[bool] = None
    no11ax: Optional[bool] = None
    no11be: Optional[bool] = None
    noprofilertlv: Optional[bool] = None

    wpa3_personal_transition: Optional[bool] = None
    wpa3_personal: Optional[bool] = None
    oui_update: Optional[bool] = None
    no_bpf_filters: Optional[bool] = None

    model_config = {"extra": "forbid"}

    @field_validator("frequency")
    @classmethod
    def validate_frequency_field(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        return validate_wifi_frequency(value)

    @field_validator("interface")
    @classmethod
    def validate_interface_field(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return validate_interface_name(value)

    @field_validator("ssid")
    @classmethod
    def validate_ssid_field(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return validate_ssid(value)
