from pydantic import BaseModel, Field
from typing import Optional

class ReachabilityTest(BaseModel):
    ping_google: Optional[str] = Field(example="12.345ms", alias="Ping Google")
    browse_google: Optional[str] = Field(examples=["OK", "FAIL"], alias="Browse Google")
    ping_gateway: Optional[str] = Field(example="12.345ms", alias="Ping Gateway")
    dns_server_1_resolution: Optional[str] = Field(default=None, examples=["OK", "FAIL"], alias="DNS Server 1 Resolution")
    dns_server_2_resolution: Optional[str] = Field(default=None, examples=["OK", "FAIL"], alias="DNS Server 2 Resolution")
    dns_server_3_resolution: Optional[str] = Field(default=None, examples=["OK", "FAIL"], alias="DNS Server 3 Resolution")
    arping_gateway: Optional[str] = Field(example="12.345ms", alias="Arping Gateway")

    class Config:
        allow_population_by_field_name = True
        orm_mode = True
        exclude_none = True
        use_enum_values = True
    
class SpeedTest(BaseModel):
    ip_address: str = Field(example="1.2.3.4")
    download_speed: str = Field(example="12.34 Mbps")
    upload_speed: str = Field(example="1.23 Mbps")
    