import json
from unittest.mock import patch

import pytest

with patch("pathlib.Path.mkdir"):
    from wlanpi_core.utils import network_config


@pytest.fixture
def cfg_dir(tmp_path):
    with patch.object(network_config, "cfg_dir", tmp_path):
        yield tmp_path


def _assert_wlan0_only(path):
    data = json.loads(path.read_text())
    assert [r["interface"] for r in data["roots"]] == ["wlan0"]
    assert data["roots"][0]["security"] is None
    assert data["roots"][0]["default_route"] is True


def test_missing_default_is_created(cfg_dir):
    cfg = network_config.get_config("default")

    assert [r.interface for r in cfg.roots] == ["wlan0"]
    _assert_wlan0_only(cfg_dir / "default.json")
    assert not list(cfg_dir.glob(".*.tmp"))


@pytest.mark.parametrize("content", ["", "   \n", "{not json", '{"roots": 5}'])
def test_unusable_default_is_moved_aside_and_rebuilt(cfg_dir, content):
    (cfg_dir / "default.json").write_text(content)

    cfg = network_config.get_config("default")

    assert cfg.id == "default"
    _assert_wlan0_only(cfg_dir / "default.json")
    bad = list(cfg_dir.glob("default.json.bad-*"))
    assert len(bad) == 1 and bad[0].read_text() == content


def test_unusable_non_default_still_raises(cfg_dir):
    (cfg_dir / "lab.json").write_text("")

    with pytest.raises(network_config.ConfigMalformedError):
        network_config.get_config("lab")
    assert (cfg_dir / "lab.json").exists()
