from __future__ import annotations

import inspect
import threading
from pathlib import Path

import pytest

from services.solver import resilience as resilience_module
from services.solver.resilience import (
    AccessPoint,
    AssumptionRepairRequest,
    DecisionGroup,
    DisruptionAssumption,
    FrozenResilienceNetwork,
    NetworkEdge,
    NetworkNode,
    analyze_disruption,
    solve_minimum_assumption_repair,
)


def _edge(
    edge_id: str,
    physical_id: str,
    source: str,
    target: str,
    *,
    car: bool = True,
) -> NetworkEdge:
    locations = {
        "S": (24.0, 60.0),
        "A": (24.001, 60.0),
        "B": (24.001, 60.001),
        "D": (24.002, 60.0),
        "X": (24.003, 60.0),
        "Y": (24.004, 60.0),
    }
    return NetworkEdge(
        id=edge_id,
        physical_id=physical_id,
        source=source,
        target=target,
        length_m=100.0,
        geometry=(locations[source], locations[target]),
        private_car=car,
    )


def _two_link_network(*, disconnected_baseline: bool = False) -> FrozenResilienceNetwork:
    nodes = [
        NetworkNode("S", 24.0, 60.0),
        NetworkNode("A", 24.001, 60.0),
        NetworkNode("D", 24.002, 60.0),
        NetworkNode("X", 24.003, 60.0),
        NetworkNode("Y", 24.004, 60.0),
    ]
    edges = [
        _edge("sa-f", "sa", "S", "A"),
        _edge("sa-r", "sa", "A", "S"),
        _edge("ad-f", "ad", "A", "D"),
        _edge("ad-r", "ad", "D", "A"),
    ]
    if disconnected_baseline:
        edges.extend(
            [
                _edge("xy-f", "xy", "X", "Y"),
                _edge("xy-r", "xy", "Y", "X"),
            ]
        )
    return FrozenResilienceNetwork.from_records(
        scenario_id="test-resilience",
        nodes=nodes,
        edges=edges,
        exposed_segment_ids={100: {"sa", "ad"}, 1000: {"sa", "ad"}},
    )


def _parallel_exit_network() -> FrozenResilienceNetwork:
    nodes = [
        NetworkNode("S", 24.0, 60.0),
        NetworkNode("A", 24.001, 60.0),
        NetworkNode("B", 24.001, 60.001),
        NetworkNode("D", 24.002, 60.0),
    ]
    edges = [
        _edge("sa-f", "sa", "S", "A"),
        _edge("sa-r", "sa", "A", "S"),
        _edge("ad-f", "ad", "A", "D"),
        _edge("ad-r", "ad", "D", "A"),
        _edge("sb-f", "sb", "S", "B"),
        _edge("sb-r", "sb", "B", "S"),
        _edge("bd-f", "bd", "B", "D"),
        _edge("bd-r", "bd", "D", "B"),
    ]
    return FrozenResilienceNetwork.from_records(
        scenario_id="parallel-exits",
        nodes=nodes,
        edges=edges,
        exposed_segment_ids={100: {"ad", "bd"}},
    )


def _long_chain_network(node_count: int = 300) -> FrozenResilienceNetwork:
    nodes = [
        NetworkNode(f"n{index:03d}", 24.0 + index * 0.00001, 60.0)
        for index in range(node_count)
    ]
    edges: list[NetworkEdge] = []
    segment_ids: set[str] = set()
    for index in range(node_count - 1):
        source = nodes[index]
        target = nodes[index + 1]
        segment_id = f"s{index:03d}"
        segment_ids.add(segment_id)
        for suffix, left, right in (
            ("f", source, target),
            ("r", target, source),
        ):
            edges.append(
                NetworkEdge(
                    id=f"{segment_id}-{suffix}",
                    physical_id=segment_id,
                    source=left.id,
                    target=right.id,
                    length_m=1.0,
                    geometry=(
                        (left.longitude, left.latitude),
                        (right.longitude, right.latitude),
                    ),
                )
            )
    return FrozenResilienceNetwork.from_records(
        scenario_id="long-chain",
        nodes=nodes,
        edges=edges,
        exposed_segment_ids={100: segment_ids},
    )


