import asyncio
from io import StringIO
import asyncio
import unittest
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch
from wlanpi_core.utils.general import run_command_async, CommandResult, RunCommandError

class MockProcess:
    def __init__(self, returncode=0, stdout="success", stderr=""):
        self.returncode = returncode
        self.stdout = stdout.encode() if isinstance(stdout, str) else stdout
        self.stderr = stderr.encode() if isinstance(stderr, str) else stderr

    async def communicate(self, input=None):
        return self.stdout, self.stderr

class TestRunCommandAsync(IsolatedAsyncioTestCase):

    async def test_run_command_async_success(self):
        cmd = ["ls", "-l"]
        with  patch('asyncio.subprocess.create_subprocess_exec', new=AsyncMock(return_value=MockProcess())) as mock_create_subprocess_exec:
            result = await run_command_async(cmd)
            mock_create_subprocess_exec.assert_called_once_with(
                cmd[0], *cmd[1:], stdin=None, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            self.assertEqual(result.stdout, "success")
            self.assertEqual(result.stderr, "")
            self.assertEqual(result.return_code, 0)

    async def test_run_command_async_success_with_input(self):
        cmd = ["cat"]
        test_input = "test input"
        with patch('asyncio.subprocess.create_subprocess_exec', new=AsyncMock(return_value=MockProcess(stdout=test_input))) as mock_create_subprocess_exec:
            result = await run_command_async(cmd, input=test_input)
            mock_create_subprocess_exec.assert_called_once_with(
                cmd[0], *cmd[1:], stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            self.assertEqual(result.stdout, test_input)
            self.assertEqual(result.stderr, "")
            self.assertEqual(result.return_code, 0)

    async def test_run_command_async_success_with_stdin(self):
        cmd = ["cat"]
        test_input = "test input"
        stdin = StringIO(test_input)
        with patch('asyncio.subprocess.create_subprocess_exec', new=AsyncMock(return_value=MockProcess(stdout=test_input))) as mock_create_subprocess_exec:
            result = await run_command_async(cmd, stdin=stdin)
            mock_create_subprocess_exec.assert_called_once_with(
                cmd[0], *cmd[1:], stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            self.assertEqual(result.stdout, test_input)
            self.assertEqual(result.stderr, "")
            self.assertEqual(result.return_code, 0)

    async def test_run_command_async_failure(self):
        cmd = ["ls", "-z"]
        with patch('asyncio.subprocess.create_subprocess_exec', new=AsyncMock(return_value=MockProcess(returncode=2, stderr="error"))) as mock_create_subprocess_exec:
            with self.assertRaises(RunCommandError) as context:
                await run_command_async(cmd)
            mock_create_subprocess_exec.assert_called_once_with(
                cmd[0], *cmd[1:], stdin=None, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            self.assertEqual(str(context.exception), "error")
            self.assertEqual(context.exception.status_code, 2)

    async def test_run_command_async_failure_no_raise(self):
        cmd = ["ls", "-z"]
        with patch('asyncio.subprocess.create_subprocess_exec', new=AsyncMock(return_value=MockProcess(returncode=2, stderr="error"))) as mock_create_subprocess_exec:
            result = await run_command_async(cmd, raise_on_fail=False)
            mock_create_subprocess_exec.assert_called_once_with(
                cmd[0], *cmd[1:], stdin=None, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            self.assertEqual(result.stderr, "error")
            self.assertEqual(result.return_code, 2)

    async def test_run_command_async_shell_success(self):
        cmd = "ls -l"
        with patch('asyncio.subprocess.create_subprocess_shell', new=AsyncMock(return_value=MockProcess())) as mock_create_subprocess_shell:
            result = await run_command_async(cmd, shell=True)
            mock_create_subprocess_shell.assert_called_once_with(
                cmd, stdin=None, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            self.assertEqual(result.stdout, "success")
            self.assertEqual(result.stderr, "")
            self.assertEqual(result.return_code, 0)

    async def test_run_command_async_shell_failure(self):
        cmd = "ls -z"
        with patch('asyncio.subprocess.create_subprocess_shell', new=AsyncMock(return_value=MockProcess(returncode=2, stderr="error"))) as mock_create_subprocess_shell:
            with self.assertRaises(RunCommandError) as context:
                await run_command_async(cmd, shell=True)
            mock_create_subprocess_shell.assert_called_once_with(
                cmd, stdin=None, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            self.assertEqual(str(context.exception), "error")
            self.assertEqual(context.exception.status_code, 2)

    async def test_run_command_async_input_and_stdin_error(self):
        cmd = ["ls", "-l"]
        with self.assertRaises(RunCommandError) as context:
            await run_command_async(cmd, input="test input", stdin=StringIO("test input"))
        self.assertEqual(str(context.exception), "You cannot use both 'input' and 'stdin' on the same call.")
        self.assertEqual(context.exception.status_code, -1)

    async def test_run_command_async_input_and_stdin_pipe_ok(self):
        cmd = ["ls", "-l"]
        with patch('asyncio.subprocess.create_subprocess_exec', new=AsyncMock(return_value=MockProcess())) as mock_create_subprocess_exec:
            result = await run_command_async(cmd, input="test input", stdin=asyncio.subprocess.PIPE)
            mock_create_subprocess_exec.assert_called_once_with(
                cmd[0], *cmd[1:], stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            self.assertEqual(result.stdout, "success")
            self.assertEqual(result.stderr, "")
            self.assertEqual(result.return_code, 0)

if __name__ == '__main__':
    unittest.main()
