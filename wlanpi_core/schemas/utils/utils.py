"""Utility endpoint schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PingTargetResult(BaseModel):
    """Result of pinging one target."""

    target: str
    success: bool
    rtt_ms_min: float | None = Field(default=None, alias="rttMsMin")
    rtt_ms_avg: float | None = Field(default=None, alias="rttMsAvg")
    rtt_ms_max: float | None = Field(default=None, alias="rttMsMax")
    packet_loss_percent: float | None = Field(default=None, alias="packetLossPercent")
    display: str = Field(description='Human-readable RTT such as "5.17ms" or "FAIL"')

    model_config = {"populate_by_name": True}


class ReachabilityTest(BaseModel):
    """Results of the reachability checks."""

    ping_google: str = Field(
        alias="Ping Google", json_schema_extra={"example": "12.345ms"}
    )
    browse_google: str = Field(examples=["OK", "FAIL"], alias="Browse Google")
    ping_gateway: str = Field(
        alias="Ping Gateway", json_schema_extra={"example": "12.345ms"}
    )
    dns_server_1_resolution: str | None = Field(
        None, examples=["9.9.9.9: OK", "9.9.9.9: FAIL"], alias="DNS Server 1 Resolution"
    )
    dns_server_2_resolution: str | None = Field(
        None, examples=["9.9.9.9: OK", "9.9.9.9: FAIL"], alias="DNS Server 2 Resolution"
    )
    dns_server_3_resolution: str | None = Field(
        None, examples=["9.9.9.9: OK", "9.9.9.9: FAIL"], alias="DNS Server 3 Resolution"
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
    """Speedtest failure response."""

    error: str = Field(description="Failure reason, e.g. speedtest timed out")


class SpeedTest(BaseModel):
    """Results of a LibreSpeed test."""

    ip_address: str = Field(alias="ipAddress", json_schema_extra={"example": "1.2.3.4"})
    download_speed: str = Field(
        alias="downloadSpeed", json_schema_extra={"example": "12.34 Mbps"}
    )
    upload_speed: str = Field(
        alias="uploadSpeed", json_schema_extra={"example": "1.23 Mbps"}
    )
    ping_ms: float | None = Field(default=None, alias="pingMs")
    jitter_ms: float | None = Field(default=None, alias="jitterMs")
    server: str | None = Field(
        default=None, description="Selected LibreSpeed server name"
    )
    tested_at: datetime | None = Field(default=None, alias="testedAt")

    model_config = {"populate_by_name": True}


class PortBlinkerState(BaseModel):
    """Result of a port blinker action."""

    status: str = Field(json_schema_extra={"example": "success"})
    action: str = Field(examples=["on", "off"])


class BlinkerStatus(BaseModel):
    """Whether the port blinker is currently running."""

    active: bool = Field(json_schema_extra={"example": True})


class BlinkerActionResponse(BaseModel):
    """Result of starting or stopping the port blinker."""

    active: bool = Field(json_schema_extra={"example": True})
    status: str = Field(
        examples=["started", "stopped", "already_running", "not_running"]
    )
    interface: str | None = Field(default=None, json_schema_extra={"example": "eth0"})


class Usb(BaseModel):
    """List of detected USB interfaces."""

    interfaces: list[Any] = Field()


class Ufw(BaseModel):
    """UFW firewall status."""

    status: str = Field()
    ports: list[Any] = Field()
