import asyncio
from io import StringIO
from unittest.mock import AsyncMock, patch

import pytest

from wlanpi_core.utils.general import RunCommandError, run_command_async


class MockProcess:
    def __init__(self, returncode=0, stdout="success", stderr=""):
        self.returncode = returncode
        self.stdout = stdout.encode() if isinstance(stdout, str) else stdout
        self.stderr = stderr.encode() if isinstance(stderr, str) else stderr

    async def communicate(self, input=None):
        return self.stdout, self.stderr


class HangingProcess(MockProcess):
    def __init__(self):
        super().__init__()
        self.returncode = None
        self.killed = False
        self._finished = asyncio.Event()

    async def communicate(self, input=None):
        await self._finished.wait()
        return self.stdout, self.stderr

    def kill(self):
        self.killed = True
        self.returncode = -9
        self._finished.set()

    async def wait(self):
        await self._finished.wait()
        return self.returncode


@pytest.mark.asyncio
async def test_run_command_async_success():
    cmd = ["ls", "-l"]
    with patch(
        "asyncio.subprocess.create_subprocess_exec",
        new=AsyncMock(return_value=MockProcess()),
    ) as mock_create_subprocess_exec:
        result = await run_command_async(cmd)
        mock_create_subprocess_exec.assert_called_once_with(
            cmd[0],
            *cmd[1:],
            stdin=None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    assert result.stdout == "success"
    assert result.stderr == ""
    assert result.return_code == 0


@pytest.mark.asyncio
async def test_run_command_async_success_with_input():
    cmd = ["cat"]
    test_input = "test input"
    with patch(
        "asyncio.subprocess.create_subprocess_exec",
        new=AsyncMock(return_value=MockProcess(stdout=test_input)),
    ) as mock_create_subprocess_exec:
        result = await run_command_async(cmd, input=test_input)
        mock_create_subprocess_exec.assert_called_once_with(
            cmd[0],
            *cmd[1:],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    assert result.stdout == test_input
    assert result.stderr == ""
    assert result.return_code == 0


@pytest.mark.asyncio
async def test_run_command_async_success_with_stdin():
    cmd = ["cat"]
    test_input = "test input"
    stdin = StringIO(test_input)
    with patch(
        "asyncio.subprocess.create_subprocess_exec",
        new=AsyncMock(return_value=MockProcess(stdout=test_input)),
    ) as mock_create_subprocess_exec:
        result = await run_command_async(cmd, stdin=stdin)
        mock_create_subprocess_exec.assert_called_once_with(
            cmd[0],
            *cmd[1:],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    assert result.stdout == test_input
    assert result.stderr == ""
    assert result.return_code == 0


@pytest.mark.asyncio
async def test_run_command_async_failure():
    cmd = ["ls", "-z"]
    with patch(
        "asyncio.subprocess.create_subprocess_exec",
        new=AsyncMock(return_value=MockProcess(returncode=2, stderr="error")),
    ) as mock_create_subprocess_exec:
        with pytest.raises(RunCommandError) as exc_info:
            await run_command_async(cmd)
    mock_create_subprocess_exec.assert_called_once_with(
        cmd[0],
        *cmd[1:],
        stdin=None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert "error" in str(exc_info.value)
    assert exc_info.value.return_code == 2


@pytest.mark.asyncio
async def test_run_command_async_failure_no_raise():
    cmd = ["ls", "-z"]
    with patch(
        "asyncio.subprocess.create_subprocess_exec",
        new=AsyncMock(return_value=MockProcess(returncode=2, stderr="error")),
    ) as mock_create_subprocess_exec:
        result = await run_command_async(cmd, raise_on_fail=False)
        mock_create_subprocess_exec.assert_called_once_with(
            cmd[0],
            *cmd[1:],
            stdin=None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    assert result.stderr == "error"
    assert result.return_code == 2


@pytest.mark.asyncio
async def test_run_command_async_shell_success():
    cmd = "ls -l"
    with patch(
        "asyncio.subprocess.create_subprocess_shell",
        new=AsyncMock(return_value=MockProcess()),
    ) as mock_create_subprocess_shell:
        result = await run_command_async(cmd, shell=True)
        mock_create_subprocess_shell.assert_called_once_with(
            cmd,
            stdin=None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    assert result.stdout == "success"
    assert result.stderr == ""
    assert result.return_code == 0


@pytest.mark.asyncio
async def test_run_command_async_shell_failure():
    cmd = "ls -z"
    with patch(
        "asyncio.subprocess.create_subprocess_shell",
        new=AsyncMock(return_value=MockProcess(returncode=2, stderr="error")),
    ) as mock_create_subprocess_shell:
        with pytest.raises(RunCommandError) as exc_info:
            await run_command_async(cmd, shell=True)
    mock_create_subprocess_shell.assert_called_once_with(
        cmd, stdin=None, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    assert "error" in str(exc_info.value)
    assert exc_info.value.return_code == 2


@pytest.mark.asyncio
async def test_run_command_async_input_and_stdin_error():
    cmd = ["ls", "-l"]
    with pytest.raises(RunCommandError) as exc_info:
        await run_command_async(cmd, input="test input", stdin=StringIO("test input"))
    assert "You cannot use both 'input' and 'stdin' on the same call." in str(
        exc_info.value
    )
    assert exc_info.value.return_code == -1


@pytest.mark.asyncio
async def test_run_command_async_input_and_stdin_pipe_ok():
    cmd = ["ls", "-l"]
    with patch(
        "asyncio.subprocess.create_subprocess_exec",
        new=AsyncMock(return_value=MockProcess()),
    ) as mock_create_subprocess_exec:
        result = await run_command_async(
            cmd, input="test input", stdin=asyncio.subprocess.PIPE
        )
        mock_create_subprocess_exec.assert_called_once_with(
            cmd[0],
            *cmd[1:],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    assert result.stdout == "success"
    assert result.stderr == ""
    assert result.return_code == 0


@pytest.mark.asyncio
async def test_run_command_async_timeout_kills_process():
    process = HangingProcess()
    with patch(
        "asyncio.subprocess.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        with pytest.raises(asyncio.TimeoutError):
            await run_command_async(["slow-command"], timeout=0.01)

    assert process.killed is True
    assert process.returncode == -9


@pytest.mark.asyncio
async def test_run_command_async_cancellation_kills_process():
    process = HangingProcess()
    with patch(
        "asyncio.subprocess.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        task = asyncio.create_task(run_command_async(["slow-command"]))
        await asyncio.sleep(0)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    assert process.killed is True
    assert process.returncode == -9
