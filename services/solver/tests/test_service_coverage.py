from __future__ import annotations

import threading
from dataclasses import replace

import pytest

from services.solver.service_coverage import (
    CandidateSite,
    DemandCell,
    DistanceRecord,
    FrozenServiceCoverageScenario,
    ServiceCoverageRequest,
    WalkingEdge,
    WalkingNode,
    solve_next_service_coverage_solution,
    solve_service_coverage,
    verify_service_coverage_solution,
)


def _audited_graph_scenario(
    *, shortcut_length_m: float | None = None
) -> FrozenServiceCoverageScenario:
    node_points = {
        "a": (24.800, 60.180),
        "b": (24.801, 60.180),
        "c": (24.802, 60.180),
    }
    route = {
        "type": "Feature",
        "properties": {
            "demand_id": "d",
            "site_id": "s",
            "distance_m": 200,
            "demand_connector_m": 0,
            "network_distance_m": 200,
            "site_connector_m": 0,
            "connector_method": "straight_line_projected_euclidean",
        },
        "geometry": {
            "type": "LineString",
            "coordinates": [node_points["a"], node_points["b"], node_points["c"]],
        },
    }
    edges = [
        WalkingEdge("ab", "a", "b", 100, (node_points["a"], node_points["b"])),
        WalkingEdge("bc", "b", "c", 100, (node_points["b"], node_points["c"])),
    ]
    if shortcut_length_m is not None:
        edges.append(
            WalkingEdge(
                "ac",
                "a",
                "c",
                shortcut_length_m,
                (node_points["a"], node_points["c"]),
            )
        )
    return FrozenServiceCoverageScenario.from_records(
        scenario_id="graph-backed",
        snapshot_id="graph-backed-1",
        demand=(
            DemandCell(
                "d",
                "Demand",
                10,
                *node_points["a"],
                node_id="a",
                snap_distance_m=0,
            ),
        ),
        sites=(
            CandidateSite(
                "s",
                "Site",
                10,
                *node_points["c"],
                node_id="c",
                snap_distance_m=0,
            ),
        ),
        distances=(
            DistanceRecord(
                "d",
                "s",
                200,
                route,
                demand_connector_m=0,
                network_distance_m=200,
                site_connector_m=0,
                route_node_ids=("a", "b", "c"),
                route_edge_ids=("ab", "bc"),
                connector_method="straight_line_projected_euclidean",
            ),
        ),
        network_nodes=tuple(
            WalkingNode(node_id, *point) for node_id, point in node_points.items()
        ),
        network_edges=tuple(edges),
    )


def _scenario(
    *,
    site_capacities: tuple[int, int, int] = (80, 80, 100),
    distances: dict[tuple[str, str], float] | None = None,
) -> FrozenServiceCoverageScenario:
    cells = (
        DemandCell("d1", "West cell", 40, 24.80, 60.18, "west"),
        DemandCell("d2", "East cell", 50, 24.82, 60.18, "east"),
    )
    sites = tuple(
        CandidateSite(site_id, label, capacity, longitude, 60.18)
        for site_id, label, capacity, longitude in (
            ("s1", "West service", site_capacities[0], 24.801),
            ("s2", "East service", site_capacities[1], 24.819),
            ("s3", "Central service", site_capacities[2], 24.810),
        )
    )
    matrix = distances or {
        ("d1", "s1"): 100,
        ("d1", "s2"): 300,
        ("d1", "s3"): 150,
        ("d2", "s1"): 400,
        ("d2", "s2"): 100,
        ("d2", "s3"): 150,
    }
    records = [
        DistanceRecord(
            demand_id,
            site_id,
            distance,
            route={
                "type": "Feature",
                "properties": {"demand_id": demand_id, "site_id": site_id},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[24.8, 60.18], [24.81, 60.18]],
                },
            },
        )
        for (demand_id, site_id), distance in matrix.items()
    ]
    return FrozenServiceCoverageScenario.from_records(
        scenario_id="synthetic-coverage",
        snapshot_id="coverage-2026-01-01",
        demand=cells,
        sites=sites,
        distances=records,
    )


