![coverage-badge](coverage.svg) [![packagecloud-badge](https://img.shields.io/badge/deb-packagecloud.io-844fec.svg)](https://packagecloud.io/)

# wlanpi-core

`wlanpi-core` is a FastAPI backend that provides centralized API services for the WLAN Pi platform. It serves as the primary data provider for consumers including `wlanpi-webui`, `wlanpi-fpms`, and the chatbot, ensuring each consumer gets the same data in a consistent way rather than reimplementing data collection independently.

## Development Workflow

See [WORKFLOW.md](WORKFLOW.md) to get started.

## Other Important Docs

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [PACKAGING.md](PACKAGING.md)

## Authors

See [AUTHORS.md](AUTHORS.md). If you contribute, feel free to add yourself.

## Open Source Software

This project is built on open source software:

- [Python](https://www.python.org/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [pydantic](https://github.com/samuelcolvin/pydantic/)
- [SQLAlchemy](https://www.sqlalchemy.org/)
- [alembic](https://alembic.sqlalchemy.org/)
- [authlib](https://docs.authlib.org/)
- [slowapi](https://github.com/laurents/slowapi)
- [uvicorn](https://www.uvicorn.org/)
- [gunicorn](https://gunicorn.org/)
- [nginx](https://nginx.org/)
- [dh-virtualenv](https://github.com/spotify/dh-virtualenv)

If we missed something, please let us know.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Open an issue or reach out to a core team member before starting work to make sure we're aligned.

## Code of Conduct

See the [WLAN Pi Code of Conduct](https://github.com/WLAN-Pi/.github/blob/main/docs/code_of_conduct.md).

## License

See [LICENSE](LICENSE).
