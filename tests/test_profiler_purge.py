"""Tests for purging profiler data (service and POST /profiler/purge)."""

import json
import os

import pytest
from fastapi.testclient import TestClient

from wlanpi_core.asgi import app
from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.profiler import cli, service


class ExitedProcess:
    returncode = 0


class RunningProcess:
    returncode = None


@pytest.fixture
def root(tmp_path, monkeypatch):
    """Point purge at a data root in tmp_path, with no profiler running."""
    data = tmp_path / "profiler"
    (data / "clients").mkdir(parents=True)
    (data / "reports").mkdir()
    monkeypatch.setattr(service, "DATA_ROOT", str(data))
    monkeypatch.setattr(cli, "STATUS_FILE", str(tmp_path / "status.json"))
    monkeypatch.setattr(cli, "profiler_process", None)
    monkeypatch.setattr(service, "check_service_status", lambda name: False)
    return data


def test_purge_removes_contents_and_keeps_dirs(root):
    client_dir = root / "clients" / "aa-bb-cc-dd-ee-ff"
    client_dir.mkdir()
    (client_dir / "aa_5GHz.json").write_bytes(b"x" * 10)
    (client_dir / "aa_5GHz.pcap").write_bytes(b"x" * 20)
    (client_dir / "nested").mkdir()
    (client_dir / "nested" / "deep.txt").write_bytes(b"x" * 5)
    (root / "reports" / "profiler-2026-09-24.csv").write_bytes(b"x" * 100)
    os.chmod(root / "clients", 0o750)
    mode = os.stat(root / "clients").st_mode

    assert service.purge_data() == {"files": 4, "bytes": 135}
    assert list((root / "clients").iterdir()) == []
    assert list((root / "reports").iterdir()) == []
    assert os.stat(root / "clients").st_mode == mode


def test_purge_removes_symlinks_without_touching_targets(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    target_file = outside / "keep.txt"
    target_file.write_text("keep")
    (root / "reports" / "link.csv").symlink_to(target_file)
    (root / "clients" / "linkdir").symlink_to(outside, target_is_directory=True)
    nested = root / "clients" / "aa"
    nested.mkdir()
    (nested / "inner").symlink_to(outside, target_is_directory=True)

    result = service.purge_data()

    assert result["files"] == 3
    assert list((root / "clients").iterdir()) == []
    assert list((root / "reports").iterdir()) == []
    assert target_file.read_text() == "keep"
    assert sorted(p.name for p in outside.iterdir()) == ["keep.txt"]


def test_purge_skips_a_purge_dir_that_is_a_symlink(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    (root / "reports").rmdir()
    (root / "reports").symlink_to(outside, target_is_directory=True)

    assert service.purge_data() == {"files": 0, "bytes": 0}
    assert (outside / "keep.txt").exists()


def test_purge_missing_dirs_is_a_no_op(root):
    (root / "clients").rmdir()
    (root / "reports").rmdir()

    assert service.purge_data() == {"files": 0, "bytes": 0}


def test_purge_refuses_while_running_and_deletes_nothing(root, monkeypatch):
    report = root / "reports" / "r.csv"
    report.write_text("x")
    monkeypatch.setattr(service, "check_service_status", lambda name: True)

    with pytest.raises(ValidationError) as exc:
        service.purge_data()

    assert exc.value.status_code == 409
    assert report.exists()


def test_profiler_active_checks_systemd_unit(root, monkeypatch):
    seen = []
    monkeypatch.setattr(service, "check_service_status", lambda name: seen.append(name))

    assert not service.profiler_active()
    assert seen == ["wlanpi-profiler"]


@pytest.mark.parametrize(
    "process, expected", [(RunningProcess(), True), (ExitedProcess(), False)]
)
def test_profiler_active_checks_cores_own_process(root, monkeypatch, process, expected):
    monkeypatch.setattr(cli, "profiler_process", process)

    assert service.profiler_active() is expected


@pytest.mark.parametrize(
    "status, expected",
    [
        ({"state": "running", "pid": os.getpid()}, True),
        ({"state": "starting"}, True),
        ({"state": "running", "pid": 2**22 + 1}, False),  # stale: pid gone
        ({"state": "failed", "pid": os.getpid()}, False),
    ],
)
def test_profiler_active_checks_status_file(root, status, expected):
    with open(cli.STATUS_FILE, "w") as f:
        json.dump(status, f)

    assert service.profiler_active() is expected


@pytest.fixture
def client():
    async def _allow():
        return True

    app.dependency_overrides[verify_auth_wrapper] = _allow
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(verify_auth_wrapper, None)


def test_purge_endpoint_returns_counts(client, root):
    (root / "reports" / "r.csv").write_bytes(b"x" * 7)

    response = client.post("/api/v1/profiler/purge")

    assert response.status_code == 200
    assert response.json() == {"files": 1, "bytes": 7}


def test_purge_endpoint_409_while_running(client, root, monkeypatch):
    (root / "reports" / "r.csv").write_text("x")
    monkeypatch.setattr(service, "check_service_status", lambda name: True)

    response = client.post("/api/v1/profiler/purge")

    assert response.status_code == 409
    assert "stop it" in response.text
    assert (root / "reports" / "r.csv").exists()


def test_purge_endpoint_500_on_os_error(client, root, monkeypatch):
    def fail():
        raise PermissionError("denied")

    monkeypatch.setattr(service, "purge_data", fail)

    response = client.post("/api/v1/profiler/purge")

    assert response.status_code == 500


def test_purge_endpoint_requires_auth(root):
    (root / "reports" / "r.csv").write_text("x")
    with TestClient(app) as test_client:
        response = test_client.post("/api/v1/profiler/purge")

    assert response.status_code == 401
    assert (root / "reports" / "r.csv").exists()
