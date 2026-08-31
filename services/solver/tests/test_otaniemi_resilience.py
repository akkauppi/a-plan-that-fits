from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import math
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from shapely.geometry import Point, shape

from services.solver.api import create_app
from services.solver.otaniemi_resilience import OtaniemiResilienceService


@pytest.fixture(scope="module")
def otaniemi_service() -> OtaniemiResilienceService:
    return OtaniemiResilienceService()


@pytest.fixture(scope="module")
def otaniemi_payload(otaniemi_service: OtaniemiResilienceService) -> dict[str, Any]:
    return otaniemi_service.scenario_payload()


@pytest.fixture(scope="module")
def teaching_result(
    otaniemi_service: OtaniemiResilienceService,
    otaniemi_payload: dict[str, Any],
) -> dict[str, Any]:
    defaults = otaniemi_payload["defaults"]
    events: list[dict[str, Any]] = []
    result = otaniemi_service.solve(
        origin_ids=defaults["origin_ids"],
        gateway_group_ids=defaults["gateway_group_ids"],
        flood_return_period_years=defaults["flood_return_period_years"],
        treat_flood_exposure_as_unavailable=(
            defaults["treat_flood_exposure_as_unavailable"]
        ),
        roadworks_segment_ids=[],
        analytical_repair_budget=defaults["analytical_repair_budget"],
        timeout_seconds=defaults["timeout_seconds"],
        cancel_event=threading.Event(),
        on_event=events.append,
    )
    result["test_streamed_events"] = events
    return result


def _sse_events(response: httpx.Response) -> list[dict[str, Any]]:
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_frozen_scenario_provenance_and_effective_car_counts_are_explicit(
    otaniemi_service: OtaniemiResilienceService,
    otaniemi_payload: dict[str, Any],
) -> None:
    assert otaniemi_service.network.base_snapshot_id == (
        "base-c8dcbcfaca2b2c9498420681"
    )
    assert otaniemi_service.network.flood_snapshot_id == (
        "flood-bf45a84ac9ce456045f8932b"
    )
    assert otaniemi_payload["snapshot_id"] == (
        "base-c8dcbcfaca2b2c9498420681+flood-bf45a84ac9ce456045f8932b+"
        "espoo-0c59d1ca21a9e918b058"
    )
    components = otaniemi_payload["snapshot_components"]
    assert components["base_network"] == {
        "snapshot_id": "base-c8dcbcfaca2b2c9498420681",
        "metadata_sha256": (
            "644f548df436f749b4ec8195856599bb646d9b12050db9378d6c5042e9e57ea1"
        ),
        "artifact": {
            "file": "base-network.json",
            "sha256": (
                "80aa8240024c9c2f8a470e5532cbeeadf592ac493d5861182a2e076874949dca"
            ),
            "byte_size": 23_779_387,
        },
    }
    assert components["flood_exposure"]["snapshot_id"] == (
        "flood-bf45a84ac9ce456045f8932b"
    )
    assert [
        artifact["sha256"]
        for artifact in components["flood_exposure"]["artifacts"]
    ] == [
        "a655dd110f012a4e1f2e71df3fa6306b49d71cddb49da25fc7c787983b2ae850",
        "97efb3c1d193b242b327a50cb6f489c4c7b42f24b0e1288c45414ba70b865a8a",
    ]
    municipal = components["municipal_evidence"]
    assert municipal["snapshot_id"] == "espoo-0c59d1ca21a9e918b058"
    assert municipal["manifest_sha256"] == (
        "73b37339d31902ed46604f5513da0c1fa9d892b0bbe66cd9eeab51307b464da8"
    )
    assert municipal["origin_derivation"]["snapped_to_snapshot_id"] == (
        "base-c8dcbcfaca2b2c9498420681"
    )
    assert municipal["layers"]["addresses"]["archive_sha256"] == (
        "4399b9cb54fe9b269bbc4b79e009195959415586693634a1fcb4bc75d35d633e"
    )
    assert municipal["layers"]["buildings"]["archive_sha256"] == (
        "1c2490d6f3704d819132876df2d067d82646eaf51fc8c7707436307f197e1ad2"
    )
    assert otaniemi_payload["counts"]["private_car_exposed_segments"] == {
        "100": 241,
        "1000": 528,
    }
    assert otaniemi_payload["counts"]["source_exposed_segments"] == {
        "100": 892,
        "1000": 1_608,
    }
    assert {
        period: len(segment_ids)
        for period, segment_ids in otaniemi_service.network.exposed_segment_ids.items()
    } == {100: 892, 1000: 1_608}

    semantics = otaniemi_payload["semantics"]
    assert semantics["exposure_is_closure"] is False
    assert semantics["closure_requires_explicit_user_assumption"] is True
    assert semantics["gateway_is_certified_safe_destination"] is False
    assert semantics["selected_decision_is_passability_finding"] is False
    assert "MML terrain" in otaniemi_payload["attribution"]
    assert "not used to close a road" in otaniemi_payload["attribution"]


