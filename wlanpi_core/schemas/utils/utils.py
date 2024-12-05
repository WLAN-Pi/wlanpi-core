from typing import Any, Optional

from pydantic import BaseModel, Extra, Field


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

    class Config:
        populate_by_name = True


class SpeedTest(BaseModel):
    ip_address: str = Field(example="1.2.3.4")
    download_speed: str = Field(example="12.34 Mbps")
    upload_speed: str = Field(example="1.23 Mbps")


class PortBlinkerState(BaseModel):
    status: str = Field(example="success")
    action: str = Field(examples=["on", "off"])


class Usb(BaseModel):
    interfaces: list = Field()


class Ufw(BaseModel):
    status: str = Field()
    ports: list = Field()


class PingRequest(BaseModel):
    host: str = Field(examples=["google.com", "192.168.1.1"])
    count: int = Field(
        examples=[1, 10], description="How many packets to send.", default=1
    )
    interval: float = Field(
        examples=[1], description="The interval between packets, in seconds", default=1
    )
    ttl: Optional[int] = Field(
        examples=[20], description="The Time-to-Live of the ping attempt.", default=None
    )
    interface: Optional[str] = Field(
        examples=["eth0"],
        description="The interface the ping should originate from",
        default=None,
    )


class PingResponse(BaseModel):
    type: str = Field(examples=["reply"])
    timestamp: float = Field(examples=[1731371899.060181])
    bytes: int = Field(examples=[64])
    response_ip: str = Field(examples=["142.250.190.142"])
    icmp_seq: int = Field(examples=[1])
    ttl: int = Field(examples=[55])
    time_ms: float = Field(examples=[26.6])
    duplicate: bool = Field(examples=[False])


class PingResult(
    BaseModel,
):
    destination_ip: str = Field(examples=["142.250.190.142"])
    interface: Optional[str] = Field(
        examples=["eth0"],
        default=None,
        description="The interface the user specified that the ping be issued from. It will be empty if there wasn't one specified.",
    )
    data_bytes: Optional[int] = Field(examples=[56], default=None)
    pattern: Optional[str] = Field(default=None)
    destination: str = Field(examples=["google.com"])
    packets_transmitted: int = Field(examples=[10])
    packets_received: int = Field(examples=[10])
    packet_loss_percent: float = Field(examples=[0.0])
    duplicates: int = Field(examples=[0])
    time_ms: float = Field(examples=[9012.0])
    round_trip_ms_min: Optional[float] = Field(examples=[24.108], default=None)
    round_trip_ms_avg: Optional[float] = Field(examples=[29.318], default=None)
    round_trip_ms_max: Optional[float] = Field(examples=[37.001], default=None)
    round_trip_ms_stddev: Optional[float] = Field(examples=[4.496], default=None)
    jitter: Optional[float] = Field(examples=[37.001], default=None)
    responses: list[PingResponse] = Field()


class PingFailure(BaseModel):
    destination: str = Field(examples=["google.com"])
    message: str = Field(examples=["No route to host"])


class Iperf3ClientRequest(BaseModel):
    host: str = Field(examples=["192.168.1.1"])
    port: int = Field(examples=[5001], default=5001)
    time: int = Field(examples=[10], default=10)
    udp: bool = Field(default=False)
    reverse: bool = Field(default=False)
    interface: Optional[str] = Field(examples=["wlan0"], default=None)


# No Iperf3Result yet as it hasn't been fully modeled and I (MDK) don't know what all potential output forms are in JSON mode.


