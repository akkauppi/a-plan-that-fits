from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import networkx as nx
import z3

FloodReturnPeriod = Literal[100, 1000]
RepairStatus = Literal[
    "verified_optimal",
    "verified_unsat",
    "timeout",
    "cancelled",
    "data_error",
]


class _AnalysisInterrupted(RuntimeError):
    """Internal control-flow signal for a request deadline or explicit cancellation."""

    def __init__(self, status: Literal["timeout", "cancelled"], phase: str) -> None:
        super().__init__(status)
        self.status = status
        self.phase = phase


@dataclass(frozen=True)
class _AnalysisControl:
    """One shared request controller used by Z3 and every graph-analysis phase."""

    deadline: float
    cancel_event: threading.Event

    def checkpoint(self, phase: str) -> None:
        if self.cancel_event.is_set():
            raise _AnalysisInterrupted("cancelled", phase)
        if time.monotonic() >= self.deadline:
            raise _AnalysisInterrupted("timeout", phase)


@dataclass(frozen=True)
class NetworkNode:
    id: str
    longitude: float
    latitude: float


@dataclass(frozen=True)
class NetworkEdge:
    id: str
    physical_id: str
    source: str
    target: str
    length_m: float
    geometry: tuple[tuple[float, float], ...]
    name: str | None = None
    highway: str | None = None
    private_car: bool = True


@dataclass(frozen=True)
class AccessPoint:
    """A reviewed map point that is deterministically snapped to the car graph."""

    id: str
    label: str
    longitude: float
    latitude: float
    allowed_destination_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SnappedAccessPoint:
    id: str
    label: str
    node_id: str
    longitude: float
    latitude: float
    requested_longitude: float
    requested_latitude: float
    snap_distance_m: float
    allowed_destination_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "node_id": self.node_id,
            "point": [self.longitude, self.latitude],
            "requested_point": [self.requested_longitude, self.requested_latitude],
            "snap_distance_m": round(self.snap_distance_m, 2),
            "allowed_destination_ids": list(self.allowed_destination_ids),
        }


@dataclass(frozen=True)
class DisruptionAssumption:
    """Explicit edge-availability assumptions; flood geometry never closes a link by itself."""

    flood_return_period_years: FloodReturnPeriod | None = None
    treat_flood_exposure_as_unavailable: bool = False
    roadworks_segment_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DecisionGroup:
    """One analytical decision spanning one or more frozen physical segments."""

    id: str
    label: str
    segment_ids: tuple[str, ...]
    cost: int = 1


@dataclass(frozen=True)
class AssumptionRepairRequest:
    """Search settings for a minimum *analytical* passability-assumption repair.

    A selected decision group means that the analysis would have to treat its member
    segments as available despite the disruption assumption. It does not mean that
    those segments are safe, open, or physically repairable. Without explicit groups,
    each eligible segment is represented by a backward-compatible singleton group.
    """

    budget: int = 4
    eligible_segment_ids: tuple[str, ...] | None = None
    decision_groups: tuple[DecisionGroup, ...] | None = None
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class FrozenResilienceNetwork:
    scenario_id: str
    base_snapshot_id: str
    flood_snapshot_id: str | None
    nodes: dict[str, NetworkNode]
    edges: tuple[NetworkEdge, ...]
    physical_segment_ids: frozenset[str]
    exposed_segment_ids: dict[int, frozenset[str]] = field(default_factory=dict)
    vertical_review_segment_ids: dict[int, frozenset[str]] = field(default_factory=dict)

    @classmethod
    def from_records(
        cls,
        *,
        scenario_id: str,
        nodes: Sequence[NetworkNode],
        edges: Sequence[NetworkEdge],
        exposed_segment_ids: dict[int, Iterable[str]] | None = None,
        base_snapshot_id: str = "test-base",
        flood_snapshot_id: str | None = "test-flood",
    ) -> FrozenResilienceNetwork:
        node_map = {node.id: node for node in nodes}
        parsed_edges = tuple(sorted(edges, key=lambda edge: edge.id))
        physical_ids = frozenset(edge.physical_id for edge in parsed_edges)
        network = cls(
            scenario_id=scenario_id,
            base_snapshot_id=base_snapshot_id,
            flood_snapshot_id=flood_snapshot_id,
            nodes=node_map,
            edges=parsed_edges,
            physical_segment_ids=physical_ids,
            exposed_segment_ids={
                int(period): frozenset(ids)
                for period, ids in (exposed_segment_ids or {}).items()
            },
        )
        network.validate()
        return network

    @classmethod
    def from_artifacts(
        cls,
        base_network_path: str | Path,
        flood_exposure_path: str | Path | None = None,
    ) -> FrozenResilienceNetwork:
        base = json.loads(Path(base_network_path).read_text(encoding="utf-8"))
        flood = (
            json.loads(Path(flood_exposure_path).read_text(encoding="utf-8"))
            if flood_exposure_path is not None
            else None
        )

        edge_to_physical: dict[str, str] = {}
        exposed: dict[int, set[str]] = {100: set(), 1000: set()}
        vertical_review: dict[int, set[str]] = {100: set(), 1000: set()}
        if flood is not None:
            base_reference = flood.get("base_network", {})
            if base_reference.get("snapshot_id") != base.get("snapshot_id"):
                raise ValueError("Flood exposure does not reference the supplied base snapshot")
            for segment in flood.get("segments", []):
                physical_id = str(segment["id"])
                for edge_id in segment.get("directed_edge_ids", []):
                    edge_to_physical[str(edge_id)] = physical_id
                for scenario in segment.get("scenarios", []):
                    period = int(scenario["return_period_years"])
                    if scenario.get("exposed"):
                        exposed.setdefault(period, set()).add(physical_id)
                        if segment.get("vertical_separation", {}).get("review_required"):
                            vertical_review.setdefault(period, set()).add(physical_id)

        parsed_nodes = {
            str(item["id"]): NetworkNode(
                id=str(item["id"]),
                longitude=float(item["longitude"]),
                latitude=float(item["latitude"]),
            )
            for item in base.get("nodes", [])
        }
        parsed_edges: list[NetworkEdge] = []
        for item in base.get("edges", []):
            edge_id = str(item["id"])
            physical_id = edge_to_physical.get(edge_id) or _physical_id_from_edge_id(edge_id)
            parsed_edges.append(
                NetworkEdge(
                    id=edge_id,
                    physical_id=physical_id,
                    source=str(item["from"]),
                    target=str(item["to"]),
                    length_m=float(item["length_m"]),
                    geometry=tuple(
                        (float(coordinate[0]), float(coordinate[1]))
                        for coordinate in item.get("geometry", [])
                    ),
                    name=item.get("name"),
                    highway=item.get("highway"),
                    private_car=bool(item.get("permissions", {}).get("private_car", False)),
                )
            )

        physical_ids = (
            frozenset(str(segment["id"]) for segment in flood.get("segments", []))
            if flood is not None
            else frozenset(edge.physical_id for edge in parsed_edges)
        )
        network = cls(
            scenario_id=str(base["scenario_id"]),
            base_snapshot_id=str(base["snapshot_id"]),
            flood_snapshot_id=str(flood["snapshot_id"]) if flood is not None else None,
            nodes=parsed_nodes,
            edges=tuple(sorted(parsed_edges, key=lambda edge: edge.id)),
            physical_segment_ids=physical_ids,
            exposed_segment_ids={period: frozenset(ids) for period, ids in exposed.items()},
            vertical_review_segment_ids={
                period: frozenset(ids) for period, ids in vertical_review.items()
            },
        )
        network.validate()
        return network

    def validate(self) -> None:
        if not self.nodes:
            raise ValueError("Resilience network has no nodes")
        if not self.edges:
            raise ValueError("Resilience network has no edges")
        edge_ids: set[str] = set()
        for edge in self.edges:
            if edge.id in edge_ids:
                raise ValueError(f"Duplicate directed edge ID: {edge.id}")
            edge_ids.add(edge.id)
            if edge.source not in self.nodes or edge.target not in self.nodes:
                raise ValueError(f"Edge {edge.id} references a missing node")
            if edge.physical_id not in self.physical_segment_ids:
                raise ValueError(f"Edge {edge.id} references an unknown physical segment")
            if edge.length_m < 0:
                raise ValueError(f"Edge {edge.id} has a negative length")
        for period, segment_ids in self.exposed_segment_ids.items():
            unknown = segment_ids - self.physical_segment_ids
            if unknown:
                raise ValueError(
                    f"Flood tier {period} references unknown segments: {sorted(unknown)[:3]}"
                )

    @property
    def private_car_node_ids(self) -> frozenset[str]:
        return frozenset(
            node_id
            for edge in self.edges
            if edge.private_car
            for node_id in (edge.source, edge.target)
        )

    def snap_points(self, points: Sequence[AccessPoint]) -> tuple[SnappedAccessPoint, ...]:
        candidate_nodes = sorted(self.private_car_node_ids)
        if not candidate_nodes:
            raise ValueError("The frozen network has no private-car links")
        seen: set[str] = set()
        snapped: list[SnappedAccessPoint] = []
        for point in points:
            if point.id in seen:
                raise ValueError(f"Duplicate access point ID: {point.id}")
            seen.add(point.id)
            node_id = min(
                candidate_nodes,
                key=lambda candidate: (
                    _distance_m(
                        point.longitude,
                        point.latitude,
                        self.nodes[candidate].longitude,
                        self.nodes[candidate].latitude,
                    ),
                    candidate,
                ),
            )
            node = self.nodes[node_id]
            snapped.append(
                SnappedAccessPoint(
                    id=point.id,
                    label=point.label,
                    node_id=node_id,
                    longitude=node.longitude,
                    latitude=node.latitude,
                    requested_longitude=point.longitude,
                    requested_latitude=point.latitude,
                    snap_distance_m=_distance_m(
                        point.longitude,
                        point.latitude,
                        node.longitude,
                        node.latitude,
                    ),
                    allowed_destination_ids=point.allowed_destination_ids,
                )
            )
        return tuple(snapped)

    def unavailable_segments(self, assumption: DisruptionAssumption) -> frozenset[str]:
        unknown_works = set(assumption.roadworks_segment_ids) - self.physical_segment_ids
        if unknown_works:
            raise ValueError(f"Unknown roadworks segments: {sorted(unknown_works)[:3]}")
        unavailable = set(assumption.roadworks_segment_ids)
        if assumption.treat_flood_exposure_as_unavailable:
            if assumption.flood_return_period_years is None:
                raise ValueError(
                    "A flood return period is required when exposure is treated as unavailable"
                )
            if assumption.flood_return_period_years not in self.exposed_segment_ids:
                raise ValueError(
                    f"Flood tier {assumption.flood_return_period_years} is not in this snapshot"
                )
            unavailable.update(
                self.exposed_segment_ids[assumption.flood_return_period_years]
            )
        return frozenset(unavailable)


