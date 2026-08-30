from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from services.scenario_builder.base_network import BaseNetworkBuildError
from services.solver.api import create_app
from services.solver.scenario_builder_api import BuilderSelection, ScenarioBuilderService

ROOT = Path(__file__).resolve().parents[3]


async def _wait_for_job(
    client: httpx.AsyncClient,
    job_id: str,
    terminal: set[str] | None = None,
) -> dict[str, Any]:
    terminal = terminal or {"verified", "cancelled", "failed", "missing_archive"}
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = await client.get(f"/api/scenario-builder/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in terminal:
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("scenario-builder job did not reach a terminal state")


@pytest.mark.asyncio
async def test_catalog_and_otaniemi_preflight_are_offline_and_leave_solver_unchanged(
    one_cut_scenario,
    tmp_path: Path,
) -> None:
    builder = ScenarioBuilderService(
        recipe_dir=ROOT / "data" / "recipes",
        source_dir=ROOT / "data" / "source" / "scenario-builder",
        derived_dir=tmp_path / "derived",
    )
    app = create_app(scenario=one_cut_scenario, scenario_builder=builder)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        catalog = (await client.get("/api/scenario-builder/catalog")).json()
        preflight = (await client.post("/api/scenario-builder/preflight", json={})).json()
        active = (await client.get("/api/scenario")).json()

    assert catalog["default_preset_id"] == "otaniemi-coastal-v1"
    assert catalog["active_solver"]["unchanged"] is True
    assert preflight["recipe"]["scenario_id"] == "espoo-otaniemi-coastal-base-v1"
    assert preflight["area"]["core_area_km2"] == pytest.approx(2.743, abs=0.001)
    assert preflight["offline_build_ready"] is True
    assert {source["adapter_id"] for source in preflight["sources"]} >= {
        "osm",
        "syke",
        "espoo_wfs",
    }
    assert preflight["semantics"]["flood_passability_inferred"] is False
    assert active["id"] == "synthetic"


def test_preflight_distinguishes_corrupt_archive_and_snapshot(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    osm_workspace = source_dir / "espoo-otaniemi-coastal-base-v1" / "osm"
    osm_workspace.mkdir(parents=True)
    (osm_workspace / "espoo-otaniemi-coastal-base-v1.osm-overpass.archive.json").write_text(
        "{}", encoding="utf-8"
    )
    output = tmp_path / "derived" / "espoo-otaniemi-coastal-base-v1-base-network"
    output.mkdir(parents=True)
    (output / "latest.json").write_text("{}", encoding="utf-8")

    def reject_snapshot(output_dir, recipe):
        raise BaseNetworkBuildError("test checksum mismatch")

    builder = ScenarioBuilderService(
        recipe_dir=ROOT / "data" / "recipes",
        source_dir=source_dir,
        derived_dir=tmp_path / "derived",
        snapshot_validator=reject_snapshot,
    )
    result = builder.preflight(BuilderSelection(preset_id="otaniemi-coastal-v1"))

    assert result["offline_build_ready"] is False
    assert result["sources"][0]["readiness"] == "invalid_archive"
    assert "integrity validation" in result["sources"][0]["message"]
    assert result["build"]["status"] == "invalid_snapshot"
    assert result["build"]["snapshot_id"] is None


@pytest.mark.asyncio
async def test_custom_location_preflight_is_bounded_and_does_not_fetch(
    one_cut_scenario,
    tmp_path: Path,
) -> None:
    empty_sources = tmp_path / "source"
    builder = ScenarioBuilderService(
        recipe_dir=ROOT / "data" / "recipes",
        source_dir=empty_sources,
        derived_dir=tmp_path / "derived",
    )
    app = create_app(scenario=one_cut_scenario, scenario_builder=builder)
    transport = httpx.ASGITransport(app=app)
    payload = {
        "area": {
            "kind": "point_radius",
            "longitude": 24.827,
            "latitude": 60.184,
            "radius_m": 900,
        }
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/scenario-builder/preflight", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["recipe"]["scenario_id"].startswith("finland-point-")
    assert body["offline_build_ready"] is False
    assert body["sources"][0]["readiness"] == "refresh_required"
    assert body["sources"][0]["spatial_coverage"] == "unknown"
    assert not empty_sources.exists()


@pytest.mark.asyncio
async def test_build_job_streams_events_and_returns_a_verified_artifact(
    one_cut_scenario,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, bool]] = []

    def runner(recipe, refresh, cancelled, emit):
        calls.append((recipe.scenario_id, refresh))
        emit("archive_loaded", "Frozen archive loaded.", {"features": 25_390})
        assert not cancelled.is_set()
        return {
            "snapshot_id": "base-test",
            "node_count": 100,
            "directed_edge_count": 220,
            "scope": "base_network_only",
        }

    builder = ScenarioBuilderService(
        recipe_dir=ROOT / "data" / "recipes",
        source_dir=tmp_path / "source",
        derived_dir=tmp_path / "derived",
        runner=runner,
    )
    app = create_app(scenario=one_cut_scenario, scenario_builder=builder)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        started = await client.post(
            "/api/scenario-builder/jobs", json={"preset_id": "otaniemi-coastal-v1"}
        )
        assert started.status_code == 202
        job = await _wait_for_job(client, started.json()["job_id"])
        events = (
            await client.get(
                f"/api/scenario-builder/jobs/{job['job_id']}/events", params={"after": 2}
            )
        ).json()

    assert calls == [("espoo-otaniemi-coastal-base-v1", False)]
    assert job["status"] == "verified"
    assert job["result"]["snapshot_id"] == "base-test"
    assert [event["sequence"] for event in job["events"]] == list(
        range(1, len(job["events"]) + 1)
    )
    assert all(event["sequence"] > 2 for event in events["events"])
    assert job["events"][-1]["type"] == "complete"


@pytest.mark.asyncio
async def test_live_refresh_requires_an_explicit_confirmation(one_cut_scenario) -> None:
    app = create_app(scenario=one_cut_scenario)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        rejected = await client.post(
            "/api/scenario-builder/jobs",
            json={"preset_id": "otaniemi-coastal-v1", "refresh": True},
        )

    assert rejected.status_code == 422
    assert "REFRESH_OSM" in rejected.text


@pytest.mark.asyncio
async def test_active_build_can_be_cancelled_at_a_safe_checkpoint(
    one_cut_scenario,
    tmp_path: Path,
) -> None:
    entered = threading.Event()

    def runner(recipe, refresh, cancelled, emit):
        entered.set()
        assert cancelled.wait(timeout=2)
        return {"cancelled": True}

    builder = ScenarioBuilderService(
        recipe_dir=ROOT / "data" / "recipes",
        source_dir=tmp_path / "source",
        derived_dir=tmp_path / "derived",
        runner=runner,
    )
    app = create_app(scenario=one_cut_scenario, scenario_builder=builder)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        started = await client.post(
            "/api/scenario-builder/jobs", json={"preset_id": "otaniemi-coastal-v1"}
        )
        job_id = started.json()["job_id"]
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set(), builder.get(job_id)
        cancellation = await client.post(f"/api/scenario-builder/jobs/{job_id}/cancel")
        job = await _wait_for_job(client, job_id)

    assert cancellation.status_code == 202
    assert cancellation.json()["accepted"] is True
    assert job["status"] == "cancelled"
    assert job["events"][-1]["type"] == "cancelled"
