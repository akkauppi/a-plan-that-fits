from __future__ import annotations

import asyncio
import copy
import json
import queue
import threading
import uuid
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .engine import AlternativeContext, FourPlantersSolver, RunRecord
from .models import CancelRequest, NextSolutionRequest, SolveRequest
from .otaniemi_resilience import (
    OtaniemiResilienceService,
    ResilienceCancelRequest,
    ResilienceSolveRequest,
)
from .scenario import DEFAULT_BROWSER_PATH, DEFAULT_SOLVER_PATH, Scenario, load_scenario
from .scenario_builder_api import (
    BuilderBuildRequest,
    BuilderSelection,
    ScenarioBuilderService,
)
from .service_coverage_api import (
    ServiceCoverageCancelRequest,
    ServiceCoverageService,
    ServiceCoverageSolveRequest,
)


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


class CancellationRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: dict[str, threading.Event] = {}

    def start(self, solve_id: str) -> threading.Event:
        event = threading.Event()
        with self._lock:
            self._events[solve_id] = event
        return event

    def finish(self, solve_id: str) -> None:
        with self._lock:
            self._events.pop(solve_id, None)

    def cancel(self, solve_id: str) -> bool:
        with self._lock:
            event = self._events.get(solve_id)
            if event is None:
                return False
            event.set()
            return True