def analyze_disruption(
    network: FrozenResilienceNetwork,
    assumption: DisruptionAssumption,
    origins: Sequence[SnappedAccessPoint],
    destinations: Sequence[SnappedAccessPoint],
    *,
    analytically_passable_segment_ids: Iterable[str] = (),
    _control: _AnalysisControl | None = None,
    _baseline_routes_by_origin: dict[str, dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Compare baseline and disrupted private-car access with map-ready evidence."""

    _checkpoint(_control, "disruption_setup")
    unavailable = network.unavailable_segments(assumption)
    repaired = frozenset(analytically_passable_segment_ids)
    _validate_access_study(network, origins, destinations, control=_control)
    if not repaired <= unavailable:
        raise ValueError("Analytically passable segments must be unavailable in the disruption")

    baseline_graph = (
        _build_graph(
            network,
            frozenset(),
            control=_control,
            phase="baseline_graph",
        )
        if _baseline_routes_by_origin is None
        else None
    )
    remaining_unavailable = unavailable - repaired
    private_car_segments = _private_car_segment_ids(
        network,
        control=_control,
        phase="disruption_private_car_segments",
    )
    effective_unavailable = remaining_unavailable & private_car_segments
    same_as_baseline = baseline_graph is not None and not effective_unavailable
    disrupted_graph = baseline_graph if same_as_baseline else _build_graph(
        network,
        effective_unavailable,
        control=_control,
        phase="disrupted_graph",
    )
    destination_by_id = {point.id: point for point in destinations}
    access_records: list[dict[str, Any]] = []
    stranded = 0

    for origin_index, origin in enumerate(sorted(origins, key=lambda point: point.id)):
        _periodic_checkpoint(_control, "access_route_analysis", origin_index)
        allowed_ids = _allowed_destination_ids(origin, destination_by_id)
        allowed_nodes = tuple(destination_by_id[item].node_id for item in allowed_ids)
        if _baseline_routes_by_origin is not None:
            if origin.id not in _baseline_routes_by_origin:
                raise ValueError(f"No cached baseline route exists for origin {origin.id}")
            baseline_route = _baseline_routes_by_origin[origin.id]
        else:
            assert baseline_graph is not None
            baseline_route = _best_route(
                network,
                baseline_graph,
                origin.node_id,
                allowed_nodes,
                control=_control,
                phase="baseline_route_search",
            )
        disrupted_route = baseline_route if same_as_baseline else _best_route(
            network,
            disrupted_graph,
            origin.node_id,
            allowed_nodes,
            control=_control,
            phase="disrupted_route_search",
        )
        for route in (baseline_route, disrupted_route):
            if route is None:
                continue
            route["destination_id"] = min(
                destination_id
                for destination_id in allowed_ids
                if destination_by_id[destination_id].node_id == route["destination_node_id"]
            )
        if baseline_route is None:
            status = "baseline_unreachable"
        elif disrupted_route is None:
            status = "stranded"
            stranded += 1
        else:
            status = "retained"
        access_records.append(
            {
                "origin": origin.as_dict(),
                "allowed_destination_ids": list(allowed_ids),
                "status": status,
                "baseline_route": baseline_route,
                "disrupted_route": disrupted_route,
                "detour_m": (
                    round(disrupted_route["length_m"] - baseline_route["length_m"], 2)
                    if baseline_route is not None and disrupted_route is not None
                    else None
                ),
            }
        )

    _checkpoint(_control, "access_route_analysis")
    weak_components = sorted(
        _weakly_connected_components(
            disrupted_graph,
            control=_control,
            phase="disrupted_components",
        ),
        key=lambda nodes: (-len(nodes), min(nodes) if nodes else ""),
    )
    node_to_component = {
        node_id: component_index
        for component_index, component in enumerate(weak_components)
        for node_id in component
    }
    relevant_component_ids = sorted(
        {
            node_to_component[point.node_id]
            for point in [*origins, *destinations]
            if point.node_id in node_to_component
        }
    )
    segments_by_component: dict[int, set[str]] = {
        component_id: set() for component_id in relevant_component_ids
    }
    for edge_index, (source, target, data) in enumerate(
        disrupted_graph.edges(data=True)
    ):
        _periodic_checkpoint(_control, "component_segment_scan", edge_index)
        component_id = node_to_component.get(source)
        if component_id in segments_by_component and node_to_component.get(target) == component_id:
            segments_by_component[component_id].add(str(data["physical_id"]))
    _checkpoint(_control, "component_segment_scan")
    baseline_unreachable_count = sum(
        record["status"] == "baseline_unreachable" for record in access_records
    )
    analysis_status = (
        "data_error"
        if baseline_unreachable_count
        else "stranded"
        if stranded
        else "verified"
    )
    return {
        "status": analysis_status,
        "message": (
            "The baseline graph cannot represent every required access relation."
            if baseline_unreachable_count
            else None
        ),
        "claim_scope": (
            "Reachability is verified only under the frozen private-car graph and the "
            "explicit unavailable-segment assumptions. Flood exposure is not an observed closure."
        ),
        "snapshot": {
            "scenario_id": network.scenario_id,
            "base_snapshot_id": network.base_snapshot_id,
            "flood_snapshot_id": network.flood_snapshot_id,
        },
        "assumption": {
            "flood_return_period_years": assumption.flood_return_period_years,
            "treat_flood_exposure_as_unavailable": (
                assumption.treat_flood_exposure_as_unavailable
            ),
            "roadworks_segment_ids": sorted(assumption.roadworks_segment_ids),
            "unavailable_segment_ids": sorted(unavailable),
            "effective_unavailable_private_car_segment_ids": sorted(effective_unavailable),
            "analytically_passable_segment_ids": sorted(repaired),
        },
        "summary": {
            "origins": len(origins),
            "retained": sum(record["status"] == "retained" for record in access_records),
            "stranded": stranded,
            "baseline_unreachable": baseline_unreachable_count,
            "source_unavailable_segments": len(unavailable),
            "effective_unavailable_private_car_segments": len(effective_unavailable),
            # Backward-compatible, but now explicitly uses the effective car-graph count.
            "unavailable_segments": len(effective_unavailable),
            "weak_components": len(weak_components),
        },
        "access": access_records,
        "components": {
            "sizes": [len(component) for component in weak_components],
            "relevant": [
                {
                    "id": component_id,
                    "node_count": len(weak_components[component_id]),
                    "physical_segment_ids": sorted(segments_by_component[component_id]),
                }
                for component_id in relevant_component_ids
            ],
            "origin_component_ids": {
                origin.id: node_to_component.get(origin.node_id)
                for origin in sorted(origins, key=lambda point: point.id)
            },
            "destination_component_ids": {
                destination.id: node_to_component.get(destination.node_id)
                for destination in sorted(destinations, key=lambda point: point.id)
            },
        },
        "destinations": [point.as_dict() for point in sorted(destinations, key=lambda p: p.id)],
    }


def solve_minimum_assumption_repair(
    network: FrozenResilienceNetwork,
    assumption: DisruptionAssumption,
    origins: Sequence[SnappedAccessPoint],
    destinations: Sequence[SnappedAccessPoint],
    request: AssumptionRepairRequest,
    *,
    cancel_event: threading.Event | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run a cut-refinement Z3 search and independently verify the final access graph."""

    started = time.monotonic()
    deadline = started + max(0.0, request.timeout_seconds)
    cancel_event = cancel_event or threading.Event()
    iterations: list[dict[str, Any]] = []
    control = _AnalysisControl(deadline=deadline, cancel_event=cancel_event)
    try:
        return _solve_minimum_assumption_repair(
            network,
            assumption,
            origins,
            destinations,
            request,
            started=started,
            deadline=deadline,
            cancel_event=cancel_event,
            iterations=iterations,
            on_event=on_event,
            control=control,
        )
    except _AnalysisInterrupted as interruption:
        message = (
            "The analysis was cancelled; no feasibility claim has been made."
            if interruption.status == "cancelled"
            else "The analysis reached its time limit. This is not an UNSAT result."
        )
        return _terminal_repair_result(
            interruption.status,
            message,
            started,
            iterations,
            diagnostics={"interrupted_phase": interruption.phase},
        )


def _solve_minimum_assumption_repair(
    network: FrozenResilienceNetwork,
    assumption: DisruptionAssumption,
    origins: Sequence[SnappedAccessPoint],
    destinations: Sequence[SnappedAccessPoint],
    request: AssumptionRepairRequest,
    *,
    started: float,
    deadline: float,
    cancel_event: threading.Event,
    iterations: list[dict[str, Any]],
    on_event: Callable[[dict[str, Any]], None] | None,
    control: _AnalysisControl,
) -> dict[str, Any]:
    constraints: list[frozenset[str]] = []
    if request.budget < 0:
        return _terminal_repair_result(
            "data_error",
            "The continuity-commitment budget cannot be negative.",
            started,
            iterations,
        )

    control.checkpoint("request_setup")
    unavailable = network.unavailable_segments(assumption)

    def record_event(event: dict[str, Any]) -> None:
        iterations.append(event)
        if on_event is not None:
            on_event(event)

    _validate_access_study(network, origins, destinations, control=control)

    eligible_segments = (
        frozenset(request.eligible_segment_ids)
        if request.eligible_segment_ids is not None
        else unavailable
    )
    unknown = eligible_segments - unavailable
    if unknown:
        return _terminal_repair_result(
            "data_error",
            "Eligible continuity commitments must cover unavailable segments in this scenario.",
            started,
            iterations,
            diagnostics={"unknown_or_available_segment_ids": sorted(unknown)},
        )
    car_segments = _private_car_segment_ids(
        network,
        control=control,
        phase="request_private_car_segments",
    )
    eligible_segments &= car_segments
    decision_groups, group_error = _prepare_decision_groups(
        request.decision_groups,
        eligible_segments,
        unavailable & car_segments,
        eligible_was_explicit=request.eligible_segment_ids is not None,
        control=control,
    )
    if group_error is not None:
        return _terminal_repair_result(
            "data_error",
            group_error[0],
            started,
            iterations,
            diagnostics=group_error[1],
        )
    decision_ids = frozenset(decision_groups)
    decision_costs = {
        decision_id: group.cost for decision_id, group in decision_groups.items()
    }
    segment_to_decision = {
        segment_id: decision_id
        for decision_id, group in decision_groups.items()
        for segment_id in group.segment_ids
    }

    baseline = analyze_disruption(
        network,
        DisruptionAssumption(),
        origins,
        destinations,
        _control=control,
    )
    baseline_failures = [
        record["origin"]["id"]
        for record in baseline["access"]
        if record["status"] == "baseline_unreachable"
    ]
    if baseline_failures:
        return _terminal_repair_result(
            "data_error",
            "At least one origin cannot reach an allowed destination in the baseline graph.",
            started,
            iterations,
            diagnostics={"baseline_unreachable_origin_ids": baseline_failures},
        )
    baseline_routes_by_origin = {
        str(record["origin"]["id"]): record["baseline_route"]
        for record in baseline["access"]
    }

    iteration_number = 0
    while True:
        control = _control_status(deadline, cancel_event)
        if control is not None:
            message = (
                "The analysis was cancelled; no feasibility claim has been made."
                if control == "cancelled"
                else "The analysis reached its time limit. This is not an UNSAT result."
            )
            return _terminal_repair_result(control, message, started, iterations)

        iteration_number += 1
        candidate_status, selected = _minimum_z3_candidate(
            decision_ids,
            decision_costs,
            constraints,
            request.budget,
            deadline,
            cancel_event,
        )
        if candidate_status in {"timeout", "cancelled"}:
            message = (
                "The analysis was cancelled; no feasibility claim has been made."
                if candidate_status == "cancelled"
                else "Z3 reached the analysis time limit. This is not an UNSAT result."
            )
            return _terminal_repair_result(candidate_status, message, started, iterations)
        if candidate_status == "unsat":
            return _terminal_repair_result(
                "verified_unsat",
                (
                    f"No assignment of at most {request.budget} eligible continuity-zone "
                    "Booleans satisfies every encoded access requirement."
                ),
                started,
                iterations,
                selected_decision_ids=[],
                selected_segment_ids=[],
                diagnostics={
                    "finding": "budget_insufficient_for_necessary_access_cuts",
                    "budget": request.budget,
                    "necessary_cut_constraints": len(constraints),
                },
                constraint_model=_constraint_model_payload(
                    decision_groups, constraints, request.budget
                ),
            )

        selected_decision_ids = frozenset(selected)
        selected_segment_ids = frozenset(
            segment_id
            for decision_id in selected_decision_ids
            for segment_id in decision_groups[decision_id].segment_ids
        )
        selected_group_cost = sum(
            decision_groups[decision_id].cost for decision_id in selected_decision_ids
        )
        candidate_analysis = analyze_disruption(
            network,
            assumption,
            origins,
            destinations,
            analytically_passable_segment_ids=selected_segment_ids,
            _control=control,
            _baseline_routes_by_origin=baseline_routes_by_origin,
        )
        candidate_event: dict[str, Any] = {
            "iteration": iteration_number,
            "type": "candidate",
            "selected_decision_ids": sorted(selected_decision_ids),
            "selected_segment_ids": sorted(selected_segment_ids),
            "selected_count": len(selected_decision_ids),
            "selected_group_cost": selected_group_cost,
            "selected_segment_count": len(selected_segment_ids),
            "constraint_count": len(constraints),
            "access_summary": candidate_analysis["summary"],
            "access": candidate_analysis["access"],
        }
        record_event(candidate_event)

        stranded_records = [
            record for record in candidate_analysis["access"] if record["status"] == "stranded"
        ]
        if not stranded_records:
            fresh = _fresh_access_verification(
                network,
                unavailable - selected_segment_ids,
                origins,
                destinations,
                control=control,
            )
            if not fresh["verified"]:
                return _terminal_repair_result(
                    "data_error",
                    "Fresh graph verification disagreed with the candidate analysis.",
                    started,
                    iterations,
                    selected_decision_ids=sorted(selected_decision_ids),
                    selected_segment_ids=sorted(selected_segment_ids),
                    diagnostics=fresh,
                )
            return _terminal_repair_result(
                "verified_optimal",
                (
                    "Every origin reaches an allowed destination under the explicit graph "
                    "assumptions. The selected decision groups are minimum continuity "
                    "commitments, not safety or operability findings."
                ),
                started,
                iterations,
                selected_decision_ids=sorted(selected_decision_ids),
                selected_segment_ids=sorted(selected_segment_ids),
                objective_values={
                    "analytical_repairs": len(selected_decision_ids),
                    "decision_group_count": len(selected_decision_ids),
                    "decision_group_cost": selected_group_cost,
                    "expanded_segment_count": len(selected_segment_ids),
                },
                verification=fresh,
                analysis=candidate_analysis,
                constraint_model=_constraint_model_payload(
                    decision_groups, constraints, request.budget
                ),
            )

        open_graph = _build_graph(
            network,
            unavailable - selected_segment_ids,
            control=control,
            phase="refinement_graph",
        )
        destination_by_id = {point.id: point for point in destinations}
        new_cut_count = 0
        for stranded_index, record in enumerate(stranded_records):
            _periodic_checkpoint(control, "refinement_origins", stranded_index)
            origin = next(point for point in origins if point.id == record["origin"]["id"])
            allowed_destination_ids = _allowed_destinations(origin, destination_by_id)
            reachable_nodes = _reachable_nodes(
                open_graph,
                origin.node_id,
                control=control,
                phase="refinement_reachability",
            )
            frontier_decision_ids, frontier_segment_ids = _decision_frontier(
                network,
                reachable_nodes,
                unavailable - selected_segment_ids,
                segment_to_decision,
                control=control,
            )
            diagnostic_route = _minimum_disruption_route(
                network,
                origin.node_id,
                allowed_destination_ids,
                unavailable - selected_segment_ids,
                control=control,
            )
            reachable_segment_id_set: set[str] = set()
            for edge_index, (source, target, data) in enumerate(
                open_graph.edges(data=True)
            ):
                _periodic_checkpoint(
                    control,
                    "refinement_reachable_segment_scan",
                    edge_index,
                )
                if source in reachable_nodes and target in reachable_nodes:
                    reachable_segment_id_set.add(str(data["physical_id"]))
            _checkpoint(control, "refinement_reachable_segment_scan")
            reachable_segment_ids = sorted(reachable_segment_id_set)
            if not frontier_decision_ids:
                unrepairable_diagnostics = {
                    "finding": "unrepairable_access_cut",
                    "origin_id": origin.id,
                    "origin_label": origin.label,
                    "reachable_node_count": len(reachable_nodes),
                    "reachable_segment_ids": reachable_segment_ids,
                    "diagnostic_route": diagnostic_route,
                }
                record_event(
                    {
                        "iteration": iteration_number,
                        "type": "unrepairable_cut",
                        **unrepairable_diagnostics,
                    }
                )
                return _terminal_repair_result(
                    "verified_unsat",
                    (
                        f"{origin.label} is separated by a directed cut with no eligible "
                        "continuity-zone decision."
                    ),
                    started,
                    iterations,
                    selected_decision_ids=sorted(selected_decision_ids),
                    selected_segment_ids=sorted(selected_segment_ids),
                    diagnostics=unrepairable_diagnostics,
                    constraint_model=_constraint_model_payload(
                        decision_groups, constraints, request.budget
                    ),
                )
            if frontier_decision_ids not in constraints:
                constraints.append(frontier_decision_ids)
                new_cut_count += 1
            record_event(
                {
                    "iteration": iteration_number,
                    "type": "access_cut_found",
                    "origin_id": origin.id,
                    "origin_label": origin.label,
                    "reachable_node_count": len(reachable_nodes),
                    "reachable_segment_ids": reachable_segment_ids,
                    "frontier_decision_ids": sorted(frontier_decision_ids),
                    "frontier_segment_ids": sorted(frontier_segment_ids),
                    "constraint": {
                        "kind": "at_least_one",
                        "variable_ids": [
                            f"passable[{decision_id}]"
                            for decision_id in sorted(frontier_decision_ids)
                        ],
                        "plain_language": (
                            "At least one decision group intersecting this directed access "
                            "frontier must be treated as passable."
                        ),
                    },
                    "diagnostic_route": diagnostic_route,
                }
            )
        if new_cut_count == 0:
            return _terminal_repair_result(
                "data_error",
                "Refinement did not add a new necessary access constraint.",
                started,
                iterations,
            )


def _build_graph(
    network: FrozenResilienceNetwork,
    unavailable_segment_ids: frozenset[str],
    *,
    control: _AnalysisControl | None = None,
    phase: str = "graph_construction",
) -> nx.MultiDiGraph:
    _checkpoint(control, phase)
    graph = nx.MultiDiGraph()
    car_node_ids = _private_car_node_ids(
        network,
        control=control,
        phase=f"{phase}_node_index",
    )
    for node_index, node in enumerate(
        sorted(network.nodes.values(), key=lambda item: item.id)
    ):
        _periodic_checkpoint(control, f"{phase}_nodes", node_index)
        if node.id in car_node_ids:
            graph.add_node(
                node.id,
                longitude=node.longitude,
                latitude=node.latitude,
            )
    for edge_index, edge in enumerate(network.edges):
        _periodic_checkpoint(control, f"{phase}_edges", edge_index)
        if not edge.private_car or edge.physical_id in unavailable_segment_ids:
            continue
        graph.add_edge(
            edge.source,
            edge.target,
            key=edge.id,
            id=edge.id,
            physical_id=edge.physical_id,
            length_m=edge.length_m,
        )
    _checkpoint(control, phase)
    return graph


def _best_route(
    network: FrozenResilienceNetwork,
    graph: nx.MultiDiGraph,
    source: str,
    destination_ids: Sequence[str],
    *,
    control: _AnalysisControl | None = None,
    phase: str = "route_search",
) -> dict[str, Any] | None:
    _checkpoint(control, phase)
    destination_nodes = frozenset(destination_ids)
    if source not in graph or not destination_nodes:
        return None
    weight_calls = 0

    def controlled_weight(
        _source: str,
        _target: str,
        parallel_edges: dict[str, dict[str, Any]],
    ) -> float:
        nonlocal weight_calls
        _periodic_checkpoint(control, phase, weight_calls)
        weight_calls += 1
        return min(float(data["length_m"]) for data in parallel_edges.values())

    distances, paths = nx.single_source_dijkstra(
        graph,
        source,
        weight=controlled_weight,
    )
    _checkpoint(control, phase)
    reachable_destinations = [node for node in destination_nodes if node in distances]
    if not reachable_destinations:
        return None
    target = min(reachable_destinations, key=lambda node: (distances[node], node))
    nodes = paths[target]
    edge_lookup: dict[tuple[str, str], list[NetworkEdge]] = {}
    for edge_index, edge in enumerate(network.edges):
        _periodic_checkpoint(control, f"{phase}_route_geometry", edge_index)
        if graph.has_edge(edge.source, edge.target, edge.id):
            edge_lookup.setdefault((edge.source, edge.target), []).append(edge)
    route_edges: list[NetworkEdge] = []
    for left, right in zip(nodes, nodes[1:], strict=False):
        route_edges.append(
            min(edge_lookup[(left, right)], key=lambda edge: (edge.length_m, edge.id))
        )
    _checkpoint(control, f"{phase}_route_geometry")
    return _route_payload(route_edges, target, float(distances[target]))


def _route_payload(
    route_edges: Sequence[NetworkEdge], destination_node_id: str, length_m: float
) -> dict[str, Any]:
    return {
        "destination_node_id": destination_node_id,
        "length_m": round(length_m, 2),
        "directed_edge_ids": [edge.id for edge in route_edges],
        "physical_segment_ids": list(dict.fromkeys(edge.physical_id for edge in route_edges)),
        "feature": {
            "type": "Feature",
            "properties": {
                "kind": "access_route",
                "length_m": round(length_m, 2),
            },
            "geometry": {
                "type": "MultiLineString",
                "coordinates": [
                    [[longitude, latitude] for longitude, latitude in edge.geometry]
                    for edge in route_edges
                    if len(edge.geometry) >= 2
                ],
            },
        },
    }


def _validate_access_study(
    network: FrozenResilienceNetwork,
    origins: Sequence[SnappedAccessPoint],
    destinations: Sequence[SnappedAccessPoint],
    *,
    control: _AnalysisControl | None = None,
) -> None:
    _checkpoint(control, "access_study_validation")
    if not origins:
        raise ValueError("At least one origin is required")
    if not destinations:
        raise ValueError("At least one destination is required")
    destination_ids = {point.id for point in destinations}
    if len(destination_ids) != len(destinations):
        raise ValueError("Destination IDs must be unique")
    if len({point.id for point in origins}) != len(origins):
        raise ValueError("Origin IDs must be unique")
    private_car_node_ids = _private_car_node_ids(
        network,
        control=control,
        phase="access_study_node_index",
    )
    for point_index, point in enumerate([*origins, *destinations]):
        _periodic_checkpoint(control, "access_study_points", point_index)
        if point.node_id not in private_car_node_ids:
            raise ValueError(f"Access point {point.id} is not snapped to a private-car node")
    for origin_index, origin in enumerate(origins):
        _periodic_checkpoint(control, "access_study_origins", origin_index)
        unknown = set(origin.allowed_destination_ids) - destination_ids
        if unknown:
            raise ValueError(f"Origin {origin.id} allows unknown destinations: {sorted(unknown)}")


def _allowed_destinations(
    origin: SnappedAccessPoint,
    destination_by_id: dict[str, SnappedAccessPoint],
) -> tuple[str, ...]:
    return tuple(
        destination_by_id[point_id].node_id
        for point_id in _allowed_destination_ids(origin, destination_by_id)
    )


def _allowed_destination_ids(
    origin: SnappedAccessPoint,
    destination_by_id: dict[str, SnappedAccessPoint],
) -> tuple[str, ...]:
    return origin.allowed_destination_ids or tuple(sorted(destination_by_id))


def _reachable_nodes(
    graph: nx.DiGraph | nx.MultiDiGraph,
    source: str,
    *,
    control: _AnalysisControl | None = None,
    phase: str = "reachability",
) -> frozenset[str]:
    _checkpoint(control, phase)
    if source not in graph:
        return frozenset()
    reachable = {source}
    pending = deque([source])
    visited_count = 0
    while pending:
        _periodic_checkpoint(control, phase, visited_count)
        visited_count += 1
        node = pending.popleft()
        for target in graph.successors(node):
            if target not in reachable:
                reachable.add(target)
                pending.append(target)
    _checkpoint(control, phase)
    return frozenset(reachable)


def _weakly_connected_components(
    graph: nx.MultiDiGraph,
    *,
    control: _AnalysisControl | None = None,
    phase: str = "weak_components",
) -> list[frozenset[str]]:
    """Return weak components while keeping long traversals interruptible."""

    _checkpoint(control, phase)
    seen: set[str] = set()
    components: list[frozenset[str]] = []
    visited_count = 0
    for start in graph.nodes:
        if start in seen:
            continue
        seen.add(start)
        component = {start}
        pending = deque([start])
        while pending:
            _periodic_checkpoint(control, phase, visited_count)
            visited_count += 1
            node = pending.popleft()
            for neighbor in (*graph.successors(node), *graph.predecessors(node)):
                if neighbor not in seen:
                    seen.add(neighbor)
                    component.add(neighbor)
                    pending.append(neighbor)
        components.append(frozenset(component))
    _checkpoint(control, phase)
    return components


def _private_car_node_ids(
    network: FrozenResilienceNetwork,
    *,
    control: _AnalysisControl | None = None,
    phase: str = "private_car_node_index",
) -> frozenset[str]:
    node_ids: set[str] = set()
    for edge_index, edge in enumerate(network.edges):
        _periodic_checkpoint(control, phase, edge_index)
        if edge.private_car:
            node_ids.update((edge.source, edge.target))
    _checkpoint(control, phase)
    return frozenset(node_ids)


def _private_car_segment_ids(
    network: FrozenResilienceNetwork,
    *,
    control: _AnalysisControl | None = None,
    phase: str = "private_car_segment_index",
) -> frozenset[str]:
    segment_ids: set[str] = set()
    for edge_index, edge in enumerate(network.edges):
        _periodic_checkpoint(control, phase, edge_index)
        if edge.private_car:
            segment_ids.add(edge.physical_id)
    _checkpoint(control, phase)
    return frozenset(segment_ids)


def _prepare_decision_groups(
    requested_groups: tuple[DecisionGroup, ...] | None,
    eligible_segments: frozenset[str],
    unavailable_car_segments: frozenset[str],
    *,
    eligible_was_explicit: bool,
    control: _AnalysisControl | None = None,
) -> tuple[dict[str, DecisionGroup], tuple[str, dict[str, Any]] | None]:
    _checkpoint(control, "decision_group_preparation")
    if requested_groups is None:
        return (
            {
                segment_id: DecisionGroup(segment_id, segment_id, (segment_id,))
                for segment_id in sorted(eligible_segments)
            },
            None,
        )

    parsed: dict[str, DecisionGroup] = {}
    assigned_segments: set[str] = set()
    for group_index, group in enumerate(requested_groups):
        _periodic_checkpoint(control, "decision_group_preparation", group_index)
        if not group.id.strip():
            return {}, (
                "Every decision group needs a nonempty ID.",
                {"finding": "empty_decision_group_id"},
            )
        if group.id in parsed:
            return {}, (
                f"Decision group ID {group.id!r} is duplicated.",
                {"finding": "duplicate_decision_group_id", "decision_group_id": group.id},
            )
        if not group.segment_ids:
            return {}, (
                f"Decision group {group.id!r} has no physical segments.",
                {"finding": "empty_decision_group", "decision_group_id": group.id},
            )
        if isinstance(group.cost, bool) or not isinstance(group.cost, int) or group.cost < 1:
            return {}, (
                f"Decision group {group.id!r} needs a positive integer aggregation cost.",
                {
                    "finding": "invalid_decision_group_cost",
                    "decision_group_id": group.id,
                    "cost": group.cost,
                },
            )
        members = frozenset(group.segment_ids)
        if len(members) != len(group.segment_ids):
            return {}, (
                f"Decision group {group.id!r} repeats a physical segment.",
                {"finding": "duplicate_segment_within_group", "decision_group_id": group.id},
            )
        invalid = members - unavailable_car_segments
        if invalid:
            return {}, (
                (
                    f"Decision group {group.id!r} includes segments that are not unavailable "
                    "private-car links."
                ),
                {
                    "finding": "invalid_decision_group_segments",
                    "decision_group_id": group.id,
                    "segment_ids": sorted(invalid),
                },
            )
        if eligible_was_explicit:
            outside_eligible = members - eligible_segments
            if outside_eligible:
                return {}, (
                    f"Decision group {group.id!r} includes segments outside the eligible set.",
                    {
                        "finding": "decision_group_outside_eligible_set",
                        "decision_group_id": group.id,
                        "segment_ids": sorted(outside_eligible),
                    },
                )
        overlap = members & assigned_segments
        if overlap:
            return {}, (
                "Decision groups must be disjoint so each physical link has one decision owner.",
                {
                    "finding": "overlapping_decision_groups",
                    "decision_group_id": group.id,
                    "segment_ids": sorted(overlap),
                },
            )
        assigned_segments.update(members)
        parsed[group.id] = DecisionGroup(
            id=group.id,
            label=group.label or group.id,
            segment_ids=tuple(sorted(members)),
            cost=group.cost,
        )
    return dict(sorted(parsed.items())), None


def _decision_frontier(
    network: FrozenResilienceNetwork,
    reachable_nodes: frozenset[str],
    currently_unavailable: frozenset[str],
    segment_to_decision: dict[str, str],
    *,
    control: _AnalysisControl | None = None,
) -> tuple[frozenset[str], frozenset[str]]:
    segment_id_set: set[str] = set()
    for edge_index, edge in enumerate(network.edges):
        _periodic_checkpoint(control, "refinement_frontier", edge_index)
        if (
            edge.private_car
            and edge.source in reachable_nodes
            and edge.target not in reachable_nodes
            and edge.physical_id in currently_unavailable
            and edge.physical_id in segment_to_decision
        ):
            segment_id_set.add(edge.physical_id)
    _checkpoint(control, "refinement_frontier")
    segment_ids = frozenset(segment_id_set)
    return (
        frozenset(segment_to_decision[segment_id] for segment_id in segment_ids),
        segment_ids,
    )


def _minimum_disruption_route(
    network: FrozenResilienceNetwork,
    source: str,
    allowed_destination_nodes: Sequence[str],
    unavailable: frozenset[str],
    *,
    control: _AnalysisControl | None = None,
) -> dict[str, Any] | None:
    phase = "diagnostic_route_search"
    _checkpoint(control, phase)
    graph = nx.MultiDiGraph()
    private_car_edges: list[NetworkEdge] = []
    max_network_length = 1.0
    for edge_index, edge in enumerate(network.edges):
        _periodic_checkpoint(control, f"{phase}_edge_index", edge_index)
        if edge.private_car:
            private_car_edges.append(edge)
            max_network_length += edge.length_m
    edge_by_id: dict[str, NetworkEdge] = {}
    for edge_index, edge in enumerate(private_car_edges):
        _periodic_checkpoint(control, f"{phase}_graph", edge_index)
        edge_by_id[edge.id] = edge
        graph.add_edge(
            edge.source,
            edge.target,
            key=edge.id,
            diagnostic_cost=(
                max_network_length if edge.physical_id in unavailable else 0.0
            )
            + edge.length_m,
        )
    if source not in graph:
        return None
    weight_calls = 0

    def controlled_weight(
        _source: str,
        _target: str,
        parallel_edges: dict[str, dict[str, Any]],
    ) -> float:
        nonlocal weight_calls
        _periodic_checkpoint(control, phase, weight_calls)
        weight_calls += 1
        return min(float(data["diagnostic_cost"]) for data in parallel_edges.values())

    distances, paths = nx.single_source_dijkstra(
        graph,
        source,
        weight=controlled_weight,
    )
    _checkpoint(control, phase)
    reachable = [node for node in allowed_destination_nodes if node in distances]
    if not reachable:
        return None
    target = min(reachable, key=lambda node: (distances[node], node))
    node_path = paths[target]
    route_edges: list[NetworkEdge] = []
    for route_index, (left, right) in enumerate(
        zip(node_path, node_path[1:], strict=False)
    ):
        _periodic_checkpoint(control, f"{phase}_payload", route_index)
        candidate_ids = sorted(graph[left][right])
        edge_id = min(
            candidate_ids,
            key=lambda candidate: (
                graph[left][right][candidate]["diagnostic_cost"], candidate
            ),
        )
        route_edges.append(edge_by_id[edge_id])
    payload = _route_payload(
        route_edges,
        target,
        sum(edge.length_m for edge in route_edges),
    )
    payload["unavailable_segment_ids"] = list(
        dict.fromkeys(edge.physical_id for edge in route_edges if edge.physical_id in unavailable)
    )
    payload["purpose"] = (
        "Diagnostic least-disrupted baseline route; it is visual evidence, not the cut constraint."
    )
    _checkpoint(control, f"{phase}_payload")
    return payload


def _minimum_z3_candidate(
    decision_ids: frozenset[str],
    decision_costs: dict[str, int],
    constraints: Sequence[frozenset[str]],
    budget: int,
    deadline: float,
    cancel_event: threading.Event,
) -> tuple[str, tuple[str, ...]]:
    active_ids = tuple(sorted(set().union(*constraints) if constraints else set()))
    if not active_ids:
        return "sat", ()
    variables = {
        decision_id: z3.Bool(f"passable_group__{decision_id}")
        for decision_id in active_ids
    }
    cost_expression = z3.Sum(
        [z3.If(variables[item], decision_costs[item], 0) for item in active_ids]
    )

    def make_solver(cardinality: int) -> z3.Solver:
        solver = z3.Solver()
        solver.add(z3.Sum([z3.If(variables[item], 1, 0) for item in active_ids]) == cardinality)
        for constraint in constraints:
            clause_ids = sorted(constraint & decision_ids)
            solver.add(z3.Or([variables[item] for item in clause_ids]))
        return solver

    for cardinality in range(0, min(budget, len(active_ids)) + 1):
        if cancel_event.is_set():
            return "cancelled", ()
        remaining_ms = math.floor((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            return "timeout", ()
        solver = make_solver(cardinality)
        solver.set("timeout", max(1, remaining_ms))
        check = solver.check()
        if check == z3.unknown:
            return "timeout", ()
        if check != z3.sat:
            continue

        # Cardinality is primary. Within that cardinality, find the exact minimum explicit
        # aggregation cost before using stable IDs to select one reproducible tied model.
        minimum_cost = 0
        maximum_cost = int(solver.model().eval(cost_expression).as_long())
        while minimum_cost < maximum_cost:
            if cancel_event.is_set():
                return "cancelled", ()
            remaining_ms = math.floor((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                return "timeout", ()
            midpoint = (minimum_cost + maximum_cost) // 2
            solver.push()
            solver.add(cost_expression <= midpoint)
            solver.set("timeout", max(1, remaining_ms))
            lower_cost_check = solver.check()
            solver.pop()
            if lower_cost_check == z3.unknown:
                return "timeout", ()
            if lower_cost_check == z3.sat:
                maximum_cost = midpoint
            else:
                minimum_cost = midpoint + 1
        solver.add(cost_expression == minimum_cost)

        # Prefer lower stable IDs when cardinality and cost tie. Only variables present in
        # discovered cuts are active, avoiding a scan of every flood-exposed segment.
        for decision_id in active_ids:
            if cancel_event.is_set():
                return "cancelled", ()
            remaining_ms = math.floor((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                return "timeout", ()
            solver.push()
            solver.add(variables[decision_id])
            solver.set("timeout", max(1, remaining_ms))
            can_be_true = solver.check()
            solver.pop()
            if can_be_true == z3.unknown:
                return "timeout", ()
            solver.add(
                variables[decision_id]
                if can_be_true == z3.sat
                else z3.Not(variables[decision_id])
            )
        if cancel_event.is_set():
            return "cancelled", ()
        remaining_ms = math.floor((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            return "timeout", ()
        solver.set("timeout", max(1, remaining_ms))
        final_check = solver.check()
        if final_check != z3.sat:
            return "timeout" if final_check == z3.unknown else "unsat", ()
        model = solver.model()
        selected = tuple(
            decision_id
            for decision_id in active_ids
            if z3.is_true(model.evaluate(variables[decision_id], model_completion=True))
        )
        return "sat", selected
    if cancel_event.is_set():
        return "cancelled", ()
    if time.monotonic() >= deadline:
        return "timeout", ()
    return "unsat", ()


def _fresh_access_verification(
    network: FrozenResilienceNetwork,
    unavailable: frozenset[str],
    origins: Sequence[SnappedAccessPoint],
    destinations: Sequence[SnappedAccessPoint],
    *,
    control: _AnalysisControl | None = None,
) -> dict[str, Any]:
    """Rebuild a new graph and verify reachability without route-payload helpers."""

    phase = "final_verification"
    _checkpoint(control, phase)
    graph = nx.DiGraph()
    graph.add_nodes_from(
        _private_car_node_ids(
            network,
            control=control,
            phase=f"{phase}_node_index",
        )
    )
    for edge_index, edge in enumerate(network.edges):
        _periodic_checkpoint(control, f"{phase}_graph", edge_index)
        if edge.private_car and edge.physical_id not in unavailable:
            graph.add_edge(edge.source, edge.target)
    destinations_by_id = {point.id: point for point in destinations}
    origin_checks: dict[str, bool] = {}
    for origin_index, origin in enumerate(sorted(origins, key=lambda point: point.id)):
        _periodic_checkpoint(control, f"{phase}_origins", origin_index)
        allowed_ids = origin.allowed_destination_ids or tuple(sorted(destinations_by_id))
        reachable = _reachable_nodes(
            graph,
            origin.node_id,
            control=control,
            phase=f"{phase}_reachability",
        )
        origin_checks[origin.id] = any(
            destinations_by_id[item].node_id in reachable for item in allowed_ids
        )
    effective_unavailable = unavailable & _private_car_segment_ids(
        network,
        control=control,
        phase=f"{phase}_segment_index",
    )
    return {
        "verified": all(origin_checks.values()),
        "method": "fresh_networkx_directed_graph",
        "origin_access": origin_checks,
        "source_unavailable_segment_count": len(unavailable),
        "effective_unavailable_private_car_segment_count": len(effective_unavailable),
        "unavailable_segment_count": len(effective_unavailable),
    }


def _constraint_model_payload(
    decision_groups: dict[str, DecisionGroup],
    constraints: Sequence[frozenset[str]],
    budget: int,
) -> dict[str, Any]:
    return {
        "decision_variable_template": "passable[decision_group_id] : Boolean",
        "decision_semantics": (
            "True means this analysis treats every frozen physical segment in that corridor "
            "or zone group as passable. It is not a field observation or engineering approval."
        ),
        "decision_groups": [
            {
                "id": group.id,
                "label": group.label,
                "segment_ids": list(group.segment_ids),
                "segment_count": len(group.segment_ids),
                "cost": group.cost,
            }
            for group in decision_groups.values()
        ],
        "hard_constraints": [
            {
                "kind": "budget",
                "expression": f"sum(passable[c]) <= {budget}",
                "plain_language": f"Use at most {budget} analytical continuity commitments.",
            },
            *[
                {
                    "kind": "directed_access_cut",
                    "expression": " or ".join(
                        f"passable[{decision_id}]" for decision_id in sorted(constraint)
                    ),
                    "plain_language": (
                        "At least one corridor or zone group intersecting this verified access "
                        "frontier must be treated as passable."
                    ),
                }
                for constraint in constraints
            ],
        ],
        "objective": (
            "Lexicographically minimize selected decision-group count, then total explicit "
            "integer group cost; break remaining ties by stable group ID."
        ),
        "cost_semantics": (
            "Group cost is an explicit analytical aggregation metric supplied with the group. "
            "It is not a monetary, engineering, safety, or construction-cost estimate."
        ),
        "eligible_variable_count": len(decision_groups),
        "refinement": (
            "Z3 proposes a minimum set for the cuts known so far. NetworkX checks the complete "
            "directed graph. A stranded origin yields another necessary cut constraint."
        ),
        "final_verification": "A newly constructed directed NetworkX graph repeats every check.",
    }


def _terminal_repair_result(
    status: RepairStatus,
    message: str,
    started: float,
    iterations: Sequence[dict[str, Any]],
    **fields: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "message": message,
        "verified": status in {"verified_optimal", "verified_unsat"},
        "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
        "iteration_count": max(
            (int(event.get("iteration", 0)) for event in iterations), default=0
        ),
        "iterations": list(iterations),
        "methodology_notice": (
            "This is an explicit graph-assumption experiment. It does not infer road closure "
            "from flood exposure, certify a route as safe, or predict disruption impacts."
        ),
    }
    result.update(fields)
    return result


def _checkpoint(control: _AnalysisControl | None, phase: str) -> None:
    if control is not None:
        control.checkpoint(phase)


def _periodic_checkpoint(
    control: _AnalysisControl | None,
    phase: str,
    index: int,
    *,
    interval: int = 128,
) -> None:
    if control is not None and index % interval == 0:
        control.checkpoint(phase)


def _control_status(deadline: float, cancel_event: threading.Event) -> str | None:
    if cancel_event.is_set():
        return "cancelled"
    if time.monotonic() >= deadline:
        return "timeout"
    return None


def _physical_id_from_edge_id(edge_id: str) -> str:
    if edge_id.endswith("-f") or edge_id.endswith("-r"):
        return edge_id[:-2]
    return edge_id


def _distance_m(lon_a: float, lat_a: float, lon_b: float, lat_b: float) -> float:
    mean_latitude = math.radians((lat_a + lat_b) / 2)
    x = math.radians(lon_b - lon_a) * math.cos(mean_latitude)
    y = math.radians(lat_b - lat_a)
    return math.hypot(x, y) * 6_371_008.8
