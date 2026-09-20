"""Tests for the getjwt CLI token-hygiene flags."""

import os
import stat

import pytest

from wlanpi_core.cli import getjwt

TOKEN = "test.jwt.token"


class FakeClient:
    def __init__(self, device_id, port):
        self.device_id = device_id
        self.port = port

    def get_token(self):
        return {"access_token": TOKEN, "token_type": "bearer"}


@pytest.fixture
def fake_client(monkeypatch):
    monkeypatch.setattr(getjwt, "DeviceAuthClient", FakeClient)


def _run(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["getjwt", *argv])
    return getjwt.main()


def test_export_prints_eval_ready_line(monkeypatch, capsys, fake_client):
    assert _run(monkeypatch, ["pi", "--export"]) == 0

    assert capsys.readouterr().out == f"export WLANPI_TOKEN={TOKEN}\n"


def test_write_env_creates_0600_file(monkeypatch, tmp_path, fake_client):
    env_file = tmp_path / "wlanpi.env"

    assert _run(monkeypatch, ["pi", "--write-env", str(env_file)]) == 0

    assert env_file.read_text() == f"WLANPI_TOKEN={TOKEN}\n"
    assert stat.S_IMODE(os.stat(env_file).st_mode) == 0o600


def test_write_env_tightens_existing_file(monkeypatch, tmp_path, fake_client):
    env_file = tmp_path / "wlanpi.env"
    env_file.write_text("old")
    env_file.chmod(0o644)

    assert _run(monkeypatch, ["pi", "--write-env", str(env_file)]) == 0

    assert stat.S_IMODE(os.stat(env_file).st_mode) == 0o600


def test_export_and_write_env_are_mutually_exclusive(monkeypatch, fake_client):
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, ["pi", "--export", "--write-env", "/tmp/x"])

    assert exc.value.code == 2


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
