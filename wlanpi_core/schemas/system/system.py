from pydantic import BaseModel, Field


class ServiceStatus(BaseModel):
    name: str = Field(example="wlanpi-fpms")
    active: bool = Field(example=True)


class ServiceRunning(BaseModel):
    name: str = Field(example="wlanpi-fpms")
    active: bool = Field(example=True)

class DeviceModel(BaseModel):
    model: str = Field(example="R4")
    
class DeviceInfo(BaseModel):
    model: str = Field(example="R4")
    name: str = Field(example="wlanpi-bc2")
    hostname: str = Field(example="wlanpi-bc2.local")
    software_version: str = Field(example="3.2.0")
    mode: str = Field(example="classic")
    
class DeviceStats(BaseModel):
    ip: str = Field(example="127.0.0.1")
    cpu: str = Field(example="23%")
    ram: str = Field(example="1022/3792MB 26.95%")
    disk: str = Field(example="6/59GB 11%")
    cpu_temp: str = Field(example="1h 40m")
    uptime: str = Field(example="1h 40m")
    
