import logging
from datetime import timedelta

from fastapi import APIRouter, Depends

from wlanpi_core.core.auth import (
    ACCESS_TOKEN_EXPIRE_DAYS,
    create_access_token,
    verify_localhost,
)
from wlanpi_core.schemas.auth import auth
from wlanpi_core.services import system_service

router = APIRouter()

log = logging.getLogger("uvicorn")


@router.post("/generate_token", dependencies=[Depends(verify_localhost)])
async def generate_token():
    token_data = {
        "sub": system_service.get_hostname()
    }  # use device hostname as token subject
    access_token_expires = timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    access_token = create_access_token(
        data=token_data, expires_delta=access_token_expires
    )
    return auth.Token(access_token=access_token, token_type="bearer")
