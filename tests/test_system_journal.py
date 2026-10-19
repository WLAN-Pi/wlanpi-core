"""Tests for the /system/journal storage read and switch."""

from types import SimpleNamespace

import pytest

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.services import system_service

MAIN = "# /etc/systemd/journald.conf\n[Journal]\n#Storage=auto\n#SystemMaxUse=\n"
OURS = (
    "\n# /etc/systemd/journald.conf.d/90-wlanpi-journal.conf\n"
    "[Journal]\nStorage=persistent\n"
)
OVERRIDE = (
    "\n# /etc/systemd/journald.conf.d/99-local.conf\n[Journal]\nStorage = volatile\n"
)
USAGE = "Archived and active journals take up 24.0M in the file system.\n"

RESTART = ["systemctl", "restart", "systemd-journald"]
FLUSH = ["journalctl", "--flush"]
CAT_CONFIG = ["systemd-analyze", "--no-pager", "cat-config", "systemd/journald.conf"]
DISK_USAGE = ["journalctl", "--disk-usage"]


class _Result:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


@pytest.fixture
def journald(monkeypatch, tmp_path):
    """Redirect the drop-in to tmp_path and fake the journald commands.

    cat-config echoes the drop-in as written, followed by `state.later`.
    """
    conf = tmp_path / "journald.conf.d" / "90-wlanpi-journal.conf"
    state = SimpleNamespace(conf=conf, calls=[], later="")

    def _run(cmd, **_kwargs):
        state.calls.append(cmd)
        if cmd == RESTART:
            assert conf.exists(), "journald restarted before the drop-in was written"
        if cmd == CAT_CONFIG:
            return _Result(f"{MAIN}\n# {conf}\n{conf.read_text()}{state.later}")
        if cmd == DISK_USAGE:
            return _Result(USAGE)
        return _Result("")

    monkeypatch.setattr(system_service, "JOURNAL_CONF_FILE", conf)
    monkeypatch.setattr(system_service, "run_command", _run)
    return state


def test_parse_storage_later_drop_in_overrides_ours():
    assert system_service._parse_journal_storage(MAIN + OURS + OVERRIDE) == (
        "volatile",
        "/etc/systemd/journald.conf.d/99-local.conf",
    )


def test_parse_storage_reports_ours_when_last():
    assert system_service._parse_journal_storage(MAIN + OURS) == (
        "persistent",
        "/etc/systemd/journald.conf.d/90-wlanpi-journal.conf",
    )


def test_parse_storage_defaults_to_auto():
    assert system_service._parse_journal_storage(MAIN) == ("auto", None)


def test_parse_storage_ignores_comments_that_start_with_a_path():
    # Debian's stock journald.conf has this comment line.
    main = (
        "# /etc/systemd/journald.conf\n"
        '# /etc/ if the original file is shipped in /usr/), or by creating "drop-ins" in\n'
        "[Journal]\nStorage=volatile\n"
    )
    assert system_service._parse_journal_storage(main) == (
        "volatile",
        "/etc/systemd/journald.conf",
    )


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (USAGE, 24 * 1024**2),
        ("Archived and active journals take up 1.5G in the file system.", 1610612736),
        ("Archived and active journals take up 512B in the file system.", 512),
        ("No journal files were found.", None),
    ],
)
def test_parse_disk_usage(output, expected):
    assert system_service._parse_journal_disk_usage(output) == expected


def test_get_journal_disk_usage_null_when_journalctl_fails(monkeypatch):
    def _run(cmd, **_kwargs):
        if cmd == DISK_USAGE:
            raise FileNotFoundError(cmd[0])
        return _Result(MAIN + OURS)

    monkeypatch.setattr(system_service, "run_command", _run)

    assert system_service.get_journal()["disk_usage_bytes"] is None


def test_get_journal_503_when_cat_config_fails(monkeypatch):
    def _run(cmd, **_kwargs):
        raise RunCommandError("boom", 1)

    monkeypatch.setattr(system_service, "run_command", _run)

    with pytest.raises(ValidationError) as exc:
        system_service.get_journal()
    assert exc.value.status_code == 503


@pytest.mark.parametrize(
    ("storage", "contents", "commands"),
    [
        (
            "persistent",
            "[Journal]\nStorage=persistent\nSystemMaxUse=256M\nRuntimeMaxUse=50M\n",
            [RESTART, FLUSH, CAT_CONFIG, DISK_USAGE],
        ),
        (
            "volatile",
            "[Journal]\nStorage=volatile\nRuntimeMaxUse=50M\n",
            [RESTART, CAT_CONFIG, DISK_USAGE],
        ),
    ],
)
def test_set_journal_storage_writes_and_restarts(journald, storage, contents, commands):
    result = system_service.set_journal_storage(storage)

    assert journald.conf.read_text() == contents
    assert journald.conf.stat().st_mode & 0o777 == 0o644
    assert journald.calls == commands
    assert result == {
        "storage": storage,
        "source": str(journald.conf),
        "disk_usage_bytes": 24 * 1024**2,
    }


def test_set_journal_storage_409_names_overriding_file(journald):
    journald.later = OVERRIDE

    with pytest.raises(ValidationError) as exc:
        system_service.set_journal_storage("persistent")

    assert exc.value.status_code == 409
    assert "/etc/systemd/journald.conf.d/99-local.conf" in exc.value.error_msg
    assert "Storage=persistent" in journald.conf.read_text()
