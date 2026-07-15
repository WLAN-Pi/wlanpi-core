import os
from types import SimpleNamespace

import pytest

from wlanpi_core.services import network_info_service


def _trusted_stat(path):
    actual = os.stat(path)
    return SimpleNamespace(
        st_mode=actual.st_mode,
        st_uid=0,
        st_nlink=actual.st_nlink,
        st_size=actual.st_size,
    )


def test_neighbour_reader_rejects_symlink(tmp_path):
    target = tmp_path / "secret"
    target.write_text("not for the API\n")
    link = tmp_path / "lldpneigh.txt"
    link.symlink_to(target)

    with pytest.raises(OSError):
        network_info_service._read_neighbour_file(str(link))


@pytest.mark.parametrize(
    ("stat_change", "message"),
    [
        ({"st_uid": 1000}, "non-root-owned"),
        ({"st_mode": 0o100666}, "writable"),
        ({"st_nlink": 2}, "multiply-linked"),
        (
            {"st_size": network_info_service._NEIGHBOUR_FILE_MAX_BYTES + 1},
            "too large",
        ),
    ],
)
def test_neighbour_reader_rejects_untrusted_metadata(
    tmp_path, monkeypatch, stat_change, message
):
    neighbour_file = tmp_path / "lldpneigh.txt"
    neighbour_file.write_text("Name: switch\n")
    neighbour_file.chmod(0o644)
    trusted = vars(_trusted_stat(neighbour_file))
    trusted.update(stat_change)
    monkeypatch.setattr(
        network_info_service.os,
        "fstat",
        lambda _fd: SimpleNamespace(**trusted),
    )

    with pytest.raises(OSError, match=message):
        network_info_service._read_neighbour_file(str(neighbour_file))


def test_neighbour_reader_accepts_trusted_regular_file(tmp_path, monkeypatch):
    neighbour_file = tmp_path / "lldpneigh.txt"
    neighbour_file.write_text("Name: switch\nNative VLAN: 10\n")
    neighbour_file.chmod(0o644)
    monkeypatch.setattr(
        network_info_service.os,
        "fstat",
        lambda _fd: _trusted_stat(neighbour_file),
    )

    assert network_info_service._read_neighbour_file(str(neighbour_file)) == [
        "Name: switch",
        "Native VLAN: 10",
    ]


def test_show_vlan_falls_back_to_cdp(monkeypatch):
    reads = {
        network_info_service.LLDPNEIGH_FILE: ["Name: switch"],
        network_info_service.CDPNEIGH_FILE: ["Native VLAN: 20"],
    }
    monkeypatch.setattr(
        network_info_service,
        "_read_neighbour_file",
        reads.__getitem__,
    )

    assert network_info_service.show_vlan() == {"info": ["Native VLAN: 20"]}


def test_show_neighbour_reports_missing_file(monkeypatch):
    monkeypatch.setattr(
        network_info_service,
        "_read_neighbour_file",
        lambda _path: None,
    )

    assert network_info_service.show_lldp_neighbour() == {
        "info": [],
        "error": "No neighbour",
    }
