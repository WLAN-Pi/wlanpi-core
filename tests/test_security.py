"""Tests for SecurityManager secret and directory permissions."""

import stat

from wlanpi_core.core import security as security_module


def _install_manager(tmp_path, monkeypatch):
    """Build a SecurityManager rooted at tmp_path with os.chown recorded.

    Tests run unprivileged, so chown to root:root would raise; record the
    calls instead and assert ownership intent separately from the modes.
    """
    calls = []
    monkeypatch.setattr(security_module, "SECRETS_DIR", str(tmp_path / "secrets"))
    monkeypatch.setattr(
        security_module.os,
        "chown",
        lambda path, uid, gid: calls.append((str(path), uid, gid)),
    )
    return security_module.SecurityManager(), calls


def test_new_shared_secret_is_root_only(tmp_path, monkeypatch):
    manager, calls = _install_manager(tmp_path, monkeypatch)
    secrets_dir = tmp_path / "secrets"
    secret_path = secrets_dir / security_module.SHARED_SECRET_FILE

    assert secret_path.read_bytes() == manager.shared_secret
    assert stat.S_IMODE(secret_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(secrets_dir.stat().st_mode) == 0o700
    assert (str(secret_path), 0, 0) in calls


def test_loose_permissions_are_tightened(tmp_path, monkeypatch):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(mode=0o710)
    secrets_dir.chmod(0o710)
    secret_path = secrets_dir / security_module.SHARED_SECRET_FILE
    secret_path.write_bytes(b"s" * 32)
    secret_path.chmod(0o640)

    _install_manager(tmp_path, monkeypatch)

    assert stat.S_IMODE(secret_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(secrets_dir.stat().st_mode) == 0o700
