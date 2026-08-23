"""Feature-flagged TLS front-ends (auth plan P3).

Pins: flags default off (merging changes nothing), TLS sites use the cert the
postinst generates, every server block forwards the true client address, the
API TLS site mirrors the HTTP site, UFW profiles match the listeners, and the
wlanpi-core-tls helper links/unlinks sites exactly per the flag file. When an
nginx binary is available the site files are also validated with `nginx -t`.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
NGINX_DIR = REPO / "install/etc/wlanpi-core/nginx"
HTTP_SITE = NGINX_DIR / "wlanpi_core.conf"
API_TLS_SITE = NGINX_DIR / "wlanpi_core_tls.conf"
MCP_TLS_SITE = NGINX_DIR / "wlanpi_mcp_tls.conf"
DEV_TLS_SITE = NGINX_DIR / "wlanpi_core_tls_dev.conf"
TLS_SITES = [API_TLS_SITE, MCP_TLS_SITE, DEV_TLS_SITE]
FLAG_FILE = REPO / "install/etc/wlanpi-core/tls.conf"
HELPER = REPO / "install/usr/bin/wlanpi-core-tls"
UFW_RULES = REPO / "install/etc/wlanpi-core/ufw/wlanpi-core.rules"
POSTINST = REPO / "debian/postinst"

CERT = "/etc/nginx/ssl/self-signed-wlanpi.cert"
KEY = "/etc/nginx/ssl/self-signed-wlanpi.key"
API_TLS_PORT = 31416
MCP_TLS_PORT = 8767
DEV_TLS_PORT = 8443


# --- Flags: off by default --------------------------------------------------


def test_tls_flags_default_off():
    text = FLAG_FILE.read_text()
    assert re.search(r"^WLANPI_CORE_TLS_API=0$", text, re.M)
    assert re.search(r"^WLANPI_CORE_TLS_MCP=0$", text, re.M)
    assert re.search(r"^WLANPI_CORE_TLS_DEV=0$", text, re.M)


def test_postinst_applies_flags_without_changing_defaults():
    text = POSTINST.read_text()
    assert "/usr/bin/wlanpi-core-tls apply" in text
    # postinst must never flip a flag itself.
    assert "wlanpi-core-tls enable" not in text


# --- Site files -------------------------------------------------------------


def _server_blocks(conf: str):
    blocks, depth, start = [], 0, None
    for i, ch in enumerate(conf):
        if ch == "{":
            if depth == 0 and conf[: i].rstrip().endswith("server"):
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                blocks.append(conf[start : i + 1])
                start = None
    assert depth == 0, "unbalanced braces"
    return blocks


@pytest.mark.parametrize("site", TLS_SITES, ids=lambda p: p.name)
def test_tls_sites_use_postinst_certificate(site):
    conf = site.read_text()
    assert f"ssl_certificate     {CERT};" in conf
    assert f"ssl_certificate_key {KEY};" in conf
    # The postinst generates exactly these files.
    postinst = POSTINST.read_text()
    assert CERT in postinst and KEY in postinst
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in conf


@pytest.mark.parametrize(
    "site, port",
    [
        (API_TLS_SITE, API_TLS_PORT),
        (MCP_TLS_SITE, MCP_TLS_PORT),
        (DEV_TLS_SITE, DEV_TLS_PORT),
    ],
    ids=["api", "mcp", "dev"],
)
def test_tls_sites_listen_on_their_own_tls_ports(site, port):
    conf = site.read_text()
    assert re.search(rf"^\s*listen {port} ssl;", conf, re.M)
    # Dual-stack window: the TLS site must not take over the plain listeners.
    assert "listen 31415" not in conf
    assert "listen 8766" not in conf
    assert "listen 8000" not in conf


@pytest.mark.parametrize("site", [HTTP_SITE, *TLS_SITES], ids=lambda p: p.name)
def test_every_server_block_forwards_true_client_address(site):
    for block in _server_blocks(site.read_text()):
        # $wlanpi_real_ip is the pre-#139 map variable still present on dev;
        # either way the TLS sites must never invent an identity of their own.
        assert re.search(
            r"proxy_set_header X-Real-IP \$(remote_addr|wlanpi_real_ip);", block
        ), f"{site.name}: server block does not set X-Real-IP from the client"
        assert "proxy_pass" in block


def test_tls_sites_do_not_add_auth_header_rewriting():
    for site in TLS_SITES:
        conf = site.read_text()
        assert not re.search(r"map\s+\$http_", conf)
        assert "192.0.2.1" not in conf
        assert "X-Real-IP $remote_addr;" in conf


def _location_block(conf: str) -> list:
    m = re.search(r"location / \{(.*?)\n    \}", conf, re.S)
    assert m, "location / block not found"
    lines = [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]
    return [
        re.sub(r"\$wlanpi_real_ip", "$remote_addr", ln)
        for ln in lines
        if not ln.startswith("#")
    ]


def test_api_tls_site_mirrors_http_site_proxy_block():
    """The HTTPS API listener must proxy exactly like the HTTP one (only the
    X-Real-IP source variable may differ until #139 lands on dev)."""
    assert _location_block(API_TLS_SITE.read_text()) == _location_block(
        HTTP_SITE.read_text()
    )


def test_dev_tls_site_mirrors_http_site_except_upstream():
    """The dev front-end must behave exactly like production TLS, differing
    only in where it proxies (the uvicorn dev server)."""

    def masked(conf):
        return [
            "proxy_pass <upstream>;" if ln.startswith("proxy_pass") else ln
            for ln in _location_block(conf)
        ]

    assert masked(DEV_TLS_SITE.read_text()) == masked(HTTP_SITE.read_text())
    assert "proxy_pass http://127.0.0.1:8000;" in DEV_TLS_SITE.read_text()


def test_mcp_tls_site_streams_to_loopback_mcp():
    conf = MCP_TLS_SITE.read_text()
    assert "proxy_pass http://127.0.0.1:8766;" in conf
    assert "proxy_buffering off;" in conf
    assert "proxy_http_version 1.1;" in conf
    assert re.search(r'proxy_set_header Connection "";', conf)
    assert "proxy_read_timeout 1h;" in conf


# --- UFW --------------------------------------------------------------------


def test_ufw_profiles_match_tls_listeners():
    rules = UFW_RULES.read_text()
    assert re.search(rf"\[wlanpi-core-tls\][^\[]*ports={API_TLS_PORT}/tcp", rules)
    assert re.search(rf"\[wlanpi-mcp-tls\][^\[]*ports={MCP_TLS_PORT}/tcp", rules)
    assert re.search(rf"\[wlanpi-core-tls-dev\][^\[]*ports={DEV_TLS_PORT}/tcp", rules)
    # The MCP cleartext port must not be opened by core.
    assert "8766" not in rules
    version = (REPO / "install/etc/wlanpi-core/ufw/current-rules-version").read_text()
    assert int(version.strip()) >= 2, "rules changed: version must be bumped"


# --- Helper behaviour (real script, temp paths, no system calls) ------------


@pytest.fixture
def tls_env(tmp_path):
    src = tmp_path / "src"
    enabled = tmp_path / "enabled"
    src.mkdir()
    enabled.mkdir()
    for site in TLS_SITES:
        shutil.copy(site, src / site.name)
    flag = tmp_path / "tls.conf"
    shutil.copy(FLAG_FILE, flag)
    env = {
        **os.environ,
        "WLANPI_TLS_FLAG_FILE": str(flag),
        "WLANPI_TLS_SITES_SRC": str(src),
        "WLANPI_TLS_SITES_ENABLED": str(enabled),
        "WLANPI_TLS_NO_SYSTEM": "1",
    }
    return env, flag, enabled


def _run(env, *args):
    return subprocess.run(
        ["bash", str(HELPER), *args], env=env, capture_output=True, text=True
    )


def test_helper_apply_with_defaults_links_nothing(tls_env):
    env, _flag, enabled = tls_env
    result = _run(env, "apply")
    assert result.returncode == 0, result.stderr
    assert list(enabled.iterdir()) == []
    for name in ("api", "mcp", "dev"):
        assert f"{name}  flag=0" in result.stdout


def test_helper_enable_and_disable_round_trip(tls_env):
    env, flag, enabled = tls_env

    assert _run(env, "enable", "api").returncode == 0
    assert (enabled / "wlanpi_core_tls.conf").is_symlink()
    assert not (enabled / "wlanpi_mcp_tls.conf").exists()
    assert re.search(r"^WLANPI_CORE_TLS_API=1$", flag.read_text(), re.M)

    assert _run(env, "enable", "mcp").returncode == 0
    assert (enabled / "wlanpi_mcp_tls.conf").is_symlink()

    assert _run(env, "enable", "dev").returncode == 0
    assert (enabled / "wlanpi_core_tls_dev.conf").is_symlink()

    assert _run(env, "disable", "api").returncode == 0
    assert not (enabled / "wlanpi_core_tls.conf").exists()
    assert (enabled / "wlanpi_mcp_tls.conf").is_symlink()
    assert (enabled / "wlanpi_core_tls_dev.conf").is_symlink()
    assert re.search(r"^WLANPI_CORE_TLS_API=0$", flag.read_text(), re.M)

    # The flag file stays the source of truth: apply reconciles stray links.
    (enabled / "wlanpi_core_tls.conf").symlink_to(flag)
    assert _run(env, "apply").returncode == 0
    assert not (enabled / "wlanpi_core_tls.conf").exists()


def test_helper_rejects_unknown_frontend_and_bad_usage(tls_env):
    env, _flag, _enabled = tls_env
    assert _run(env, "enable", "webui").returncode == 2
    assert _run(env).returncode == 2
    assert _run(env, "frobnicate").returncode == 2


def test_helper_treats_missing_or_malformed_flags_as_off(tls_env):
    env, flag, enabled = tls_env
    flag.write_text("WLANPI_CORE_TLS_API=maybe\n")  # MCP line absent entirely
    assert _run(env, "apply").returncode == 0
    assert list(enabled.iterdir()) == []


# --- nginx -t, when an nginx binary exists ---------------------------------


@pytest.mark.skipif(
    shutil.which("nginx") is None or shutil.which("openssl") is None,
    reason="nginx/openssl not available",
)
def test_site_files_pass_nginx_config_test(tmp_path):
    ssl = tmp_path / "ssl"
    ssl.mkdir()
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=test", "-keyout", str(ssl / "k.pem"), "-out", str(ssl / "c.pem"),
        ],
        check=True,
        capture_output=True,
    )
    sites = tmp_path / "sites"
    sites.mkdir()
    for site in [HTTP_SITE, *TLS_SITES]:
        text = (
            site.read_text()
            .replace(CERT, str(ssl / "c.pem"))
            .replace(KEY, str(ssl / "k.pem"))
            .replace("/var/log/wlanpi_core/", f"{tmp_path}/")
        )
        (sites / site.name).write_text(text)

    conf = tmp_path / "nginx.conf"
    conf.write_text(
        f"pid {tmp_path}/nginx.pid;\nerror_log {tmp_path}/error.log;\n"
        "events {}\n"
        f"http {{ include {sites}/*.conf; }}\n"
    )
    result = subprocess.run(
        ["nginx", "-t", "-c", str(conf), "-p", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
