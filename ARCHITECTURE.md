# wlanpi-core architecture

The `wlanpi-core` is a FastAPI backend built for the WLAN Pi.

The primary goal when we choose tools for development include developer productivity, lightweight system requirements, and high performance. 

# Why a backend?

During the first iterations of the WLAN Pi project, various developers working on tools ended up doing their own thing for gathering the same sets of data. 

The purpose of the backend is to eliminate the need for various 

# Choosing a backend

When we looked at our goals and what was available at the time. `FastAPI` made the most sense given it's developer productivity, async first design, automatic API documentation, and performance compared to the previous tools like `Django`, `Flask`, `Requests`, etc. 

# Server

We're giving a go at running Uvicorn with Gunicorn. https://www.uvicorn.org/#running-with-gunicorn

Gunicorn is a fully featured server and process manager.

Uvicorn gives us the ASGI goodness. https://www.uvicorn.org/deployment/

# Consumers

Here are some of the projects we expect to leverage this backend

## wlanpi-webui
## wlanpi-fpms
## wlanpi-profiler
## wlanpi-chatbot