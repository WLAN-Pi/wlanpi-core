# -*- coding: utf-8 -*-
#
# Hardened Pastebin Server for paste.wlanpi.com
# To run this on your VPS:
# pip install fastapi uvicorn
# uvicorn pastebin_server:app --host 0.0.0.0 --port 8000
#

import re
import secrets
import string
import time
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

app = FastAPI()
PASTES_DIR = Path("./pastes")
PASTES_DIR.mkdir(exist_ok=True)

# SECURITY SETTINGS
MAX_PASTE_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB size limit
RATE_LIMIT_MAX_REQUESTS = 10  # 10 pastes per minute
RATE_LIMIT_WINDOW_SECONDS = 60

# In-memory rate limiting store: client_ip -> list of timestamps
upload_records = defaultdict(list)


def check_rate_limit(ip: str) -> bool:
    """Returns True if the IP is rate limited (exceeded threshold)."""
    now = time.time()
    # Remove timestamps outside the sliding window
    upload_records[ip] = [
        t for t in upload_records[ip] if now - t < RATE_LIMIT_WINDOW_SECONDS
    ]
    if len(upload_records[ip]) >= RATE_LIMIT_MAX_REQUESTS:
        return True
    upload_records[ip].append(now)
    return False


def generate_slug(length: int = 6) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


@app.post("/")
async def create_paste(request: Request):
    client_ip = request.client.host if request.client else "unknown"

    # 1. Rate Limiting Check
    if check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a minute before trying again.",
        )

    # 2. Content-Length Header Validation
    content_length_header = request.headers.get("content-length")
    if content_length_header:
        try:
            if int(content_length_header) > MAX_PASTE_SIZE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Paste exceeds maximum allowed size of {MAX_PASTE_SIZE_BYTES / (1024*1024):.1f} MB",
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header")

    # 3. Stream & Read Payload (defends against large slow-post attacks)
    body_bytes = bytearray()
    async for chunk in request.stream():
        body_bytes.extend(chunk)
        if len(body_bytes) > MAX_PASTE_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Paste exceeds maximum allowed size of {MAX_PASTE_SIZE_BYTES / (1024*1024):.1f} MB",
            )

    if not body_bytes:
        raise HTTPException(status_code=400, detail="Paste content cannot be empty")

    # 4. Text Validation: Only accept valid text files (reject binaries)
    try:
        # Try decoding as UTF-8. If it fails, reject it as binary
        body_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Invalid content. Only plain text files are accepted.",
        )

    # 5. Generate unique slug
    slug = generate_slug()
    while (PASTES_DIR / slug).exists():
        slug = generate_slug()

    # 6. Save Paste to disk
    (PASTES_DIR / slug).write_bytes(body_bytes)

    # Build response URL
    host = request.headers.get("host", "paste.wlanpi.com")
    scheme = request.headers.get("x-forwarded-proto", "https")

    return Response(content=f"{scheme}://{host}/{slug}\n", media_type="text/plain")


@app.get("/{slug}", response_class=PlainTextResponse)
def get_paste(slug: str):
    # 7. Strict Slug Sanitization (guards against directory traversal)
    if not re.fullmatch(r"[a-z0-9]{6}", slug):
        raise HTTPException(
            status_code=400, detail="Invalid paste identifier format"
        )

    safe_slug = slug
    base_dir = PASTES_DIR.resolve()
    paste_file = (base_dir / safe_slug).resolve()
    try:
        paste_file.relative_to(base_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid paste identifier format")

    if not paste_file.exists() or not paste_file.is_file():
        raise HTTPException(status_code=404, detail="Paste not found")

    try:
        return paste_file.read_text(encoding="utf-8")
    except Exception:
        raise HTTPException(status_code=500, detail="Error reading paste content")
