from pydantic import BaseModel, Field


class NetworkInfo(BaseModel):
    a: str = Field(example="a")