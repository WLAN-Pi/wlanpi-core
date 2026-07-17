"""Country codes supported by the appliance's Linux wireless regulatory DB."""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

REGULATORY_DB_FILE = Path("/usr/lib/firmware/regulatory.db")
ISO3166_TABLE_FILE = Path("/usr/share/zoneinfo/iso3166.tab")
_REGDB_MAGIC = b"RGDB"
_REGDB_HEADER_SIZE = 8
_REGDB_COUNTRY_RECORD_SIZE = 4
_COUNTRY_CODE_RE = re.compile(rb"(?:00|[A-Z]{2})")

# Keep the endpoint useful in development environments without wireless-regdb.
# Production WLAN Pi images use the active regulatory.db file above, so package
# updates can add or remove domains without a wlanpi-core release.
_FALLBACK_REG_DOMAIN_CODES = tuple(
    "AD AE AF AI AL AM AN AR AS AT AU AW AZ BA BB BD BE BF BG BH BL BM BN BO "
    "BR BS BT BW BY BZ CA CF CH CI CL CN CO CR CU CX CY CZ DE DK DM DO DZ EC "
    "EE EG ES ET FI FM FR GB GD GE GF GH GL GP GR GT GU GY HK HN HR HT HU ID "
    "IE IL IN IR IS IT JM JO JP KE KH KN KP KR KW KY KZ LB LC LI LK LS LT LU "
    "LV MA MC MD ME MF MH MK MN MO MP MQ MR MT MU MV MW MX MY NA NG NI NL NO "
    "NP NZ OM PA PE PF PG PH PK PL PM PR PT PW PY QA RE RO RS RU RW SA SE SG "
    "SI SK SN SR SV SX SY TC TD TG TH TN TR TT TW TZ UA UG US UY UZ VC VE VI "
    "VN VU WF WS YE YT ZA ZW".split()
)

_COUNTRY_NAME_OVERRIDES = {
    "AN": "Netherlands Antilles",
    "BR": "Brazil",
    "CA": "Canada",
    "CZ": "Czech Republic",
    "DE": "Germany",
    "FR": "France",
    "GB": "United Kingdom",
    "NL": "Netherlands",
    "NO": "Norway",
    "US": "United States",
}


def _read_regdb_country_codes(path: Path) -> tuple[str, ...]:
    """Read alpha-2 records from the Linux regulatory.db country table."""
    data = path.read_bytes()
    if len(data) < _REGDB_HEADER_SIZE + _REGDB_COUNTRY_RECORD_SIZE:
        raise ValueError("wireless regulatory database is truncated")
    if data[:4] != _REGDB_MAGIC:
        raise ValueError("wireless regulatory database has an invalid header")

    codes: list[str] = []
    for offset in range(
        _REGDB_HEADER_SIZE,
        len(data) - _REGDB_COUNTRY_RECORD_SIZE + 1,
        _REGDB_COUNTRY_RECORD_SIZE,
    ):
        raw_code = data[offset : offset + 2]
        if not _COUNTRY_CODE_RE.fullmatch(raw_code):
            break

        rules_offset = int.from_bytes(data[offset + 2 : offset + 4], "big")
        if rules_offset >= len(data):
            raise ValueError("wireless regulatory database has an invalid rule offset")

        if raw_code != b"00":
            codes.append(raw_code.decode("ascii"))

    if not codes:
        raise ValueError("wireless regulatory database has no country records")
    return tuple(sorted(set(codes)))


def _read_country_names(path: Path) -> dict[str, str]:
    """Read English alpha-2 display names from tzdata's ISO 3166 table."""
    names: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        code, separator, name = line.partition("\t")
        if separator and re.fullmatch(r"[A-Z]{2}", code) and name:
            names[code] = name
    return names


@lru_cache(maxsize=1)
def _country_data() -> tuple[tuple[str, str], ...]:
    try:
        codes = _read_regdb_country_codes(REGULATORY_DB_FILE)
    except (OSError, ValueError) as exc:
        log.warning(
            "Unable to read %s; using bundled regulatory-domain fallback: %s",
            REGULATORY_DB_FILE,
            exc,
        )
        codes = _FALLBACK_REG_DOMAIN_CODES

    try:
        names = _read_country_names(ISO3166_TABLE_FILE)
    except OSError as exc:
        log.warning(
            "Unable to read ISO country names from %s: %s",
            ISO3166_TABLE_FILE,
            exc,
        )
        names = {}

    return tuple(
        (code, _COUNTRY_NAME_OVERRIDES.get(code) or names.get(code) or code)
        for code in codes
    )


def reg_domain_country_codes() -> list[str]:
    return [code for code, _ in _country_data()]


def reg_domain_country_entries() -> list[dict[str, str]]:
    return [{"code": code, "name": name} for code, name in _country_data()]


def is_supported_reg_domain(code: str) -> bool:
    normalized = code.strip().upper()
    return any(entry_code == normalized for entry_code, _ in _country_data())
