from pydantic import BaseModel

class TokenRequest(BaseModel):
    device_id: str
    
class Token(BaseModel):
    access_token: str
    token_type: str
