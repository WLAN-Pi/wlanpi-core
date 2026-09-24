"""Tests for purging profiler data (service and POST /profiler/purge)."""

import asyncio
import json
import os
import shutil
import threading

import pytest
from fastapi.testclient import TestClient

from wlanpi_core.asgi import app
from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.profiler import cli, service
from wlanpi_core.services import system_service


class ObservedLock(asyncio.Lock):
    """asyncio.Lock that flags when someone has to wait for it."""

    def __init__(self):
        super().__init__()
        self.contended = asyncio.Event()

    async def acquire(self):
        """Flag contention, then acquire as usual."""
        if self.locked():
            self.contended.set()
        return await super().acquire()


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
    monkeypatch.setattr(cli, "_profiler_lock", asyncio.Lock())
    monkeypatch.setattr(service, "get_service_active_state", lambda name: "inactive")
    return data


def purge():
    return asyncio.run(service.purge_data())


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

    assert purge() == {"files": 4, "bytes": 135}
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

    result = purge()

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

    assert purge() == {"files": 0, "bytes": 0}
    assert (outside / "keep.txt").exists()


def test_purge_missing_dirs_is_a_no_op(root):
    (root / "clients").rmdir()
    (root / "reports").rmdir()

    assert purge() == {"files": 0, "bytes": 0}


class VanishingOs:
    """os as service sees it, but unlink finds the file already removed."""

    def __getattr__(self, name):
        """Delegate everything else to the real os module."""
        return getattr(os, name)

    def unlink(self, path):
        os.unlink(path)  # someone else got there first
        os.unlink(path)


def test_purge_skips_file_removed_concurrently(root, monkeypatch):
    (root / "reports" / "gone.csv").write_bytes(b"x" * 3)
    monkeypatch.setattr(service, "os", VanishingOs())

    assert purge() == {"files": 0, "bytes": 0}
    assert list((root / "reports").iterdir()) == []


def test_purge_skips_dir_removed_concurrently(root, monkeypatch):
    (root / "clients" / "aa").mkdir()
    (root / "clients" / "aa" / "a.json").write_text("x")
    (root / "reports" / "r.csv").write_bytes(b"x" * 4)
    real_usage = service._tree_usage

    def usage_then_vanish(path):
        result = real_usage(path)
        shutil.rmtree(path)  # removed between counting and rmtree
        return result

    monkeypatch.setattr(service, "_tree_usage", usage_then_vanish)

    assert purge() == {"files": 2, "bytes": 5}
    assert list((root / "clients").iterdir()) == []
    assert list((root / "reports").iterdir()) == []


def test_purge_refuses_while_running_and_deletes_nothing(root, monkeypatch):
    report = root / "reports" / "r.csv"
    report.write_text("x")
    monkeypatch.setattr(service, "get_service_active_state", lambda name: "active")

    with pytest.raises(ValidationError) as exc:
        purge()

    assert exc.value.status_code == 409
    assert report.exists()


@pytest.mark.asyncio
async def test_purge_waits_for_start_lock_and_rechecks(root):
    report = root / "reports" / "r.csv"
    report.write_text("x")

    await cli._profiler_lock.acquire()
    task = asyncio.create_task(service.purge_data())
    await asyncio.sleep(0)  # let the purge run up to the lock
    assert not task.done()
    # A Core start spawns its child while holding the lock.
    cli.profiler_process = RunningProcess()
    cli._profiler_lock.release()

    with pytest.raises(ValidationError) as exc:
        await task

    assert exc.value.status_code == 409
    assert report.exists()


