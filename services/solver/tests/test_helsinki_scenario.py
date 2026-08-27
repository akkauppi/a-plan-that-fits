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
    assert scenario.browser_payload["terminal_zone"]["properties"] == {
        "boundary_distance_metric": "projected_candidate_display_point_to_study_boundary",
        "candidate_eligible": False,
        "id": "candidate-terminal-zone",
        "kind": "analysis_boundary_candidate_setback",
        "name": "Candidate terminal zone",
        "protected": False,
        "reason": (
            "Modal-filter points are excluded here to remove boundary-adjacent cuts; "
            "this is an analytical eligibility rule, not transport protection."
        ),
        "setback_m": 60.0,
    }
    approach_zone = scenario.browser_payload["portal_approach_zones"]
    assert approach_zone["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    assert approach_zone["properties"]["setback_m"] == 120.0
    assert (
        approach_zone["properties"]["nearest_primary_portal_distance_metric"]
        == "projected_candidate_display_point_to_nearest_primary_portal_crossing"
    )
    assert approach_zone["properties"]["protected"] is False
    primary_portal_ids = {portal["id"] for portal in scenario.browser_payload["portals"]}
    assert set(approach_zone["properties"]["primary_portal_ids"]) == primary_portal_ids
    assert len(scenario.candidates) == 272
    assert all(
        candidate["boundary_distance_m"] >= 60
        and candidate["boundary_distance_metric"]
        == "projected_candidate_display_point_to_study_boundary"
        and candidate["nearest_primary_portal_distance_m"] >= 120
        and candidate["nearest_primary_portal_distance_metric"]
        == "projected_candidate_display_point_to_nearest_primary_portal_crossing"
        and candidate["nearest_primary_portal_id"] in primary_portal_ids
        and candidate["nearest_primary_portal_crossing_id"]
        in approach_zone["properties"]["primary_portal_crossing_ids"]
        and candidate["primary_portal_approach_ineligible"] is False
        and candidate["terminal_zone_ineligible"] is False
        and candidate["base_candidate_eligible"] is True
        and candidate["candidate_ineligibility_reason"] is None
        for candidate in scenario.browser_payload["candidates"]
    )
    candidate_policy = scenario.metadata["candidate_policy"]
    assert candidate_policy["terminal_zone_ineligible_physical_segments"] == 80
    assert candidate_policy["primary_portal_approach_ineligible_physical_segments"] == 79
    assert candidate_policy["setback_overlap_ineligible_physical_segments"] == 47
    assert candidate_policy["additional_primary_portal_approach_exclusions"] == 32
    assert candidate_policy["eligible_candidate_physical_segments"] == 272
    assert scenario.default_portal_pairs == [
        {
            "a": "p-east-01",
            "b": "p-south-04",
            "label": "Southern cross-neighbourhood permeability",
        },
        {
            "a": "p-north-03",
            "b": "p-west-01",
            "label": "Western cross-neighbourhood permeability",
        },
    ]

    request = SolveRequest(
        scenario_id=scenario.id,
        budget=4,
        required_portal_pairs=None,
        objective_mode="balanced",
        timeout_seconds=30,
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
    assert len(selected) == request.budget == 4
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
    assert first_result["objective_values"]["access_penalty"] == sum(
        scenario.candidates[candidate_id].access_penalty for candidate_id in selected
    )
    assert first_result["objective_values"]["adjacency_penalty"] == sum(
        left in selected and right in selected for left, right in solver._close_pairs
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
