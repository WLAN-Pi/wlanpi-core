"""Parametrized tests driven by tests/scenarios/p0_api_test_matrix.csv.

Handlers are added incrementally as P0 endpoints ship. Unimplemented rows are
skipped until a handler exists.

See tests/scenarios/P0_API_OUTCOMES.md for outcome semantics.
"""

import pytest

from tests.scenarios.p0_loader import ApiScenario, load_api_scenarios
from tests.test_p0_api_matrix.handlers import HANDLERS, run_api_scenario

pytestmark = pytest.mark.usefixtures("no_real_run_command")

# Rows that replicate open bugs. strict=True, so the fix must delete its entry.
KNOWN_BUGS = {
    "network_config_activate_stale_phy_mismatch": "#236: prepare trusts cfg.phy over the live phy",
    "network_config_activate_default_single_radio": "#202: default has wlan1 and WPA2 without psk",
    "network_config_create_snapshots_mac": "#237: add_config does not snapshot the MAC",
}


def _scenario_id(scenario: ApiScenario) -> str:
    return f"{scenario.scope}:{scenario.name}"


def _params() -> list:
    params = []
    for scenario in load_api_scenarios():
        marks = []
        if scenario.name in KNOWN_BUGS:
            marks.append(
                pytest.mark.xfail(strict=True, reason=KNOWN_BUGS[scenario.name])
            )
        params.append(pytest.param(scenario, marks=marks, id=_scenario_id(scenario)))
    return params


@pytest.mark.parametrize("scenario", _params())
def test_p0_api_matrix_scenario(scenario, client, auth_headers, netcfg_env):
    """Execute one matrix row when a handler is registered."""
    if scenario.name not in HANDLERS:
        pytest.skip(f"Handler not yet implemented for {scenario.name}")
    run_api_scenario(scenario, client, auth_headers, netcfg_env)


def test_p0_matrix_has_unique_scenarios():
    scenarios = load_api_scenarios()
    assert scenarios, "P0 API matrix must not be empty"
    identifiers = [(scenario.scope, scenario.name) for scenario in scenarios]
    assert len(identifiers) == len(set(identifiers)), "Duplicate P0 API matrix rows"

    # HANDLERS is keyed by name, so names must also remain globally unique even
    # when the matrix grows to cover additional scopes.
    names = [scenario.name for scenario in scenarios]
    assert len(names) == len(set(names)), "Duplicate P0 API scenario names"


def test_p0_matrix_handler_registry_documents_gaps():
    """All implemented handlers must map to real matrix names."""
    scenarios = load_api_scenarios()
    names = {s.name for s in scenarios}
    orphan = [k for k in HANDLERS if k not in names]
    assert not orphan, f"Handlers without matrix rows: {orphan}"


def test_known_bugs_name_real_rows():
    names = {s.name for s in load_api_scenarios()}
    orphan = [name for name in KNOWN_BUGS if name not in names]
    assert not orphan, f"KNOWN_BUGS entries without matrix rows: {orphan}"
