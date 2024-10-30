import logging

from fastapi import APIRouter, Depends

from wlanpi_core.core.auth import create_access_token, verify_localhost
from wlanpi_core.services import system_service

router = APIRouter()

log = logging.getLogger("uvicorn")


@router.post("/generate_token", dependencies=[Depends(verify_localhost)])
async def generate_token():
    token_data = {
        "sub": system_service.get_hostname()
    }  # use device hostname as token subject
    access_token = create_access_token(data=token_data)
    return {"access_token": access_token}
