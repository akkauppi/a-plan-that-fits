from __future__ import annotations

import json

import httpx
import pytest

from services.solver.api import create_app
from services.solver.service_coverage_api import ServiceCoverageService


def _artifact() -> dict:
    return {
        "scenario_id": "service-test-v1",
        "snapshot_id": "service-test-snapshot",
        "distance_metric": "walking_network_m",
        "crs": {"analysis": "EPSG:3067", "display": "EPSG:4326"},
        "network_snapshot_id": "walking-test-v1",
        "demand": [
            {
                "id": "cell-a",
                "label": "Cell A",
                "population": 100,
                "district_id": "north",
                "point": [24.82, 60.18],
                "node_id": "n0",
                "snap_distance_m": 0,
            }
        ],
        "sites": [
            {
                "id": "site-near",
                "label": "Near site",
                "capacity": 200,
                "point": [24.821, 60.18],
                "node_id": "n1",
                "snap_distance_m": 0,
            },
            {
                "id": "site-far",
                "label": "Far site",
                "capacity": 200,
                "point": [24.822, 60.18],
                "node_id": "n2",
                "snap_distance_m": 0,
            },
        ],
        "distances": [
            {
                "demand_id": "cell-a",
                "site_id": "site-near",
                "distance_m": 100,
                "demand_connector_m": 0,
                "network_distance_m": 100,
                "site_connector_m": 0,
                "connector_method": "straight_line_projected_euclidean",
                "route_node_ids": ["n0", "n1"],
                "route_edge_ids": ["edge-near"],
                "route": {
                    "type": "Feature",
                    "properties": {
                        "demand_id": "cell-a",
                        "site_id": "site-near",
                        "distance_m": 100,
                        "demand_connector_m": 0,
                        "network_distance_m": 100,
                        "site_connector_m": 0,
                        "connector_method": "straight_line_projected_euclidean",
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[24.82, 60.18], [24.821, 60.18]],
                    },
                },
            },
            {
                "demand_id": "cell-a",
                "site_id": "site-far",
                "distance_m": 120,
                "demand_connector_m": 0,
                "network_distance_m": 120,
                "site_connector_m": 0,
                "connector_method": "straight_line_projected_euclidean",
                "route_node_ids": ["n0", "n2"],
                "route_edge_ids": ["edge-far"],
                "route": {
                    "type": "Feature",
                    "properties": {
                        "demand_id": "cell-a",
                        "site_id": "site-far",
                        "distance_m": 120,
                        "demand_connector_m": 0,
                        "network_distance_m": 120,
                        "site_connector_m": 0,
                        "connector_method": "straight_line_projected_euclidean",
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[24.82, 60.18], [24.822, 60.18]],
                    },
                },
            },
        ],
        "network": {
            "directed": True,
            "nodes": [
                {"id": "n0", "point": [24.82, 60.18]},
                {"id": "n1", "point": [24.821, 60.18]},
                {"id": "n2", "point": [24.822, 60.18]},
            ],
            "edges": [
                {
                    "id": "edge-near",
                    "from": "n0",
                    "to": "n1",
                    "length_m": 100,
                    "geometry": [[24.82, 60.18], [24.821, 60.18]],
                },
                {
                    "id": "edge-far",
                    "from": "n0",
                    "to": "n2",
                    "length_m": 120,
                    "geometry": [[24.82, 60.18], [24.822, 60.18]],
                },
            ],
        },
        "browser": {
            "id": "service-test-v1",
            "name": "Service test",
            "description": "Synthetic API contract fixture.",
            "snapshot_id": "service-test-snapshot",
            "snapshot_timestamp": "2026-09-01T00:00:00Z",
            "bbox": [24.81, 60.17, 24.83, 60.19],
            "center": [24.82, 60.18],
            "network": {"type": "FeatureCollection", "features": []},
            "population_cells": [],
            "candidate_sites": [],
            "defaults": {
                "site_budget": 1,
                "max_distance_m": 1_200,
                "capacity_multiplier": 1,
                "timeout_seconds": 30,
            },
            "methodology": "Fixture only.",
            "attribution": "Fixture only.",
        },
    }


def _events(response: httpx.Response) -> list[dict]:
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.asyncio
async def test_service_coverage_scenario_and_verified_stream(one_cut_scenario) -> None:
    service = ServiceCoverageService(artifact=_artifact())
    transport = httpx.ASGITransport(
        app=create_app(
            scenario=one_cut_scenario,
            service_coverage_service=service,
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        scenario = await client.get("/api/service-coverage/scenario")
        response = await client.post(
            "/api/service-coverage/solve",
            json={
                "scenario_id": "service-test-v1",
                "site_budget": 1,
                "max_distance_m": 1_200,
                "capacity_multiplier": 1,
                "forced_site_ids": [],
                "banned_site_ids": [],
                "timeout_seconds": 5,
            },
        )

    assert scenario.status_code == 200
    assert scenario.json()["snapshot_id"] == "service-test-snapshot"
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-solve-id"]
    events = _events(response)
    event_types = [event["type"] for event in events]
    assert event_types[0] == "started"
    assert "matrix_compiled" in event_types
    assert "feasible_assignment" in event_types
    assert "fresh_verification" in event_types
    result = events[-1]["result"]
    assert result["status"] == "verified_optimal"
    assert result["selected_site_ids"] == ["site-near"]
    assert result["verification"]["verified"] is True
    assert result["snapshot_id"] == "service-test-snapshot"


@pytest.mark.asyncio
async def test_service_coverage_unsat_and_validation_are_distinct(one_cut_scenario) -> None:
    service = ServiceCoverageService(artifact=_artifact())
    transport = httpx.ASGITransport(
        app=create_app(
            scenario=one_cut_scenario,
            service_coverage_service=service,
        )
    )
    base = {
        "scenario_id": "service-test-v1",
        "site_budget": 1,
        "max_distance_m": 1_200,
        "capacity_multiplier": 0.1,
        "forced_site_ids": [],
        "banned_site_ids": [],
        "timeout_seconds": 5,
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unsat_response = await client.post("/api/service-coverage/solve", json=base)
        invalid_response = await client.post(
            "/api/service-coverage/solve",
            json={
                **base,
                "forced_site_ids": ["site-near"],
                "banned_site_ids": ["site-near"],
            },
        )
        missing_cancel = await client.post(
            "/api/service-coverage/solve/cancel", json={"solve_id": "missing"}
        )

    result = _events(unsat_response)[-1]["result"]
    assert result["status"] == "verified_unsat"
    assert result["diagnostics"]["unsat_core"]
    assert invalid_response.status_code == 422
    assert missing_cancel.status_code == 404
    assert missing_cancel.json()["accepted"] is False
