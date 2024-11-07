import logging

from fastapi import APIRouter, Depends
from datetime import timedelta

from wlanpi_core.core.auth import create_access_token, verify_localhost, ACCESS_TOKEN_EXPIRE_DAYS
from wlanpi_core.services import system_service
from wlanpi_core.schemas.auth import auth

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