def test_sat_solution_uses_one_central_site_and_preserves_route_evidence() -> None:
    result = solve_service_coverage(
        _scenario(), ServiceCoverageRequest(site_budget=2, max_distance_m=500)
    )

    assert result["status"] == "verified_optimal"
    assert result["selected_site_ids"] == ["s3"]
    assert {item["demand_id"] for item in result["assignments"]} == {"d1", "d2"}
    assert {item["demand_cell_id"] for item in result["assignments"]} == {"d1", "d2"}
    assert all(item["site_id"] == "s3" for item in result["assignments"])
    assert all(item["route"]["type"] == "Feature" for item in result["assignments"])
    assert result["objective_values"] == {
        "selected_site_count": 1,
        "open_sites": 1,
        "worst_distance_m": 150.0,
        "population_weighted_distance_m": 13_500.0,
        "population_weighted_total_distance_person_m": 13_500.0,
        "population_weighted_mean_distance_m": 150.0,
        "load_imbalance_people": 0,
    }
    assert result["verification"]["verified"] is True
    assert result["verification"]["all_cells_assigned"] is True
    assert result["verification"]["capacities_respected"] is True
    assert result["verification"]["evidence_basis"] == "frozen_distance_matrix"
    assert [item["type"] for item in result["iterations"]] == [
        "matrix_compiled",
        "feasible_assignment",
        "objective_improved",
        "objective_improved",
        "objective_improved",
        "objective_improved",
        "objective_improved",
        "fresh_verification",
    ]
    assert result["district_summary"] == [
        {
            "district_id": "east",
            "population": 50,
            "mean_distance_m": 150.0,
            "worst_distance_m": 150.0,
        },
        {
            "district_id": "west",
            "population": 40,
            "mean_distance_m": 150.0,
            "worst_distance_m": 150.0,
        },
    ]


def test_capacity_and_budget_combination_has_human_readable_unsat_finding() -> None:
    scenario = _scenario(site_capacities=(50, 50, 50))

    result = solve_service_coverage(
        scenario, ServiceCoverageRequest(site_budget=1, max_distance_m=500)
    )

    assert result["status"] == "verified_unsat"
    assert result["diagnostics"]["finding"] == "insufficient_capacity_under_budget"
    assert result["diagnostics"]["capacity_bound"] == {
        "included_population": 90,
        "maximum_capacity_under_budget": 50,
    }
    assert "Increase the site budget or capacity assumption" in result["message"]
    assert {item["kind"] for item in result["diagnostics"]["unsat_core"]} >= {
        "assignment",
        "capacity",
        "budget",
    }


def test_distance_gap_is_not_misreported_as_capacity_unsat() -> None:
    distances = {
        ("d1", "s1"): 100,
        ("d1", "s2"): 200,
        ("d1", "s3"): 150,
        ("d2", "s1"): 800,
        ("d2", "s2"): 900,
        ("d2", "s3"): 700,
    }

    result = solve_service_coverage(
        _scenario(distances=distances),
        ServiceCoverageRequest(site_budget=3, max_distance_m=500),
    )

    assert result["status"] == "verified_unsat"
    assert result["diagnostics"]["finding"] == "distance_coverage_gap"
    assert result["diagnostics"]["uncovered_demand_ids"] == ["d2"]
    assert "no eligible, non-banned site within 500 m" in result["message"]


def test_forced_and_banned_sites_are_hard_constraints() -> None:
    forced = solve_service_coverage(
        _scenario(),
        ServiceCoverageRequest(
            site_budget=2,
            max_distance_m=500,
            forced_site_ids=("s1",),
            banned_site_ids=("s3",),
        ),
    )
    conflict = solve_service_coverage(
        _scenario(),
        ServiceCoverageRequest(
            site_budget=2,
            max_distance_m=500,
            forced_site_ids=("s1",),
            banned_site_ids=("s1",),
        ),
    )

    assert forced["status"] == "verified_optimal"
    assert forced["selected_site_ids"] == ["s1", "s2"]
    assert conflict["status"] == "verified_unsat"
    assert conflict["diagnostics"]["finding"] == "forced_and_banned_site_conflict"
    assert {item["kind"] for item in conflict["diagnostics"]["unsat_core"]} == {
        "forced_site",
        "banned_site",
    }


def test_forced_sites_over_budget_return_an_explanation_not_a_data_error() -> None:
    result = solve_service_coverage(
        _scenario(),
        ServiceCoverageRequest(
            site_budget=1,
            max_distance_m=500,
            forced_site_ids=("s1", "s2"),
        ),
    )

    assert result["status"] == "verified_unsat"
    assert result["diagnostics"]["finding"] == "forced_sites_exceed_budget"
    assert "2 sites are forced active" in result["message"]
    assert {item["kind"] for item in result["diagnostics"]["unsat_core"]} >= {
        "budget",
        "forced_site",
    }


def test_capacity_multiplier_is_explicit_and_uses_floor_semantics() -> None:
    scenario = _scenario(site_capacities=(60, 60, 60))

    result = solve_service_coverage(
        scenario,
        ServiceCoverageRequest(
            site_budget=1,
            max_distance_m=500,
            capacity_multiplier=1.5,
        ),
    )

    assert result["status"] == "verified_optimal"
    selected_load = next(item for item in result["site_loads"] if item["selected"])
    assert selected_load["declared_capacity"] == 60
    assert selected_load["effective_capacity"] == 90
    assert result["constraint_model"]["capacity_semantics"]["rounding"] == (
        "floor_to_whole_people"
    )


