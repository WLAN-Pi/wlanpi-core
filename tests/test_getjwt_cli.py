"""Tests for the getjwt CLI."""

from unittest.mock import MagicMock

import pytest

from wlanpi_core.cli import getjwt

TOKEN = "test.jwt.token"


class FakeClient:
    def __init__(self, device_id, port):
        self.device_id = device_id
        self.port = port

    def get_token(self):
        return {"access_token": TOKEN, "token_type": "bearer"}


class UnreadableSecret:
    def read_bytes(self):
        raise PermissionError("permission denied")


@pytest.fixture
def fake_client(monkeypatch):
    monkeypatch.setattr(getjwt, "DeviceAuthClient", FakeClient)


@pytest.fixture
def connected_socket(monkeypatch):
    monkeypatch.setattr(getjwt.socket, "socket", lambda *a, **k: MagicMock())


def _run(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["getjwt", *argv])
    return getjwt.main()


def test_export_prints_eval_ready_line(monkeypatch, capsys, fake_client):
    assert _run(monkeypatch, ["pi", "--export"]) == 0

    assert capsys.readouterr().out == f"export WLANPI_TOKEN={TOKEN}\n"


def test_default_still_prints_json(monkeypatch, capsys, fake_client):
    assert _run(monkeypatch, ["pi", "--no-color"]) == 0

    assert f'"access_token": "{TOKEN}"' in capsys.readouterr().out


def test_export_without_access_token_fails(monkeypatch, capsys):
    class NoTokenClient(FakeClient):
        def get_token(self):
            return {"token_type": "bearer"}

    monkeypatch.setattr(getjwt, "DeviceAuthClient", NoTokenClient)

    assert _run(monkeypatch, ["pi", "--export"]) == 1
    assert "access_token" in capsys.readouterr().err


def test_unreadable_secret_points_at_sudo(monkeypatch, connected_socket, tmp_path):
    secret = tmp_path / "shared_secret.bin"
    secret.write_bytes(b"secret")
    monkeypatch.setattr(getjwt, "SECRET_PATH", str(secret))

    client = getjwt.DeviceAuthClient("pi")
    client.secret_file = UnreadableSecret()

    with pytest.raises(PermissionError, match="Run getjwt with sudo"):
        client.validate_setup()


def test_unstattable_secret_points_at_sudo(monkeypatch, connected_socket):
    monkeypatch.setattr(getjwt, "SECRET_PATH", "/nonexistent/shared_secret.bin")
    monkeypatch.setattr(getjwt, "_running_as_root", lambda: False)

    with pytest.raises(PermissionError, match="Run getjwt with sudo"):
        getjwt.DeviceAuthClient("pi")


def test_missing_secret_reported_when_root(monkeypatch, connected_socket):
    monkeypatch.setattr(getjwt, "SECRET_PATH", "/nonexistent/shared_secret.bin")
    monkeypatch.setattr(getjwt, "_running_as_root", lambda: True)

    with pytest.raises(FileNotFoundError, match="Secret not found"):
        getjwt.DeviceAuthClient("pi")
