"""Bluetooth status and pairing schemas."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class BluetoothStatus(BaseModel):
    """Bluetooth adapter status."""

    name: str = Field(json_schema_extra={"example": "wlanpi-bc2"})
    alias: str = Field(json_schema_extra={"example": "wlanpi-bc2"})
    addr: str = Field(json_schema_extra={"example": "00:00:00:00:00:00"})
    power: str = Field(examples=["On", "Off"])
    paired_devices: list[dict[str, Any]] = Field(
        json_schema_extra={"example": [{"name": "device", "addr": "00:00:00:00:00:00"}]}
    )


class PowerState(BaseModel):
    """Result of a bluetooth power action."""

    status: str = Field(json_schema_extra={"example": "success"})
    action: str = Field(examples=["on", "off"])


class BluetoothPairResponse(BaseModel):
    """Result of entering bluetooth pairing mode."""

    status: Literal["discoverable"] = Field(
        json_schema_extra={"example": "discoverable"}
    )
    alias: str = Field(json_schema_extra={"example": "wlanpi-bc2"})
    message: str = Field(
        json_schema_extra={"example": 'Bluetooth is on. Discoverable as "wlanpi-bc2"'}
    )