def test_timeout_and_precancel_are_distinct_from_unsat() -> None:
    timeout = solve_service_coverage(
        _scenario(),
        ServiceCoverageRequest(site_budget=2, timeout_seconds=0),
    )
    cancelled_event = threading.Event()
    cancelled_event.set()
    cancelled = solve_service_coverage(
        _scenario(),
        ServiceCoverageRequest(site_budget=2),
        cancel_event=cancelled_event,
    )

    assert timeout["status"] == "timeout"
    assert "not UNSAT" in timeout["message"]
    assert cancelled["status"] == "cancelled"
    assert "no feasibility claim" in cancelled["message"]


def test_cancellation_after_model_compilation_stops_before_a_candidate() -> None:
    cancel_event = threading.Event()

    def cancel_after_compile(event: dict[str, object]) -> None:
        if event["type"] == "matrix_compiled":
            cancel_event.set()

    result = solve_service_coverage(
        _scenario(),
        ServiceCoverageRequest(site_budget=2),
        cancel_event=cancel_event,
        on_event=cancel_after_compile,
    )

    assert result["status"] == "cancelled"
    assert [event["type"] for event in result["iterations"]] == ["matrix_compiled"]


def test_repeated_runs_are_deterministic_including_event_sequence() -> None:
    scenario = _scenario()
    request = ServiceCoverageRequest(site_budget=2, max_distance_m=500)

    first = solve_service_coverage(scenario, request)
    second = solve_service_coverage(scenario, request)

    assert first["selected_site_ids"] == second["selected_site_ids"]
    assert first["assignments"] == second["assignments"]
    assert first["objective_vector"] == second["objective_vector"]
    assert [item["type"] for item in first["iterations"]] == [
        item["type"] for item in second["iterations"]
    ]


def test_independent_verifier_rejects_a_tampered_assignment() -> None:
    scenario = _scenario()
    request = ServiceCoverageRequest(site_budget=2, max_distance_m=500)
    result = solve_service_coverage(scenario, request)
    tampered = [dict(item) for item in result["assignments"]]
    tampered[0]["distance_m"] = 1.0

    verification = verify_service_coverage_solution(
        scenario,
        request,
        result["selected_site_ids"],
        tampered,
        objective_vector=tuple(result["objective_vector"]),
    )

    assert verification["verified"] is False
    assert "assignment_distance_disagrees_with_matrix" in {
        item["kind"] for item in verification["errors"]
    }


def test_optional_walking_graph_is_recomputed_during_verification() -> None:
    scenario = _audited_graph_scenario()

    result = solve_service_coverage(
        scenario, ServiceCoverageRequest(site_budget=1, max_distance_m=250)
    )

    assert result["status"] == "verified_optimal"
    assert result["verification"]["evidence_basis"] == (
        "frozen_distance_matrix_and_walking_graph"
    )
    assert result["verification"]["graph_checks"] == [
        {
            "demand_id": "d",
            "site_id": "s",
            "matrix_total_distance_m": 200,
            "matrix_network_distance_m": 200,
            "recomputed_shortest_network_distance_m": 200.0,
            "matches": True,
        }
    ]


def test_graph_matrix_disagreement_becomes_a_verification_data_error() -> None:
    scenario = _audited_graph_scenario(shortcut_length_m=150)

    result = solve_service_coverage(
        scenario, ServiceCoverageRequest(site_budget=1, max_distance_m=250)
    )

    assert result["status"] == "data_error"
    assert result["diagnostics"]["finding"] == "independent_verification_failed"
    assert "network_distance_shortest_path_mismatch" in {
        item["kind"] for item in result["verification"]["errors"]
    }


def test_exact_route_geometry_tamper_is_rejected_even_when_length_is_unchanged() -> None:
    scenario = _audited_graph_scenario()
    record = scenario.distances[0]
    tampered_route = {
        **record.route,
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [24.800, 60.180],
                [24.801, 60.181],
                [24.802, 60.180],
            ],
        },
    }
    tampered = replace(
        scenario,
        distances=(replace(record, route=tampered_route),),
    )
    assignments = [{"demand_id": "d", "site_id": "s", "distance_m": 200}]

    verification = verify_service_coverage_solution(
        tampered,
        ServiceCoverageRequest(site_budget=1, max_distance_m=250),
        ["s"],
        assignments,
        objective_vector=(1, 20_000, 200_000, 0),
    )

    assert verification["verified"] is False
    assert "route_geometry_does_not_match_edge_chain" in {
        item["kind"] for item in verification["errors"]
    }


