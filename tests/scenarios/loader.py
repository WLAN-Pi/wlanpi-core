"""Load namespace test scenarios from the CSV matrix.

Outcome semantics for activate_config (persist vs rollback) are documented in
ACTIVATION_OUTCOMES.md in this directory.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

MATRIX_PATH = Path(__file__).resolve().parent / "namespace_test_matrix.csv"


@dataclass(frozen=True)
class Scenario:
    scope: str
    name: str
    description: str
    purpose: str
    file_condition: str
    adapter1_initial: str
    adapter2_initial: str
    adapter1_final: str
    adapter2_final: str
    autostart_app: str
    outcome: str
    user_response: str
    entry_point: str
    test_type: str
    assertion_detail: str
    ci_stubs: str
    stub_phases: str
    runs_real: str


def load_scenarios(path: Path | None = None) -> list[Scenario]:
    path = path or MATRIX_PATH
    scenarios: list[Scenario] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            scenarios.append(
                Scenario(
                    scope=row["Test scope"].strip(),
                    name=row["Namespaces Test Name"].strip(),
                    description=row["Description"].strip(),
                    purpose=row["Purpose"].strip(),
                    file_condition=row["Namespaces file condition"].strip(),
                    adapter1_initial=row["WLAN Adapter 1 Initial Condition"].strip(),
                    adapter2_initial=row["WLAN Adapter 2 Initial Condition"].strip(),
                    adapter1_final=row["WLAN Adapter 1 Final Condition"].strip(),
                    adapter2_final=row["WLAN Adapter 2 Final Condition"].strip(),
                    autostart_app=row["Autorun App availability"].strip(),
                    outcome=row["Outcome (success/fail)"].strip(),
                    user_response=row["User response"].strip(),
                    entry_point=row["Entry point"].strip(),
                    test_type=row["Test type"].strip(),
                    assertion_detail=row["Assertion detail"].strip(),
                    ci_stubs=row["CI stubs (mock/patch targets)"].strip(),
                    stub_phases=row["Stub phase sequence (time-ordered)"].strip(),
                    runs_real=row["Runs real (no mock)"].strip(),
                )
            )
    return scenarios


def scenarios_by_scope(scope: str) -> list[Scenario]:
    return [s for s in load_scenarios() if s.scope == scope]


def scenario_by_name(name: str) -> Scenario:
    for scenario in load_scenarios():
        if scenario.name == name:
            return scenario
    raise KeyError(name)
