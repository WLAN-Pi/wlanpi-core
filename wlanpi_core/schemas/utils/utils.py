from pydantic import BaseModel, Field


class ReachabilityTest(BaseModel):
    reachability: list = Field(example=[])
    
