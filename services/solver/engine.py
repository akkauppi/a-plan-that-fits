from __future__ import annotations

import hashlib
import heapq
import json
import logging
import math
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import networkx as nx
import z3

from .models import PortalPair, SolveRequest
from .scenario import Scenario, distance_metres

LOGGER = logging.getLogger("geospatial_constraint_lab.modal_filter_solver")


@dataclass(frozen=True)
class PathClause:
    pair_key: str
    pair_label: str
    candidate_ids: tuple[str, ...]


@dataclass(frozen=True)
class AccessClause:
    cluster_id: str
    candidate_ids: tuple[str, ...]


@dataclass
class AlternativeContext:
    objective_values: dict[str, int]
    path_clauses: list[PathClause]
    access_clauses: list[AccessClause]
    excluded_solutions: list[frozenset[str]]


@dataclass
class RunRecord:
    request: SolveRequest
    solve_id: str
    result: dict[str, Any]
    context: AlternativeContext | None


@dataclass(frozen=True)
class ConstraintRecord:
    key: str
    label: str
    expression: z3.BoolRef
    category: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CandidateAnswer:
    status: str
    selected: frozenset[str] = frozenset()
    objectives: dict[str, int] = field(default_factory=dict)
    unsat_core: list[ConstraintRecord] = field(default_factory=list)
    reason: str | None = None