def test_espoo_archives_are_rejected_when_declared_hash_is_wrong(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "addresses.gml.gz"
    raw_content = b"frozen municipal evidence"
    archive.write_bytes(gzip.compress(raw_content, mtime=0))
    actual_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    layer = {
        "layer": "GIS:Osoitteet",
        "archive_file": archive.name,
        "archive_sha256": actual_sha256,
        "raw_sha256": hashlib.sha256(raw_content).hexdigest(),
        "byte_size": archive.stat().st_size,
    }
    service = OtaniemiResilienceService(
        espoo_dir=tmp_path,
        espoo_pointer=tmp_path / "manifest.json",
    )
    resolved, declaration = service._espoo_archive({"layers": [layer]}, "GIS:Osoitteet")
    assert resolved == archive
    assert declaration is layer

    tampered = {**layer, "archive_sha256": "0" * 64}
    with pytest.raises(ValueError, match="SHA-256 does not match"):
        service._espoo_archive({"layers": [tampered]}, "GIS:Osoitteet")

    tampered_raw = {**layer, "raw_sha256": "0" * 64}
    with pytest.raises(ValueError, match="raw content SHA-256 does not match"):
        service._espoo_archive({"layers": [tampered_raw]}, "GIS:Osoitteet")


def test_browser_geometries_and_all_stable_references_resolve(
    otaniemi_payload: dict[str, Any],
) -> None:
    network_features = [
        feature
        for feature in otaniemi_payload["base_network"]["features"]
        if feature["properties"]["layer"] == "base_network"
    ]
    network_ids = {
        feature["properties"]["physical_segment_id"] for feature in network_features
    }
    assert len(network_ids) == otaniemi_payload["counts"][
        "private_car_physical_segments"
    ]
    assert all(
        feature["properties"]["physical_segment_id"] in network_ids
        for feature in otaniemi_payload["flood_exposure"]["features"]
    )
    assert all(
        feature["properties"]["geometry_semantics"]
        == "clipped horizontal intersection only"
        and feature["properties"]["passability_not_inferred"] is True
        for feature in otaniemi_payload["flood_exposure"]["features"]
    )
    assert all(
        segment_id in network_ids
        for groups in otaniemi_payload["decision_groups_by_return_period"].values()
        for group in groups
        for segment_id in group["segment_ids"]
    )
    assert len(otaniemi_payload["buildings"]["features"]) == 1_189


def test_representative_origins_are_inside_core_and_reviewably_snapped(
    otaniemi_service: OtaniemiResilienceService,
    otaniemi_payload: dict[str, Any],
) -> None:
    origins = otaniemi_payload["origins"]
    core = shape(otaniemi_payload["core_boundary"])
    assert len(origins) == 15
    assert sum(origin["address_count"] for origin in origins) == 297
    assert all(origin["node_id"] in otaniemi_service.network.nodes for origin in origins)
    assert all(
        core.covers(Point(*origin["requested_point"])) for origin in origins
    )
    assert all(
        math.isfinite(origin["snap_distance_m"])
        and origin["snap_distance_m"] <= 60
        for origin in origins
    )
    assert all(origin["aggregation"].startswith("deterministic 500 m") for origin in origins)


def test_reviewed_gateways_are_exact_outbound_nodes_and_access_is_an_or_requirement(
    otaniemi_service: OtaniemiResilienceService,
    otaniemi_payload: dict[str, Any],
) -> None:
    expected_nodes = {
        "gateway-east-kuusisaarentie": "osm-boundary-7b941de776af6b9c",
        "gateway-south-tapiolantie": "osm-boundary-c97c13269991761e",
        "gateway-west-kalevalantie": "osm-boundary-3794e75dd2e13051",
        "gateway-north-keha-i": "osm-boundary-bcf840a7014acbf0",
    }
    gateways = {group.id: group for group in otaniemi_service.gateway_groups}
    assert set(gateways) == set(expected_nodes)
    for gateway_id, node_id in expected_nodes.items():
        destination = gateways[gateway_id].destinations[0]
        assert destination.node_id == node_id
        assert any(
            edge.private_car and edge.target == node_id
            for edge in otaniemi_service.network.edges
        )

    origins, destinations, _groups = otaniemi_service.resolve_study(
        origin_ids=[origin["id"] for origin in otaniemi_payload["origins"]],
        gateway_group_ids=list(expected_nodes),
        period=1000,
        roadworks_segment_ids=[],
    )
    destination_ids = tuple(destination.id for destination in destinations)
    assert len(destination_ids) == 4
    assert all(origin.allowed_destination_ids == destination_ids for origin in origins)
    baseline = otaniemi_service.network
    analysis = otaniemi_payload["default_disruption_analysis"]
    assert baseline.scenario_id == "espoo-otaniemi-coastal-base-v1"
    assert analysis["summary"]["baseline_unreachable"] == 0


@pytest.mark.parametrize("period", [100, 1000])
def test_continuity_groups_are_disjoint_visible_aggregation_units(
    otaniemi_service: OtaniemiResilienceService,
    period: int,
) -> None:
    groups = otaniemi_service.corridor_groups[period]
    physical_edges = otaniemi_service._physical_edges()
    effective_exposed = (
        otaniemi_service.network.exposed_segment_ids[period] & physical_edges.keys()
    )
    seen: set[str] = set()
    for group in groups:
        members = set(group.decision.segment_ids)
        assert members
        assert not members & seen
        assert members <= effective_exposed
        assert group.decision.cost == max(1, round(group.length_m))
        assert group.point and all(math.isfinite(value) for value in group.point)
        seen.update(members)
    assert seen == effective_exposed


def test_declared_roadworks_are_fixed_and_never_become_decision_members(
    otaniemi_service: OtaniemiResilienceService,
    otaniemi_payload: dict[str, Any],
) -> None:
    first_group = otaniemi_service.corridor_groups[1000][0]
    roadwork_id = first_group.decision.segment_ids[0]
    defaults = otaniemi_payload["defaults"]
    _origins, _destinations, dynamic_groups = otaniemi_service.resolve_study(
        origin_ids=defaults["origin_ids"],
        gateway_group_ids=defaults["gateway_group_ids"],
        period=1000,
        roadworks_segment_ids=[roadwork_id],
    )
    decision_members = {
        segment_id
        for group in dynamic_groups
        for segment_id in group.decision.segment_ids
    }
    assert roadwork_id not in decision_members


def test_disabled_flood_closure_has_no_decision_variables_or_selected_links(
    otaniemi_service: OtaniemiResilienceService,
    otaniemi_payload: dict[str, Any],
) -> None:
    defaults = otaniemi_payload["defaults"]
    result = otaniemi_service.solve(
        origin_ids=defaults["origin_ids"],
        gateway_group_ids=defaults["gateway_group_ids"],
        flood_return_period_years=1000,
        treat_flood_exposure_as_unavailable=False,
        roadworks_segment_ids=[],
        analytical_repair_budget=4,
        timeout_seconds=10,
        cancel_event=threading.Event(),
    )
    assert result["status"] == "verified_optimal"
    assert result["verified"] is True
    assert result["decision_groups"] == []
    assert result["selected_decision_ids"] == []
    assert result["selected_segment_ids"] == []
    assert result["objective_values"]["decision_group_count"] == 0
    assert result["verification"]["effective_unavailable_private_car_segment_count"] == 0


@pytest.mark.parametrize(
    ("timeout_seconds", "cancel_before_start", "expected_status"),
    [(0.0, False, "timeout"), (30.0, True, "cancelled")],
)
def test_otaniemi_request_control_covers_initial_disruption_analysis(
    otaniemi_service: OtaniemiResilienceService,
    otaniemi_payload: dict[str, Any],
    timeout_seconds: float,
    cancel_before_start: bool,
    expected_status: str,
) -> None:
    defaults = otaniemi_payload["defaults"]
    cancellation = threading.Event()
    if cancel_before_start:
        cancellation.set()
    result = otaniemi_service.solve(
        origin_ids=defaults["origin_ids"],
        gateway_group_ids=defaults["gateway_group_ids"],
        flood_return_period_years=defaults["flood_return_period_years"],
        treat_flood_exposure_as_unavailable=True,
        roadworks_segment_ids=[],
        analytical_repair_budget=4,
        timeout_seconds=timeout_seconds,
        cancel_event=cancellation,
    )

    assert result["status"] == expected_status
    assert result["verified"] is False
    assert result["diagnostics"]["interrupted_phase"] == "otaniemi_request_setup"
    assert "baseline_disruption_analysis" not in result
    assert result["elapsed_ms"] >= 0


def test_teaching_preset_refines_then_freshly_verifies_group_and_fragment_counts(
    teaching_result: dict[str, Any],
) -> None:
    assert teaching_result["snapshot_id"].endswith("espoo-0c59d1ca21a9e918b058")
    assert teaching_result["snapshot_components"]["municipal_evidence"][
        "snapshot_id"
    ] == "espoo-0c59d1ca21a9e918b058"
    assert teaching_result["status"] == "verified_optimal"
    assert teaching_result["verified"] is True
    assert teaching_result["objective_values"] == {
        "analytical_repairs": 3,
        "decision_group_count": 3,
        "decision_group_cost": 388,
        "expanded_segment_count": 21,
    }
    selected_decisions = teaching_result["selected_decisions"]
    selected_segment_ids = teaching_result["selected_segment_ids"]
    assert len(selected_decisions) == 3
    assert len(selected_segment_ids) == 21
    assert sorted(
        segment_id
        for decision in selected_decisions
        for segment_id in decision["segment_ids"]
    ) == selected_segment_ids
    assert any(decision["highway"] == "service" for decision in selected_decisions)

    verification = teaching_result["verification"]
    assert verification["verified"] is True
    assert verification["method"] == "fresh_networkx_directed_graph"
    assert all(verification["origin_access"].values())
    remaining_unavailable = set(
        teaching_result["baseline_disruption_analysis"]["assumption"][
            "effective_unavailable_private_car_segment_ids"
        ]
    ) - set(selected_segment_ids)
    for access in teaching_result["analysis"]["access"]:
        assert access["status"] == "retained"
        assert not (
            set(access["disrupted_route"]["physical_segment_ids"])
            & remaining_unavailable
        )

    events = teaching_result["test_streamed_events"]
    assert events == teaching_result["iterations"]
    assert [event["type"] for event in events].count("access_cut_found") == 3
    assert events[-1]["type"] == "candidate"
    assert events[-1]["selected_decision_ids"] == teaching_result[
        "selected_decision_ids"
    ]
    for event in events:
        if event["type"] != "access_cut_found":
            continue
        assert event["frontier_decision_ids"]
        assert event["constraint"]["kind"] == "at_least_one"
        assert all(
            variable.startswith("passable[")
            for variable in event["constraint"]["variable_ids"]
        )
        assert event["diagnostic_route"] is not None


class _ImmediateResilienceService:
    def scenario_payload(self) -> dict[str, Any]:
        return {"id": "otaniemi-access-v1", "snapshot_id": "frozen-test"}

    def solve(
        self,
        *,
        cancel_event: threading.Event,
        on_event: Callable[[dict[str, Any]], None],
        **_settings: Any,
    ) -> dict[str, Any]:
        assert not cancel_event.is_set()
        on_event(
            {
                "type": "candidate",
                "iteration": 1,
                "selected_decision_ids": ["zone-a"],
                "selected_segment_ids": ["link-a"],
                "access_summary": {"retained": 0, "stranded": 1},
            }
        )
        on_event(
            {
                "type": "access_cut_found",
                "iteration": 1,
                "origin_id": "origin-a",
                "origin_label": "Otaranta",
                "frontier_decision_ids": ["zone-b"],
                "frontier_segment_ids": ["link-b"],
                "constraint": {
                    "kind": "at_least_one",
                    "variable_ids": ["passable[zone-b]"],
                },
                "diagnostic_route": {
                    "unavailable_segment_ids": ["witness-link"],
                    "feature": {
                        "type": "Feature",
                        "properties": {"role": "diagnostic_witness"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[24.8, 60.1], [24.9, 60.2]],
                        },
                    },
                },
            }
        )
        return {
            "status": "verified_optimal",
            "verified": True,
            "message": "Fresh graph verification retained access.",
            "selected_decision_ids": ["zone-b"],
            "selected_segment_ids": ["link-b"],
            "verification": {
                "verified": True,
                "method": "fresh_networkx_directed_graph",
            },
        }


