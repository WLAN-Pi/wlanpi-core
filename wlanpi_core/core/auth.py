from datetime import datetime, timedelta, timezone
from typing import Annotated
import jwt

from fastapi import HTTPException, Request, Security, status, Depends
from fastapi.security.api_key import APIKeyHeader
from jwt.exceptions import InvalidTokenError

from .config import SECRET_KEY

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

API_TOKEN_HEADER = APIKeyHeader(name="Authorization")


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


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
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload
