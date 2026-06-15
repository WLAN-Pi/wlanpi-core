from typing import Optional

from pydantic import BaseModel, Field


class KeyResponse(BaseModel):
    key_id: int
    message: str
    key: Optional[str] = None  # Base64 encoded key, only included when needed


class TokenRequest(BaseModel):
    device_id: str


class Token(BaseModel):
    access_token: str = Field(description="JWT bearer token")
    token_type: str = Field(default="bearer", examples=["bearer"])


class TokenRevokeResponse(BaseModel):
    status: str = Field(
        examples=["success", "info", "warning"],
        description="success | info (already revoked) | warning (not found)",
    )
    message: str = Field(examples=["Token revoked"])
    device_id: Optional[str] = Field(
        default=None, description="Present when a token record was matched"
    )
