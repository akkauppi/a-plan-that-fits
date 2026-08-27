from __future__ import annotations

import asyncio
import json
import queue
import threading
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .engine import AlternativeContext, FourPlantersSolver, RunRecord
from .models import CancelRequest, NextSolutionRequest, SolveRequest
from .scenario import DEFAULT_BROWSER_PATH, DEFAULT_SOLVER_PATH, Scenario, load_scenario


class SessionRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cancel_events: dict[str, threading.Event] = {}
        self._records: dict[str, RunRecord] = {}

    def start(self, solve_id: str) -> threading.Event:
        event = threading.Event()
        with self._lock:
            self._cancel_events[solve_id] = event
        return event

    def complete(self, record: RunRecord) -> None:
        with self._lock:
            self._records[record.solve_id] = record
            self._cancel_events.pop(record.solve_id, None)

    def cancel(self, solve_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(solve_id)
            if event is None:
                return False
            event.set()
            return True

    def get(self, solve_id: str) -> RunRecord | None:
        with self._lock:
            return self._records.get(solve_id)


async def _sse(
    events: Iterator[dict[str, Any]], cancel_event: threading.Event
) -> AsyncIterator[str]:
    """Bridge the blocking Z3 generator without occupying the ASGI event loop."""
    mailbox: queue.Queue[dict[str, Any] | BaseException | None] = queue.Queue()

    def worker() -> None:
        try:
            for item in events:
                mailbox.put(item)
        except BaseException as exc:  # pragma: no cover - defensive stream boundary
            mailbox.put(exc)
        finally:
            mailbox.put(None)

    thread = threading.Thread(target=worker, name="four-planters-solve", daemon=True)
    thread.start()
    sequence = 0
    try:
        while True:
            try:
                item = mailbox.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)
                continue
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            sequence += 1
            body = {"sequence": sequence, **item}
            yield (
                f"id: {sequence}\n"
                "event: solve_event\n"
                f"data: {json.dumps(body, separators=(',', ':'), ensure_ascii=False)}\n\n"
            )
    finally:
        if thread.is_alive():
            cancel_event.set()


def create_app(
    *,
    scenario: Scenario | None = None,
    solver_path: str | Path = DEFAULT_SOLVER_PATH,
    browser_path: str | Path | None = DEFAULT_BROWSER_PATH,
) -> FastAPI:
    app = FastAPI(
        title="Four Planters Solver API",
        version="0.1.0",
        description=(
            "Counterexample-guided modal-filter search over a frozen OpenStreetMap-derived "
            "Helsinki street graph. Results are scoped to the encoded graph assumptions."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
        expose_headers=["X-Solve-ID"],
    )
    registry = SessionRegistry()
    loaded_scenario: Scenario | None = scenario
    load_error: str | None = None
    if loaded_scenario is None:
        try:
            loaded_scenario = load_scenario(solver_path, browser_path)
        except Exception as exc:  # service remains inspectable through /health
            load_error = f"{type(exc).__name__}: {exc}"
    engine = FourPlantersSolver(loaded_scenario) if loaded_scenario else None
    app.state.scenario = loaded_scenario
    app.state.engine = engine
    app.state.registry = registry
    app.state.load_error = load_error

    def require_engine() -> FourPlantersSolver:
        if app.state.engine is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "data_error",
                    "message": app.state.load_error or "No scenario loaded",
                },
            )
        return app.state.engine

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        if app.state.scenario is None:
            return {
                "status": "data_error",
                "ready": False,
                "error": app.state.load_error,
            }
        current: Scenario = app.state.scenario
        return {
            "status": "ok",
            "ready": True,
            "service": "four-planters-solver",
            "scenario_id": current.id,
            "snapshot_id": current.snapshot_id,
            "stats": current.public_payload()["stats"],
        }

    @app.get("/api/scenario")
    async def scenario_endpoint() -> dict[str, Any]:
        require_engine()
        return app.state.scenario.public_payload()

    def stream_run(
        solve_request: SolveRequest,
        *,
        alternative: AlternativeContext | None = None,
    ) -> StreamingResponse:
        solver = require_engine()
        solve_id = str(uuid.uuid4())
        cancel_event = registry.start(solve_id)
        events = solver.iter_solve(
            solve_request,
            solve_id=solve_id,
            cancel_event=cancel_event,
            alternative=alternative,
            on_complete=registry.complete,
        )
        return StreamingResponse(
            _sse(events, cancel_event),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Solve-ID": solve_id,
            },
        )

    @app.post("/api/solve")
    async def solve(solve_request: SolveRequest) -> StreamingResponse:
        return stream_run(solve_request)

    @app.post("/api/solutions/next")
    async def next_solution(next_request: NextSolutionRequest) -> StreamingResponse:
        prior_id = next_request.solve_id
        prior = registry.get(prior_id)
        if prior is None:
            raise HTTPException(
                status_code=404, detail="The referenced solve session is unavailable."
            )
        if prior.context is None:
            raise HTTPException(
                status_code=409, detail="The referenced solve has no verified solution."
            )
        # The browser sends the full current request. If only solve_id/timeout is
        # supplied, faithfully reuse the previous scenario assumptions.
        override_fields = next_request.model_fields_set - {"solve_id"}
        overrides = next_request.model_dump(include=override_fields)
        merged = prior.request.model_dump()
        merged.update(overrides)
        merged["solve_id"] = None
        solve_request = SolveRequest.model_validate(merged)
        return stream_run(solve_request, alternative=prior.context)

    @app.post("/api/solve/cancel")
    async def cancel(cancel_request: CancelRequest) -> JSONResponse:
        accepted = registry.cancel(cancel_request.solve_id)
        return JSONResponse(
            status_code=202 if accepted else 404,
            content={
                "status": "cancellation_requested" if accepted else "not_active",
                "solve_id": cancel_request.solve_id,
                "accepted": accepted,
            },
        )

    @app.post("/api/solve/json")
    async def solve_json(solve_request: SolveRequest) -> dict[str, Any]:
        solver = require_engine()
        solve_id = str(uuid.uuid4())
        cancel_event = registry.start(solve_id)
        holder: list[RunRecord] = []

        def save(record: RunRecord) -> None:
            holder.append(record)
            registry.complete(record)

        events = list(
            solver.iter_solve(
                solve_request,
                solve_id=solve_id,
                cancel_event=cancel_event,
                on_complete=save,
            )
        )
        return {"result": holder[0].result, "events": events}

    return app


app = create_app()
