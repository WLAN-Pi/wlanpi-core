"""Tests for install/etc/wlanpi-core/scripts/wlanpi-generate-certs.sh (core#175)."""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HELPER = REPO_ROOT / "install/etc/wlanpi-core/scripts/wlanpi-generate-certs.sh"


def _run(tmp_path, env_extra=None):
    nginx_dir = tmp_path / "nginx"
    env = {
        **os.environ,
        "NGINX_SSL_DIR": str(nginx_dir),
        "COCKPIT_CERTS_DIR": str(tmp_path / "cockpit"),
        "WLANPI_ETH0_MAC": "aa:bb:cc:dd:ee:12",
    }
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [str(HELPER)], env=env, capture_output=True, text=True, check=False
    )
    return proc, nginx_dir


def _san(cert_path):
    proc = subprocess.run(
        ["openssl", "x509", "-in", str(cert_path), "-noout", "-text"],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


def test_generates_cert_with_renamed_local_hostname(tmp_path):
    proc, nginx_dir = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    cert = nginx_dir / "self-signed-wlanpi.cert"
    key = nginx_dir / "self-signed-wlanpi.key"
    assert cert.exists() and key.exists()
    san = _san(cert)
    assert "DNS:wlanpi-e12.local" in san
    assert "DNS:localhost" in san
    assert "DNS:wlanpi.local" in san
    assert "IP Address:127.0.0.1" in san
    assert (nginx_dir / "self-signed-grafana.cert").exists()
    assert (tmp_path / "cockpit" / "0-self-signed-wlanpi.cert").exists()


def test_second_run_is_noop(tmp_path):
    _, nginx_dir = _run(tmp_path)
    cert = nginx_dir / "self-signed-wlanpi.cert"
    mtime_before = cert.stat().st_mtime_ns
    proc, _ = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert cert.stat().st_mtime_ns == mtime_before


def test_regenerates_when_renamed_local_san_missing(tmp_path):
    # Simulate a certificate from before #175: no wlanpi-###.local SAN.
    nginx_dir = tmp_path / "nginx"
    nginx_dir.mkdir()
    key = nginx_dir / "self-signed-wlanpi.key"
    cert = nginx_dir / "self-signed-wlanpi.cert"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
            "-days", "3650", "-nodes",
            "-keyout", str(key), "-out", str(cert),
            "-subj", "/CN=wlanpi.local",
            "-addext",
            "subjectAltName=DNS:localhost,DNS:wlanpi.local,"
            "IP:127.0.0.1,IP:198.18.42.1",
        ],
        check=True,
    )
    mtime_before = cert.stat().st_mtime_ns
    proc, _ = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "DNS:wlanpi-e12.local" in _san(cert)
    assert cert.stat().st_mtime_ns != mtime_before