class FourPlantersSolver:
    """Counterexample-guided solver with independent directed-graph verification.

    Z3 searches a relaxation made of discovered path cuts. Network reachability is
    the source of truth: every proposed model is checked for still-open forbidden
    routes and local address egress. A result is only labelled verified after the
    complete check is repeated from a fresh blocked-edge set.
    """

    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.candidate_ids = tuple(sorted(scenario.candidates))
        self._adjacency: dict[str, list[dict[str, Any]]] = {node: [] for node in scenario.nodes}
        for edge in scenario.edges.values():
            self._adjacency.setdefault(edge["u"], []).append(edge)
        for edges in self._adjacency.values():
            edges.sort(key=lambda edge: edge["id"])
        self._close_pairs = tuple(
            (left, right)
            for index, left in enumerate(self.candidate_ids)
            for right in self.candidate_ids[index + 1 :]
            if distance_metres(scenario.candidates[left].point, scenario.candidates[right].point)
            < 45
        )
        self._baseline_access: dict[str, float] = {}
        for cluster in scenario.address_clusters.values():
            route = self._route_to_portals(cluster.node_id, cluster.allowed_portal_ids, frozenset())
            self._baseline_access[cluster.id] = route["length_m"] if route else math.inf

    def solve_to_completion(
        self,
        request: SolveRequest,
        *,
        solve_id: str = "test-solve",
        cancel_event: threading.Event | None = None,
        alternative: AlternativeContext | None = None,
    ) -> tuple[list[dict[str, Any]], RunRecord]:
        events: list[dict[str, Any]] = []
        holder: list[RunRecord] = []
        events.extend(
            self.iter_solve(
                request,
                solve_id=solve_id,
                cancel_event=cancel_event,
                alternative=alternative,
                on_complete=holder.append,
            )
        )
        return events, holder[0]

    def iter_solve(
        self,
        request: SolveRequest,
        *,
        solve_id: str,
        cancel_event: threading.Event | None = None,
        alternative: AlternativeContext | None = None,
        on_complete: Callable[[RunRecord], None] | None = None,
    ) -> Iterator[dict[str, Any]]:
        cancel_event = cancel_event or threading.Event()
        started = time.monotonic()
        deadline = started + request.timeout_seconds
        iteration = 0
        terminal_result: dict[str, Any]
        context: AlternativeContext | None = None

        def event(
            event_type: str,
            state: str,
            message: str,
            payload: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            body = {
                "type": event_type,
                "solve_id": solve_id,
                "iteration": iteration,
                "state": state,
                "message": message,
                "timestamp_ms": round((time.monotonic() - started) * 1000),
                "payload": payload or {},
            }
            # Top-level fields keep the event ergonomic for simple SSE clients.
            body.update(payload or {})
            return body

        def finish(
            status: str,
            message: str,
            *,
            result_fields: dict[str, Any] | None = None,
            event_type: str | None = None,
        ) -> Iterator[dict[str, Any]]:
            nonlocal terminal_result
            terminal_result = self._base_result(
                request,
                solve_id,
                status,
                message,
                iteration,
                started,
            )
            terminal_result.update(result_fields or {})
            yield event(event_type or status, status, message, {"result": terminal_result})
            yield event("complete", status, message, {"result": terminal_result})

        yield event(
            "started",
            "solving",
            "The solver is testing a deterministic intervention model.",
            {
                "scenario_id": self.scenario.id,
                "snapshot_id": self.scenario.snapshot_id,
                "budget": request.budget,
                "alternative": alternative is not None,
            },
        )

        error = self._validate_request(request)
        if error:
            yield from finish("data_error", error)
            record = RunRecord(request, solve_id, terminal_result, None)
            if on_complete:
                on_complete(record)
            return

        pairs = self._pairs(request)
        path_clauses = list(alternative.path_clauses) if alternative else []
        access_clauses = list(alternative.access_clauses) if alternative else []
        exclusions = list(alternative.excluded_solutions) if alternative else []
        fixed_objectives = dict(alternative.objective_values) if alternative else None
        objective_keys = self._objective_keys(request.objective_mode)
        # During CEGIS, secondary optimisation is work on a relaxation that may
        # immediately be invalidated by the next graph counterexample.  Prove
        # the primary (filter-count) optimum while discovering paths, then run
        # the full lexicographic objective vector only after a graph-feasible
        # model has been found.  Any new route exposed by that structural
        # choice returns the loop to the inexpensive refinement phase.
        optimise_full_objective = alternative is not None or len(objective_keys) == 1
        # Path and access clauses are only ever strengthened.  Once an earlier
        # relaxation proves a cardinality lower bound, no later refinement can
        # admit a smaller solution.  Carrying that proof forward avoids asking
        # Z3 to re-prove the same expensive UNSAT bound every iteration.
        primary_lower_bound = int((fixed_objectives or {}).get("intervention_count", 0))

        while True:
            iteration += 1
            control = self._control_state(deadline, cancel_event)
            if control:
                message = (
                    "Solving was cancelled. No claim about feasibility has been made."
                    if control == "cancelled"
                    else "The solver reached its time limit. This is not an UNSAT result."
                )
                yield from finish(control, message)
                break

            answer = self._solve_candidate(
                request,
                pairs,
                path_clauses,
                access_clauses,
                exclusions,
                fixed_objectives,
                deadline,
                cancel_event,
                optimise_secondary=optimise_full_objective,
                primary_lower_bound=primary_lower_bound,
            )
            if answer.status == "cancelled":
                yield from finish(
                    "cancelled",
                    "Solving was cancelled. No claim about feasibility has been made.",
                )
                break
            if answer.status == "timeout":
                yield from finish(
                    "timeout",
                    "The constraint solver reached its time limit. This is not an UNSAT result.",
                    result_fields={"diagnostics": {"z3_reason": answer.reason}},
                )
                break
            if answer.status == "error":
                yield from finish(
                    "data_error",
                    (
                        "The deterministic model selector disagreed with the Z3 model; "
                        "no feasibility claim has been made."
                    ),
                    result_fields={
                        "diagnostics": {
                            "kind": "model_selection_inconsistency",
                            "reason": answer.reason,
                        }
                    },
                )
                break
            if answer.status == "unsat":
                if alternative is not None:
                    message = "No further intervention set has the same verified objective values."
                    yield from finish(
                        "alternatives_exhausted",
                        message,
                        result_fields={
                            "objective_values": fixed_objectives,
                            "alternatives_checked": len(exclusions),
                        },
                    )
                else:
                    explanation = self._explain_unsat(request, pairs, answer.unsat_core)
                    yield from finish(
                        "verified_unsat",
                        explanation["message"],
                        result_fields={
                            "verification_status": "z3_unsat_core",
                            "unsat_core": [item["label"] for item in explanation["core"]],
                            "unsat_core_details": explanation["core"],
                            "suggested_relaxations": explanation["suggestions"],
                        },
                    )
                break

            selected = answer.selected
            objective_values = answer.objectives
            primary_lower_bound = max(
                primary_lower_bound, int(objective_values.get("intervention_count", 0))
            )
            LOGGER.info(
                json.dumps(
                    {
                        "solve_id": solve_id,
                        "iteration": iteration,
                        "event": "candidate_found",
                        "selected": sorted(selected),
                        "objectives": objective_values,
                    }
                )
            )
            yield event(
                "candidate_found",
                "candidate_found",
                f"Candidate {iteration} uses {len(selected)} modal filter(s).",
                {
                    "selected_intervention_ids": sorted(selected),
                    "objective_values": objective_values,
                },
            )

            counterexamples = self._counterexample_batch(selected, pairs)
            control = self._control_state(deadline, cancel_event)
            if control:
                message = (
                    "Solving was cancelled. No claim about feasibility has been made."
                    if control == "cancelled"
                    else "The solver reached its time limit. This is not an UNSAT result."
                )
                yield from finish(control, message)
                break
            if counterexamples:
                counterexample = counterexamples[0]
                route = counterexample["route"]
                unblockable = next(
                    (item for item in counterexamples if not item["route"]["candidate_ids"]),
                    None,
                )
                if unblockable is not None:
                    counterexample = unblockable
                    route = counterexample["route"]
                yield event(
                    "counterexample_found",
                    "counterexample_found",
                    f"A private-car route still connects {counterexample['pair_label']}.",
                    {
                        "counterexample": counterexample,
                        "route": route["geometry"],
                        "route_details": route,
                        "portal_pair": counterexample["pair"],
                        "counterexamples_found": len(counterexamples),
                    },
                )
                if unblockable is not None:
                    names = list(dict.fromkeys(route["street_names"]))
                    corridor = ", ".join(names[:3]) or "an ineligible or protected corridor"
                    message = (
                        f"The {counterexample['pair_label']} route cannot be cut by any eligible "
                        f"candidate. It survives along {corridor}."
                    )
                    yield from finish(
                        "verified_unsat",
                        message,
                        result_fields={
                            "verification_status": "graph_unblockable_route",
                            "diagnostics": {
                                "kind": "unblockable_protected_corridor",
                                "pair": counterexample["pair"],
                                "route": route,
                            },
                            "suggested_relaxations": [
                                {
                                    "type": "remove_portal_pair",
                                    "pair": counterexample["pair"],
                                    "label": "Remove this portal-pair requirement",
                                },
                                {
                                    "type": "review_candidate_rules",
                                    "label": "Review protected-corridor and candidate assumptions",
                                },
                            ],
                        },
                    )
                    break
                new_clauses: list[PathClause] = []
                for item in counterexamples:
                    clause = PathClause(
                        pair_key=item["pair_key"],
                        pair_label=item["pair_label"],
                        candidate_ids=tuple(sorted(item["route"]["candidate_ids"])),
                    )
                    if clause not in new_clauses:
                        new_clauses.append(clause)
                added_clauses = self._merge_path_clauses(path_clauses, new_clauses)
                optimise_full_objective = alternative is not None
                if not added_clauses:
                    yield from finish(
                        "data_error",
                        (
                            "Refinement rediscovered a route already represented by the "
                            "constraint model; no result is claimed."
                        ),
                        result_fields={
                            "diagnostics": {
                                "kind": "refinement_stalled",
                                "counterexample": counterexample,
                            }
                        },
                    )
                    break
                representative_clause = added_clauses[0]
                route_word = "routes" if len(added_clauses) != 1 else "route"
                yield event(
                    "refining",
                    "refining",
                    f"The model now cuts {len(added_clauses)} distinct surviving {route_word} "
                    "found across the selected portal groups.",
                    {
                        "clause": {
                            "kind": "through_route_cut",
                            "pair_key": representative_clause.pair_key,
                            "candidate_ids": list(representative_clause.candidate_ids),
                        },
                        "clauses": [
                            {
                                "kind": "through_route_cut",
                                "pair_key": clause.pair_key,
                                "candidate_ids": list(clause.candidate_ids),
                            }
                            for clause in added_clauses
                        ],
                        "routes_added": len(added_clauses),
                    },
                )
                continue

            failed_access = self._first_failed_access(selected)
            if failed_access:
                if not selected:
                    message = (
                        f"{failed_access['cluster_label']} has no permitted portal route in the "
                        "unfiltered baseline graph; the frozen scenario cannot prove local access."
                    )
                    yield from finish(
                        "data_error",
                        message,
                        result_fields={
                            "diagnostics": {"kind": "baseline_access_missing", **failed_access}
                        },
                    )
                    break
                clause = AccessClause(failed_access["cluster_id"], tuple(sorted(selected)))
                if clause not in access_clauses:
                    access_clauses.append(clause)
                optimise_full_objective = alternative is not None
                yield event(
                    "candidate_rejected",
                    "candidate_found",
                    (
                        f"Candidate rejected: {failed_access['cluster_label']} "
                        "loses permitted car access."
                    ),
                    {
                        "address_cluster": failed_access,
                        "selected_intervention_ids": sorted(selected),
                    },
                )
                yield event(
                    "refining",
                    "refining",
                    (
                        "A corrective constraint excludes this access-severing set "
                        "and all of its supersets."
                    ),
                    {
                        "clause": {
                            "kind": "local_access",
                            "cluster_id": clause.cluster_id,
                            "at_least_one_must_open": list(clause.candidate_ids),
                        }
                    },
                )
                continue

            if not optimise_full_objective:
                optimise_full_objective = True
                yield event(
                    "refining",
                    "refining",
                    (
                        "A minimum-filter cut is graph-feasible. The solver is now "
                        "optimising cost and spacing before final verification."
                    ),
                    {
                        "clause": {
                            "kind": "objective_phase",
                            "primary_objective": "intervention_count",
                            "secondary_objectives": list(objective_keys[1:]),
                        }
                    },
                )
                continue

            verification = self.verify_solution(request, selected, pairs)
            if not verification["verified"]:
                yield from finish(
                    "data_error",
                    (
                        "Independent verification disagreed with the search loop; "
                        "no result is claimed."
                    ),
                    result_fields={"diagnostics": verification},
                )
                break

            metrics = self._access_metrics(selected)
            access_routes = self._access_routes_geojson(selected)
            baseline_components, baseline_component_summary = self._components_geojson(frozenset())
            filtered_components, filtered_component_summary = self._components_geojson(selected)
            proof_payload = {
                "selected_intervention_ids": sorted(selected),
                "objective_values": objective_values,
                "verification_status": "independently_verified",
                "address_access_summary": verification["address_access_summary"],
                "portal_connectivity_summary": verification["portal_connectivity_summary"],
                "mode_connectivity_summary": {
                    "walking": "not_separately_modelled_filter_assumed_passable",
                    "cycling": "not_separately_modelled_filter_assumed_passable",
                    "emergency": (
                        "not_separately_modelled_removable_filter_assumption"
                        if request.emergency_permeable
                        else "not_asserted"
                    ),
                    "service_access": "unsupported_not_verified",
                },
                "local_detour_metrics": metrics,
                "access_routes": access_routes,
                "private_car_connectivity": {
                    "metric": "directed_strongly_connected_components",
                    "definition": (
                        "A component is a maximal set of private-car graph nodes where every "
                        "node can reach every other node following directed street edges."
                    ),
                    "baseline": baseline_component_summary,
                    "filtered": filtered_component_summary,
                },
                "baseline_components": baseline_components,
                "filtered_components": filtered_components,
                # Compatibility alias for clients that predate the explicit
                # before/after component collections.
                "components": filtered_components,
                "proof_hash": self._proof_hash(request, selected, verification),
            }
            explanation = (
                f"Under snapshot {self.scenario.snapshot_id}, the selected filters cut every "
                "requested private-car portal connection while every included address cluster "
                "retains a permitted private-car portal route. Walking and cycling passability "
                "and removable emergency passage are filter assumptions; those mode networks "
                "are not separately verified."
            )
            context = AlternativeContext(
                objective_values=objective_values,
                path_clauses=path_clauses,
                access_clauses=access_clauses,
                excluded_solutions=exclusions + [selected],
            )
            yield from finish(
                "verified_optimal",
                explanation,
                result_fields=proof_payload,
                event_type="verified_optimal",
            )
            break

        record = RunRecord(request, solve_id, terminal_result, context)
        if on_complete:
            on_complete(record)

    def _base_result(
        self,
        request: SolveRequest,
        solve_id: str,
        status: str,
        explanation: str,
        iteration: int,
        started: float,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "solve_id": solve_id,
            "scenario_id": self.scenario.id,
            "snapshot_id": self.scenario.snapshot_id,
            "selected_intervention_ids": [],
            "objective_values": {},
            "verification_status": "not_verified",
            "address_access_summary": {},
            "portal_connectivity_summary": [],
            "local_detour_metrics": {},
            "timing_ms": round((time.monotonic() - started) * 1000),
            "iteration_count": iteration,
            "explanation": explanation,
            "assumptions": {
                "budget_is_maximum": request.budget,
                "emergency_permeable": request.emergency_permeable,
                "service_access_enabled": request.service_access_enabled,
                "objective_mode": request.objective_mode,
            },
        }

    def _validate_request(self, request: SolveRequest) -> str | None:
        if request.service_access_enabled:
            return (
                "Service-access preservation is not implemented or verified; "
                "set service_access_enabled to false."
            )
        if request.scenario_id != self.scenario.id:
            return (
                f"Unknown scenario {request.scenario_id!r}; "
                f"loaded scenario is {self.scenario.id!r}."
            )
        candidate_ids = set(self.candidate_ids)
        unknown_forced = sorted(set(request.forced_interventions) - candidate_ids)
        unknown_locked = sorted(set(request.locked_open_streets) - candidate_ids)
        if unknown_forced:
            return (
                f"Forced intervention IDs are not eligible candidates: {', '.join(unknown_forced)}."
            )
        if unknown_locked:
            return f"Locked-open IDs are not eligible candidates: {', '.join(unknown_locked)}."
        for pair in self._pairs(request):
            if pair.a not in self.scenario.portals or pair.b not in self.scenario.portals:
                return f"Portal pair {pair.a} ↔ {pair.b} references an unknown portal."
            if pair.a == pair.b:
                return f"Portal pair {pair.a} uses the same portal twice."
        return None

    def _pairs(self, request: SolveRequest) -> list[PortalPair]:
        if request.required_portal_pairs is not None:
            return request.required_portal_pairs
        return [PortalPair.model_validate(pair) for pair in self.scenario.default_portal_pairs]

    @staticmethod
    def _control_state(deadline: float, cancel_event: threading.Event) -> str | None:
        if cancel_event.is_set():
            return "cancelled"
        if time.monotonic() >= deadline:
            return "timeout"
        return None

    def _expressions(
        self,
        variables: dict[str, z3.BoolRef],
        candidate_ids: Sequence[str] | None = None,
    ) -> dict[str, z3.ArithRef]:
        candidates = tuple(candidate_ids if candidate_ids is not None else self.candidate_ids)
        candidate_set = set(candidates)
        count_terms = [z3.If(variables[candidate], 1, 0) for candidate in candidates]
        cost_terms = [
            z3.If(variables[candidate], self.scenario.candidates[candidate].cost, 0)
            for candidate in candidates
        ]
        access_terms = [
            z3.If(variables[candidate], self.scenario.candidates[candidate].access_penalty, 0)
            for candidate in candidates
        ]
        adjacency_terms = [
            z3.If(z3.And(variables[left], variables[right]), 1, 0)
            for left, right in self._close_pairs
            if left in candidate_set and right in candidate_set
        ]
        return {
            "intervention_count": z3.Sum(count_terms) if count_terms else z3.IntVal(0),
            "weighted_cost": z3.Sum(cost_terms) if cost_terms else z3.IntVal(0),
            "access_penalty": z3.Sum(access_terms) if access_terms else z3.IntVal(0),
            "adjacency_penalty": (z3.Sum(adjacency_terms) if adjacency_terms else z3.IntVal(0)),
        }

    def _constraint_records(
        self,
        request: SolveRequest,
        pairs: Sequence[PortalPair],
        path_clauses: Sequence[PathClause],
        access_clauses: Sequence[AccessClause],
        variables: dict[str, z3.BoolRef],
        expressions: dict[str, z3.ArithRef],
    ) -> list[ConstraintRecord]:
        records = [
            ConstraintRecord(
                "budget",
                f"Budget is at most {request.budget}",
                expressions["intervention_count"] <= request.budget,
                "budget",
                {"budget": request.budget},
            )
        ]
        for candidate_id in request.forced_interventions:
            records.append(
                ConstraintRecord(
                    f"forced:{candidate_id}",
                    f"{self.scenario.candidates[candidate_id].street_name} must receive a filter",
                    variables[candidate_id],
                    "forced_intervention",
                    {"candidate_id": candidate_id},
                )
            )
        for candidate_id in request.locked_open_streets:
            records.append(
                ConstraintRecord(
                    f"locked:{candidate_id}",
                    f"{self.scenario.candidates[candidate_id].street_name} must remain open",
                    z3.Not(variables[candidate_id]),
                    "locked_open",
                    {"candidate_id": candidate_id},
                )
            )
        for pair in pairs:
            key = self._pair_key(pair.a, pair.b)
            clauses = [
                z3.Or([variables[candidate] for candidate in clause.candidate_ids])
                for clause in path_clauses
                if clause.pair_key == key
            ]
            if clauses:
                label = pair.label or self._pair_label(pair.a, pair.b)
                records.append(
                    ConstraintRecord(
                        f"portal_pair:{key}",
                        f"{label} portals must be disconnected for private cars",
                        z3.And(clauses),
                        "portal_pair",
                        {"a": pair.a, "b": pair.b, "label": label},
                    )
                )
        if access_clauses:
            clauses = [
                z3.Or([z3.Not(variables[candidate]) for candidate in clause.candidate_ids])
                for clause in access_clauses
            ]
            records.append(
                ConstraintRecord(
                    "local_access",
                    "Every included address cluster must retain a route to a permitted portal",
                    z3.And(clauses),
                    "local_access",
                    {"cluster_ids": sorted({clause.cluster_id for clause in access_clauses})},
                )
            )
        return records

    def _solve_candidate(
        self,
        request: SolveRequest,
        pairs: Sequence[PortalPair],
        path_clauses: Sequence[PathClause],
        access_clauses: Sequence[AccessClause],
        exclusions: Sequence[frozenset[str]],
        fixed_objectives: dict[str, int] | None,
        deadline: float,
        cancel_event: threading.Event,
        *,
        optimise_secondary: bool = True,
        primary_lower_bound: int = 0,
    ) -> CandidateAnswer:
        active_candidates = set(request.forced_interventions)
        active_candidates.update(
            candidate for clause in path_clauses for candidate in clause.candidate_ids
        )
        active_candidates.update(
            candidate for clause in access_clauses for candidate in clause.candidate_ids
        )
        active_candidates.update(candidate for solution in exclusions for candidate in solution)
        active_candidate_ids = tuple(sorted(active_candidates))
        variables = {
            candidate: z3.Bool(f"blocked__{candidate}") for candidate in self.candidate_ids
        }
        expressions = self._expressions(variables, active_candidate_ids)
        records = self._constraint_records(
            request, pairs, path_clauses, access_clauses, variables, expressions
        )
        internal: list[z3.BoolRef] = []
        # Candidates absent from every positive path/user constraint cannot
        # occur in a minimum-cardinality model: removing one preserves all path
        # cuts, budget and access no-goods while strictly improving objective 1.
        # Fixing them open shrinks the secondary Z3 search without changing any
        # attainable lexicographic optimum. Exclusion members stay active for
        # equal-vector alternative enumeration.
        internal.extend(
            z3.Not(variables[candidate])
            for candidate in self.candidate_ids
            if candidate not in active_candidates
        )
        for previous in exclusions:
            internal.append(
                z3.Or(
                    [
                        z3.Not(variables[candidate])
                        if candidate in previous
                        else variables[candidate]
                        for candidate in self.candidate_ids
                    ]
                )
            )
        primary_bound_expression: z3.BoolRef | None = None
        if fixed_objectives:
            for key, value in fixed_objectives.items():
                if key in expressions:
                    internal.append(expressions[key] == value)
        elif primary_lower_bound > 0:
            # This is a previously proved consequence of the tracked records,
            # not a new user-facing assumption.  Keep it out of ``internal`` so
            # UNSAT-core extraction still reports the original causes.
            primary_bound_expression = expressions["intervention_count"] >= primary_lower_bound

        requested_objective_keys = self._objective_keys(request.objective_mode)
        objective_keys = (
            requested_objective_keys
            if optimise_secondary or fixed_objectives
            else requested_objective_keys[:1]
        )
        search = z3.Solver()
        search.set(random_seed=0)
        search.add(*[record.expression for record in records], *internal)
        if primary_bound_expression is not None:
            search.add(primary_bound_expression)
        status, control = self._cooperative_solver_check(search, deadline, cancel_event)
        if control:
            return CandidateAnswer(control, reason="solve control requested during Z3 check")
        assert status is not None
        if status == z3.unknown:
            return CandidateAnswer("timeout", reason=search.reason_unknown())
        if status == z3.unsat:
            if primary_bound_expression is not None:
                # The bound is a solver-proved consequence of the earlier,
                # weaker relaxation.  Since records only strengthen during a
                # run, the complete current record set is a valid (though not
                # necessarily minimal) core when UNSAT relies on that lemma.
                # Expanding the lemma back to its tracked causes also avoids
                # exposing an opaque internal constraint to users.
                core = list(records)
            else:
                core = self._unsat_core(records, internal, deadline, cancel_event)
                control = self._control_state(deadline, cancel_event)
                if control:
                    return CandidateAnswer(control, reason="solve control requested during core")
            return CandidateAnswer("unsat", unsat_core=core)
        current_model = search.model()
        objectives: dict[str, int] = {}
        if fixed_objectives:
            objectives = {
                key: current_model.eval(expressions[key], model_completion=True).as_long()
                for key in objective_keys
            }
        else:
            # Explicit integer bound minimisation is dramatically faster and
            # easier to inspect than Optimize's general lex engine for this
            # sparse Boolean hitting-set model. Prior objectives are fixed
            # before the next is searched, preserving exact lexicographic
            # semantics.
            for objective_index, key in enumerate(objective_keys):
                expression = expressions[key]
                current_value = current_model.eval(expression, model_completion=True).as_long()
                domain = self._objective_domain(
                    key,
                    objectives.get("intervention_count", current_value),
                    current_value,
                )
                if key == "intervention_count" and primary_lower_bound:
                    domain = [value for value in domain if value >= primary_lower_bound]
                current_index = domain.index(current_value)
                # Ask for the immediately cheaper attainable value. A SAT
                # model may jump several values; a single UNSAT answer then
                # proves the current value minimal. This avoids broad numeric
                # binary searches over impossible weighted-cost values.
                while current_index > 0:
                    control = self._control_state(deadline, cancel_event)
                    if control:
                        return CandidateAnswer(control, reason="objective search control request")
                    threshold = domain[current_index - 1]
                    search.push()
                    search.add(expression <= threshold)
                    bounded_status, control = self._cooperative_solver_check(
                        search, deadline, cancel_event
                    )
                    if control:
                        search.pop()
                        return CandidateAnswer(
                            control, reason="solve control requested during objective search"
                        )
                    assert bounded_status is not None
                    if bounded_status == z3.sat:
                        bounded_model = search.model()
                        current_value = bounded_model.eval(
                            expression, model_completion=True
                        ).as_long()
                        current_index = domain.index(current_value)
                        current_model = bounded_model
                    elif bounded_status == z3.unsat:
                        search.pop()
                        break
                    else:
                        search.pop()
                        return CandidateAnswer("timeout", reason=search.reason_unknown())
                    search.pop()
                objectives[key] = current_value
                # ``current_model`` came from the base check or the latest
                # tighter SAT bound and therefore already witnesses this exact
                # value. After the cheaper bound is UNSAT, adding the equality
                # is sufficient; immediately re-checking the same witness can
                # be dramatically more expensive than the proof itself. The
                # next objective check (or deterministic final selector)
                # enforces every equality in the documented lexicographic
                # vector.
                search.add(expression == current_value)
                remaining_needs_search = False
                for remaining_key in objective_keys[objective_index + 1 :]:
                    remaining_expression = expressions[remaining_key]
                    remaining_value = current_model.eval(
                        remaining_expression, model_completion=True
                    ).as_long()
                    remaining_domain = self._objective_domain(
                        remaining_key,
                        objectives.get("intervention_count", remaining_value),
                        remaining_value,
                    )
                    if remaining_key == "intervention_count" and primary_lower_bound:
                        remaining_domain = [
                            value for value in remaining_domain if value >= primary_lower_bound
                        ]
                    if remaining_domain.index(remaining_value) > 0:
                        remaining_needs_search = True
                        break
                if remaining_needs_search:
                    fixed_status, control = self._cooperative_solver_check(
                        search, deadline, cancel_event
                    )
                    if control:
                        return CandidateAnswer(
                            control,
                            reason="solve control requested while fixing an objective",
                        )
                    assert fixed_status is not None
                    if fixed_status != z3.sat:
                        return CandidateAnswer("timeout", reason=search.reason_unknown())
                    current_model = search.model()

        # Z3 has established the exact objective vector. Select a unique model
        # with a small deterministic hitting-set search over only candidates
        # that occur in discovered/user constraints. This is an enumeration
        # tie-break, not another city objective, and avoids relying on Z3's
        # intentionally unspecified choice among equal Boolean models.
        try:
            selected = self._deterministic_selection(
                request,
                path_clauses,
                access_clauses,
                exclusions,
                objectives,
                deadline,
                cancel_event,
            )
        except TimeoutError:
            control = self._control_state(deadline, cancel_event)
            return CandidateAnswer(
                control or "timeout",
                reason="structural tie-break cancelled"
                if control == "cancelled"
                else "structural tie-break deadline",
            )
        if selected is None:
            return CandidateAnswer(
                "error", reason="deterministic selector found no equal-objective model"
            )
        # Include current values for the complete public vector even during the
        # cardinality-only refinement phase.  Secondary values are descriptive
        # until the explicit full-objective phase has completed.
        objectives = self._selected_objective_values(selected, requested_objective_keys)
        return CandidateAnswer("sat", selected, objectives)

    def _deterministic_selection(
        self,
        request: SolveRequest,
        path_clauses: Sequence[PathClause],
        access_clauses: Sequence[AccessClause],
        exclusions: Sequence[frozenset[str]],
        fixed_objectives: dict[str, int],
        deadline: float,
        cancel_event: threading.Event,
    ) -> frozenset[str] | None:
        if self._control_state(deadline, cancel_event):
            raise TimeoutError
        target_count = int(fixed_objectives.get("intervention_count", 0))
        active = set(request.forced_interventions)
        active.update(candidate for clause in path_clauses for candidate in clause.candidate_ids)
        active.update(candidate for clause in access_clauses for candidate in clause.candidate_ids)
        active.update(candidate for solution in exclusions for candidate in solution)
        locked = set(request.locked_open_streets)
        ordered = tuple(sorted(active - locked))
        index_by_candidate = {candidate: index for index, candidate in enumerate(ordered)}

        def mask_for(candidates: Sequence[str] | frozenset[str]) -> int:
            mask = 0
            for candidate in candidates:
                index = index_by_candidate.get(candidate)
                if index is not None:
                    mask |= 1 << index
            return mask

        forced_mask = mask_for(request.forced_interventions)
        if forced_mask.bit_count() != len(request.forced_interventions):
            return None
        path_masks = tuple(mask_for(clause.candidate_ids) for clause in path_clauses)
        if any(mask == 0 for mask in path_masks):
            return None
        access_masks = tuple(
            mask for clause in access_clauses if (mask := mask_for(clause.candidate_ids))
        )
        excluded_masks = {mask_for(solution) for solution in exclusions}
        forced_count = forced_mask.bit_count()
        optional_indices = tuple(
            index for index in range(len(ordered)) if not forced_mask & (1 << index)
        )
        optional_slots = target_count - forced_count
        if optional_slots < 0 or optional_slots > len(optional_indices):
            return None

        def objectives_match(mask: int) -> bool:
            if set(fixed_objectives) == {"intervention_count"}:
                return True
            selected = frozenset(
                candidate for index, candidate in enumerate(ordered) if mask & (1 << index)
            )
            values = self._selected_objective_values(selected, tuple(fixed_objectives))
            return all(values[key] == value for key, value in fixed_objectives.items())

        for choice_index, choice in enumerate(combinations(optional_indices, optional_slots)):
            if choice_index % 1024 == 0 and self._control_state(deadline, cancel_event):
                raise TimeoutError
            selected_mask = forced_mask
            for index in choice:
                selected_mask |= 1 << index
            if any(not selected_mask & clause_mask for clause_mask in path_masks):
                continue
            if any(selected_mask & mask == mask for mask in access_masks):
                continue
            if selected_mask in excluded_masks or not objectives_match(selected_mask):
                continue
            return frozenset(
                candidate for index, candidate in enumerate(ordered) if selected_mask & (1 << index)
            )
        return None

    def _selected_objective_values(
        self, selected: frozenset[str], keys: Sequence[str]
    ) -> dict[str, int]:
        values = {
            "intervention_count": len(selected),
            "weighted_cost": sum(self.scenario.candidates[item].cost for item in selected),
            "access_penalty": sum(
                self.scenario.candidates[item].access_penalty for item in selected
            ),
            "adjacency_penalty": sum(
                left in selected and right in selected for left, right in self._close_pairs
            ),
        }
        return {key: int(values[key]) for key in keys}

    @staticmethod
    def _merge_path_clauses(
        existing: list[PathClause], incoming: Sequence[PathClause]
    ) -> list[PathClause]:
        """Merge path cuts while retaining a logically equivalent antichain.

        For clauses belonging to the same portal pair, ``Or(A)`` subsumes
        ``Or(B)`` when ``A`` is a subset of ``B``.  Keeping only subset-minimal
        routes removes large numbers of overlapping boundary-node paths without
        weakening the CEGIS relaxation.
        """

        added: list[PathClause] = []
        for clause in sorted(
            incoming,
            key=lambda item: (item.pair_key, len(item.candidate_ids), item.candidate_ids),
        ):
            candidate_set = set(clause.candidate_ids)
            if any(
                current.pair_key == clause.pair_key
                and set(current.candidate_ids).issubset(candidate_set)
                for current in existing
            ):
                continue
            existing[:] = [
                current
                for current in existing
                if not (
                    current.pair_key == clause.pair_key
                    and candidate_set.issubset(set(current.candidate_ids))
                )
            ]
            existing.append(clause)
            added.append(clause)
        existing.sort(key=lambda item: (item.pair_key, len(item.candidate_ids), item.candidate_ids))
        return added

    @staticmethod
    def _objective_keys(mode: str) -> tuple[str, ...]:
        if mode in {"fewest", "minimum_filters"}:
            return ("intervention_count",)
        if mode == "access":
            return ("intervention_count", "access_penalty", "weighted_cost", "adjacency_penalty")
        return ("intervention_count", "weighted_cost", "access_penalty", "adjacency_penalty")

    def _objective_domain(self, key: str, intervention_count: int, upper: int) -> list[int]:
        if key == "intervention_count" or key == "adjacency_penalty":
            return list(range(upper + 1))
        attribute = "cost" if key == "weighted_cost" else "access_penalty"
        reachable: list[set[int]] = [set() for _ in range(intervention_count + 1)]
        reachable[0].add(0)
        for candidate in self.scenario.candidates.values():
            value = int(getattr(candidate, attribute))
            for count in range(intervention_count - 1, -1, -1):
                reachable[count + 1].update(total + value for total in reachable[count])
        domain = sorted(value for value in reachable[intervention_count] if value <= upper)
        if upper not in domain:
            domain.append(upper)
            domain.sort()
        return domain

    @staticmethod
    def _unsat_core(
        records: Sequence[ConstraintRecord],
        internal: Sequence[z3.BoolRef],
        deadline: float,
        cancel_event: threading.Event,
    ) -> list[ConstraintRecord]:
        solver = z3.Solver()
        assumptions: list[z3.BoolRef] = []
        by_name: dict[str, ConstraintRecord] = {}
        for index, record in enumerate(records):
            assumption = z3.Bool(f"assumption__{index}")
            assumptions.append(assumption)
            by_name[assumption.decl().name()] = record
            solver.add(z3.Implies(assumption, record.expression))
        solver.add(*internal)
        status, control = FourPlantersSolver._cooperative_solver_check(
            solver, deadline, cancel_event, *assumptions
        )
        if control or status != z3.unsat:
            return []
        return [by_name[item.decl().name()] for item in solver.unsat_core()]

    @staticmethod
    def _cooperative_solver_check(
        solver: z3.Solver,
        deadline: float,
        cancel_event: threading.Event,
        *assumptions: z3.BoolRef,
    ) -> tuple[z3.CheckSatResult | None, str | None]:
        """Run a Z3 check that a cancellation request can interrupt promptly.

        Z3's Python call blocks its worker thread. A short-lived watcher invokes
        the solver's thread-safe interrupt hook only when this run's cancellation
        event is set. The solver retains its normal deadline as a distinct timeout.
        """

        control = FourPlantersSolver._control_state(deadline, cancel_event)
        if control:
            return None, control
        solver.set(timeout=max(1, int((deadline - time.monotonic()) * 1000)))
        finished = threading.Event()

        def interrupt_when_cancelled() -> None:
            while not finished.wait(0.01):
                if cancel_event.is_set():
                    solver.interrupt()
                    return

        watcher = threading.Thread(
            target=interrupt_when_cancelled,
            name="geospatial-lab-z3-cancel",
            daemon=True,
        )
        watcher.start()
        try:
            status = solver.check(*assumptions)
        finally:
            finished.set()
            watcher.join(timeout=0.1)
        return status, FourPlantersSolver._control_state(deadline, cancel_event)

    def _counterexample_batch(
        self, selected: frozenset[str], pairs: Sequence[PortalPair]
    ) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        seen_clauses: set[tuple[str, tuple[str, ...]]] = set()
        for pair in pairs:
            portal_a = self.scenario.portals[pair.a]
            portal_b = self.scenario.portals[pair.b]
            label = pair.label or self._pair_label(pair.a, pair.b)
            for sources, targets, direction in (
                (portal_a.node_ids, portal_b.node_ids, f"{portal_a.label} → {portal_b.label}"),
                (portal_b.node_ids, portal_a.node_ids, f"{portal_b.label} → {portal_a.label}"),
            ):
                for source in sorted(sources):
                    for target in sorted(targets):
                        route = self._shortest_route([source], [target], selected)
                        if route is None:
                            continue
                        candidate_key = tuple(sorted(route["candidate_ids"]))
                        clause_key = (self._pair_key(pair.a, pair.b), candidate_key)
                        if clause_key in seen_clauses:
                            continue
                        seen_clauses.add(clause_key)
                        found.append(
                            {
                                "pair": {"a": pair.a, "b": pair.b},
                                "pair_key": self._pair_key(pair.a, pair.b),
                                "pair_label": label,
                                "direction": direction,
                                "source_node_id": source,
                                "target_node_id": target,
                                "route": route,
                            }
                        )

        # Seed each endpoint with two deterministic alternatives. Temporarily
        # removing one candidate from the base route can only reveal another
        # route that is open in the actual selected graph, so every resulting
        # clause is a sound CEGIS counterexample. This bounded diversity avoids
        # several expensive solve/refine round trips without attempting to
        # enumerate all paths.
        alternatives: list[dict[str, Any]] = []
        for item in list(found):
            candidate_ids = item["route"]["candidate_ids"]
            middle = (len(candidate_ids) - 1) / 2
            candidate_indices = sorted(
                range(len(candidate_ids)), key=lambda index: (abs(index - middle), index)
            )
            alternatives_for_endpoint = 0
            for candidate_index in candidate_indices:
                route = self._shortest_route(
                    [item["source_node_id"]],
                    [item["target_node_id"]],
                    selected | frozenset({candidate_ids[candidate_index]}),
                )
                if route is None:
                    continue
                candidate_key = tuple(sorted(route["candidate_ids"]))
                clause_key = (item["pair_key"], candidate_key)
                if clause_key in seen_clauses:
                    continue
                seen_clauses.add(clause_key)
                alternatives.append({**item, "route": route})
                alternatives_for_endpoint += 1
                if alternatives_for_endpoint >= 2:
                    break
        found.extend(alternatives)
        found.sort(
            key=lambda item: (
                not bool(item["route"]["candidate_ids"]),
                item["route"]["length_m"],
                item["pair_key"],
                item["direction"],
                item["source_node_id"],
                item["target_node_id"],
                tuple(item["route"]["edge_ids"]),
            )
        )
        return found

    def _first_failed_access(self, selected: frozenset[str]) -> dict[str, Any] | None:
        for cluster in self.scenario.address_clusters.values():
            route = self._route_to_portals(cluster.node_id, cluster.allowed_portal_ids, selected)
            if not route:
                return {
                    "cluster_id": cluster.id,
                    "cluster_label": cluster.label,
                    "node_id": cluster.node_id,
                    "allowed_portal_ids": list(cluster.allowed_portal_ids),
                }
        return None

    def _route_to_portals(
        self,
        node_id: str,
        allowed_portal_ids: Sequence[str],
        selected: frozenset[str],
    ) -> dict[str, Any] | None:
        targets = sorted(
            {
                node
                for portal_id in allowed_portal_ids
                if portal_id in self.scenario.portals
                for node in self.scenario.portals[portal_id].node_ids
            }
        )
        if node_id in targets and node_id in self.scenario.nodes:
            node = self.scenario.nodes[node_id]
            point = [float(node["lon"]), float(node["lat"])]
            return {
                "node_ids": [node_id],
                "edge_ids": [],
                "candidate_ids": [],
                "street_names": [],
                "length_m": 0.0,
                # GeoJSON LineStrings require at least two positions. A
                # repeated point safely represents zero-length portal access.
                "geometry": {"type": "LineString", "coordinates": [point, point]},
            }
        return self._shortest_route([node_id], targets, selected)

    def _shortest_route(
        self,
        sources: Sequence[str],
        targets: Sequence[str],
        selected: frozenset[str],
    ) -> dict[str, Any] | None:
        blocked_edges = {
            edge_id
            for candidate in selected
            for edge_id in self.scenario.candidates[candidate].edge_ids
        }
        target_set = set(targets)
        queue: list[tuple[float, tuple[str, ...], str, tuple[str, ...]]] = []
        best: dict[str, tuple[float, tuple[str, ...]]] = {}
        for source in sorted(set(sources)):
            if source not in self.scenario.nodes:
                continue
            state = (0.0, (), source, (source,))
            heapq.heappush(queue, state)
            best[source] = (0.0, ())
        while queue:
            distance, edge_ids, node, node_ids = heapq.heappop(queue)
            if best.get(node) != (distance, edge_ids):
                continue
            if node in target_set and edge_ids:
                return self._route_payload(node_ids, edge_ids, distance)
            for edge in self._adjacency.get(node, []):
                if edge["id"] in blocked_edges:
                    continue
                next_node = edge["v"]
                next_distance = distance + max(0.01, float(edge.get("length_m", 1)))
                next_edges = edge_ids + (edge["id"],)
                candidate_state = (next_distance, next_edges)
                if next_node not in best or candidate_state < best[next_node]:
                    best[next_node] = candidate_state
                    heapq.heappush(
                        queue, (next_distance, next_edges, next_node, node_ids + (next_node,))
                    )
        return None

    def _route_payload(
        self, node_ids: Sequence[str], edge_ids: Sequence[str], length_m: float
    ) -> dict[str, Any]:
        candidates: list[str] = []
        street_names: list[str] = []
        coordinates: list[list[float]] = []
        for index, edge_id in enumerate(edge_ids):
            edge = self.scenario.edges[edge_id]
            candidate = edge.get("candidate_id")
            if candidate and candidate not in candidates:
                candidates.append(candidate)
            name = str(edge.get("name") or "Unnamed street")
            if name not in street_names:
                street_names.append(name)
            geometry = edge.get("geometry")
            if isinstance(geometry, dict):
                geometry = geometry.get("coordinates")
            if not geometry:
                u = self.scenario.nodes[edge["u"]]
                v = self.scenario.nodes[edge["v"]]
                geometry = [[float(u["lon"]), float(u["lat"])], [float(v["lon"]), float(v["lat"])]]
            points = [[float(point[0]), float(point[1])] for point in geometry]
            u_node = self.scenario.nodes[edge["u"]]
            u_point = (float(u_node["lon"]), float(u_node["lat"]))
            if points and self._coordinate_distance(
                points[-1], u_point
            ) < self._coordinate_distance(points[0], u_point):
                points.reverse()
            if index and coordinates and points and coordinates[-1] == points[0]:
                points = points[1:]
            coordinates.extend(points)
        return {
            "node_ids": list(node_ids),
            "edge_ids": list(edge_ids),
            "candidate_ids": candidates,
            "street_names": street_names,
            "length_m": round(length_m, 1),
            "geometry": {"type": "LineString", "coordinates": coordinates},
        }

    @staticmethod
    def _coordinate_distance(point: Sequence[float], other: Sequence[float]) -> float:
        return (float(point[0]) - float(other[0])) ** 2 + (float(point[1]) - float(other[1])) ** 2

    def verify_solution(
        self,
        request: SolveRequest,
        selected: frozenset[str],
        pairs: Sequence[PortalPair] | None = None,
    ) -> dict[str, Any]:
        pairs = list(pairs if pairs is not None else self._pairs(request))
        errors: list[str] = []
        if len(selected) > request.budget:
            errors.append("intervention budget exceeded")
        if not set(request.forced_interventions).issubset(selected):
            errors.append("a forced intervention is missing")
        if set(request.locked_open_streets) & selected:
            errors.append("a locked-open street is selected")
        if not selected.issubset(self.scenario.candidates):
            errors.append("a selected intervention is ineligible")

        # Deliberately rebuild a fresh NetworkX graph instead of reusing the
        # custom Dijkstra implementation that generates CEGIS counterexamples.
        # This is the independent final connectivity check: a defect in route
        # reconstruction or the solver's adjacency cache cannot certify itself.
        blocked_edges = {
            edge_id
            for candidate_id in selected
            if candidate_id in self.scenario.candidates
            for edge_id in self.scenario.candidates[candidate_id].edge_ids
        }
        verification_graph = nx.DiGraph()
        verification_graph.add_nodes_from(self.scenario.nodes)
        for edge_id, edge in self.scenario.edges.items():
            if edge_id not in blocked_edges:
                verification_graph.add_edge(edge["u"], edge["v"])

        reachable_cache: dict[tuple[str, ...], set[str]] = {}

        def reachable_from(sources: Sequence[str]) -> set[str]:
            key = tuple(sorted(set(sources)))
            cached = reachable_cache.get(key)
            if cached is not None:
                return cached
            reachable = set(key)
            for source in key:
                if source in verification_graph:
                    reachable.update(nx.descendants(verification_graph, source))
            reachable_cache[key] = reachable
            return reachable

        pair_summary: list[dict[str, Any]] = []
        for pair in pairs:
            portal_a = self.scenario.portals[pair.a]
            portal_b = self.scenario.portals[pair.b]
            forward_exists = bool(reachable_from(portal_a.node_ids).intersection(portal_b.node_ids))
            reverse_exists = bool(reachable_from(portal_b.node_ids).intersection(portal_a.node_ids))
            disconnected = not forward_exists and not reverse_exists
            if not disconnected:
                errors.append(f"portal pair {pair.a} ↔ {pair.b} remains connected")
            pair_summary.append(
                {
                    "a": pair.a,
                    "b": pair.b,
                    "label": pair.label or self._pair_label(pair.a, pair.b),
                    "private_car_disconnected": disconnected,
                    "forward_route_exists": forward_exists,
                    "reverse_route_exists": reverse_exists,
                }
            )
        served = 0
        unserved: list[str] = []
        cluster_details: list[dict[str, Any]] = []
        reverse_graph = verification_graph.reverse(copy=False)
        access_cache: dict[tuple[str, ...], set[str]] = {}
        for cluster in self.scenario.address_clusters.values():
            portal_key = tuple(sorted(cluster.allowed_portal_ids))
            nodes_reaching_portals = access_cache.get(portal_key)
            if nodes_reaching_portals is None:
                portal_nodes = sorted(
                    {
                        node_id
                        for portal_id in portal_key
                        if portal_id in self.scenario.portals
                        for node_id in self.scenario.portals[portal_id].node_ids
                    }
                )
                nodes_reaching_portals = set(portal_nodes)
                for portal_node in portal_nodes:
                    if portal_node in reverse_graph:
                        nodes_reaching_portals.update(nx.descendants(reverse_graph, portal_node))
                access_cache[portal_key] = nodes_reaching_portals
            is_served = cluster.node_id in nodes_reaching_portals
            if is_served:
                served += 1
            else:
                unserved.append(cluster.id)
                errors.append(f"address cluster {cluster.id} has no permitted portal route")
            cluster_details.append(
                {
                    "id": cluster.id,
                    "served": is_served,
                }
            )
        return {
            "verified": not errors,
            "errors": errors,
            "portal_connectivity_summary": pair_summary,
            "address_access_summary": {
                "included_clusters": len(self.scenario.address_clusters),
                "served_clusters": served,
                "unserved_cluster_ids": unserved,
                "all_served": not unserved,
                "total": len(self.scenario.address_clusters),
                "served": served,
                "unserved_ids": unserved,
                "all_accessible": not unserved,
                "details": cluster_details,
            },
        }

    def _access_metrics(self, selected: frozenset[str]) -> dict[str, Any]:
        detours: list[float] = []
        significantly_affected = 0
        for cluster in self.scenario.address_clusters.values():
            route = self._route_to_portals(cluster.node_id, cluster.allowed_portal_ids, selected)
            baseline = self._baseline_access.get(cluster.id, math.inf)
            if not route or not math.isfinite(baseline):
                continue
            detour = max(0.0, float(route["length_m"]) - baseline)
            detours.append(detour)
            if baseline > 0 and detour / baseline >= 0.25 and detour >= 100:
                significantly_affected += 1
        detours.sort()
        mean = sum(detours) / len(detours) if detours else 0.0
        median = detours[len(detours) // 2] if detours else 0.0
        return {
            "mean_additional_distance_m": round(mean, 1),
            "median_additional_distance_m": round(median, 1),
            "maximum_additional_distance_m": round(max(detours, default=0.0), 1),
            "significantly_affected_clusters": significantly_affected,
            "definition": (
                "Directed shortest egress distance to the nearest permitted portal, "
                "compared with the unfiltered graph."
            ),
        }

    def _access_routes_geojson(self, selected: frozenset[str]) -> dict[str, Any]:
        features: list[dict[str, Any]] = []
        portal_nodes = {
            node_id: portal.id
            for portal in self.scenario.portals.values()
            for node_id in portal.node_ids
        }
        for cluster in self.scenario.address_clusters.values():
            route = self._route_to_portals(cluster.node_id, cluster.allowed_portal_ids, selected)
            if not route:
                continue
            endpoint = route["node_ids"][-1]
            features.append(
                {
                    "type": "Feature",
                    "id": f"access-route-{cluster.id}",
                    "properties": {
                        "cluster_id": cluster.id,
                        "cluster_label": cluster.label,
                        "portal_id": portal_nodes.get(endpoint),
                        "length_m": route["length_m"],
                        "verified": True,
                    },
                    "geometry": route["geometry"],
                }
            )
        return {"type": "FeatureCollection", "features": features}

    def _components_geojson(
        self, selected: frozenset[str]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Describe directed private-car strong connectivity for one graph state.

        Strongly connected components are the appropriate directed analogue of
        connected regions: every node within one component can reach every other
        node while respecting one-way streets. Open edges between components are
        retained in the GeoJSON but identified as one-way inter-component links;
        they are not coloured as though they belonged to either mutual-reachability
        region.
        """

        blocked_edges = {
            edge_id
            for candidate in selected
            for edge_id in self.scenario.candidates[candidate].edge_ids
        }
        graph = nx.DiGraph()
        graph.add_nodes_from(self.scenario.nodes)
        open_directed_edge_count = 0
        for edge in self.scenario.edges.values():
            if edge["id"] not in blocked_edges:
                graph.add_edge(edge["u"], edge["v"])
                open_directed_edge_count += 1
        components = sorted(
            (set(values) for values in nx.strongly_connected_components(graph)),
            key=lambda values: (-len(values), min(values)),
        )
        component_by_node = {
            node: index for index, component in enumerate(components) for node in component
        }
        palette = ("#3c8b84", "#db7a37", "#516fa8", "#9a6688", "#82914d", "#967258")
        color_by_component = {
            index: palette[
                int(hashlib.sha256(min(component).encode("utf-8")).hexdigest()[:8], 16)
                % len(palette)
            ]
            for index, component in enumerate(components)
        }
        features: list[dict[str, Any]] = []
        seen_physical: set[str] = set()
        inter_component_physical_edges = 0
        for edge in sorted(self.scenario.edges.values(), key=lambda value: value["id"]):
            if edge["id"] in blocked_edges:
                continue
            physical_id = str(edge.get("physical_id") or edge["id"])
            if physical_id in seen_physical:
                continue
            seen_physical.add(physical_id)
            from_component_id = component_by_node[edge["u"]]
            to_component_id = component_by_node[edge["v"]]
            within_component = from_component_id == to_component_id
            if not within_component:
                inter_component_physical_edges += 1
            component_id = from_component_id if within_component else None
            geometry = edge.get("geometry")
            if isinstance(geometry, dict):
                geometry = geometry.get("coordinates")
            if not geometry:
                u = self.scenario.nodes[edge["u"]]
                v = self.scenario.nodes[edge["v"]]
                geometry = [[float(u["lon"]), float(u["lat"])], [float(v["lon"]), float(v["lat"])]]
            features.append(
                {
                    "type": "Feature",
                    "id": f"component-{physical_id}",
                    "properties": {
                        "metric": "directed_strongly_connected_components",
                        "directed": True,
                        "component_id": component_id,
                        "component_size": (
                            len(components[component_id]) if component_id is not None else None
                        ),
                        "from_component_id": from_component_id,
                        "to_component_id": to_component_id,
                        "within_component": within_component,
                        "color": (
                            color_by_component[component_id]
                            if component_id is not None
                            else "#777c79"
                        ),
                    },
                    "geometry": {"type": "LineString", "coordinates": geometry},
                }
            )
        node_count = len(self.scenario.nodes)
        largest_component_size = len(components[0]) if components else 0
        summary = {
            "component_count": len(components),
            "node_count": node_count,
            "largest_component_node_count": largest_component_size,
            "largest_component_fraction": (
                round(largest_component_size / node_count, 4) if node_count else 0.0
            ),
            "singleton_component_count": sum(len(component) == 1 for component in components),
            "open_directed_edge_count": open_directed_edge_count,
            "rendered_physical_edge_count": len(features),
            "inter_component_physical_edge_count": inter_component_physical_edges,
        }
        return {"type": "FeatureCollection", "features": features}, summary

    def _explain_unsat(
        self,
        request: SolveRequest,
        pairs: Sequence[PortalPair],
        core: Sequence[ConstraintRecord],
    ) -> dict[str, Any]:
        core_items = [
            {
                "key": item.key,
                "label": item.label,
                "category": item.category,
                "details": item.details,
            }
            for item in core
        ]
        categories = {item.category for item in core}
        labels = [item.label for item in core if item.category != "budget"]
        if "budget" in categories and "locked_open" in categories and "portal_pair" in categories:
            message = (
                f"At most {request.budget} interventions are insufficient while "
                + ", ".join(labels)
                + "."
            )
        elif "budget" in categories and "portal_pair" in categories:
            pair_labels = [item.label for item in core if item.category == "portal_pair"]
            message = (
                f"At most {request.budget} interventions cannot disconnect "
                + " and ".join(pair_labels)
                + " under the current candidate and local-access assumptions."
            )
        elif "forced_intervention" in categories and "local_access" in categories:
            message = (
                "The forced intervention combination severs required local access. "
                "At least one forced street must be released."
            )
        elif labels:
            message = (
                "The requested assumptions are mutually incompatible: " + "; ".join(labels) + "."
            )
        else:
            message = (
                "No intervention set satisfies the current candidate, portal-pair, budget, and "
                "local-access constraints."
            )
        suggestions: list[dict[str, Any]] = []
        if "budget" in categories:
            suggestions.append(
                {
                    "type": "increase_budget",
                    "value": min(request.budget + 1, 20),
                    "label": f"Try a budget of {min(request.budget + 1, 20)}",
                }
            )
        for item in core:
            if item.category == "locked_open":
                street_name = self.scenario.candidates[item.details["candidate_id"]].street_name
                suggestions.append(
                    {
                        "type": "unlock_street",
                        "candidate_id": item.details["candidate_id"],
                        "label": f"Unlock {street_name}",
                    }
                )
            elif item.category == "forced_intervention":
                street_name = self.scenario.candidates[item.details["candidate_id"]].street_name
                suggestions.append(
                    {
                        "type": "release_forced_intervention",
                        "candidate_id": item.details["candidate_id"],
                        "label": f"Release {street_name}",
                    }
                )
            elif item.category == "portal_pair":
                suggestions.append(
                    {
                        "type": "remove_portal_pair",
                        "pair": {"a": item.details["a"], "b": item.details["b"]},
                        "label": f"Remove {item.details['label']}",
                    }
                )
        return {"message": message, "core": core_items, "suggestions": suggestions}

    def _proof_hash(
        self,
        request: SolveRequest,
        selected: frozenset[str],
        verification: dict[str, Any],
    ) -> str:
        payload = {
            "snapshot_id": self.scenario.snapshot_id,
            "request": request.model_dump(exclude={"timeout_seconds", "solve_id"}),
            "selected": sorted(selected),
            "verification": verification,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:20]

    def _pair_label(self, portal_a: str, portal_b: str) -> str:
        return f"{self.scenario.portals[portal_a].label} ↔ {self.scenario.portals[portal_b].label}"

    @staticmethod
    def _pair_key(portal_a: str, portal_b: str) -> str:
        return "::".join(sorted((portal_a, portal_b)))
