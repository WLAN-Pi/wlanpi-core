"""Parametrized tests driven by tests/scenarios/namespace_test_matrix.csv.

See tests/scenarios/ACTIVATION_OUTCOMES.md for activate_config persist vs rollback paths.
"""

import pytest

from tests.scenarios.loader import Scenario, load_scenarios
from tests.test_namespace_matrix.handlers import HANDLERS, run_scenario

pytestmark = pytest.mark.usefixtures("no_real_run_command")

# Rows that replicate open bugs. strict=True, so the fix must delete its entry.
KNOWN_BUGS = {
    "default_created_when_missing": "#202: default config is hardcoded phy0/phy1",
    "default_single_radio_no_500": "#202: default has wlan1 and WPA2 without psk",
    "create_profile_snapshots_mac": "#237: add_config does not snapshot the MAC",
}


def _scenario_id(scenario: Scenario) -> str:
    return f"{scenario.scope}:{scenario.name}"


def _params() -> list:
    params = []
    for scenario in load_scenarios():
        marks = []
        if scenario.name in KNOWN_BUGS:
            marks.append(
                pytest.mark.xfail(strict=True, reason=KNOWN_BUGS[scenario.name])
            )
        params.append(pytest.param(scenario, marks=marks, id=_scenario_id(scenario)))
    return params


@pytest.mark.parametrize("scenario", _params())
def test_namespace_matrix_scenario(scenario, namespace_service, netcfg_env):
    """Execute one matrix row; handler name must exist in HANDLERS."""
    assert scenario.name in HANDLERS, f"Missing handler for {scenario.name}"
    run_scenario(scenario, namespace_service, netcfg_env)


def test_matrix_covers_all_unique_rows():
    scenarios = load_scenarios()
    assert scenarios, "Namespace matrix must not be empty"
    identifiers = [(scenario.scope, scenario.name) for scenario in scenarios]
    assert len(identifiers) == len(set(identifiers)), "Duplicate namespace matrix rows"

    names = [scenario.name for scenario in scenarios]
    assert len(names) == len(set(names)), "Duplicate namespace scenario names"
    missing = [s.name for s in scenarios if s.name not in HANDLERS]
    assert not missing, f"Handlers missing for: {missing}"


def test_known_bugs_name_real_rows():
    names = {s.name for s in load_scenarios()}
    orphan = [name for name in KNOWN_BUGS if name not in names]
    assert not orphan, f"KNOWN_BUGS entries without matrix rows: {orphan}"