def _study(
    network: FrozenResilienceNetwork,
    *,
    destination_longitude: float = 24.002,
) -> tuple[tuple, tuple]:
    origins = network.snap_points(
        [
            AccessPoint(
                "campus",
                "Campus",
                24.0,
                60.0,
                allowed_destination_ids=("exit",),
            )
        ]
    )
    destinations = network.snap_points(
        [AccessPoint("exit", "External access", destination_longitude, 60.0)]
    )
    return origins, destinations


def test_explicit_flood_assumption_changes_reachability_and_emits_visual_route() -> None:
    network = _two_link_network()
    origins, destinations = _study(network)

    evidence_only = analyze_disruption(
        network,
        DisruptionAssumption(
            flood_return_period_years=100,
            treat_flood_exposure_as_unavailable=False,
        ),
        origins,
        destinations,
    )
    disrupted = analyze_disruption(
        network,
        DisruptionAssumption(
            flood_return_period_years=100,
            treat_flood_exposure_as_unavailable=True,
        ),
        origins,
        destinations,
    )

    assert evidence_only["status"] == "verified"
    assert evidence_only["access"][0]["disrupted_route"]["feature"]["geometry"]["type"] == (
        "MultiLineString"
    )
    assert disrupted["status"] == "stranded"
    assert disrupted["summary"]["stranded"] == 1
    assert disrupted["assumption"]["unavailable_segment_ids"] == ["ad", "sa"]
    assert "not an observed closure" in disrupted["claim_scope"]


def test_baseline_unreachable_analysis_is_a_data_error_not_verified() -> None:
    network = _two_link_network(disconnected_baseline=True)
    origins, destinations = _study(network, destination_longitude=24.003)

    result = analyze_disruption(
        network,
        DisruptionAssumption(),
        origins,
        destinations,
    )

    assert result["status"] == "data_error"
    assert result["summary"]["baseline_unreachable"] == 1
    assert result["access"][0]["status"] == "baseline_unreachable"
    assert "baseline graph" in result["message"]


def test_summary_distinguishes_source_exposure_from_effective_car_closures() -> None:
    base = _two_link_network()
    network = FrozenResilienceNetwork.from_records(
        scenario_id="mixed-mode-exposure",
        nodes=tuple(base.nodes.values()),
        edges=(
            *base.edges,
            _edge("walk-only", "walk", "X", "D", car=False),
        ),
        exposed_segment_ids={100: {"ad", "walk"}},
    )
    origins, destinations = _study(network)

    result = analyze_disruption(
        network,
        DisruptionAssumption(
            flood_return_period_years=100,
            treat_flood_exposure_as_unavailable=True,
        ),
        origins,
        destinations,
    )

    assert result["summary"]["source_unavailable_segments"] == 2
    assert result["summary"]["effective_unavailable_private_car_segments"] == 1
    assert result["summary"]["unavailable_segments"] == 1
    assert result["assumption"]["unavailable_segment_ids"] == ["ad", "walk"]
    assert result["assumption"]["effective_unavailable_private_car_segment_ids"] == ["ad"]


def test_user_declared_roadworks_segment_is_an_explicit_closure() -> None:
    network = _two_link_network()
    origins, destinations = _study(network)

    result = analyze_disruption(
        network,
        DisruptionAssumption(roadworks_segment_ids=("ad",)),
        origins,
        destinations,
    )

    assert result["status"] == "stranded"
    assert result["assumption"]["roadworks_segment_ids"] == ["ad"]
    with pytest.raises(ValueError, match="Unknown roadworks"):
        analyze_disruption(
            network,
            DisruptionAssumption(roadworks_segment_ids=("invented",)),
            origins,
            destinations,
        )


