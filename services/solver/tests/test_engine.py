from __future__ import annotations

import threading

from services.solver.engine import FourPlantersSolver
from services.solver.models import PortalPair, SolveRequest

from .conftest import synthetic_scenario, undirected


def request(**overrides: object) -> SolveRequest:
    values = {
        "scenario_id": "synthetic",
        "budget": 4,
        "required_portal_pairs": [{"a": "west", "b": "east"}],
        "timeout_seconds": 5,
    }
    values.update(overrides)
    return SolveRequest.model_validate(values)


def final_result(events: list[dict]) -> dict:
    assert events[-1]["type"] == "complete"
    return events[-1]["result"]


def test_graph_solvable_with_one_intervention(one_cut_scenario) -> None:
    solver = FourPlantersSolver(one_cut_scenario)
    events, _ = solver.solve_to_completion(request())
    result = final_result(events)
    assert result["status"] == "verified_optimal"
    assert result["selected_intervention_ids"] == ["c1"]
    assert result["address_access_summary"]["all_accessible"] is True
    assert result["verification_status"] == "independently_verified"


def test_graph_requires_exactly_two_interventions(two_cut_scenario) -> None:
    solver = FourPlantersSolver(two_cut_scenario)
    events, _ = solver.solve_to_completion(request())
    result = final_result(events)
    assert result["status"] == "verified_optimal"
    assert set(result["selected_intervention_ids"]) == {"c1", "c2"}
    assert result["objective_values"]["intervention_count"] == 2


def test_budget_driven_unsat_has_named_core(two_cut_scenario) -> None:
    solver = FourPlantersSolver(two_cut_scenario)
    events, _ = solver.solve_to_completion(request(budget=1))
    result = final_result(events)
    assert result["status"] == "verified_unsat"
    categories = {item["category"] for item in result["unsat_core_details"]}
    assert {"budget", "portal_pair"}.issubset(categories)
    assert any(item["type"] == "increase_budget" for item in result["suggested_relaxations"])


def test_forced_intervention_is_hard_constraint() -> None:
    scenario = synthetic_scenario(
        [
            *undirected("west-a", "W", "A", "c1"),
            *undirected("a-east", "A", "E", "c2"),
        ],
        candidate_costs={"c1": 100, "c2": 200},
    )
    events, _ = FourPlantersSolver(scenario).solve_to_completion(
        request(forced_interventions=["c2"])
    )
    assert final_result(events)["selected_intervention_ids"] == ["c2"]


def test_locked_open_candidate_is_never_selected() -> None:
    scenario = synthetic_scenario(
        [
            *undirected("west-a", "W", "A", "c1"),
            *undirected("a-east", "A", "E", "c2"),
        ],
        candidate_costs={"c1": 100, "c2": 200},
    )
    events, _ = FourPlantersSolver(scenario).solve_to_completion(
        request(locked_open_streets=["c1"])
    )
    assert final_result(events)["selected_intervention_ids"] == ["c2"]


def test_local_access_failure_rejects_candidate_and_refines() -> None:
    scenario = synthetic_scenario(
        [
            *undirected("west-a", "W", "A", "z_safe"),
            *undirected("a-east", "A", "E", "a_access"),
        ],
        candidate_costs={"a_access": 100, "z_safe": 200},
        clusters=[("homes", "A", ["east"])],
    )
    events, _ = FourPlantersSolver(scenario).solve_to_completion(request())
    assert any(event["type"] == "candidate_rejected" for event in events)
    assert final_result(events)["selected_intervention_ids"] == ["z_safe"]


def test_multiple_equally_optimal_solutions_can_be_enumerated() -> None:
    scenario = synthetic_scenario(
        [
            *undirected("west-a", "W", "A", "c1"),
            *undirected("a-east", "A", "E", "c2"),
        ]
    )
    solver = FourPlantersSolver(scenario)
    first_events, first = solver.solve_to_completion(request())
    assert first.context is not None
    second_events, second = solver.solve_to_completion(
        request(), solve_id="alternative", alternative=first.context
    )
    first_ids = set(final_result(first_events)["selected_intervention_ids"])
    second_ids = set(final_result(second_events)["selected_intervention_ids"])
    assert first_ids != second_ids
    assert first.result["objective_values"] == second.result["objective_values"]
    assert second.context is not None
    third_events, _ = solver.solve_to_completion(
        request(), solve_id="exhausted", alternative=second.context
    )
    assert final_result(third_events)["status"] == "alternatives_exhausted"


def test_surviving_path_is_streamed_before_refinement(one_cut_scenario) -> None:
    events, _ = FourPlantersSolver(one_cut_scenario).solve_to_completion(request())
    counterexample = next(event for event in events if event["type"] == "counterexample_found")
    assert counterexample["route"]["type"] == "LineString"
    assert counterexample["route_details"]["edge_ids"]
    assert any(event["type"] == "refining" for event in events)


def test_path_with_no_eligible_blocker_is_graph_verified_unsat() -> None:
    scenario = synthetic_scenario([*undirected("protected", "W", "E", None, protected=True)])
    events, _ = FourPlantersSolver(scenario).solve_to_completion(request())
    result = final_result(events)
    assert result["status"] == "verified_unsat"
    assert result["verification_status"] == "graph_unblockable_route"
    assert result["diagnostics"]["kind"] == "unblockable_protected_corridor"


def test_forced_filter_that_breaks_access_is_unsat() -> None:
    scenario = synthetic_scenario(
        [
            *undirected("west-a", "W", "A"),
            *undirected("a-east", "A", "E", "only_exit"),
        ],
        clusters=[("homes", "A", ["east"])],
    )
    events, _ = FourPlantersSolver(scenario).solve_to_completion(
        request(forced_interventions=["only_exit"], required_portal_pairs=[])
    )
    result = final_result(events)
    assert result["status"] == "verified_unsat"
    categories = {item["category"] for item in result["unsat_core_details"]}
    assert {"forced_intervention", "local_access"}.issubset(categories)


def test_cancellation_is_not_reported_as_unsat(one_cut_scenario) -> None:
    cancelled = threading.Event()
    cancelled.set()
    events, _ = FourPlantersSolver(one_cut_scenario).solve_to_completion(
        request(), cancel_event=cancelled
    )
    assert [event["type"] for event in events[-2:]] == ["cancelled", "complete"]
    assert final_result(events)["status"] == "cancelled"


def test_timeout_is_not_reported_as_unsat(one_cut_scenario) -> None:
    timed_out_request = SolveRequest.model_construct(
        scenario_id="synthetic",
        budget=4,
        required_portal_pairs=[PortalPair(a="west", b="east")],
        forced_interventions=[],
        locked_open_streets=[],
        emergency_permeable=True,
        service_access_enabled=False,
        objective_mode="balanced",
        timeout_seconds=-1.0,
        solve_id=None,
    )
    events, _ = FourPlantersSolver(one_cut_scenario).solve_to_completion(timed_out_request)
    assert [event["type"] for event in events[-2:]] == ["timeout", "complete"]
    assert final_result(events)["status"] == "timeout"


def test_result_includes_real_access_and_component_geometries(one_cut_scenario) -> None:
    events, _ = FourPlantersSolver(one_cut_scenario).solve_to_completion(request())
    result = final_result(events)
    assert result["access_routes"]["features"]
    assert result["components"]["features"]
    assert all(
        feature["geometry"]["type"] == "LineString" for feature in result["components"]["features"]
    )
