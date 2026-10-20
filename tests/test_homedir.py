"""Tests for wlanpi XDG data-home ownership self-heal."""

import os

import pytest

from wlanpi_core.utils import homedir


class _FakePasswd:
    def __init__(self, uid: int) -> None:
        self.pw_uid = uid


def _raise_keyerror(name: str) -> None:
    raise KeyError(name)


@pytest.fixture
def fake_wlanpi_identity(monkeypatch):
    """Pretend a wlanpi user/group with uid/gid 1500 exists."""
    monkeypatch.setattr(
        homedir.pwd,
        "getpwnam",
        lambda name: _FakePasswd(1500) if name == "wlanpi" else _raise_keyerror(name),
    )

    class _FakeGrp:
        gr_gid = 1500

    monkeypatch.setattr(
        homedir.grp,
        "getgrnam",
        lambda name: _FakeGrp() if name == "wlanpi" else _raise_keyerror(name),
    )


def _record_chown(monkeypatch):
    calls = []
    monkeypatch.setattr(
        homedir.os, "chown", lambda path, uid, gid: calls.append((str(path), uid, gid))
    )
    return calls


def test_creates_missing_dirs_owned_by_wlanpi(
    tmp_path, monkeypatch, fake_wlanpi_identity
):
    calls = _record_chown(monkeypatch)

    homedir.ensure_wlanpi_home_data_dirs(tmp_path)

    assert (tmp_path / ".local").is_dir()
    assert (tmp_path / ".local" / "share").is_dir()
    assert (str(tmp_path / ".local"), 1500, 1500) in calls
    assert (str(tmp_path / ".local" / "share"), 1500, 1500) in calls


def test_reclaims_root_owned_dirs(tmp_path, monkeypatch, fake_wlanpi_identity):
    (tmp_path / ".local" / "share").mkdir(parents=True)
    calls = _record_chown(monkeypatch)

    homedir.ensure_wlanpi_home_data_dirs(tmp_path)

    assert (str(tmp_path / ".local"), 1500, 1500) in calls
    assert (str(tmp_path / ".local" / "share"), 1500, 1500) in calls


def test_does_not_touch_correctly_owned_dirs(tmp_path, monkeypatch):
    # Use the real process uid/gid as the "wlanpi" identity so the dirs
    # created below are already correctly owned, with no need to fake stat().
    uid, gid = os.getuid(), os.getgid()
    monkeypatch.setattr(
        homedir.pwd,
        "getpwnam",
        lambda name: _FakePasswd(uid) if name == "wlanpi" else _raise_keyerror(name),
    )

    class _FakeGrp:
        gr_gid = gid

    monkeypatch.setattr(
        homedir.grp,
        "getgrnam",
        lambda name: _FakeGrp() if name == "wlanpi" else _raise_keyerror(name),
    )

    (tmp_path / ".local" / "share").mkdir(parents=True)
    calls = _record_chown(monkeypatch)

    homedir.ensure_wlanpi_home_data_dirs(tmp_path)

    assert calls == []


def test_noop_when_wlanpi_user_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(homedir.pwd, "getpwnam", _raise_keyerror)
    calls = _record_chown(monkeypatch)

    homedir.ensure_wlanpi_home_data_dirs(tmp_path)

    assert not (tmp_path / ".local").exists()
    assert calls == []