def test_cut_refinement_finds_and_freshly_verifies_minimum_two_link_repair() -> None:
    network = _two_link_network()
    origins, destinations = _study(network)
    streamed_events: list[dict] = []

    result = solve_minimum_assumption_repair(
        network,
        DisruptionAssumption(
            flood_return_period_years=100,
            treat_flood_exposure_as_unavailable=True,
        ),
        origins,
        destinations,
        AssumptionRepairRequest(budget=2),
        on_event=streamed_events.append,
    )

    assert result["status"] == "verified_optimal"
    assert result["selected_segment_ids"] == ["ad", "sa"]
    assert result["objective_values"] == {
        "analytical_repairs": 2,
        "decision_group_count": 2,
        "decision_group_cost": 2,
        "expanded_segment_count": 2,
    }
    assert result["verification"] == {
        "verified": True,
        "method": "fresh_networkx_directed_graph",
        "origin_access": {"campus": True},
        "source_unavailable_segment_count": 0,
        "effective_unavailable_private_car_segment_count": 0,
        "unavailable_segment_count": 0,
    }
    cut_events = [event for event in result["iterations"] if event["type"] == "access_cut_found"]
    assert len(cut_events) == 2
    assert streamed_events == result["iterations"]
    assert cut_events[0]["diagnostic_route"]["feature"]["geometry"]["type"] == (
        "MultiLineString"
    )
    assert result["constraint_model"]["decision_variable_template"].startswith("passable")
    assert "NetworkX" in result["constraint_model"]["refinement"]


def test_budget_unsat_is_verified_and_not_reported_as_timeout() -> None:
    network = _two_link_network()
    origins, destinations = _study(network)

    result = solve_minimum_assumption_repair(
        network,
        DisruptionAssumption(
            flood_return_period_years=100,
            treat_flood_exposure_as_unavailable=True,
        ),
        origins,
        destinations,
        AssumptionRepairRequest(budget=1),
    )

    assert result["status"] == "verified_unsat"
    assert result["verified"] is True
    assert result["diagnostics"]["finding"] == (
        "budget_insufficient_for_necessary_access_cuts"
    )
    assert "at most 1" in result["message"]


def test_corridor_group_expands_multiple_segments_but_counts_as_one_decision() -> None:
    network = _two_link_network()
    origins, destinations = _study(network)
    streamed_events: list[dict] = []

    result = solve_minimum_assumption_repair(
        network,
        DisruptionAssumption(
            flood_return_period_years=100,
            treat_flood_exposure_as_unavailable=True,
        ),
        origins,
        destinations,
        AssumptionRepairRequest(
            budget=1,
            decision_groups=(
                DecisionGroup(
                    "shoreline-corridor",
                    "Shoreline corridor",
                    ("sa", "ad"),
                ),
            ),
        ),
        on_event=streamed_events.append,
    )

    assert result["status"] == "verified_optimal"
    assert result["selected_decision_ids"] == ["shoreline-corridor"]
    assert result["selected_segment_ids"] == ["ad", "sa"]
    assert result["objective_values"] == {
        "analytical_repairs": 1,
        "decision_group_count": 1,
        "decision_group_cost": 1,
        "expanded_segment_count": 2,
    }
    assert result["verification"]["verified"] is True
    cut_events = [event for event in streamed_events if event["type"] == "access_cut_found"]
    assert len(cut_events) == 1
    assert cut_events[0]["frontier_decision_ids"] == ["shoreline-corridor"]
    assert cut_events[0]["frontier_segment_ids"] == ["sa"]
    assert cut_events[0]["constraint"]["variable_ids"] == [
        "passable[shoreline-corridor]"
    ]
    assert result["constraint_model"]["decision_groups"] == [
        {
            "id": "shoreline-corridor",
            "label": "Shoreline corridor",
            "segment_ids": ["ad", "sa"],
            "segment_count": 2,
            "cost": 1,
        }
    ]


