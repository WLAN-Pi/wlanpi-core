from datetime import datetime, timedelta

from fastapi import HTTPException, Request, Security, status
from fastapi.security.api_key import APIKeyHeader
from jose import JWTError, jwt

from .config import SECRET_KEY

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

API_TOKEN_HEADER = APIKeyHeader(name="Authorization")


def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.now() + (
        expires_delta if expires_delta else timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_localhost(request: Request):
    if request.client.host != "127.0.0.1":
        raise HTTPException(
            status_code=403,
            detail="Access forbidden: endpoint available only on localhost",
        )


def verify_jwt_token(api_key: str = Security(API_TOKEN_HEADER)):
    token = api_key.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload
