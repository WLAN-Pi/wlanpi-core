# wlanpi-core architecture

The `wlanpi-core` is a FastAPI backend built for the WLAN Pi.

## Goals

The primary goals include:

- developer productivity
- contributor familiarity with the language
- lightweight system requirements
- high performance
- async out of the box

## Why a backend?

During the first iterations of the WLAN Pi project, various developers working on tools (like fpms, ui, chatbot, etc.) ended up doing their own thing for gathering the same sets of data.

The purpose of the backend is to provide a way for various subscribers to get the same set of data from the WLAN Pi device.

## Choosing a backend

When we looked at our goals and what was available at the time. `FastAPI` made the most sense given it's developer productivity, async first design, automatic API documentation, and performance compared to the previous tools like `Django`, `Flask`, `Requests`, etc.

## Server

We're giving a go at running Uvicorn with Gunicorn. https://www.uvicorn.org/#running-with-gunicorn

Uvicorn gives us the Asynchronous Server Gateway Interface (ASGI) goodness. It runs async Python web code in a single process. https://www.uvicorn.org/deployment/

Gunicorn is a fully featured server and process manager. We can use it to manage multiple concurrent processes. This gives us concurrency and paralleism. https://gunicorn.org/

In our case, we're binding Gunicorn to a UNIX socket. Then we're using nginx as a proxy/load balancer. https://nginx.org/en/

## Consumers

Here are some of the projects (consumers) we expect to leverage the backend:

## Questions

Something missing here or just doesn't make sense? Let us know so we can correct it or add clarity. Thanks!
