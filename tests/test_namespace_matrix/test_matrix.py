"""Parametrized tests driven by tests/scenarios/namespace_test_matrix.csv.

See tests/scenarios/ACTIVATION_OUTCOMES.md for activate_config persist vs rollback paths.
"""
import pytest

from tests.scenarios.loader import Scenario, load_scenarios
from tests.test_namespace_matrix.handlers import HANDLERS, run_scenario


def _scenario_id(scenario: Scenario) -> str:
    return f"{scenario.scope}:{scenario.name}"


@pytest.mark.parametrize(
    "scenario",
    load_scenarios(),
    ids=_scenario_id,
)
def test_namespace_matrix_scenario(scenario, namespace_service, netcfg_env):
    """Execute one matrix row; handler name must exist in HANDLERS."""
    assert scenario.name in HANDLERS, f"Missing handler for {scenario.name}"
    run_scenario(scenario, namespace_service, netcfg_env)


def test_matrix_covers_all_rows():
    scenarios = load_scenarios()
    assert len(scenarios) == 41
    missing = [s.name for s in scenarios if s.name not in HANDLERS]
    assert not missing, f"Handlers missing for: {missing}"
