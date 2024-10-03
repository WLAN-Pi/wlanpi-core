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
