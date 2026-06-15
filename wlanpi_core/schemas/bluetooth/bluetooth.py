from typing import Optional

from pydantic import BaseModel, Field


class BluetoothStatus(BaseModel):
    name: str = Field(example="wlanpi-bc2")
    alias: str = Field(example="wlanpi-bc2")
    addr: str = Field(example="00:00:00:00:00:00")
    power: str = Field(examples=["On", "Off"])
    paired_devices: list[dict] = Field(
        example=[{"name": "device", "addr": "00:00:00:00:00:00"}]
    )


class PowerState(BaseModel):
    status: str = Field(example="success")
    action: str = Field(examples=["on", "off"])


class PairedDevice(BaseModel):
    name: str = Field(example="My Phone")
    addr: str = Field(example="00:11:22:33:44:55")


class BluetoothPairResponse(BaseModel):
    status: str = Field(examples=["discoverable", "paired"])
    alias: Optional[str] = Field(default=None, example="wlanpi-bc2")
    message: str = Field(example='Bluetooth is on. Discoverable as "wlanpi-bc2"')
    device: Optional[PairedDevice] = None
