from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

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
    ping_google: str = Field(
        alias="Ping Google", json_schema_extra={"example": "12.345ms"}
    )
    browse_google: str = Field(examples=["OK", "FAIL"], alias="Browse Google")
    ping_gateway: str = Field(
        alias="Ping Gateway", json_schema_extra={"example": "12.345ms"}
    )
    dns_server_1_resolution: Optional[str] = Field(
        None, examples=["OK", "FAIL"], alias="DNS Server 1 Resolution"
    )
    dns_server_2_resolution: Optional[str] = Field(
        None, examples=["OK", "FAIL"], alias="DNS Server 2 Resolution"
    )
    dns_server_3_resolution: Optional[str] = Field(
        None, examples=["OK", "FAIL"], alias="DNS Server 3 Resolution"
    )
    arping_gateway: str = Field(
        alias="Arping Gateway", json_schema_extra={"example": "12.345ms"}
    )
    custom: list[PingTargetResult] = Field(
        default_factory=list,
        description="Optional user-supplied targets pinged in parallel",
    )

    model_config = {"populate_by_name": True}


class SpeedTestErrorResponse(BaseModel):
    error: str = Field(description="Failure reason, e.g. speedtest timed out")


class SpeedTest(BaseModel):
    ip_address: str = Field(alias="ipAddress", json_schema_extra={"example": "1.2.3.4"})
    download_speed: str = Field(
        alias="downloadSpeed", json_schema_extra={"example": "12.34 Mbps"}
    )
    upload_speed: str = Field(
        alias="uploadSpeed", json_schema_extra={"example": "1.23 Mbps"}
    )
    ping_ms: Optional[float] = Field(default=None, alias="pingMs")
    jitter_ms: Optional[float] = Field(default=None, alias="jitterMs")
    server: Optional[str] = Field(
        default=None, description="Selected LibreSpeed server name"
    )
    tested_at: Optional[datetime] = Field(default=None, alias="testedAt")

    model_config = {"populate_by_name": True}


class PortBlinkerState(BaseModel):
    status: str = Field(json_schema_extra={"example": "success"})
    action: str = Field(examples=["on", "off"])


class BlinkerStatus(BaseModel):
    active: bool = Field(json_schema_extra={"example": True})


class BlinkerActionResponse(BaseModel):
    active: bool = Field(json_schema_extra={"example": True})
    status: str = Field(
        examples=["started", "stopped", "already_running", "not_running"]
    )
    interface: Optional[str] = Field(
        default=None, json_schema_extra={"example": "eth0"}
    )


class Usb(BaseModel):
    interfaces: list[Any] = Field()


class Ufw(BaseModel):
    status: str = Field()
    ports: list[Any] = Field()
