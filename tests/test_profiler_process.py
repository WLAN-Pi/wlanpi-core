import asyncio
import json
import os
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from wlanpi_core.api.api_v1.endpoints import profiler_api
from wlanpi_core.asgi import app
from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.profiler import cli
from wlanpi_core.profiler.models import Start


class ProfilerProcess:
    """Fake child; wait() blocks until exit() is called, like a real process."""

    pid = 4242

    def __init__(self):
        self.returncode = None
        self._exited = asyncio.Event()

    def exit(self, code):
        self.returncode = code
        self._exited.set()

    async def wait(self):
        await self._exited.wait()
        return self.returncode


@pytest.fixture(autouse=True)
def reset_profiler_state(tmp_path, monkeypatch):
    cli.profiler_process = None
    cli._profiler_lock = asyncio.Lock()
    monkeypatch.setattr(cli, "STATUS_FILE", str(tmp_path / "status.json"))
    monkeypatch.setattr(cli, "LAST_SESSION_FILE", str(tmp_path / "last.json"))
    monkeypatch.setattr(cli, "_PROFILER_START_POLL_SEC", 0.01)
    yield
    cli.profiler_process = None


def write_json(path, data, mtime=None):
    with open(path, "w") as f:
        json.dump(data, f)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def spawn(mocker, process, on_spawn=None):
    """Patch process creation; on_spawn runs as the child would at startup."""

    async def create(*args, **kwargs):
        if on_spawn:
            on_spawn()
        return process

    return mocker.patch.object(
        cli.asyncio, "create_subprocess_exec", new=AsyncMock(side_effect=create)
    )


@pytest.mark.asyncio
async def test_start_profiler_waits_for_running_and_isolates_process(mocker):
    process = ProfilerProcess()
    create_process = spawn(
        mocker,
        process,
        lambda: write_json(cli.STATUS_FILE, {"state": "running", "pid": process.pid}),
    )

    result = await cli.start_profiler(Start(interface="wlanpi0", debug=True))

    assert result == {"success": True}
    create_process.assert_awaited_once_with(
        "profiler", "-i", "wlanpi0", "--debug", start_new_session=True
    )
    assert cli.profiler_process is process


@pytest.mark.asyncio
async def test_start_profiler_reports_exit_reason_from_last_session(mocker):
    process = ProfilerProcess()

    def fail():
        write_json(
            cli.LAST_SESSION_FILE,
            {"exit": {"reason": "interface_validation", "message": "no wlan9"}},
        )
        process.exit(1)

    spawn(mocker, process, fail)

    result = await cli.start_profiler(Start(interface="wlan9"))

    assert result == {
        "success": False,
        "reason": "interface_validation",
        "message": "no wlan9",
    }


@pytest.mark.asyncio
async def test_start_profiler_ignores_files_from_an_earlier_run(mocker):
    # A future mtime proves freshness is not judged by the clock.
    future = 4_000_000_000
    write_json(cli.STATUS_FILE, {"state": "running", "pid": 1}, mtime=future)
    write_json(cli.LAST_SESSION_FILE, {"exit": {"reason": "stale"}}, mtime=future)
    process = ProfilerProcess()
    spawn(mocker, process, lambda: process.exit(2))

    result = await cli.start_profiler(Start())

    assert result["success"] is False
    assert result["reason"] == "exited"
    assert "code 2" in result["message"]


@pytest.mark.asyncio
async def test_start_profiler_tolerates_malformed_exit_metadata(mocker):
    process = ProfilerProcess()

    def fail():
        write_json(cli.LAST_SESSION_FILE, {"exit": "invalid"})
        process.exit(3)

    spawn(mocker, process, fail)

    result = await cli.start_profiler(Start())

    assert result["reason"] == "exited"
    assert "code 3" in result["message"]


