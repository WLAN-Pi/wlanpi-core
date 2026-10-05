"""Tests for reading profiler output (GET /profiler/files and /profiler/files/{path})."""

import os

import pytest
from fastapi.testclient import TestClient

from wlanpi_core.asgi import app
from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.profiler import service

MAC = "a8-93-4a-e2-02-3b"


@pytest.fixture
def root(tmp_path, monkeypatch):
    """Build a data root with one client (two bands) and one report."""
    data = tmp_path / "profiler"
    client_dir = data / "clients" / MAC
    client_dir.mkdir(parents=True)
    (data / "reports").mkdir()
    (client_dir / f"{MAC}_5GHz.json").write_text('{"mac": "a8:93:4a:e2:02:3b"}')
    (client_dir / f"{MAC}_5GHz.txt").write_text("report\n")
    (client_dir / f"{MAC}_5GHz.pcap").write_bytes(b"\xd4\xc3\xb2\xa1")
    (client_dir / f"{MAC}_2.4GHz.json").write_text("{}")
    (data / "reports" / "profiler-2026-09-30.csv").write_text("Client_Mac\n")
    monkeypatch.setattr(service, "DATA_ROOT", str(data))
    return data


@pytest.fixture
def client():
    async def _allow():
        return True

    app.dependency_overrides[verify_auth_wrapper] = _allow
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(verify_auth_wrapper, None)


def test_list_files(client, root):
    response = client.get("/api/v1/profiler/files")

    assert response.status_code == 200
    body = response.json()
    (entry,) = body["clients"]
    assert entry["mac"] == "a8:93:4a:e2:02:3b"
    assert [f["path"] for f in entry["files"]] == [
        f"clients/{MAC}/{MAC}_2.4GHz.json",
        f"clients/{MAC}/{MAC}_5GHz.json",
        f"clients/{MAC}/{MAC}_5GHz.pcap",
        f"clients/{MAC}/{MAC}_5GHz.txt",
    ]
    assert entry["files"][2]["size"] == 4
    assert (
        entry["files"][2]["modified"].endswith("Z")
        or "+00:00" in entry["files"][2]["modified"]
    )
    assert [f["path"] for f in body["reports"]] == ["reports/profiler-2026-09-30.csv"]


def test_list_files_skips_symlinks_and_other_entries(client, root, tmp_path):
    outside = tmp_path / "outside"
    (outside / "x").mkdir(parents=True)
    (outside / "x" / "secret.json").write_text("{}")
    os.symlink(outside / "x", root / "clients" / "11-22-33-44-55-66")
    os.symlink(outside / "x" / "secret.json", root / "clients" / MAC / "link.json")
    os.mkfifo(root / "reports" / "fifo.csv")
    (root / "clients" / "stray.txt").write_text("not a client dir")
    (root / "clients" / "aa-aa-aa-aa-aa-aa").mkdir()

    body = client.get("/api/v1/profiler/files").json()

    assert [c["mac"] for c in body["clients"]] == ["a8:93:4a:e2:02:3b"]
    assert all("link" not in f["path"] for f in body["clients"][0]["files"])
    assert [f["path"] for f in body["reports"]] == ["reports/profiler-2026-09-30.csv"]


def test_list_files_symlinked_data_dirs_are_empty(client, tmp_path, monkeypatch):
    real = tmp_path / "real"
    (real / "clients" / MAC).mkdir(parents=True)
    (real / "clients" / MAC / "a.json").write_text("{}")
    (real / "reports").mkdir()
    (real / "reports" / "r.csv").write_text("x")
    data = tmp_path / "profiler"
    data.mkdir()
    os.symlink(real / "clients", data / "clients")
    os.symlink(real / "reports", data / "reports")
    monkeypatch.setattr(service, "DATA_ROOT", str(data))

    assert client.get("/api/v1/profiler/files").json() == {"clients": [], "reports": []}


