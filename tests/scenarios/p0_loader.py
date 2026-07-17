"""Load P0 API test scenarios from p0_api_test_matrix.csv.

Outcome semantics: tests/scenarios/P0_API_OUTCOMES.md
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

MATRIX_PATH = Path(__file__).resolve().parent / "p0_api_test_matrix.csv"


@dataclass(frozen=True)
class ApiScenario:
    scope: str
    name: str
    description: str
    purpose: str
    precondition: str
    hardware_adapters: str
    request: str
    expected_http: str
    expected_response: str
    entry_point: str
    test_type: str
    assertion_detail: str
    ci_stubs: str
    runs_real: str


def load_api_scenarios(path: Path | None = None) -> list[ApiScenario]:
    path = path or MATRIX_PATH
    scenarios: list[ApiScenario] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            scenarios.append(
                ApiScenario(
                    scope=row["Test scope"].strip(),
                    name=row["API test name"].strip(),
                    description=row["Description"].strip(),
                    purpose=row["Purpose"].strip(),
                    precondition=row["Precondition"].strip(),
                    hardware_adapters=row["Hardware adapters (monitor/managed)"].strip(),
                    request=row["Request"].strip(),
                    expected_http=row["Expected HTTP"].strip(),
                    expected_response=row["Expected response"].strip(),
                    entry_point=row["Entry point"].strip(),
                    test_type=row["Test type"].strip(),
                    assertion_detail=row["Assertion detail"].strip(),
                    ci_stubs=row["CI stubs (mock/patch targets)"].strip(),
                    runs_real=row["Runs real (no mock)"].strip(),
                )
            )
    return scenarios


def api_scenarios_by_scope(scope: str) -> list[ApiScenario]:
    return [s for s in load_api_scenarios() if s.scope == scope]
