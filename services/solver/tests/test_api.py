from __future__ import annotations

import asyncio
import json
import threading

import httpx
import pytest

from services.solver.api import create_app


def _events(response) -> list[dict]:
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


@pytest.mark.asyncio
async def test_health_and_scenario_contract(one_cut_scenario) -> None:
    transport = httpx.ASGITransport(app=create_app(scenario=one_cut_scenario))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["ready"] is True
        scenario = (await client.get("/api/scenario")).json()
        assert scenario["snapshot_id"] == "synthetic-v1"
        assert scenario["stats"]["candidate_interventions"] == 1


@pytest.mark.asyncio
async def test_sse_solve_and_next_solution_contract() -> None:
    from .conftest import synthetic_scenario, undirected

    scenario = synthetic_scenario(
        [
            *undirected("west-a", "W", "A", "c1"),
            *undirected("a-east", "A", "E", "c2"),
        ]
    )
    transport = httpx.ASGITransport(app=create_app(scenario=scenario))
    payload = {
        "scenario_id": "synthetic",
        "budget": 4,
        "required_portal_pairs": [{"a": "west", "b": "east"}],
        "forced_interventions": [],
        "locked_open_streets": [],
        "emergency_permeable": True,
        "objective_mode": "fewest",
        "timeout_seconds": 5,
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/solve", json=payload)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _events(response)
        assert events[-1]["type"] == "complete"
        first_result = events[-1]["result"]
        assert first_result["status"] == "verified_optimal"
        next_response = await client.post(
            "/api/solutions/next", json={**payload, "solve_id": first_result["solve_id"]}
        )
        next_result = _events(next_response)[-1]["result"]
        assert next_result["status"] == "verified_optimal"
        assert next_result["selected_intervention_ids"] != first_result["selected_intervention_ids"]
        assert next_result["objective_values"] == first_result["objective_values"]


@pytest.mark.asyncio
async def test_json_endpoint_always_returns_final_result(one_cut_scenario) -> None:
    transport = httpx.ASGITransport(app=create_app(scenario=one_cut_scenario))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/solve/json",
            json={
                "scenario_id": "synthetic",
                "budget": 4,
                "required_portal_pairs": [["west", "east"]],
                "objective_mode": "access",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["events"][-1]["type"] == "complete"
        assert body["result"]["verification_status"] == "independently_verified"


@pytest.mark.asyncio
async def test_cancel_unknown_solve_is_explicit(one_cut_scenario) -> None:
    transport = httpx.ASGITransport(app=create_app(scenario=one_cut_scenario))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/solve/cancel", json={"solve_id": "missing"})
        assert response.status_code == 404
        assert response.json()["status"] == "not_active"


@pytest.mark.asyncio
async def test_active_stream_can_be_cancelled_cooperatively(one_cut_scenario, monkeypatch) -> None:
    app = create_app(scenario=one_cut_scenario)
    solve_id = "00000000-0000-0000-0000-000000000042"
    monkeypatch.setattr("services.solver.api.uuid.uuid4", lambda: solve_id)
    entered_verifier = threading.Event()
    release_verifier = threading.Event()
    original_counterexamples = app.state.engine._counterexample_batch

    def paused_counterexamples(*args, **kwargs):
        entered_verifier.set()
        if not release_verifier.wait(timeout=5):
            raise AssertionError("test did not release the graph verifier")
        return original_counterexamples(*args, **kwargs)

    monkeypatch.setattr(app.state.engine, "_counterexample_batch", paused_counterexamples)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        solve_task = asyncio.create_task(
            client.post(
                "/api/solve",
                json={
                    "scenario_id": "synthetic",
                    "budget": 4,
                    "required_portal_pairs": [["west", "east"]],
                    "timeout_seconds": 5,
                },
            )
        )
        try:
            assert await asyncio.to_thread(entered_verifier.wait, 2)
            cancellation = await client.post("/api/solve/cancel", json={"solve_id": solve_id})
            assert cancellation.status_code == 202
            assert cancellation.json() == {
                "status": "cancellation_requested",
                "solve_id": solve_id,
                "accepted": True,
            }
        finally:
            release_verifier.set()

        response = await asyncio.wait_for(solve_task, timeout=5)

    events = _events(response)
    assert [event["type"] for event in events[-2:]] == ["cancelled", "complete"]
    assert events[-1]["result"]["status"] == "cancelled"
    assert events[-1]["result"]["verification_status"] == "not_verified"


@pytest.mark.asyncio
async def test_service_access_request_is_rejected_as_unsupported(one_cut_scenario) -> None:
    transport = httpx.ASGITransport(app=create_app(scenario=one_cut_scenario))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/solve",
            json={
                "scenario_id": "synthetic",
                "service_access_enabled": True,
            },
        )
        next_response = await client.post(
            "/api/solutions/next",
            json={"solve_id": "any-prior-run", "service_access_enabled": True},
        )

    assert response.status_code == 422
    issue = response.json()["detail"][0]
    assert issue["loc"] == ["body", "service_access_enabled"]
    assert issue["type"] == "value_error"
    assert "not implemented or verified" in issue["msg"]

    assert next_response.status_code == 422
    next_issue = next_response.json()["detail"][0]
    assert next_issue["loc"] == ["body", "service_access_enabled"]