class Iperf2ClientRequest(BaseModel):
    host: str = Field(examples=["192.168.1.1"])
    port: int = Field(examples=[5001], default=5001)
    time: int = Field(examples=[10], default=10)
    udp: bool = Field(default=False)
    reverse: bool = Field(default=False)
    compatibility: bool = Field(default=False)
    interface: Optional[str] = Field(examples=["wlan0"], default=None)
    # version: int = Field(examples=[2, 3], default=3)
    # interface: Optional[str] = Field(examples=["eth0, wlan0"], default=None)
    # bind_address: Optional[str] = Field(examples=["192.168.1.12"], default=None)
    #
    # @model_validator(mode="after")
    # def check_dynamic_condition(self) -> Self:
    #     # print(self)
    #     if self.version not in [2, 3]:
    #         raise ValueError("iPerf version can be 2 or 3.")
    #     if self.bind_address is not None and self.interface is not None:
    #         raise ValueError("Only interface or bind_address can be specified.")
    #     return self


class Iperf2Result(BaseModel, extra=Extra.allow):
    timestamp: int = Field()
    source_address: str = Field(examples=["192.168.1.5"])
    source_port: int = Field(examples=[5001])
    destination_address: str = Field(examples=["192.168.1.1"])
    destination_port: int = Field(examples=[12345])
    transfer_id: int = Field(examples=[3])
    interval: list[float] = Field(examples=[0.0, 10.0])
    transferred_bytes: int = Field()
    transferred_mbytes: float = Field()
    bps: int = Field()
    mbps: float = Field()
    jitter: Optional[float] = Field(default=None)
    error_count: Optional[int] = Field(default=None)
    datagrams: Optional[int] = Field(default=None)


class TracerouteRequest(BaseModel):
    host: str = Field(examples=["dns.google.com"])
    interface: Optional[str] = Field(examples=["wlan0"], default=None)
    bypass_routing: bool = Field(default=False)
    queries: Optional[int] = Field(default=3)
    max_ttl: Optional[int] = Field(default=30)


class TracerouteProbes(BaseModel):
    annotation: Any
    asn: Any
    ip: str = Field(examples=["8.8.4.4"])
    name: str = Field(examples=["syn-098-123-060-049.biz.spectrum.com"])
    rtt: float = Field(examples=["3.177"])


class TracerouteHops(BaseModel):
    hop: int = Field(examples=[1], default=0)
    probes: list[TracerouteProbes] = Field()


class TracerouteResponse(BaseModel):
    destination_ip: str = Field(examples=["8.8.4.4"])
    destination_name: str = Field(examples=["dns.google.com"])
    hops: list[TracerouteHops] = Field()


class DhcpTestResponse(BaseModel):
    time: float = Field()
    duid: str = Field(examples=["00:01:00:01:2e:74:ef:71:dc:a6:32:8e:04:17"])
    events: list[str] = Field()
    data: dict[str, str] = Field()


class DhcpTestRequest(BaseModel):
    interface: Optional[str] = Field(examples=["wlan0"], default=None)
    timeout: int = Field(default=5)


class DigRequest(BaseModel):
    interface: Optional[str] = Field(examples=["wlan0"], default=None)
    nameserver: Optional[str] = Field(examples=["wlan0"], default=None)
    host: str = Field(examples=["wlanpi.com"])


class DigQuestion(BaseModel):
    name: str = Field(examples=["wlanpi.com."])
    question_class: str = Field(examples=["IN"], alias="class")
    type: str = Field(examples=["A"])


class DigAnswer(BaseModel):
    name: str = Field(examples=["wlanpi.com."])
    answer_class: str = Field(examples=["IN"], alias="class")
    type: str = Field(examples=["A"])
    ttl: int = Field(examples=[1795])
    data: str = Field(examples=["165.227.111.100"])


class DigResponse(BaseModel):
    id: int = Field()
    opcode: str = Field()
    status: str = Field()
    flags: list[str] = Field()
    query_num: int = Field()
    answer_num: int = Field()
    authority_num: int = Field()
    additional_num: int = Field()
    question: DigQuestion = Field()
    answer: list[DigAnswer] = Field()
    query_time: int = Field(examples=[3])
    server: str = Field(examples=["192.168.30.1#53(192.168.30.1)"])
    when: str = Field(examples=["Thu Nov 14 19:15:39 EST 2024"])
    rcvd: int = Field(examples=[82])
