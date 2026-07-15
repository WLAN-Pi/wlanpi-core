"""WLAN Pi supported Wi-Fi regulatory domain country codes.

Matches the fixed set exposed by legacy FPMS (sys.rf.* menu entries).
"""

from typing import Iterable

# (ISO 3166-1 alpha-2, English display name)
REG_DOMAIN_COUNTRIES: tuple[tuple[str, str], ...] = (
    ("US", "United States"),
    ("CA", "Canada"),
    ("GB", "United Kingdom"),
    ("BR", "Brazil"),
    ("FR", "France"),
    ("CZ", "Czech Republic"),
    ("NL", "Netherlands"),
    ("DE", "Germany"),
    ("NO", "Norway"),
)


def reg_domain_country_codes() -> list[str]:
    return [code for code, _ in REG_DOMAIN_COUNTRIES]


def reg_domain_country_entries() -> list[dict[str, str]]:
    return [{"code": code, "name": name} for code, name in REG_DOMAIN_COUNTRIES]


def is_supported_reg_domain(code: str) -> bool:
    normalized = code.strip().upper()
    return any(entry_code == normalized for entry_code, _ in REG_DOMAIN_COUNTRIES)
