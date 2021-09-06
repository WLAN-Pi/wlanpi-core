from pydantic import BaseModel, Field


class SystemSummary(BaseModel):
    ip: str = Field(example="192.168.1.21")
    cpu_util: str = Field(title="CPU Utilization", example="0.76")
    mem_usage: str = Field(title="Memory Usage", example="398/987MB 40.32%")
    disk_util: str = Field(title="Disk Utilization", example="4/15GB 32%")
    temp: str = Field(title="Temperature", example="35.53C")
