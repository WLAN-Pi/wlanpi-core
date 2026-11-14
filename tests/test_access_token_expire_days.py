import pytest

from wlanpi_core.core.config import MAX_ACCESS_TOKEN_EXPIRE_DAYS, Settings


def test_default_is_seven_days(monkeypatch):
    monkeypatch.delenv("ACCESS_TOKEN_EXPIRE_DAYS", raising=False)

    assert Settings().ACCESS_TOKEN_EXPIRE_DAYS == 7


@pytest.mark.parametrize(
    "value, expected",
    [
        ("1", 1),
        ("30", 30),
        (" 30 ", 30),
        (str(MAX_ACCESS_TOKEN_EXPIRE_DAYS), MAX_ACCESS_TOKEN_EXPIRE_DAYS),
    ],
)
def test_environment_value_in_range_is_used(monkeypatch, value, expected):
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_DAYS", value)

    assert Settings().ACCESS_TOKEN_EXPIRE_DAYS == expected


@pytest.mark.parametrize(
    "value",
    [
        "abc",
        "",
        "7.5",
        "0",
        "-1",
        str(MAX_ACCESS_TOKEN_EXPIRE_DAYS + 1),
        "9" * 5000,
    ],
)
def test_invalid_environment_value_falls_back_to_default(monkeypatch, caplog, value):
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_DAYS", value)

    assert Settings().ACCESS_TOKEN_EXPIRE_DAYS == 7
    assert "Invalid ACCESS_TOKEN_EXPIRE_DAYS" in caplog.text


def test_value_that_is_not_text_or_integer_falls_back_to_default():
    assert Settings(ACCESS_TOKEN_EXPIRE_DAYS=7.5).ACCESS_TOKEN_EXPIRE_DAYS == 7
