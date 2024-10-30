from io import StringIO
from unittest.mock import patch

import pytest

from wlanpi_core.utils.general import CommandResult, RunCommandError, run_command


def test_run_command_success():
    # Test a successful command execution
    result = run_command(["echo", "test"])
    assert result.stdout == "test\n"
    assert result.stderr == ""
    assert result.return_code == 0


def test_run_command_failure():
    # Test a failing command execution with raise_on_fail=True
    with pytest.raises(RunCommandError) as context:
        run_command(["ls", "nonexistent_file"])
    assert "No such file or directory" in str(context.value)


def test_run_command_failure_no_raise():
    # Test a failing command execution with raise_on_fail=False
    result = run_command(["false"], raise_on_fail=False)
    assert result.return_code == 1


def test_run_command_input():
    # Test providing input to the command
    result = run_command(["cat"], input="test input")
    assert result.stdout == "test input"


@patch("subprocess.run")
def test_run_command_stdin(mock_run):
    # Test providing stdin to the command
    mock_run.return_value.stdout = "test input"
    mock_run.return_value.stderr = ""
    mock_run.return_value.return_code = 0
    result = run_command(["cat"], stdin=StringIO("test input"))
    assert result.stdout == "test input"


def test_run_command_input_and_stdin_error():
    # Test raising an error when both input and stdin are provided
    with pytest.raises(RunCommandError) as context:
        run_command(["echo"], input="test", stdin=StringIO("test"))
    assert "You cannot use both 'input' and 'stdin'" in str(context.value)


def test_run_command_shell_warning(caplog):
    # Test the warning message when using shell=True
    with caplog.at_level("WARNING"):
        run_command("echo test", shell=True)
    assert "Command echo test being run as a shell script" in caplog.text


def test_command_result():
    # Test the CommandResult class
    result = CommandResult("output", "error", 0)
    assert result.stdout == "output"
    assert result.stderr == "error"
    assert result.return_code == 0
