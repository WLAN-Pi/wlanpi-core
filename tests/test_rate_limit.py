"""Rate limits count per client address, not per nginx connection."""

from starlette.requests import Request

from wlanpi_core.app import create_app, rate_limit_key


def _request(client: tuple[str, int] | None, real_ip: str | None = None) -> Request:
    headers = [(b"x-real-ip", real_ip.encode())] if real_ip else []
    return Request({"type": "http", "headers": headers, "client": client})


def test_unix_socket_uses_the_address_nginx_saw():
    assert rate_limit_key(_request(None, "192.0.2.7")) == "192.0.2.7"


def test_unix_socket_without_header_is_local():
    assert rate_limit_key(_request(None)) == "127.0.0.1"


def test_loopback_peer_uses_the_address_nginx_saw():
    assert rate_limit_key(_request(("127.0.0.1", 50000), "192.0.2.7")) == "192.0.2.7"


def test_direct_client_cannot_choose_its_key():
    assert rate_limit_key(_request(("192.0.2.9", 50000), "192.0.2.7")) == "192.0.2.9"


def test_app_limits_per_client():
    # Not a request loop: under newer FastAPI, slowapi's middleware can't see
    # included routes, so it would pass without limiting anything.
    assert create_app(debug=False).state.limiter._key_func is rate_limit_key
