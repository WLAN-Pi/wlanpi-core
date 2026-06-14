"""Parametrized tests driven by tests/scenarios/p0_api_test_matrix.csv.

Handlers are added incrementally as P0 endpoints ship. Unimplemented rows are
skipped until a handler exists.

See tests/scenarios/P0_API_OUTCOMES.md for outcome semantics.
"""
import pytest

from tests.scenarios.p0_loader import ApiScenario, load_api_scenarios

try:
    from tests.test_p0_api_matrix.handlers import HANDLERS, run_api_scenario
except ImportError:
    HANDLERS = {}
    run_api_scenario = None  # type: ignore


def _scenario_id(scenario: ApiScenario) -> str:
    return f"{scenario.scope}:{scenario.name}"


@pytest.mark.parametrize(
    "scenario",
    load_api_scenarios(),
    ids=_scenario_id,
)
def test_p0_api_matrix_scenario(scenario, client, auth_headers):
    """Execute one matrix row when a handler is registered."""
    if scenario.name not in HANDLERS:
        pytest.skip(f"Handler not yet implemented for {scenario.name}")
    run_api_scenario(scenario, client, auth_headers)


def test_p0_matrix_row_count():
    scenarios = load_api_scenarios()
    assert len(scenarios) == 40


def test_p0_matrix_handler_registry_documents_gaps():
    """All implemented handlers must map to real matrix names."""
    scenarios = load_api_scenarios()
    names = {s.name for s in scenarios}
    orphan = [k for k in HANDLERS if k not in names]
    assert not orphan, f"Handlers without matrix rows: {orphan}"