@pytest.mark.asyncio
async def test_stop_during_startup_wait_ends_the_start(mocker):
    process = ProfilerProcess()
    spawned = asyncio.Event()
    spawn(mocker, process, spawned.set)

    async def terminate(target, grace):
        target.exit(-15)

    mocker.patch.object(cli, "terminate_process_async", side_effect=terminate)

    start = asyncio.create_task(cli.start_profiler(Start()))
    await spawned.wait()
    assert await cli.stop_profiler() is True
    result = await asyncio.wait_for(start, timeout=5)

    assert result["success"] is False
    assert result["reason"] == "exited"
    assert cli.profiler_process is None


@pytest.mark.asyncio
async def test_start_profiler_reports_starting_when_wait_runs_out(mocker):
    mocker.patch.object(cli, "_PROFILER_START_WAIT_SEC", 0)
    spawn(mocker, ProfilerProcess())

    result = await cli.start_profiler(Start())

    assert result["success"] is True
    assert result["reason"] == "starting"


@pytest.mark.asyncio
async def test_start_profiler_reports_spawn_failure(mocker):
    mocker.patch.object(
        cli.asyncio,
        "create_subprocess_exec",
        new=AsyncMock(side_effect=FileNotFoundError("profiler")),
    )

    result = await cli.start_profiler(Start())

    assert result["success"] is False
    assert result["reason"] == "spawn_failed"
    assert cli.profiler_process is None


@pytest.mark.asyncio
async def test_start_profiler_rejects_duplicate_process(mocker):
    cli.profiler_process = ProfilerProcess()
    create_process = mocker.patch.object(
        cli.asyncio,
        "create_subprocess_exec",
        new=AsyncMock(),
    )

    result = await cli.start_profiler(Start())

    assert result["success"] is False
    assert result["reason"] == "already_running"
    create_process.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_profiler_terminates_and_reaps_process(mocker):
    process = ProfilerProcess()
    cli.profiler_process = process

    async def terminate(target, grace):
        assert target is process
        process.exit(-15)

    terminate_process = mocker.patch.object(
        cli,
        "terminate_process_async",
        side_effect=terminate,
    )

    assert await cli.stop_profiler() is True

    terminate_process.assert_awaited_once_with(process, grace=10.0)
    assert cli.profiler_process is None


@pytest.mark.asyncio
async def test_stop_profiler_endpoint_matches_response_model(mocker):
    mocker.patch.object(
        profiler_api.cli,
        "stop_profiler",
        new=AsyncMock(return_value=True),
    )

    assert await profiler_api.stop_profiler() == {"success": True}


@pytest.mark.parametrize(
    "values",
    [
        {"channel": 0},
        {"channel": 234},
        {"frequency": 3000},
        {"frequency": 99999},
        {"interface": "--help"},
        {"ssid": "bad\nssid"},
        {"ssid": "💻" * 9},
        {"unexpected": True},
    ],
)
def test_profiler_start_rejects_unsafe_launch_arguments(values):
    with pytest.raises(ValidationError):
        Start(**values)


@pytest.mark.parametrize("frequency", [2400, 2500, 4900, 7125])
def test_profiler_start_accepts_supported_frequency_band_boundaries(frequency):
    assert Start(frequency=frequency).frequency == frequency


@pytest.fixture
def client():
    async def _allow():
        return True

    app.dependency_overrides[verify_auth_wrapper] = _allow
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(verify_auth_wrapper, None)


@pytest.mark.parametrize(
    "result, body",
    [
        ({"success": True}, {"success": True}),
        (
            {"success": False, "reason": "interface_validation", "message": "no"},
            {"success": False, "reason": "interface_validation", "message": "no"},
        ),
    ],
)
def test_start_endpoint_response_shape(client, mocker, result, body):
    mocker.patch.object(
        profiler_api.cli, "start_profiler", new=AsyncMock(return_value=result)
    )

    response = client.post("/api/v1/profiler/start", json={})

    assert response.status_code == 200
    assert response.json() == body
