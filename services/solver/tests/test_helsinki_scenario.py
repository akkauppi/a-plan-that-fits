from __future__ import annotations

from services.solver.engine import FourPlantersSolver
from services.solver.models import SolveRequest
from services.solver.scenario import DEFAULT_BROWSER_PATH, DEFAULT_SOLVER_PATH, load_scenario


def test_frozen_helsinki_scenario_invariants_and_determinism() -> None:
    scenario = load_scenario(DEFAULT_SOLVER_PATH, DEFAULT_BROWSER_PATH)
    assert scenario.metadata["source"] == "OpenStreetMap via Overpass API"
    assert scenario.metadata["source_sha256"]
    assert scenario.metadata["snapshot_timestamp"].endswith("Z")
    assert scenario.metadata["license_url"] == "https://www.openstreetmap.org/copyright"
    assert scenario.browser_payload["buildings"]["features"]
    assert scenario.browser_payload["initial_through_route"]["geometry"]["coordinates"]

    request = SolveRequest(
        scenario_id=scenario.id,
        budget=4,
        required_portal_pairs=None,
        timeout_seconds=20,
    )
    solver = FourPlantersSolver(scenario)
    first_events, first = solver.solve_to_completion(request, solve_id="helsinki-first")
    second_events, second = solver.solve_to_completion(request, solve_id="helsinki-second")

    first_result = first.result
    second_result = second.result
    assert first_result["status"] == "verified_optimal"
    assert first_result["verification_status"] == "independently_verified"
    assert first_result["selected_intervention_ids"] == second_result["selected_intervention_ids"]
    assert first_result["objective_values"] == second_result["objective_values"]
    assert first_result["proof_hash"] == second_result["proof_hash"]
    assert [event["type"] for event in first_events] == [event["type"] for event in second_events]

    selected = frozenset(first_result["selected_intervention_ids"])
    assert len(selected) <= request.budget
    assert selected.issubset(scenario.candidates)
    assert all(
        not scenario.edges[edge_id]["protected"]
        for candidate_id in selected
        for edge_id in scenario.candidates[candidate_id].edge_ids
    )
    assert first_result["objective_values"]["intervention_count"] == len(selected)
    assert first_result["objective_values"]["weighted_cost"] == sum(
        scenario.candidates[candidate_id].cost for candidate_id in selected
    )
    assert all(
        item["private_car_disconnected"] for item in first_result["portal_connectivity_summary"]
    )
    assert first_result["address_access_summary"]["served"] == len(scenario.address_clusters)
    assert first_result["address_access_summary"]["all_accessible"] is True
    connectivity = first_result["private_car_connectivity"]
    assert connectivity["metric"] == "directed_strongly_connected_components"
    assert connectivity["baseline"]["node_count"] == len(scenario.nodes)
    assert connectivity["filtered"]["node_count"] == len(scenario.nodes)
    assert first_result["baseline_components"]["features"]
    assert first_result["filtered_components"]["features"]

    verification = solver.verify_solution(request, selected)
    assert verification["verified"] is True
    assert not verification["errors"]
