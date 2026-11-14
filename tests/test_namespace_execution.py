import logging
from unittest.mock import patch

import pytest

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec

_LOGGER = "wlanpi_core.utils.namespace_execution"


def _run(result, caplog, **kwargs):
    with (
        patch(f"{_LOGGER}.run_command", return_value=result),
        caplog.at_level(logging.DEBUG, logger=_LOGGER),
    ):
        ns_exec(["iw", "dev"], **kwargs)
    return caplog.records


def test_ns_exec_writes_one_debug_record_per_command(caplog):
    records = _run(CommandResult("phy#0\n", "", 0), caplog, namespace="lab")

    assert [r.levelno for r in records] == [logging.DEBUG]
    message = records[0].getMessage()
    assert "namespace 'lab'" in message
    assert "sudo ip netns exec lab iw dev" in message
    assert "return_code=0" in message
    assert "stdout: phy#0\n" in message
    assert "stderr" not in message


def test_ns_exec_record_holds_stderr_when_not_empty(caplog):
    records = _run(
        CommandResult("", "no such device\n", 237), caplog, raise_on_fail=False
    )

    assert len(records) == 1
    message = records[0].getMessage()
    assert "namespace 'root'" in message
    assert "return_code=237" in message
    assert "stderr: no such device\n" in message


def test_ns_exec_no_output_leaves_stdout_and_stderr_out(caplog):
    records = _run(CommandResult("secret\n", "noise\n", 0), caplog, no_output=True)

    assert len(records) == 1
    message = records[0].getMessage()
    assert "sudo iw dev" in message
    assert "return_code=0" in message
    assert "secret" not in message
    assert "noise" not in message


def test_ns_exec_failure_writes_only_the_error_record(caplog):
    with (
        patch(f"{_LOGGER}.run_command", side_effect=RunCommandError("boom", 1)),
        caplog.at_level(logging.DEBUG, logger=_LOGGER),
        pytest.raises(RunCommandError),
    ):
        ns_exec(["iw", "dev"])

    assert [r.levelno for r in caplog.records] == [logging.ERROR]
