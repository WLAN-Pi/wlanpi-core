from __future__ import annotations

from datetime import datetime
from typing import Optional
from typing import Optional

from pydantic import BaseModel, Field


class PingTargetResult(BaseModel):
    target: str
    success: bool
    rtt_ms_min: Optional[float] = Field(default=None, alias="rttMsMin")
    rtt_ms_avg: Optional[float] = Field(default=None, alias="rttMsAvg")
    rtt_ms_max: Optional[float] = Field(default=None, alias="rttMsMax")
    packet_loss_percent: Optional[float] = Field(
        default=None, alias="packetLossPercent"
    )
    display: str = Field(description='Human-readable RTT such as "5.17ms" or "FAIL"')

    model_config = {"populate_by_name": True}


class ReachabilityTest(BaseModel):
    ping_google: str = Field(example="12.345ms", alias="Ping Google")
    browse_google: str = Field(examples=["OK", "FAIL"], alias="Browse Google")
    ping_gateway: str = Field(example="12.345ms", alias="Ping Gateway")
    dns_server_1_resolution: Optional[str] = Field(
        None, examples=["OK", "FAIL"], alias="DNS Server 1 Resolution"
    )
    dns_server_2_resolution: Optional[str] = Field(
        None, examples=["OK", "FAIL"], alias="DNS Server 2 Resolution"
    )
    dns_server_3_resolution: Optional[str] = Field(
        None, examples=["OK", "FAIL"], alias="DNS Server 3 Resolution"
    )
    arping_gateway: str = Field(example="12.345ms", alias="Arping Gateway")
    custom: list[PingTargetResult] = Field(
        default_factory=list,
        description="Optional user-supplied targets pinged in parallel",
    )

    model_config = {"populate_by_name": True}


class SpeedTestErrorResponse(BaseModel):
    error: str = Field(description="Failure reason, e.g. speedtest timed out")


class SpeedTest(BaseModel):
    ip_address: str = Field(example="1.2.3.4", alias="ipAddress")
    download_speed: str = Field(example="12.34 Mbps", alias="downloadSpeed")
    upload_speed: str = Field(example="1.23 Mbps", alias="uploadSpeed")
    ping_ms: Optional[float] = Field(default=None, alias="pingMs")
    jitter_ms: Optional[float] = Field(default=None, alias="jitterMs")
    server: Optional[str] = Field(
        default=None, description="Selected LibreSpeed server name"
    )
    tested_at: Optional[datetime] = Field(default=None, alias="testedAt")

    model_config = {"populate_by_name": True}


class PortBlinkerState(BaseModel):
    status: str = Field(example="success")
    action: str = Field(examples=["on", "off"])


class BlinkerStatus(BaseModel):
    active: bool = Field(example=True)


class BlinkerActionResponse(BaseModel):
    active: bool = Field(example=True)
    status: str = Field(examples=["started", "stopped", "already_running", "not_running"])
    interface: Optional[str] = Field(default=None, example="eth0")


class Usb(BaseModel):
    interfaces: list = Field()


class Ufw(BaseModel):
    status: str = Field()
    ports: list = Field()
