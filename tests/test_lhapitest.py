"""lhapitest signs requests exactly the way verify_hmac checks them."""

import hashlib
import hmac
import importlib.util
import io
import sys
import urllib.error
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "install" / "usr" / "bin" / "lhapitest"
_spec = importlib.util.spec_from_loader(
    "lhapitest", SourceFileLoader("lhapitest", str(SCRIPT))
)
assert _spec is not None and _spec.loader is not None
lhapitest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lhapitest)

# NUL and trailing newline: the bytes the old bash version could not carry.
SECRET = b"\x38\x11\x00\x67\n" * 6 + b"\x00\n"


def _run(argv, secret_path, urlopen):
    with (
        patch.object(sys, "argv", ["lhapitest", "-s", str(secret_path), *argv]),
        patch.object(lhapitest.urllib.request, "urlopen", urlopen),
        patch.object(lhapitest.ssl, "create_default_context", return_value=None),
        patch.object(sys, "stderr", io.StringIO()),
    ):
        return lhapitest.main()


def test_post_signature_uses_raw_secret_bytes_and_canonical_query(tmp_path):
    secret_path = tmp_path / "secret.bin"
    secret_path.write_bytes(SECRET)
    seen = {}

    class Resp:
        status = 200

        def read(self):
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(req, context=None):
        seen["req"] = req
        return Resp()

    body = '{"device_id": "t"}'
    rc = _run(
        ["-X", "POST", "-e", "/auth/token", "-q", "a=1,2&a=x y&b=", "-P", body],
        secret_path,
        urlopen,
    )

    assert rc == 0
    req = seen["req"]
    # Server side: urlencode(request.query_params), last value per key wins.
    canonical = f"POST\n/api/v1/auth/token\na=x+y&b=\n{body}".encode()
    expected = hmac.new(SECRET, canonical, hashlib.sha256).hexdigest()
    assert req.get_header("X-request-signature") == expected
    assert req.full_url == "https://127.0.0.1:31415/api/v1/auth/token?a=x+y&b="
    assert req.data == body.encode()
    assert req.get_method() == "POST"


@pytest.mark.parametrize(
    ("exc", "rc"),
    [
        (urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b'{"d":1}')), 2),
        (urllib.error.URLError(ConnectionRefusedError(111, "refused")), 1),
    ],
)
def test_exit_codes(tmp_path, exc, rc):
    secret_path = tmp_path / "secret.bin"
    secret_path.write_bytes(SECRET)

    def urlopen(req, context=None):
        raise exc

    assert _run(["-e", "/x"], secret_path, urlopen) == rc


def test_unreadable_secret_returns_1(tmp_path):
    assert _run(["-e", "/x"], tmp_path / "missing.bin", None) == 1
