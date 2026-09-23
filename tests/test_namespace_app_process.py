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
        json.dumps({"pid": 1234, "app_id": "orb", "app_command": "orb --serve"})
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
        json.dumps({"pid": 1234, "app_id": "orb", "app_command": "orb --serve"})
    )
    mocker.patch.object(apps, "terminate_process", side_effect=RuntimeError("failed"))

    assert apps.stop_app_in_namespace("test-ns", pid_dir=tmp_path) is False

    assert apps._owned_app_processes[1234] is owned
    assert pid_file.exists()


@pytest.mark.parametrize(
    ("cmdline", "killed"),
    [
        (b"orb\0--serve\0", True),
        (b"/usr/bin/python3\0/usr/bin/orb\0--serve\0", True),  # PATH + shebang
        (b"orb\0--other\0", False),  # same program, other arguments
        (b"/usr/sbin/sshd\0-D\0", False),  # PID reused after a reboot (#304)
        (b"", False),  # process gone
    ],
)
def test_root_stop_signals_only_the_recorded_command(mocker, tmp_path, cmdline, killed):
    (tmp_path / "root.pid").write_text(
        json.dumps({"pid": 4321, "app_id": "orb", "app_command": "orb --serve"})
    )
    real_read_bytes = apps.Path.read_bytes

    def read_bytes(path):
        if str(path) == "/proc/4321/cmdline":
            return cmdline
        return real_read_bytes(path)

    mocker.patch.object(apps.Path, "read_bytes", read_bytes)
    run = mocker.patch.object(apps, "run_command")

    assert apps.stop_app_in_namespace(None, pid_dir=tmp_path) is True
    assert run.called is killed
    assert not (tmp_path / "root.pid").exists()


def test_namespace_stop_signals_only_the_recorded_command(mocker, tmp_path):
    # #304 review: after a restart the pidfile PID may be reused inside the
    # namespace; neither it nor a process that merely contains "orb" is killed.
    (tmp_path / "ns_a.pid").write_text(
        json.dumps({"pid": 10, "app_id": "orb", "app_command": "orb --serve"})
    )
    cmdlines = {
        10: b"/usr/sbin/sshd\0-D\0",  # reused PID from the file
        11: b"/usr/bin/python3\0/usr/bin/orb\0--serve\0",  # Core's app
        12: b"orbital-tool\0--serve\0",  # substring only
    }
    real_read_bytes = apps.Path.read_bytes

    def read_bytes(path):
        name = str(path)
        if name.startswith("/proc/") and name.endswith("/cmdline"):
            return cmdlines.get(int(name.split("/")[2]), b"")
        return real_read_bytes(path)

    mocker.patch.object(apps.Path, "read_bytes", read_bytes)
    mocker.patch("wlanpi_core.namespaces.namespace.namespace_exists", return_value=True)
    mocker.patch.object(
        apps.processes, "get_processes_in_namespace", return_value=[10, 11, 12]
    )
    run = mocker.patch.object(apps, "run_command")
    run.return_value = MagicMock(return_code=0, stdout="ns_a\n")

    assert apps.stop_app_in_namespace("ns_a", pid_dir=tmp_path) is True
    kills = [c.args[0] for c in run.call_args_list if c.args[0][0] == "kill"]
    assert kills == [["kill", "11"]]


def test_stale_namespace_pidfile_is_dropped_without_signalling(mocker, tmp_path):
    (tmp_path / "ns_a.pid").write_text(
        json.dumps({"pid": 10, "app_id": "orb", "app_command": "orb --serve"})
    )
    mocker.patch.object(apps, "_is_recorded_app", return_value=False)
    mocker.patch("wlanpi_core.namespaces.namespace.namespace_exists", return_value=True)
    mocker.patch.object(apps.processes, "get_processes_in_namespace", return_value=[10])
    run = mocker.patch.object(apps, "run_command")
    run.return_value = MagicMock(return_code=0, stdout="ns_a\n")

    assert apps.stop_app_in_namespace("ns_a", pid_dir=tmp_path) is True
    assert not [c for c in run.call_args_list if c.args[0][0] == "kill"]
    assert not (tmp_path / "ns_a.pid").exists()


def test_start_is_not_blocked_by_a_reused_pid(mocker, tmp_path):
    (tmp_path / "root.pid").write_text(
        json.dumps({"pid": 10, "app_id": "orb", "app_command": "orb --serve"})
    )
    mocker.patch.object(apps.os, "kill")  # PID 10 is alive...
    mocker.patch.object(apps, "_is_recorded_app", return_value=False)  # ...not orb
    mocker.patch.object(apps, "get_app_command", return_value="orb --serve")
    process = MagicMock(pid=20)
    process.poll.return_value = None
    popen = mocker.patch.object(apps.subprocess, "Popen", return_value=process)
    mocker.patch.object(apps.time, "sleep")

    assert apps.start_app_in_namespace(None, "orb", pid_dir=tmp_path) is True
    popen.assert_called_once()
    assert json.loads((tmp_path / "root.pid").read_text())["pid"] == 20


def test_namespace_prefix_does_not_verify_a_pid_from_another_namespace(
    mocker, tmp_path
):
    # `ip netns identify` says ns_ab; the pidfile belongs to ns_a (#304 review).
    (tmp_path / "ns_a.pid").write_text(
        json.dumps({"pid": 10, "app_id": "orb", "app_command": "orb --serve"})
    )
    mocker.patch.object(apps, "_is_recorded_app", return_value=True)
    mocker.patch("wlanpi_core.namespaces.namespace.namespace_exists", return_value=True)
    mocker.patch.object(
        apps.processes,
        "get_processes_in_namespace",
        side_effect=apps.RunCommandError("enumeration failed", 1),
    )
    run = mocker.patch.object(apps, "run_command")
    run.return_value = MagicMock(return_code=0, stdout="ns_ab\n")

    assert apps.stop_app_in_namespace("ns_a", pid_dir=tmp_path) is False
    assert not [c for c in run.call_args_list if c.args[0][0] == "kill"]