def test_equal_cardinality_prefers_minimum_explicit_group_cost_before_id() -> None:
    network = _parallel_exit_network()
    origins, destinations = _study(network)

    result = solve_minimum_assumption_repair(
        network,
        DisruptionAssumption(
            flood_return_period_years=100,
            treat_flood_exposure_as_unavailable=True,
        ),
        origins,
        destinations,
        AssumptionRepairRequest(
            budget=1,
            decision_groups=(
                DecisionGroup("a-expensive", "Expensive route", ("ad",), cost=10),
                DecisionGroup("z-cheap", "Cheap route", ("bd",), cost=2),
            ),
        ),
    )

    assert result["status"] == "verified_optimal"
    assert result["selected_decision_ids"] == ["z-cheap"]
    assert result["selected_segment_ids"] == ["bd"]
    assert result["objective_values"] == {
        "analytical_repairs": 1,
        "decision_group_count": 1,
        "decision_group_cost": 2,
        "expanded_segment_count": 1,
    }
    assert "aggregation metric" in result["constraint_model"]["cost_semantics"]
    assert "not a monetary" in result["constraint_model"]["cost_semantics"]


def test_equal_group_count_and_cost_use_stable_id_tie_break() -> None:
    network = _parallel_exit_network()
    origins, destinations = _study(network)

    result = solve_minimum_assumption_repair(
        network,
        DisruptionAssumption(
            flood_return_period_years=100,
            treat_flood_exposure_as_unavailable=True,
        ),
        origins,
        destinations,
        AssumptionRepairRequest(
            budget=1,
            decision_groups=(
                DecisionGroup("a-first", "First by stable ID", ("ad",), cost=3),
                DecisionGroup("z-second", "Second by stable ID", ("bd",), cost=3),
            ),
        ),
    )

    assert result["status"] == "verified_optimal"
    assert result["selected_decision_ids"] == ["a-first"]


@pytest.mark.parametrize(
    ("groups", "finding"),
    [
        ((DecisionGroup("empty", "Empty", ()),), "empty_decision_group"),
        (
            (
                DecisionGroup("first", "First", ("sa",)),
                DecisionGroup("second", "Second", ("sa", "ad")),
            ),
            "overlapping_decision_groups",
        ),
        (
            (DecisionGroup("not-closed", "Not closed", ("never",)),),
            "invalid_decision_group_segments",
        ),
        (
            (DecisionGroup("zero-cost", "Zero cost", ("sa",), cost=0),),
            "invalid_decision_group_cost",
        ),
    ],
)
def test_invalid_decision_groups_return_data_error(
    groups: tuple[DecisionGroup, ...], finding: str
) -> None:
    network = _two_link_network()
    origins, destinations = _study(network)

    result = solve_minimum_assumption_repair(
        network,
        DisruptionAssumption(
            flood_return_period_years=100,
            treat_flood_exposure_as_unavailable=True,
        ),
        origins,
        destinations,
        AssumptionRepairRequest(budget=2, decision_groups=groups),
    )

    assert result["status"] == "data_error"
    assert result["verified"] is False
    assert result["diagnostics"]["finding"] == finding


def test_ineligible_frontier_returns_specific_graph_finding() -> None:
    network = _two_link_network()
    origins, destinations = _study(network)

    result = solve_minimum_assumption_repair(
        network,
        DisruptionAssumption(roadworks_segment_ids=("sa",)),
        origins,
        destinations,
        AssumptionRepairRequest(budget=4, eligible_segment_ids=()),
    )

    assert result["status"] == "verified_unsat"
    assert result["diagnostics"]["finding"] == "unrepairable_access_cut"
    assert any(event["type"] == "unrepairable_cut" for event in result["iterations"])


def test_timeout_and_cancellation_are_indeterminate_not_unsat() -> None:
    network = _two_link_network()
    origins, destinations = _study(network)
    assumption = DisruptionAssumption(
        flood_return_period_years=100,
        treat_flood_exposure_as_unavailable=True,
    )

    timed_out = solve_minimum_assumption_repair(
        network,
        assumption,
        origins,
        destinations,
        AssumptionRepairRequest(budget=2, timeout_seconds=0.0),
    )
    cancellation = threading.Event()
    cancellation.set()
    cancelled = solve_minimum_assumption_repair(
        network,
        assumption,
        origins,
        destinations,
        AssumptionRepairRequest(budget=2),
        cancel_event=cancellation,
    )

    assert timed_out["status"] == "timeout"
    assert timed_out["verified"] is False
    assert "not an UNSAT" in timed_out["message"]
    assert cancelled["status"] == "cancelled"
    assert cancelled["verified"] is False


