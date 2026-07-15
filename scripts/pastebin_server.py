# -*- coding: utf-8 -*-
#
# Minimal Pastebin Server for paste.wlanpi.com
# To run this on your VPS:
# pip install fastapi uvicorn
# uvicorn pastebin_server:app --host 0.0.0.0 --port 8000
#

import secrets
import string
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

app = FastAPI()
PASTES_DIR = Path("./pastes")
PASTES_DIR.mkdir(exist_ok=True)


def generate_slug(length: int = 6) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


@app.post("/")
async def create_paste(request: Request):
    # Read raw body
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Paste content cannot be empty")

    # Generate unique slug
    slug = generate_slug()
    while (PASTES_DIR / slug).exists():
        slug = generate_slug()

    # Save paste
    (PASTES_DIR / slug).write_bytes(body)

    # Get hostname from request to build the return URL
    host = request.headers.get("host", "paste.wlanpi.com")
    # For local testing or if SSL is handled via a reverse proxy (Nginx/Traefik) on the VPS
    scheme = request.headers.get("x-forwarded-proto", "https")

    return Response(content=f"{scheme}://{host}/{slug}\n", media_type="text/plain")


@app.get("/{slug}", response_class=PlainTextResponse)
def get_paste(slug: str):
    paste_file = PASTES_DIR / slug
    if not paste_file.exists() or not paste_file.is_file():
        raise HTTPException(status_code=404, detail="Paste not found")

    try:
        return paste_file.read_text(encoding="utf-8")
    except Exception:
        raise HTTPException(status_code=500, detail="Error reading paste content")
