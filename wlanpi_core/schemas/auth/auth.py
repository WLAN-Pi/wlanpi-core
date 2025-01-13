from typing import Optional

from pydantic import BaseModel


class KeyResponse(BaseModel):
    key_id: int
    message: str
    key: Optional[str] = None  # Base64 encoded key, only included when needed


class TokenRequest(BaseModel):
    device_id: str


class Token(BaseModel):
    access_token: str
    token_type: str