@asynccontextmanager
async def _application_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Warm immutable evidence before health checks admit browser traffic."""

    try:
        resilience_payload = await asyncio.to_thread(
            app.state.resilience_service.scenario_payload
        )
        app.state.resilience_startup_error = None
        app.state.experiment_readiness["resilient_access"] = _ready_experiment(
            resilience_payload,
            fallback_scenario_id="otaniemi-access-v1",
        )
    except (OSError, TypeError, ValueError, KeyError) as error:
        # Keep the service observable: the scenario endpoint will return the scoped
        # data_error instead of preventing health and diagnostics from starting.
        app.state.resilience_startup_error = str(error)
        app.state.experiment_readiness["resilient_access"] = _failed_experiment(error)
    try:
        service_payload = await asyncio.to_thread(
            app.state.service_coverage_service.scenario_payload
        )
        app.state.service_coverage_startup_error = None
        app.state.experiment_readiness["service_coverage"] = _ready_experiment(
            service_payload,
            fallback_scenario_id="service-coverage-otaniemi-tapiola-v1",
        )
    except (OSError, TypeError, ValueError, KeyError) as error:
        # Experiments fail independently: missing service-coverage evidence must not
        # prevent health checks or either established experiment from starting.
        app.state.service_coverage_startup_error = str(error)
        app.state.experiment_readiness["service_coverage"] = _failed_experiment(error)
    yield


def _ready_experiment(
    payload: Mapping[str, Any], *, fallback_scenario_id: str
) -> dict[str, Any]:
    return {
        "status": "ready",
        "ready": True,
        "scenario_id": str(
            payload.get("scenario_id") or payload.get("id") or fallback_scenario_id
        ),
        "snapshot_id": payload.get("snapshot_id"),
    }


def _failed_experiment(error: BaseException) -> dict[str, Any]:
    return {
        "status": "data_error",
        "ready": False,
        "error": f"{type(error).__name__}: {error}",
    }


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

    thread = threading.Thread(target=worker, name="geospatial-lab-solve", daemon=True)
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


def _resilience_public_event(event: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("type", "data_error"))
    if event_type == "candidate":
        access_summary = event.get("access_summary", {})
        selected_count = len(event.get("selected_decision_ids", []))
        return {
            **event,
            "type": "candidate_found",
            "message": (
                f"Z3 proposed {selected_count} continuity commitment"
                f"{'s' if selected_count != 1 else ''}; NetworkX is checking every origin."
            ),
            "access_summary": access_summary,
        }
    if event_type == "access_cut_found":
        constraint = event.get("constraint", {})
        variables = constraint.get("variable_ids", []) if isinstance(constraint, dict) else []
        route = event.get("diagnostic_route")
        route_feature = route.get("feature") if isinstance(route, dict) else None
        witness_ids = (
            route.get("unavailable_segment_ids", []) if isinstance(route, dict) else []
        )
        return {
            **event,
            "type": "counterexample_found",
            "message": (
                f"{event.get('origin_label', 'An origin')} still lacks gateway access; "
                "the graph returned a directed frontier."
            ),
            "route": route_feature,
            "witness_segment_ids": witness_ids,
            "learned_clause_ids": event.get("frontier_decision_ids", []),
            "constraint_expression": " ∨ ".join(str(value) for value in variables),
        }
    if event_type == "unrepairable_cut":
        route = event.get("diagnostic_route")
        route_feature = route.get("feature") if isinstance(route, dict) else None
        witness_ids = (
            route.get("unavailable_segment_ids", []) if isinstance(route, dict) else []
        )
        return {
            **event,
            "type": "counterexample_found",
            "finding": event.get("finding", "unrepairable_access_cut"),
            "message": (
                f"{event.get('origin_label', 'A stranded origin')} has no eligible "
                "continuity zone on its directed frontier."
            ),
            "route": route_feature,
            "witness_segment_ids": witness_ids,
            "learned_clause_ids": [],
        }
    return event


def _iter_resilience_solve(
    service: OtaniemiResilienceService,
    request: ResilienceSolveRequest,
    solve_id: str,
    cancel_event: threading.Event,
) -> Iterator[dict[str, Any]]:
    mailbox: queue.Queue[dict[str, Any] | BaseException | None] = queue.Queue()
    result_holder: list[dict[str, Any]] = []

    def emit(event: dict[str, Any]) -> None:
        mailbox.put(event)

    def worker() -> None:
        try:
            payload = request.model_dump(exclude={"scenario_id"})
            result_holder.append(
                service.solve(
                    **payload,
                    cancel_event=cancel_event,
                    on_event=emit,
                )
            )
        except BaseException as error:  # pragma: no cover - defensive stream boundary
            mailbox.put(error)
        finally:
            mailbox.put(None)

    thread = threading.Thread(
        target=worker,
        name="otaniemi-resilience-solve",
        daemon=True,
    )
    thread.start()
    yield {
        "type": "started",
        "solve_id": solve_id,
        "message": (
            "The explicit availability scenario was compiled. Z3 will propose continuity "
            "zones and NetworkX will test the complete directed graph."
        ),
    }
    try:
        while True:
            item = mailbox.get()
            if item is None:
                break
            if isinstance(item, BaseException):
                result_holder.append(
                    {
                        "status": "data_error",
                        "verified": False,
                        "message": f"{type(item).__name__}: {item}",
                        "methodology_notice": (
                            "The frozen scenario could not be analysed; no reachability or "
                            "infeasibility claim was made."
                        ),
                    }
                )
                continue
            yield {"solve_id": solve_id, **_resilience_public_event(item)}
        result = result_holder[-1] if result_holder else {
            "status": "data_error",
            "verified": False,
            "message": "The resilience worker ended without a terminal result.",
        }
        result["solve_id"] = solve_id
        yield {
            "type": str(result.get("status", "data_error")),
            "solve_id": solve_id,
            "message": str(result.get("message", "Analysis complete.")),
            "result": result,
        }
    finally:
        if thread.is_alive():
            cancel_event.set()


def _iter_service_coverage_solve(
    service: ServiceCoverageService,
    request: ServiceCoverageSolveRequest,
    solve_id: str,
    cancel_event: threading.Event,
) -> Iterator[dict[str, Any]]:
    """Expose the direct allocation solve as truthful, inspectable SSE stages."""

    mailbox: queue.Queue[dict[str, Any] | BaseException | None] = queue.Queue()
    result_holder: list[dict[str, Any]] = []

    def emit(event: dict[str, Any]) -> None:
        mailbox.put(event)

    def worker() -> None:
        try:
            result_holder.append(
                service.solve(request, cancel_event=cancel_event, on_event=emit)
            )
        except BaseException as error:  # pragma: no cover - defensive stream boundary
            mailbox.put(error)
        finally:
            mailbox.put(None)

    thread = threading.Thread(
        target=worker,
        name="service-coverage-solve",
        daemon=True,
    )
    thread.start()
    yield {
        "type": "started",
        "solve_id": solve_id,
        "message": (
            "The frozen demand, facility and walking evidence is loaded. Network "
            "relationships will be compiled before Z3 assigns coverage."
        ),
    }
    try:
        while True:
            item = mailbox.get()
            if item is None:
                break
            if isinstance(item, BaseException):
                result_holder.append(
                    {
                        "status": "data_error",
                        "message": f"{type(item).__name__}: {item}",
                        "claim_scope": (
                            "The allocation worker failed; no feasibility or "
                            "infeasibility claim was made."
                        ),
                        "selected_site_ids": [],
                        "assignments": [],
                        "site_loads": [],
                    }
                )
                continue
            yield {"solve_id": solve_id, **item}
        result = result_holder[-1] if result_holder else {
            "status": "data_error",
            "message": "The allocation worker ended without a terminal result.",
            "selected_site_ids": [],
            "assignments": [],
            "site_loads": [],
        }
        snapshot = result.get("snapshot")
        if isinstance(snapshot, dict):
            result.setdefault("snapshot_id", snapshot.get("snapshot_id"))
        timing = result.get("timing")
        if isinstance(timing, dict):
            result.setdefault("solver_timing_ms", timing.get("elapsed_ms"))
        yield {
            "type": str(result.get("status", "data_error")),
            "solve_id": solve_id,
            "message": str(result.get("message", "Allocation analysis complete.")),
            "result": result,
        }
    finally:
        if thread.is_alive():
            cancel_event.set()


def create_app(
    *,
    scenario: Scenario | None = None,
    solver_path: str | Path = DEFAULT_SOLVER_PATH,
    browser_path: str | Path | None = DEFAULT_BROWSER_PATH,
    scenario_builder: ScenarioBuilderService | None = None,
    resilience_service: OtaniemiResilienceService | None = None,
    service_coverage_service: ServiceCoverageService | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Geospatial Constraint Lab API",
        lifespan=_application_lifespan,
        version="0.1.0",
        description=(
            "Geospatial constraint-solving experiments over frozen Helsinki-region evidence: "
            "counterexample-guided modal-filter and resilient-access models, plus directly "
            "compiled capacitated public-service allocation. Results are scoped to the encoded "
            "graph and scenario assumptions."
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
    resilience_registry = CancellationRegistry()
    service_coverage_registry = CancellationRegistry()
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
    app.state.scenario_builder = scenario_builder or ScenarioBuilderService()
    app.state.resilience_service = resilience_service or OtaniemiResilienceService()
    app.state.resilience_registry = resilience_registry
    app.state.service_coverage_service = (
        service_coverage_service or ServiceCoverageService()
    )
    app.state.service_coverage_registry = service_coverage_registry
    app.state.experiment_readiness = {
        "modal_filter": (
            {
                "status": "ready",
                "ready": True,
                "scenario_id": loaded_scenario.id,
                "snapshot_id": loaded_scenario.snapshot_id,
            }
            if loaded_scenario is not None
            else {
                "status": "data_error",
                "ready": False,
                "error": load_error or "No modal-filter scenario loaded",
            }
        ),
        "resilient_access": {
            "status": "not_checked",
            "ready": False,
            "scenario_id": "otaniemi-access-v1",
        },
        "service_coverage": {
            "status": "not_checked",
            "ready": False,
            "scenario_id": "service-coverage-otaniemi-tapiola-v1",
        },
    }

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
                "service": "geospatial-constraint-lab",
                "experiments": copy.deepcopy(app.state.experiment_readiness),
            }
        current: Scenario = app.state.scenario
        return {
            "status": "ok",
            "ready": True,
            "service": "geospatial-constraint-lab",
            "scenario_id": current.id,
            "snapshot_id": current.snapshot_id,
            "stats": current.public_payload()["stats"],
            "experiments": copy.deepcopy(app.state.experiment_readiness),
        }

    @app.get("/api/scenario")
    async def scenario_endpoint() -> dict[str, Any]:
        require_engine()
        return app.state.scenario.public_payload()

    @app.get("/api/scenario-builder/catalog")
    async def scenario_builder_catalog() -> dict[str, Any]:
        return app.state.scenario_builder.catalog()

    @app.get("/api/resilience/scenario")
    async def resilience_scenario() -> dict[str, Any]:
        try:
            return await asyncio.to_thread(app.state.resilience_service.scenario_payload)
        except (OSError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=503,
                detail={"status": "data_error", "message": str(error)},
            ) from error

    @app.post("/api/resilience/solve")
    async def resilience_solve(request: ResilienceSolveRequest) -> StreamingResponse:
        solve_id = str(uuid.uuid4())
        cancel_event = resilience_registry.start(solve_id)
        events = _iter_resilience_solve(
            app.state.resilience_service,
            request,
            solve_id,
            cancel_event,
        )

        async def stream() -> AsyncIterator[str]:
            try:
                async for event in _sse(events, cancel_event):
                    yield event
            finally:
                resilience_registry.finish(solve_id)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Solve-ID": solve_id,
            },
        )

    @app.post("/api/resilience/solve/cancel")
    async def resilience_cancel(request: ResilienceCancelRequest) -> JSONResponse:
        accepted = resilience_registry.cancel(request.solve_id)
        return JSONResponse(
            status_code=202 if accepted else 404,
            content={
                "status": "cancellation_requested" if accepted else "not_active",
                "solve_id": request.solve_id,
                "accepted": accepted,
            },
        )

    @app.get("/api/service-coverage/scenario")
    async def service_coverage_scenario() -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                app.state.service_coverage_service.scenario_payload
            )
        except (OSError, TypeError, ValueError, KeyError) as error:
            raise HTTPException(
                status_code=503,
                detail={"status": "data_error", "message": str(error)},
            ) from error

    @app.post("/api/service-coverage/solve")
    async def service_coverage_solve(
        request: ServiceCoverageSolveRequest,
    ) -> StreamingResponse:
        solve_id = str(uuid.uuid4())
        cancel_event = service_coverage_registry.start(solve_id)
        events = _iter_service_coverage_solve(
            app.state.service_coverage_service,
            request,
            solve_id,
            cancel_event,
        )

        async def stream() -> AsyncIterator[str]:
            try:
                async for event in _sse(events, cancel_event):
                    yield event
            finally:
                service_coverage_registry.finish(solve_id)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Solve-ID": solve_id,
            },
        )

    @app.post("/api/service-coverage/solve/cancel")
    async def service_coverage_cancel(
        request: ServiceCoverageCancelRequest,
    ) -> JSONResponse:
        accepted = service_coverage_registry.cancel(request.solve_id)
        return JSONResponse(
            status_code=202 if accepted else 404,
            content={
                "status": "cancellation_requested" if accepted else "not_active",
                "solve_id": request.solve_id,
                "accepted": accepted,
            },
        )

    @app.post("/api/scenario-builder/preflight")
    async def scenario_builder_preflight(selection: BuilderSelection) -> dict[str, Any]:
        try:
            return app.state.scenario_builder.preflight(selection)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "preflight_failed", "message": str(error)},
            ) from error

    @app.post("/api/scenario-builder/jobs", status_code=status.HTTP_202_ACCEPTED)
    async def scenario_builder_start(request: BuilderBuildRequest) -> dict[str, Any]:
        try:
            return app.state.scenario_builder.start(request)
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "build_already_active", "message": str(error)},
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "build_request_invalid", "message": str(error)},
            ) from error

    @app.get("/api/scenario-builder/jobs/{job_id}")
    async def scenario_builder_job(job_id: str) -> dict[str, Any]:
        try:
            return app.state.scenario_builder.get(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Scenario build job not found.") from error

    @app.get("/api/scenario-builder/jobs/{job_id}/events")
    async def scenario_builder_events(
        job_id: str,
        after: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        try:
            return app.state.scenario_builder.events(job_id, after)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Scenario build job not found.") from error

    @app.post("/api/scenario-builder/jobs/{job_id}/cancel", status_code=202)
    async def scenario_builder_cancel(job_id: str) -> JSONResponse:
        try:
            result = app.state.scenario_builder.cancel(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Scenario build job not found.") from error
        return JSONResponse(status_code=202 if result["accepted"] else 409, content=result)

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