@pytest.mark.asyncio
async def test_resilience_sse_stream_exposes_candidates_witnesses_clauses_and_result(
    one_cut_scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    solve_id = "00000000-0000-0000-0000-000000000777"
    monkeypatch.setattr("services.solver.api.uuid.uuid4", lambda: solve_id)
    app = create_app(
        scenario=one_cut_scenario,
        resilience_service=_ImmediateResilienceService(),  # type: ignore[arg-type]
    )
    transport = httpx.ASGITransport(app=app)
    request = {
        "scenario_id": "otaniemi-access-v1",
        "flood_return_period_years": 1000,
        "treat_flood_exposure_as_unavailable": True,
        "roadworks_segment_ids": [],
        "origin_ids": ["origin-a"],
        "gateway_group_ids": ["gateway-east-kuusisaarentie"],
        "analytical_repair_budget": 4,
        "timeout_seconds": 30,
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        scenario_response = await client.get("/api/resilience/scenario")
        response = await client.post("/api/resilience/solve", json=request)

    assert scenario_response.json() == {
        "id": "otaniemi-access-v1",
        "snapshot_id": "frozen-test",
    }
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-solve-id"] == solve_id
    events = _sse_events(response)
    assert [event["sequence"] for event in events] == [1, 2, 3, 4]
    assert [event["type"] for event in events] == [
        "started",
        "candidate_found",
        "counterexample_found",
        "verified_optimal",
    ]
    assert events[1]["message"].startswith("Z3 proposed 1 continuity commitment")
    counterexample = events[2]
    assert counterexample["route"]["properties"]["role"] == "diagnostic_witness"
    assert counterexample["witness_segment_ids"] == ["witness-link"]
    assert counterexample["learned_clause_ids"] == ["zone-b"]
    assert counterexample["constraint_expression"] == "passable[zone-b]"
    terminal = events[-1]
    assert terminal["result"]["verified"] is True
    assert terminal["result"]["solve_id"] == solve_id


class _CancellableResilienceService:
    def __init__(self) -> None:
        self.entered = threading.Event()

    def scenario_payload(self) -> dict[str, Any]:
        return {"id": "otaniemi-access-v1"}

    def solve(
        self,
        *,
        cancel_event: threading.Event,
        on_event: Callable[[dict[str, Any]], None],
        **_settings: Any,
    ) -> dict[str, Any]:
        self.entered.set()
        if not cancel_event.wait(timeout=3):
            raise AssertionError("test did not request cancellation")
        on_event({"type": "cancelled", "message": "Cancellation observed."})
        return {
            "status": "cancelled",
            "verified": False,
            "message": "Cancelled; no feasibility claim was made.",
        }


@pytest.mark.asyncio
async def test_resilience_stream_can_be_cancelled_without_an_unsat_claim(
    one_cut_scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    solve_id = "00000000-0000-0000-0000-000000000778"
    monkeypatch.setattr("services.solver.api.uuid.uuid4", lambda: solve_id)
    service = _CancellableResilienceService()
    app = create_app(
        scenario=one_cut_scenario,
        resilience_service=service,  # type: ignore[arg-type]
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        solve_task = asyncio.create_task(
            client.post(
                "/api/resilience/solve",
                json={
                    "origin_ids": ["origin-a"],
                    "gateway_group_ids": ["gateway-east-kuusisaarentie"],
                },
            )
        )
        assert await asyncio.to_thread(service.entered.wait, 2)
        cancellation = await client.post(
            "/api/resilience/solve/cancel", json={"solve_id": solve_id}
        )
        response = await asyncio.wait_for(solve_task, timeout=5)

    assert cancellation.status_code == 202
    assert cancellation.json() == {
        "status": "cancellation_requested",
        "solve_id": solve_id,
        "accepted": True,
    }
    events = _sse_events(response)
    assert events[-1]["type"] == "cancelled"
    assert events[-1]["result"]["verified"] is False
    assert all(event["type"] != "verified_unsat" for event in events)


class _FailingResilienceService:
    def scenario_payload(self) -> dict[str, Any]:
        raise ValueError("frozen evidence missing")

    def solve(self, **_settings: Any) -> dict[str, Any]:
        raise ValueError("unknown frozen segment")


@pytest.mark.asyncio
async def test_resilience_data_errors_are_not_presented_as_unsat(one_cut_scenario) -> None:
    app = create_app(
        scenario=one_cut_scenario,
        resilience_service=_FailingResilienceService(),  # type: ignore[arg-type]
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        scenario_response = await client.get("/api/resilience/scenario")
        solve_response = await client.post(
            "/api/resilience/solve",
            json={
                "origin_ids": ["invented-origin"],
                "gateway_group_ids": ["invented-gateway"],
            },
        )

    assert scenario_response.status_code == 503
    assert scenario_response.json()["detail"] == {
        "status": "data_error",
        "message": "frozen evidence missing",
    }
    events = _sse_events(solve_response)
    assert events[-1]["type"] == "data_error"
    assert events[-1]["result"]["verified"] is False
    assert "ValueError: unknown frozen segment" in events[-1]["result"]["message"]
    assert all(event["type"] != "verified_unsat" for event in events)