def test_request_deadline_interrupts_networkx_route_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network = _two_link_network()
    origins, destinations = _study(network)

    def clock_that_expires_inside_dijkstra() -> float:
        frame = inspect.currentframe()
        while frame is not None:
            if frame.f_code.co_name == "controlled_weight":
                return 2.0
            frame = frame.f_back
        return 0.0

    monkeypatch.setattr(
        resilience_module.time,
        "monotonic",
        clock_that_expires_inside_dijkstra,
    )
    result = solve_minimum_assumption_repair(
        network,
        DisruptionAssumption(
            flood_return_period_years=100,
            treat_flood_exposure_as_unavailable=True,
        ),
        origins,
        destinations,
        AssumptionRepairRequest(budget=2, timeout_seconds=1.0),
    )

    assert result["status"] == "timeout"
    assert result["verified"] is False
    assert result["diagnostics"]["interrupted_phase"] == "baseline_route_search"
    assert "not an UNSAT" in result["message"]


def test_cancellation_interrupts_an_in_progress_component_traversal() -> None:
    network = _long_chain_network()
    origins = network.snap_points(
        [
            AccessPoint(
                "campus",
                "Campus",
                network.nodes["n000"].longitude,
                network.nodes["n000"].latitude,
                allowed_destination_ids=("exit",),
            )
        ]
    )
    destinations = network.snap_points(
        [
            AccessPoint(
                "exit",
                "External access",
                network.nodes["n299"].longitude,
                network.nodes["n299"].latitude,
            )
        ]
    )

    class CancelDuringTraversal(threading.Event):
        def is_set(self) -> bool:
            frame = inspect.currentframe()
            while frame is not None:
                if (
                    frame.f_code.co_name == "_weakly_connected_components"
                    and frame.f_locals.get("visited_count", 0) >= 128
                ):
                    self.set()
                    break
                frame = frame.f_back
            return super().is_set()

    cancellation = CancelDuringTraversal()
    result = solve_minimum_assumption_repair(
        network,
        DisruptionAssumption(),
        origins,
        destinations,
        AssumptionRepairRequest(budget=0),
        cancel_event=cancellation,
    )

    assert cancellation.is_set()
    assert result["status"] == "cancelled"
    assert result["verified"] is False
    assert result["diagnostics"]["interrupted_phase"] == "disrupted_components"
    assert result["iterations"] == []


def test_baseline_unreachable_is_a_data_error_not_an_impossibility_claim() -> None:
    network = _two_link_network(disconnected_baseline=True)
    origins, destinations = _study(network, destination_longitude=24.003)

    result = solve_minimum_assumption_repair(
        network,
        DisruptionAssumption(),
        origins,
        destinations,
        AssumptionRepairRequest(budget=2),
    )

    assert result["status"] == "data_error"
    assert result["verified"] is False
    assert result["diagnostics"]["baseline_unreachable_origin_ids"] == ["campus"]


def test_real_frozen_artifacts_load_with_expected_ids_and_exposure_counts() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    base = repository_root / (
        "data/derived/espoo-otaniemi-coastal-base-v1-base-network/snapshots/"
        "base-c8dcbcfaca2b2c9498420681/base-network.json"
    )
    flood = repository_root / (
        "data/derived/espoo-otaniemi-coastal-v1-flood-exposure/snapshots/"
        "flood-bf45a84ac9ce456045f8932b/flood-exposure.json"
    )
    if not base.exists() or not flood.exists():
        pytest.skip("Frozen Otaniemi artifacts are not present")

    network = FrozenResilienceNetwork.from_artifacts(base, flood)

    assert network.base_snapshot_id == "base-c8dcbcfaca2b2c9498420681"
    assert network.flood_snapshot_id == "flood-bf45a84ac9ce456045f8932b"
    assert len(network.nodes) == 18_710
    assert len(network.edges) == 42_077
    assert len(network.exposed_segment_ids[100]) == 892
    assert len(network.exposed_segment_ids[1000]) == 1_608