def test_list_files_missing_data_root(client, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DATA_ROOT", str(tmp_path / "absent"))

    assert client.get("/api/v1/profiler/files").json() == {"clients": [], "reports": []}


@pytest.mark.parametrize("mac", ["A8:93:4A:E2:02:3B", "a8-93-4a-e2-02-3b"])
def test_list_files_mac_filter(client, root, mac):
    (root / "clients" / "11-22-33-44-55-66").mkdir()
    (root / "clients" / "11-22-33-44-55-66" / "x.json").write_text("{}")

    body = client.get("/api/v1/profiler/files", params={"mac": mac}).json()

    assert [c["mac"] for c in body["clients"]] == ["a8:93:4a:e2:02:3b"]
    assert len(body["reports"]) == 1


@pytest.mark.parametrize("mac", ["a8934ae2023b", "../../etc", "a8:93:4a:e2:02"])
def test_list_files_rejects_bad_mac(client, root, mac):
    assert client.get("/api/v1/profiler/files", params={"mac": mac}).status_code == 422


@pytest.mark.parametrize(
    ("path", "body", "media_type"),
    [
        (
            f"clients/{MAC}/{MAC}_5GHz.json",
            b'{"mac": "a8:93:4a:e2:02:3b"}',
            "application/json",
        ),
        (f"clients/{MAC}/{MAC}_5GHz.txt", b"report\n", "text/plain; charset=utf-8"),
        (
            f"clients/{MAC}/{MAC}_5GHz.pcap",
            b"\xd4\xc3\xb2\xa1",
            "application/vnd.tcpdump.pcap",
        ),
        ("reports/profiler-2026-09-30.csv", b"Client_Mac\n", "text/csv; charset=utf-8"),
    ],
)
def test_read_file(client, root, path, body, media_type):
    response = client.get(f"/api/v1/profiler/files/{path}")

    assert response.status_code == 200
    assert response.content == body
    assert response.headers["content-type"] == media_type


def test_read_file_unknown_extension_is_octet_stream(client, root):
    (root / "reports" / "notes").write_bytes(b"\x00\x01")

    response = client.get("/api/v1/profiler/files/reports/notes")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"


@pytest.mark.parametrize(
    "path",
    [
        "reports/absent.csv",
        f"clients/{MAC}",
        f"clients/{MAC}/",
        "clients",
        "reports",
        f"clients/{MAC}/{MAC}_5GHz.json/x",
        "reports/%2e%2e/%2e%2e/outside.txt",
        "reports/..%2f..%2foutside.txt",
        "reports//profiler-2026-09-30.csv",
        "other/file.txt",
        "outside.txt",
    ],
)
def test_read_file_rejects_paths_outside_layout(client, root, tmp_path, path):
    (tmp_path / "outside.txt").write_text("secret")
    (root / "outside.txt").write_text("not in clients/ or reports/")

    response = client.get(f"/api/v1/profiler/files/{path}")

    assert response.status_code == 404
    assert b"secret" not in response.content


@pytest.mark.parametrize(
    "path",
    [
        "reports/../outside.txt",
        "reports/../../outside.txt",
        f"clients/../clients/{MAC}/{MAC}_5GHz.json",
        f"clients/{MAC}/../{MAC}/{MAC}_5GHz.json",
        "/etc/passwd",
        "reports/./profiler-2026-09-30.csv",
        "./reports/profiler-2026-09-30.csv",
        "reports/profiler-2026-09-30.csv\0",
    ],
)
def test_read_file_rejects_dot_segments(root, tmp_path, path):
    # HTTP clients normalise literal dot segments before sending, so test the
    # service directly as well as through encoded paths above.
    (tmp_path / "outside.txt").write_text("secret")

    with pytest.raises(ValidationError) as excinfo:
        service.read_file(path)
    assert excinfo.value.status_code == 404


def test_read_file_rejects_symlinks(client, root, tmp_path):
    secret = tmp_path / "secret.json"
    secret.write_text("secret")
    os.symlink(secret, root / "reports" / "link.csv")
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "x.json").write_text("secret")
    os.symlink(tmp_path / "elsewhere", root / "clients" / "11-22-33-44-55-66")

    for path in ("reports/link.csv", "clients/11-22-33-44-55-66/x.json"):
        response = client.get(f"/api/v1/profiler/files/{path}")
        assert response.status_code == 404
        assert b"secret" not in response.content