@pytest.mark.parametrize(
    "start, blocking_call",
    [
        (system_service.start_systemd_service, "start_service"),
        (system_service.restart_systemd_service, "restart_service"),
    ],
)
@pytest.mark.parametrize("unit", ["wlanpi-profiler", "wlanpi-profiler.service"])
@pytest.mark.asyncio
async def test_profiler_unit_start_waits_for_purge(
    root, monkeypatch, start, blocking_call, unit
):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def blocking_delete():
        entered.set()
        if not release.wait(timeout=5):
            raise AssertionError("purge was never released")
        return {"files": 0, "bytes": 0}

    lock = ObservedLock()
    monkeypatch.setattr(cli, "_profiler_lock", lock)
    monkeypatch.setattr(service, "_delete_contents", blocking_delete)
    monkeypatch.setattr(system_service, blocking_call, calls.append)

    purge_task = asyncio.create_task(service.purge_data())
    start_task = None
    try:
        assert await asyncio.to_thread(entered.wait, 5), "purge never started"
        start_task = asyncio.create_task(start(unit))
        await asyncio.wait_for(lock.contended.wait(), timeout=5)
        assert not start_task.done()
        assert calls == []
    finally:
        release.set()
        await purge_task
    await start_task

    assert calls == [unit]


@pytest.mark.parametrize(
    "start, blocking_call",
    [
        (system_service.start_systemd_service, "start_service"),
        (system_service.restart_systemd_service, "restart_service"),
    ],
)
@pytest.mark.asyncio
async def test_other_unit_start_ignores_profiler_lock(
    root, monkeypatch, start, blocking_call
):
    calls = []
    lock = ObservedLock()
    monkeypatch.setattr(cli, "_profiler_lock", lock)
    monkeypatch.setattr(system_service, blocking_call, calls.append)

    await lock.acquire()
    try:
        await asyncio.wait_for(start("iperf"), timeout=5)
    finally:
        lock.release()

    assert calls == ["iperf"]
    assert not lock.contended.is_set()


@pytest.mark.parametrize(
    "state, expected",
    [
        ("active", True),
        ("activating", True),
        ("deactivating", True),
        ("reloading", True),
        ("inactive", False),
        ("failed", False),
    ],
)
def test_profiler_active_checks_systemd_state(root, monkeypatch, state, expected):
    seen = []

    def active_state(name):
        seen.append(name)
        return state

    monkeypatch.setattr(service, "get_service_active_state", active_state)

    assert service.profiler_active() is expected
    assert seen == ["wlanpi-profiler"]


@pytest.mark.parametrize(
    "process, expected", [(RunningProcess(), True), (ExitedProcess(), False)]
)
def test_profiler_active_checks_cores_own_process(root, monkeypatch, process, expected):
    monkeypatch.setattr(cli, "profiler_process", process)

    assert service.profiler_active() is expected


@pytest.mark.parametrize(
    "content, expected",
    [
        (json.dumps({"state": "running", "pid": os.getpid()}), True),
        (json.dumps({"state": "starting", "pid": os.getpid()}), True),
        (json.dumps({"state": "starting"}), False),  # missing pid
        (json.dumps({"state": "running", "pid": str(os.getpid())}), False),
        (json.dumps({"state": "running", "pid": True}), False),
        (json.dumps({"state": "running", "pid": 0}), False),
        (json.dumps({"state": "running", "pid": 2**22 + 1}), False),  # pid gone
        (json.dumps({"state": "failed", "pid": os.getpid()}), False),
        (json.dumps(["running"]), False),
        ('{"state": "running", ', False),  # malformed
    ],
)
def test_profiler_active_checks_status_file(root, content, expected):
    with open(cli.STATUS_FILE, "w") as f:
        f.write(content)

    assert service.profiler_active() is expected


def test_profiler_active_ignores_unreadable_status_file(root):
    os.mkdir(cli.STATUS_FILE)  # open() fails with an OSError

    assert service.profiler_active() is False


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
    monkeypatch.setattr(service, "get_service_active_state", lambda name: "activating")

    response = client.post("/api/v1/profiler/purge")

    assert response.status_code == 409
    assert "stop it" in response.text
    assert (root / "reports" / "r.csv").exists()


def test_purge_endpoint_500_on_os_error(client, root, monkeypatch):
    async def fail():
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
