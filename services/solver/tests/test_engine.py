from __future__ import annotations

import threading
import time

import z3

from services.solver.engine import FourPlantersSolver, PathClause
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
    assert any(
        event["type"] == "refining" and event.get("clause", {}).get("kind") == "objective_phase"
        for event in events
    )
    assert result["objective_values"] == {
        "intervention_count": 1,
        "weighted_cost": 100,
        "access_penalty": 0,
        "adjacency_penalty": 0,
    }
    assert result["mode_connectivity_summary"] == {
        "walking": "not_separately_modelled_filter_assumed_passable",
        "cycling": "not_separately_modelled_filter_assumed_passable",
        "emergency": "not_separately_modelled_removable_filter_assumption",
        "service_access": "unsupported_not_verified",
    }
    assert "not separately verified" in result["explanation"]


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


def test_inactive_objective_reduction_keeps_forced_disconnected_candidate() -> None:
    scenario = synthetic_scenario(
        [
            *undirected("west-a", "W", "A", "route_cut"),
            *undirected("a-east", "A", "E"),
            *undirected("unrelated", "X", "Y", "forced_elsewhere"),
        ],
        candidate_costs={"route_cut": 100, "forced_elsewhere": 90},
    )

    events, _ = FourPlantersSolver(scenario).solve_to_completion(
        request(forced_interventions=["forced_elsewhere"])
    )
    result = final_result(events)

    assert result["status"] == "verified_optimal"
    assert set(result["selected_intervention_ids"]) == {"route_cut", "forced_elsewhere"}
    assert result["objective_values"]["intervention_count"] == 2
    assert result["objective_values"]["weighted_cost"] == 190


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


def test_counterexample_batch_includes_bounded_route_diversity() -> None:
    scenario = synthetic_scenario(
        [
            *undirected("west-a", "W", "A", "c1"),
            *undirected("a-east", "A", "E"),
            *undirected("west-b", "W", "B", "c2"),
            *undirected("b-east", "B", "E"),
        ]
    )
    solver = FourPlantersSolver(scenario)

    counterexamples = solver._counterexample_batch(frozenset(), solver._pairs(request()))
    candidate_sets = {tuple(sorted(item["route"]["candidate_ids"])) for item in counterexamples}

    assert {("c1",), ("c2",)}.issubset(candidate_sets)
    assert all(item["route"]["edge_ids"] for item in counterexamples)


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
    records = []
    event_stream = FourPlantersSolver(one_cut_scenario).iter_solve(
        request(),
        solve_id="active-cancel",
        cancel_event=cancelled,
        on_complete=records.append,
    )
    events = [next(event_stream)]
    assert events[0]["type"] == "started"

    cancelled.set()
    events.extend(event_stream)

    assert [event["type"] for event in events[-2:]] == ["cancelled", "complete"]
    assert final_result(events)["status"] == "cancelled"
    assert final_result(events)["verification_status"] == "not_verified"
    assert records[0].result["status"] == "cancelled"


def test_active_z3_check_is_interrupted_cooperatively() -> None:
    entered_check = threading.Event()
    interrupted = threading.Event()
    cancelled = threading.Event()
    outcome: list[tuple[z3.CheckSatResult | None, str | None]] = []

    class BlockingSolver:
        def set(self, **_settings: int) -> None:
            pass

        def check(self, *_assumptions: z3.BoolRef) -> z3.CheckSatResult:
            entered_check.set()
            if not interrupted.wait(timeout=2):
                raise AssertionError("cooperative interrupt was not delivered")
            return z3.unknown

        def interrupt(self) -> None:
            interrupted.set()

    worker = threading.Thread(
        target=lambda: outcome.append(
            FourPlantersSolver._cooperative_solver_check(
                BlockingSolver(), time.monotonic() + 5, cancelled
            )
        )
    )
    worker.start()
    assert entered_check.wait(timeout=1)

    cancelled.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert interrupted.is_set()
    assert outcome == [(z3.unknown, "cancelled")]


def test_engine_cannot_verify_unvalidated_service_access_request(one_cut_scenario) -> None:
    unsupported = request().model_copy(update={"service_access_enabled": True})

    events, _ = FourPlantersSolver(one_cut_scenario).solve_to_completion(unsupported)
    result = final_result(events)

    assert result["status"] == "data_error"
    assert result["verification_status"] == "not_verified"
    assert "not implemented or verified" in result["explanation"]


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


def test_model_selection_inconsistency_is_a_data_error(one_cut_scenario, monkeypatch) -> None:
    solver = FourPlantersSolver(one_cut_scenario)
    monkeypatch.setattr(solver, "_deterministic_selection", lambda *_args, **_kwargs: None)

    events, _ = solver.solve_to_completion(request())
    result = final_result(events)

    assert [event["type"] for event in events[-2:]] == ["data_error", "complete"]
    assert result["status"] == "data_error"
    assert result["diagnostics"]["kind"] == "model_selection_inconsistency"