def test_read_file_rejects_symlinked_reports_dir(client, tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    (real / "r.csv").write_text("secret")
    data = tmp_path / "profiler"
    data.mkdir()
    os.symlink(real, data / "reports")
    monkeypatch.setattr(service, "DATA_ROOT", str(data))

    assert client.get("/api/v1/profiler/files/reports/r.csv").status_code == 404


def test_read_file_follows_symlinked_data_root(client, root, tmp_path, monkeypatch):
    link = tmp_path / "profiler-link"
    os.symlink(root, link)
    monkeypatch.setattr(service, "DATA_ROOT", str(link))

    response = client.get("/api/v1/profiler/files/reports/profiler-2026-09-30.csv")

    assert response.status_code == 200


def test_read_file_opens_without_blocking_or_following(root, monkeypatch):
    # Fails fast where the FIFO test below would hang if O_NONBLOCK went away.
    real_open = os.open
    calls = []

    def recording_open(path, flags, *args, **kwargs):
        calls.append((path, flags))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)
    service.read_file("reports/profiler-2026-09-30.csv")
    monkeypatch.undo()

    assert [p for p, _ in calls] == [
        str(root),
        "reports",
        "profiler-2026-09-30.csv",
    ]
    assert calls[1][1] & os.O_NOFOLLOW
    assert calls[2][1] & os.O_NOFOLLOW
    assert calls[2][1] & os.O_NONBLOCK


def test_read_file_fifo_is_404_without_blocking(client, root):
    os.mkfifo(root / "reports" / "fifo.csv")

    assert client.get("/api/v1/profiler/files/reports/fifo.csv").status_code == 404


@pytest.mark.parametrize(
    ("path", "swapped"),
    [
        ("reports/profiler-2026-09-30.csv", "reports"),
        (f"clients/{MAC}/{MAC}_5GHz.json", f"clients/{MAC}"),
    ],
)
def test_read_file_refuses_dir_swapped_for_symlink_mid_open(
    root, tmp_path, monkeypatch, path, swapped
):
    # A directory replaced by a symlink after the path is validated, before
    # the file is opened, must not lead outside the data root.
    outside = tmp_path / "outside"
    outside.mkdir()
    for name in (f"{MAC}_5GHz.json", "profiler-2026-09-30.csv"):
        (outside / name).write_text("secret")
    real_open = os.open
    swapped_already = []

    def swapping_open(p, flags, *args, **kwargs):
        fd = real_open(p, flags, *args, **kwargs)
        if not swapped_already:
            swapped_already.append(True)
            os.rename(root / swapped, tmp_path / "moved")
            os.symlink(outside, root / swapped)
        return fd

    monkeypatch.setattr(os, "open", swapping_open)
    with pytest.raises(ValidationError) as excinfo:
        service.read_file(path)
    monkeypatch.undo()

    assert excinfo.value.status_code == 404


def test_read_file_nul_byte_is_404(client, root):
    assert client.get("/api/v1/profiler/files/reports/a%00.csv").status_code == 404


def test_list_files_skips_entry_removed_while_listing(root, monkeypatch):
    real_scandir = os.scandir

    class Vanished:
        name = "zz-gone.csv"

        def stat(self, follow_symlinks=True):
            raise FileNotFoundError

    class WithVanished:
        def __init__(self, it):
            self.it = it

        def __enter__(self):
            return [*self.it.__enter__(), Vanished()]

        def __exit__(self, *exc):
            return self.it.__exit__(*exc)

    monkeypatch.setattr(os, "scandir", lambda fd: WithVanished(real_scandir(fd)))
    body = service.list_files()
    monkeypatch.undo()

    assert [f["path"] for f in body["reports"]] == ["reports/profiler-2026-09-30.csv"]


def test_list_files_skips_names_that_are_not_utf8(client, root):
    with open(os.path.join(os.fsencode(root / "reports"), b"bad-\xff.csv"), "w") as f:
        f.write("x")

    response = client.get("/api/v1/profiler/files")

    assert response.status_code == 200
    assert [f["path"] for f in response.json()["reports"]] == [
        "reports/profiler-2026-09-30.csv"
    ]


def test_list_files_500_on_unexpected_error(client, root, monkeypatch):
    def fail(mac=None):
        raise PermissionError("denied")

    monkeypatch.setattr(service, "list_files", fail)

    assert client.get("/api/v1/profiler/files").status_code == 500


def test_read_file_500_on_unexpected_error(client, root, monkeypatch):
    def fail(path):
        raise PermissionError("denied")

    monkeypatch.setattr(service, "read_file", fail)

    assert client.get("/api/v1/profiler/files/reports/x.csv").status_code == 500


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/profiler/files",
        "/api/v1/profiler/files/reports/profiler-2026-09-30.csv",
    ],
)
def test_files_endpoints_require_auth(root, path):
    with TestClient(app) as test_client:
        assert test_client.get(path).status_code == 401
