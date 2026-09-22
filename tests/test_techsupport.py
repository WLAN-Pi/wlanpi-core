from unittest.mock import Mock

from wlanpi_core.cli import techsupport


def test_techsupport_file_report(mocker, tmp_path):
    run = mocker.patch.object(
        techsupport.subprocess,
        "run",
        return_value=Mock(stdout="ok\n"),
    )
    out = tmp_path / "report.txt"

    rc = techsupport.main(["--file", str(out), "--no-color"])

    assert rc == 0
    text = out.read_text()
    assert "1. OS and Kernel Information" in text
    assert "10. Recent wlanpi-core logs" in text
    assert run.call_count > 0
    assert all(
        call.kwargs.get("timeout") == techsupport.COMMAND_TIMEOUT_SEC
        for call in run.call_args_list
    )