def test_result_includes_real_access_and_component_geometries(one_cut_scenario) -> None:
    events, _ = FourPlantersSolver(one_cut_scenario).solve_to_completion(request())
    result = final_result(events)
    assert result["access_routes"]["features"]
    assert result["private_car_connectivity"]["metric"] == (
        "directed_strongly_connected_components"
    )
    assert result["baseline_components"]["features"]
    assert result["filtered_components"]["features"]
    assert result["components"] == result["filtered_components"]
    assert result["private_car_connectivity"]["baseline"]["component_count"] == 1
    assert result["private_car_connectivity"]["filtered"]["component_count"] == 2
    assert all(
        feature["geometry"]["type"] == "LineString"
        for feature in result["baseline_components"]["features"]
    )


def test_component_overlay_respects_directed_one_way_reachability() -> None:
    scenario = synthetic_scenario(
        [
            ("west-a", "W", "A", None, False),
            *undirected("a-east", "A", "E"),
        ]
    )
    components, summary = FourPlantersSolver(scenario)._components_geojson(frozenset())

    # An undirected component calculation would incorrectly report one region.
    assert summary["component_count"] == 2
    assert summary["largest_component_node_count"] == 2
    west_link = next(
        feature for feature in components["features"] if feature["id"] == "component-west-a"
    )
    assert west_link["properties"]["within_component"] is False
    assert west_link["properties"]["component_id"] is None
    assert (
        west_link["properties"]["from_component_id"] != (west_link["properties"]["to_component_id"])
    )


def test_path_clause_antichain_pruning_is_logically_equivalent() -> None:
    broad = PathClause("west::east", "West ↔ east", ("a", "b", "c"))
    tighter = PathClause("west::east", "West ↔ east", ("a", "b"))
    redundant = PathClause("west::east", "West ↔ east", ("a", "b", "d"))
    other_pair = PathClause("north::south", "North ↔ south", ("a", "b", "c"))
    clauses = [broad, other_pair]

    added = FourPlantersSolver._merge_path_clauses(clauses, [redundant, tighter])

    assert added == [tighter]
    assert clauses == [other_pair, tighter]
    assignments = [
        frozenset(),
        frozenset({"a"}),
        frozenset({"b"}),
        frozenset({"c"}),
        frozenset({"d"}),
    ]
    for selected in assignments:
        original_pair_is_cut = bool(selected.intersection(broad.candidate_ids)) and bool(
            selected.intersection(tighter.candidate_ids)
        )
        retained_pair_is_cut = bool(selected.intersection(tighter.candidate_ids))
        assert original_pair_is_cut == retained_pair_is_cut


def test_independent_networkx_verifier_does_not_reuse_cegis_routes(
    one_cut_scenario, monkeypatch
) -> None:
    solver = FourPlantersSolver(one_cut_scenario)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("the independent verifier reused the CEGIS route finder")

    monkeypatch.setattr(solver, "_shortest_route", fail_if_called)
    verification = solver.verify_solution(request(), frozenset({"c1"}))

    assert verification["verified"] is True
    assert verification["portal_connectivity_summary"] == [
        {
            "a": "west",
            "b": "east",
            "label": "West ↔ East",
            "private_car_disconnected": True,
            "forward_route_exists": False,
            "reverse_route_exists": False,
        }
    ]
    assert verification["address_access_summary"]["all_accessible"] is True


def test_independent_verifier_detects_an_open_parallel_edge() -> None:
    scenario = synthetic_scenario(
        [
            ("filterable-forward", "W", "E", "c1", False),
            ("filterable-reverse", "E", "W", "c1", False),
            ("parallel-open-forward", "W", "E", None, True),
            ("parallel-open-reverse", "E", "W", None, True),
        ]
    )

    verification = FourPlantersSolver(scenario).verify_solution(request(), frozenset({"c1"}))

    assert verification["verified"] is False
    assert verification["portal_connectivity_summary"][0]["forward_route_exists"] is True
    assert verification["portal_connectivity_summary"][0]["reverse_route_exists"] is True


def test_address_cluster_on_permitted_portal_has_zero_length_access() -> None:
    scenario = synthetic_scenario(
        [*undirected("crossing", "W", "E", "c1")],
        clusters=[("portal_home", "W", ["west"])],
    )

    solver = FourPlantersSolver(scenario)
    route = solver._route_to_portals("W", ["west"], frozenset({"c1"}))
    verification = solver.verify_solution(request(), frozenset({"c1"}))

    assert route is not None
    assert route["length_m"] == 0.0
    assert route["edge_ids"] == []
    assert route["geometry"]["coordinates"][0] == route["geometry"]["coordinates"][1]
    assert solver._baseline_access["portal_home"] == 0.0
    assert solver._access_metrics(frozenset({"c1"}))["maximum_additional_distance_m"] == 0.0
    assert verification["verified"] is True
    assert verification["address_access_summary"]["served"] == 1
    assert verification["address_access_summary"]["unserved_ids"] == []
