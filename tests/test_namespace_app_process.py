import json
from unittest.mock import MagicMock

import pytest

from wlanpi_core.namespaces import apps


@pytest.fixture(autouse=True)
def reset_owned_processes():
    apps._owned_app_processes.clear()
    yield
    apps._owned_app_processes.clear()


def test_start_app_isolates_and_tracks_process(mocker, tmp_path):
    process = MagicMock(pid=1234)
    process.poll.return_value = None
    popen = mocker.patch.object(apps.subprocess, "Popen", return_value=process)
    mocker.patch.object(apps, "get_app_command", return_value="orb --serve")
    mocker.patch.object(apps.time, "sleep")
    mocker.patch.object(apps, "_verify_app_in_namespace")

    assert apps.start_app_in_namespace("test-ns", "orb", pid_dir=tmp_path) is True

    popen.assert_called_once()
    assert popen.call_args.args[0] == [
        "ip",
        "netns",
        "exec",
        "test-ns",
        "orb",
        "--serve",
    ]
    assert popen.call_args.kwargs["start_new_session"] is True
    assert apps._owned_app_processes[1234].process is process
    assert json.loads((tmp_path / "test-ns.pid").read_text())["pid"] == 1234


def test_duplicate_start_does_not_orphan_first_process(mocker, tmp_path):
    process = MagicMock(pid=1234)
    process.poll.return_value = None
    apps._owned_app_processes[1234] = apps._OwnedAppProcess(
        process,
        "test-ns",
        "orb",
    )
    mocker.patch.object(apps, "get_app_command", return_value="orb --serve")
    popen = mocker.patch.object(apps.subprocess, "Popen")

    assert apps.start_app_in_namespace("test-ns", "orb", pid_dir=tmp_path) is False
    popen.assert_not_called()


def test_start_rejects_live_process_in_inherited_pid_file(mocker, tmp_path):
    (tmp_path / "test-ns.pid").write_text(json.dumps({"pid": 1234}))
    mocker.patch.object(apps, "get_app_command", return_value="orb --serve")
    mocker.patch.object(apps.os, "kill")
    popen = mocker.patch.object(apps.subprocess, "Popen")

    assert apps.start_app_in_namespace("test-ns", "orb", pid_dir=tmp_path) is False
    popen.assert_not_called()


def test_stop_owned_app_terminates_group_and_reaps(mocker, tmp_path):
    process = MagicMock(pid=1234)
    process.poll.return_value = None
    apps._owned_app_processes[1234] = apps._OwnedAppProcess(
        process,
        "test-ns",
        "orb",
    )
    pid_file = tmp_path / "test-ns.pid"
    pid_file.write_text(
        json.dumps(
            {"pid": 1234, "app_id": "orb", "app_command": "orb --serve"}
        )
    )
    terminate = mocker.patch.object(apps, "terminate_process")

    assert apps.stop_app_in_namespace("test-ns", pid_dir=tmp_path) is True

    terminate.assert_called_once_with(process)
    assert apps._owned_app_processes == {}
    assert not pid_file.exists()


def test_failed_owned_stop_preserves_tracking_for_retry(mocker, tmp_path):
    process = MagicMock(pid=1234)
    process.poll.return_value = None
    owned = apps._OwnedAppProcess(process, "test-ns", "orb")
    apps._owned_app_processes[1234] = owned
    pid_file = tmp_path / "test-ns.pid"
    pid_file.write_text(
        json.dumps(
            {"pid": 1234, "app_id": "orb", "app_command": "orb --serve"}
        )
    )
    mocker.patch.object(apps, "terminate_process", side_effect=RuntimeError("failed"))

    assert apps.stop_app_in_namespace("test-ns", pid_dir=tmp_path) is False

    assert apps._owned_app_processes[1234] is owned
    assert pid_file.exists()
