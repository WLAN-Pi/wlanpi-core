from typing import Optional

from pydantic import BaseModel, Field


class OoklaSpeedtest_Ping(BaseModel):
    jitter: float = Field(example=3.971)
    latency: float = Field(example=11.151)


class OoklaSpeedtest_Download(BaseModel):
    bandwidth: int = Field(example=19780836)
    bytes: int = Field(example=226938080)
    elapsed: int = Field(example=11707)


class OoklaSpeedtest_Upload(BaseModel):
    bandwidth: int = Field(example=1364478)
    bytes: int = Field(example=5226800)
    elapsed: int = Field(example=3813)


class OoklaSpeedtest_Interface(BaseModel):
    internalIp: str = Field(example="192.168.1.21")
    name: str = Field(example="eth0")
    macAddr: str = Field(example="02:01:78:00:00:00")
    isVpn: bool = Field(example=False)
    externalIp: str = Field(example="46.156.79.21")


class OoklaSpeedtest_Server(BaseModel):
    id: int = Field(example=20398)
    name: str = Field(example="Rando LLC")
    location: str = Field(example="NYC")
    country: str = Field(example="United States")
    host: str = Field(example="speedtest.rando-llc.com")
    port: int = Field(example=8080)
    ip: str = Field(example="243.238.215.215")


class OoklaSpeedtest_Result(BaseModel):
    id: str = Field(example="949308a2-e34e-2fe0-81f7-8d12cc02daab")
    url: str = Field(
        example="https://www.speedtest.net/result/c/949308a2-e34e-2fe0-81f7-8d12cc02daab"
    )


class OoklaSpeedtest(BaseModel):
    type: str = Field(example="result")
    timestamp: str = Field(example="2021-01-04T04:01:06Z")
    ping: Optional[OoklaSpeedtest_Ping]
    download: Optional[OoklaSpeedtest_Download]
    upload: Optional[OoklaSpeedtest_Upload]
    isp: str = Field(exmaple="Awesome ISP")
    interface: Optional[OoklaSpeedtest_Interface]
    server: Optional[OoklaSpeedtest_Server]
    result: Optional[OoklaSpeedtest_Result]

    class Config:
        arbitrary_types_allowed = True