@pytest.mark.parametrize(
    ("changes", "finding"),
    [
        ({"route": None}, "route_geometry_missing"),
        ({"route_edge_ids": ("bc", "ab")}, "route_edge_chain_mismatch"),
        (
            {"distance_m": 190, "network_distance_m": 190},
            "route_edge_length_sum_mismatch",
        ),
        ({"demand_connector_m": 10}, "demand_connector_snap_mismatch"),
    ],
)
def test_malformed_graph_evidence_is_a_data_error(
    changes: dict[str, object], finding: str
) -> None:
    scenario = _audited_graph_scenario()
    tampered = replace(
        scenario,
        distances=(replace(scenario.distances[0], **changes),),
    )

    result = solve_service_coverage(
        tampered, ServiceCoverageRequest(site_budget=1, max_distance_m=250)
    )

    assert result["status"] == "data_error"
    assert result["diagnostics"]["finding"] == "independent_verification_failed"
    assert finding in {item["kind"] for item in result["verification"]["errors"]}


def test_fourth_objective_balances_load_between_forced_sites() -> None:
    demand = tuple(
        DemandCell(f"d{index}", f"Cell {index}", 10, 24.80 + index * 0.001, 60.18)
        for index in range(4)
    )
    sites = (
        CandidateSite("s1", "Site 1", 100, 24.80, 60.18),
        CandidateSite("s2", "Site 2", 100, 24.82, 60.18),
    )
    scenario = FrozenServiceCoverageScenario.from_records(
        scenario_id="balance",
        demand=demand,
        sites=sites,
        distances=tuple(
            DistanceRecord(cell.id, site.id, 100) for cell in demand for site in sites
        ),
    )

    result = solve_service_coverage(
        scenario,
        ServiceCoverageRequest(
            site_budget=2,
            forced_site_ids=("s1", "s2"),
        ),
    )

    assert result["status"] == "verified_optimal"
    assert result["objective_values"]["load_imbalance_people"] == 0
    assert sorted(item["assigned_population"] for item in result["site_loads"]) == [20, 20]


def test_equally_optimal_alternative_excludes_previous_site_set() -> None:
    scenario = _scenario(
        site_capacities=(100, 100, 40),
        distances={
            ("d1", "s1"): 100,
            ("d1", "s2"): 100,
            ("d1", "s3"): 50,
            ("d2", "s1"): 100,
            ("d2", "s2"): 100,
            ("d2", "s3"): 50,
        },
    )
    request = ServiceCoverageRequest(site_budget=2, max_distance_m=500)

    first = solve_service_coverage(scenario, request)
    second = solve_next_service_coverage_solution(scenario, request, first)
    exhausted = solve_next_service_coverage_solution(
        scenario,
        ServiceCoverageRequest(
            site_budget=2,
            max_distance_m=500,
            excluded_site_sets=(tuple(first["selected_site_ids"]),),
        ),
        second,
    )

    assert first["selected_site_ids"] in (["s1"], ["s2"])
    assert second["status"] == "verified_optimal"
    assert {first["selected_site_ids"][0], second["selected_site_ids"][0]} == {
        "s1",
        "s2",
    }
    assert second["objective_vector"] == first["objective_vector"]
    assert exhausted["status"] == "verified_unsat"
    assert exhausted["diagnostics"]["finding"] == "no_equal_objective_alternative"


def test_artifact_loader_preserves_display_and_provenance_contract() -> None:
    payload = {
        "scenario_id": "loader-test",
        "snapshot_id": "loader-test-1",
        "network_snapshot_id": "osm-2026-08-31",
        "distance_metric": "walking_network_m",
        "crs": {"analysis": "EPSG:3067", "display": "EPSG:4326"},
        "demand": [
            {
                "id": "d",
                "label": "Demand",
                "population": 12,
                "district_id": "district",
                "point": [24.8, 60.18],
            }
        ],
        "sites": [
            {
                "id": "s",
                "label": "Site",
                "capacity": 20,
                "geometry": {"type": "Point", "coordinates": [24.81, 60.18]},
            }
        ],
        "distances": [{"demand_id": "d", "site_id": "s", "distance_m": 400}],
        "metadata": {"licences": ["CC BY 4.0", "ODbL"]},
    }

    scenario = FrozenServiceCoverageScenario.from_artifact(payload)

    assert scenario.analysis_crs == "EPSG:3067"
    assert scenario.display_crs == "EPSG:4326"
    assert scenario.network_snapshot_id == "osm-2026-08-31"
    assert scenario.metadata["licences"] == ["CC BY 4.0", "ODbL"]


@pytest.mark.parametrize(
    ("coverage_request", "message"),
    [
        (ServiceCoverageRequest(capacity_multiplier=0), "capacity multiplier"),
        (ServiceCoverageRequest(forced_site_ids=("missing",)), "Unknown requested site"),
    ],
)
def test_invalid_requests_return_data_error(
    coverage_request: ServiceCoverageRequest, message: str
) -> None:
    result = solve_service_coverage(_scenario(), coverage_request)

    assert result["status"] == "data_error"
    assert message in result["message"]
