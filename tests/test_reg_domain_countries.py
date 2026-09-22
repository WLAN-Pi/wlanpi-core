"""Tests for regulatory.db-backed country discovery."""

from wlanpi_core.data import reg_domain_countries


def _regdb(*codes: str) -> bytes:
    records = b"".join(code.encode("ascii") + b"\x00\x20" for code in codes)
    return b"RGDB\x00\x00\x00\x14" + records + b"\x00\x00\x00\x00" + (b"\x00" * 64)


def test_country_data_uses_active_wireless_regdb(tmp_path, monkeypatch):
    database = tmp_path / "regulatory.db"
    database.write_bytes(_regdb("00", "AU", "GB", "US"))
    names = tmp_path / "iso3166.tab"
    names.write_text(
        "# code\tname\nAU\tAustralia\nGB\tUnited Kingdom\nUS\tUnited States\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(reg_domain_countries, "REGULATORY_DB_FILE", database)
    monkeypatch.setattr(reg_domain_countries, "ISO3166_TABLE_FILE", names)
    reg_domain_countries._country_data.cache_clear()

    try:
        assert reg_domain_countries.reg_domain_country_entries() == [
            {"code": "AU", "name": "Australia"},
            {"code": "GB", "name": "United Kingdom"},
            {"code": "US", "name": "United States"},
        ]
        assert reg_domain_countries.is_supported_reg_domain("au") is True
        assert reg_domain_countries.is_supported_reg_domain("ZZ") is False
    finally:
        reg_domain_countries._country_data.cache_clear()


def test_country_data_falls_back_when_regdb_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        reg_domain_countries,
        "REGULATORY_DB_FILE",
        tmp_path / "missing-regulatory.db",
    )
    monkeypatch.setattr(
        reg_domain_countries,
        "ISO3166_TABLE_FILE",
        tmp_path / "missing-iso3166.tab",
    )
    reg_domain_countries._country_data.cache_clear()

    try:
        codes = reg_domain_countries.reg_domain_country_codes()
        assert len(codes) > 100
        assert {"AU", "GB", "JP", "US"}.issubset(codes)
        assert "00" not in codes
    finally:
        reg_domain_countries._country_data.cache_clear()
