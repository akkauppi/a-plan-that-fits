from __future__ import annotations

import hashlib
import json
from pathlib import Path

import networkx as nx
import pytest

from services.solver.service_coverage import (
    FrozenServiceCoverageScenario,
    ServiceCoverageRequest,
    solve_service_coverage,
)

ROOT = Path(__file__).resolve().parents[3]
SCENARIO_PATH = (
    ROOT / "data" / "derived" / "service-coverage-otaniemi-tapiola-v1" / "scenario.json"
)
MANIFEST_PATH = (
    ROOT
    / "data"
    / "source"
    / "service-coverage"
    / "otaniemi-tapiola-v1"
    / "source-manifest.json"
)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_frozen_service_coverage_sources_match_manifest_checksums() -> None:
    manifest = _read(MANIFEST_PATH)

    for artifact in manifest["artifacts"]:
        source_path = ROOT / artifact["path"]
        assert source_path.is_file()
        assert source_path.stat().st_size == artifact["byte_size"]
        assert hashlib.sha256(source_path.read_bytes()).hexdigest() == artifact["sha256"]


def test_frozen_service_coverage_contract_has_real_demand_and_declared_capacity() -> None:
    artifact = _read(SCENARIO_PATH)
    solver = artifact["solver"]
    browser = artifact["browser"]

    assert artifact["snapshot_id"] == "coverage-4e7e682613eb7d074b8a3341"
    assert len(solver["demand"]) == 33
    assert sum(cell["population"] for cell in solver["demand"]) == 8_554
    assert len(solver["sites"]) == 10
    assert len(solver["distances"]) == 330
    assert {site["capacity"] for site in solver["sites"]} == {5_000}
    assert all(site["capacity_status"] == "declared" for site in browser["candidate_sites"])
    assert all(
        site["capacity_basis"] == "analyst_declared_not_source_fact"
        for site in browser["candidate_sites"]
    )
    assert all(site["source"]["unit_id"] for site in browser["candidate_sites"])
    assert all(source["licence_url"] for source in browser["attribution_sources"])
    assert all(source["modifications"] for source in browser["attribution_sources"])
    assert browser["derived_processing"]
    assert set(cell["district_id"] for cell in solver["demand"]) == {
        "tapiola-west",
        "otaniemi-central",
        "otaniemi-east",
    }


def test_every_matrix_distance_matches_the_compact_walking_graph() -> None:
    solver = _read(SCENARIO_PATH)["solver"]
    graph = nx.DiGraph()
    graph.add_nodes_from(node["id"] for node in solver["network"]["nodes"])
    for edge in solver["network"]["edges"]:
        graph.add_edge(edge["from"], edge["to"], weight=edge["length_m"])

    demand = {cell["id"]: cell for cell in solver["demand"]}
    sites = {site["id"]: site for site in solver["sites"]}
    by_demand: dict[str, list[dict]] = {}
    for record in solver["distances"]:
        by_demand.setdefault(record["demand_id"], []).append(record)

    for demand_id, records in by_demand.items():
        distances = nx.single_source_dijkstra_path_length(
            graph, demand[demand_id]["node_id"], weight="weight"
        )
        for record in records:
            site = sites[record["site_id"]]
            assert abs(distances[site["node_id"]] - record["network_distance_m"]) <= 0.01
            assert record["demand_connector_m"] == demand[demand_id]["snap_distance_m"]
            assert record["site_connector_m"] == site["snap_distance_m"]
            assert record["distance_m"] == pytest.approx(
                record["demand_connector_m"]
                + record["network_distance_m"]
                + record["site_connector_m"],
                abs=0.001,
            )
            assert record["connector_method"] == "straight_line_projected_euclidean"
            assert record["route"]["geometry"]["type"] == "LineString"
            coordinates = record["route"]["geometry"]["coordinates"]
            assert coordinates[0] == demand[demand_id]["point"]
            assert coordinates[-1] == site["point"]
            assert record["route_node_ids"][0] == demand[demand_id]["node_id"]
            assert record["route_node_ids"][-1] == site["node_id"]
            assert len(record["route_edge_ids"]) == len(record["route_node_ids"]) - 1


def test_default_capacity_has_a_clear_budget_sensitivity() -> None:
    solver = _read(SCENARIO_PATH)["solver"]
    population = sum(cell["population"] for cell in solver["demand"])
    capacity = solver["sites"][0]["capacity"]

    assert capacity < population
    assert solver["defaults"]["site_budget"] == 4
    assert solver["defaults"]["site_budget"] * capacity >= population
    assert solver["defaults"]["max_distance_m"] == 1_600


def test_frozen_default_request_is_freshly_verified() -> None:
    solver = _read(SCENARIO_PATH)["solver"]
    scenario = FrozenServiceCoverageScenario.from_artifact(solver)

    result = solve_service_coverage(
        scenario,
        ServiceCoverageRequest(
            site_budget=solver["defaults"]["site_budget"],
            max_distance_m=solver["defaults"]["max_distance_m"],
            capacity_multiplier=solver["defaults"]["capacity_multiplier"],
            timeout_seconds=solver["defaults"]["timeout_seconds"],
        ),
    )

    assert result["status"] == "verified_optimal"
    assert result["verification"]["verified"] is True
    assert result["verification"]["summary"]["assigned_cells"] == 33
    assert result["verification"]["summary"]["population"] == 8_554
    assert len(result["selected_site_ids"]) <= 4
    assert result["objective_values"]["worst_distance_m"] <= 1_600


def test_frozen_budget_one_has_explainable_capacity_unsat() -> None:
    solver = _read(SCENARIO_PATH)["solver"]
    scenario = FrozenServiceCoverageScenario.from_artifact(solver)

    result = solve_service_coverage(
        scenario,
        ServiceCoverageRequest(
            site_budget=1,
            max_distance_m=solver["defaults"]["max_distance_m"],
            capacity_multiplier=1,
            timeout_seconds=10,
        ),
    )

    assert result["status"] == "verified_unsat"
    assert result["diagnostics"]["finding"] == "insufficient_capacity_under_budget"
    assert result["diagnostics"]["capacity_bound"] == {
        "included_population": 8_554,
        "maximum_capacity_under_budget": 5_000,
    }
    assert "increase_site_budget" in result["diagnostics"]["suggested_relaxations"]
