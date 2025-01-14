# wlanpi-core architecture

`wlanpi-core` is a FastAPI backend built for the WLAN Pi that provides centralized API services.

## Why a backend?

During the first iterations of the WLAN Pi project, various developers working on tools (like FPMS, WebUI, chatbot, etc.) ended up doing their own thing for gathering the same sets of data. The purpose of the backend is to provide a way for various consumers to get the same set of data in a consistent manner.

## Choosing a backend

When we looked at our goals and what was available at the time, `FastAPI` made the most sense given its developer productivity, async first design, automatic API documentation, and claimed performance compared to the previous tools like `Django`, `Flask`, `Requests`, etc.

## Goals

The primary goals include:

- Developer productivity 
- Contributor familiarity with Python
- Lightweight system requirements
- Decent performance with async capabilities
- Centralized data access for WLAN Pi services

## Core Components

### API Layers

- Authentication (/auth)
- Network (/network)
- System (/system)
- Bluetooth (/bluetooth)
- Utils (/utils)

### Database

- SQLite with WAL mode for better concurrency
- Token and activity tracking
- Connection pooling and management
- Automated migrations

## Security

- JWT-based authentication with key rotation
- Rate limiting and request throttling via slowapi
- HMAC validation for internal requests
- Token management (issuance, validation, revocation)
- Activity monitoring and logging
- Access control via allowed services list

## Data Flow

1. Client request via REST API
2. Authentication verification (JWT/HMAC)
3. Rate limit check
4. Request routing to appropriate service
5. Service processing with optional database interaction
6. Response formatting and delivery

## Logging behavior

1. Console/journalctl:
    - INFO and above by default
    - DEBUG and above when run with --debug flag
2. /var/log/wlanpi_core/app.log:
    - Always INFO and above
    - Never changes
3. /var/log/wlanpi_core/debug/debug.log:
    - Always DEBUG and above
    - Never changes
    - tmpfs (not persistent on reboot)

## Server Stack

- Uvicorn for Asynchronous Server Gateway Interface (ASGI) goodness. Uvicorn runs async Python web code in a single process. https://www.uvicorn.org/deployment/
- Gunicorn for process management. Gunicorn is a fully-featured server and process manager. We can use it to manage multiple concurrent processes. This gives us concurrency and parallelism. https://www.uvicorn.org/#running-with-gunicorn https://gunicorn.org/
- Nginx as reverse proxy https://nginx.org/en/
- Unix socket binding for interprocess communication. Gunicorn is bound to a UNIX socket.

## Consumers

The backend serves various WLAN Pi services requiring device data and control:

- wlanpi-fpms
- wlanpi-webui
- wlanpi-app
- CLI tools

## Questions

Something missing here or just doesn't make sense? Let us know and open an issue on GitHub so we can correct it or add clarity. Thanks!
