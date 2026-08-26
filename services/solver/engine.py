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
from typing import Any

import networkx as nx
import z3

from .models import PortalPair, SolveRequest
from .scenario import Scenario, distance_metres

LOGGER = logging.getLogger("four_planters.solver")


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
            )
            if answer.status == "timeout":
                yield from finish(
                    "timeout",
                    "The constraint solver reached its time limit. This is not an UNSAT result.",
                    result_fields={"diagnostics": {"z3_reason": answer.reason}},
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
                    if clause not in path_clauses and clause not in new_clauses:
                        new_clauses.append(clause)
                path_clauses.extend(new_clauses)
                representative_clause = new_clauses[0]
                route_word = "routes" if len(new_clauses) != 1 else "route"
                yield event(
                    "refining",
                    "refining",
                    f"The model now cuts {len(new_clauses)} distinct surviving {route_word} "
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
                            for clause in new_clauses
                        ],
                        "routes_added": len(new_clauses),
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
            components = self._components_geojson(selected)
            proof_payload = {
                "selected_intervention_ids": sorted(selected),
                "objective_values": objective_values,
                "verification_status": "independently_verified",
                "address_access_summary": verification["address_access_summary"],
                "portal_connectivity_summary": verification["portal_connectivity_summary"],
                "mode_connectivity_summary": {
                    "walking": "unchanged_by_filter_semantics",
                    "cycling": "unchanged_by_filter_semantics",
                    "emergency": (
                        "passable_under_removable_filter_assumption"
                        if request.emergency_permeable
                        else "not_asserted"
                    ),
                },
                "local_detour_metrics": metrics,
                "access_routes": access_routes,
                "components": components,
                "proof_hash": self._proof_hash(request, selected, verification),
            }
            explanation = (
                f"Under snapshot {self.scenario.snapshot_id}, the selected filters cut every "
                "requested private-car portal connection while every included address cluster "
                "retains a permitted portal route. Walking and cycling edges are unchanged by "
                "the filter semantics."
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
    ) -> dict[str, z3.ArithRef]:
        count_terms = [z3.If(variables[candidate], 1, 0) for candidate in self.candidate_ids]
        cost_terms = [
            z3.If(variables[candidate], self.scenario.candidates[candidate].cost, 0)
            for candidate in self.candidate_ids
        ]
        access_terms = [
            z3.If(variables[candidate], self.scenario.candidates[candidate].access_penalty, 0)
            for candidate in self.candidate_ids
        ]
        adjacency_terms = [
            z3.If(z3.And(variables[left], variables[right]), 1, 0)
            for left, right in self._close_pairs
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
    ) -> CandidateAnswer:
        variables = {
            candidate: z3.Bool(f"blocked__{candidate}") for candidate in self.candidate_ids
        }
        expressions = self._expressions(variables)
        records = self._constraint_records(
            request, pairs, path_clauses, access_clauses, variables, expressions
        )
        internal: list[z3.BoolRef] = []
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
        if fixed_objectives:
            for key, value in fixed_objectives.items():
                if key in expressions:
                    internal.append(expressions[key] == value)

        objective_keys = self._objective_keys(request.objective_mode)
        search = z3.Solver()
        search.set(timeout=max(1, int((deadline - time.monotonic()) * 1000)), random_seed=0)
        search.add(*[record.expression for record in records], *internal)
        status = search.check()
        if status == z3.unknown:
            return CandidateAnswer("timeout", reason=search.reason_unknown())
        if status == z3.unsat:
            core = self._unsat_core(records, internal, deadline)
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
            for key in objective_keys:
                expression = expressions[key]
                current_value = current_model.eval(expression, model_completion=True).as_long()
                domain = self._objective_domain(
                    key,
                    objectives.get("intervention_count", current_value),
                    current_value,
                )
                current_index = domain.index(current_value)
                # Ask for the immediately cheaper attainable value. A SAT
                # model may jump several values; a single UNSAT answer then
                # proves the current value minimal. This avoids broad numeric
                # binary searches over impossible weighted-cost values.
                while current_index > 0:
                    if time.monotonic() >= deadline:
                        return CandidateAnswer("timeout", reason="objective search deadline")
                    threshold = domain[current_index - 1]
                    search.set(timeout=max(1, int((deadline - time.monotonic()) * 1000)))
                    search.push()
                    search.add(expression <= threshold)
                    bounded_status = search.check()
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
                search.add(expression == current_value)
                search.set(timeout=max(1, int((deadline - time.monotonic()) * 1000)))
                fixed_status = search.check()
                if fixed_status != z3.sat:
                    return CandidateAnswer("timeout", reason=search.reason_unknown())
                current_model = search.model()

        # Select a unique Boolean model after fixing the real objective vector.
        # Only variables that occur in a discovered/user constraint can be true
        # in a minimum-cardinality solution; fixing all others open keeps the
        # incremental tie-break compact even for hundreds of street candidates.
        active = set(request.forced_interventions)
        active.update(candidate for clause in path_clauses for candidate in clause.candidate_ids)
        active.update(candidate for clause in access_clauses for candidate in clause.candidate_ids)
        active.update(candidate for solution in exclusions for candidate in solution)
        selector = z3.Solver()
        selector.set(timeout=max(1, int((deadline - time.monotonic()) * 1000)), random_seed=0)
        selector.add(*[record.expression for record in records], *internal)
        selector.add(
            *[expressions[key] == value for key, value in objectives.items() if key in expressions]
        )
        selector.add(
            *[
                z3.Not(variables[candidate])
                for candidate in self.candidate_ids
                if candidate not in active
            ]
        )
        # Stable variable/constraint insertion plus a fixed Z3 seed gives a
        # reproducible structural model without adding a hidden city objective.
        selector.set(timeout=max(1, int((deadline - time.monotonic()) * 1000)))
        if selector.check() != z3.sat:
            return CandidateAnswer("timeout", reason=selector.reason_unknown())
        model = selector.model()
        selected = frozenset(
            candidate
            for candidate, variable in variables.items()
            if z3.is_true(model.eval(variable, model_completion=True))
        )
        return CandidateAnswer("sat", selected, objectives)

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
    ) -> list[ConstraintRecord]:
        solver = z3.Solver()
        solver.set(timeout=max(1, int((deadline - time.monotonic()) * 1000)))
        assumptions: list[z3.BoolRef] = []
        by_name: dict[str, ConstraintRecord] = {}
        for index, record in enumerate(records):
            assumption = z3.Bool(f"assumption__{index}")
            assumptions.append(assumption)
            by_name[assumption.decl().name()] = record
            solver.add(z3.Implies(assumption, record.expression))
        solver.add(*internal)
        if solver.check(*assumptions) != z3.unsat:
            return []
        return [by_name[item.decl().name()] for item in solver.unsat_core()]

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
        pair_summary: list[dict[str, Any]] = []
        for pair in pairs:
            portal_a = self.scenario.portals[pair.a]
            portal_b = self.scenario.portals[pair.b]
            forward = self._shortest_route(portal_a.node_ids, portal_b.node_ids, selected)
            reverse = self._shortest_route(portal_b.node_ids, portal_a.node_ids, selected)
            disconnected = forward is None and reverse is None
            if not disconnected:
                errors.append(f"portal pair {pair.a} ↔ {pair.b} remains connected")
            pair_summary.append(
                {
                    "a": pair.a,
                    "b": pair.b,
                    "label": pair.label or self._pair_label(pair.a, pair.b),
                    "private_car_disconnected": disconnected,
                    "forward_route_exists": forward is not None,
                    "reverse_route_exists": reverse is not None,
                }
            )
        served = 0
        unserved: list[str] = []
        cluster_details: list[dict[str, Any]] = []
        for cluster in self.scenario.address_clusters.values():
            route = self._route_to_portals(cluster.node_id, cluster.allowed_portal_ids, selected)
            if route:
                served += 1
            else:
                unserved.append(cluster.id)
                errors.append(f"address cluster {cluster.id} has no permitted portal route")
            cluster_details.append(
                {
                    "id": cluster.id,
                    "served": route is not None,
                    "route_length_m": route["length_m"] if route else None,
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

    def _components_geojson(self, selected: frozenset[str]) -> dict[str, Any]:
        blocked_edges = {
            edge_id
            for candidate in selected
            for edge_id in self.scenario.candidates[candidate].edge_ids
        }
        graph = nx.Graph()
        graph.add_nodes_from(self.scenario.nodes)
        for edge in self.scenario.edges.values():
            if edge["id"] not in blocked_edges:
                graph.add_edge(edge["u"], edge["v"])
        components = sorted(
            nx.connected_components(graph), key=lambda values: (-len(values), min(values))
        )
        component_by_node = {
            node: index for index, component in enumerate(components) for node in component
        }
        palette = ("#3c8b84", "#db7a37", "#516fa8", "#9a6688", "#82914d", "#967258")
        features: list[dict[str, Any]] = []
        seen_physical: set[str] = set()
        for edge in sorted(self.scenario.edges.values(), key=lambda value: value["id"]):
            if edge["id"] in blocked_edges:
                continue
            physical_id = str(edge.get("physical_id") or edge["id"])
            if physical_id in seen_physical:
                continue
            seen_physical.add(physical_id)
            component_id = component_by_node.get(edge["u"], 0)
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
                        "component_id": component_id,
                        "component_size": len(components[component_id]),
                        "color": palette[component_id % len(palette)],
                    },
                    "geometry": {"type": "LineString", "coordinates": geometry},
                }
            )
        return {"type": "FeatureCollection", "features": features}

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
