import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from wlanpi_core.api.api_v1.endpoints import profiler_api
from wlanpi_core.profiler import cli
from wlanpi_core.profiler.models import Start


class ProfilerProcess:
    def __init__(self):
        self.returncode = None

    async def wait(self):
        return self.returncode


@pytest.fixture(autouse=True)
def reset_profiler_state():
    cli.profiler_process = None
    cli._profiler_lock = asyncio.Lock()
    yield
    cli.profiler_process = None


@pytest.mark.asyncio
async def test_start_profiler_discards_output_and_isolates_process(mocker):
    process = ProfilerProcess()
    create_process = mocker.patch.object(
        cli.asyncio,
        "create_subprocess_exec",
        new=AsyncMock(return_value=process),
    )

    assert await cli.start_profiler(Start(interface="wlanpi0", debug=True)) is True

    create_process.assert_awaited_once_with(
        "profiler",
        "-i",
        "wlanpi0",
        "--debug",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    assert cli.profiler_process is process


@pytest.mark.asyncio
async def test_start_profiler_rejects_duplicate_process(mocker):
    cli.profiler_process = ProfilerProcess()
    create_process = mocker.patch.object(
        cli.asyncio,
        "create_subprocess_exec",
        new=AsyncMock(),
    )

    assert await cli.start_profiler(Start()) is False
    create_process.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_profiler_terminates_and_reaps_process(mocker):
    process = ProfilerProcess()
    cli.profiler_process = process

    async def terminate(target):
        assert target is process
        process.returncode = -15

    terminate_process = mocker.patch.object(
        cli,
        "terminate_process_async",
        side_effect=terminate,
    )

    assert await cli.stop_profiler() is True

    terminate_process.assert_awaited_once_with(process)
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
