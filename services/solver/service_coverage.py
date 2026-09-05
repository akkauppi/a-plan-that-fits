from __future__ import annotations

import copy
import json
import math
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import combinations
from pathlib import Path
from typing import Any, Literal

import networkx as nx
import z3

CoverageStatus = Literal[
    "verified_optimal",
    "verified_unsat",
    "timeout",
    "cancelled",
    "data_error",
]

_OBJECTIVE_KEYS = (
    "open_sites",
    "worst_distance_cm",
    "population_weighted_total_cm_people",
    "load_imbalance_people",
)


class _CoverageInterrupted(RuntimeError):
    def __init__(self, status: Literal["timeout", "cancelled"], phase: str) -> None:
        super().__init__(status)
        self.status = status
        self.phase = phase


@dataclass(frozen=True)
class _CoverageControl:
    deadline: float
    cancel_event: threading.Event

    def checkpoint(self, phase: str) -> None:
        if self.cancel_event.is_set():
            raise _CoverageInterrupted("cancelled", phase)
        if time.monotonic() >= self.deadline:
            raise _CoverageInterrupted("timeout", phase)


@dataclass(frozen=True)
class DemandCell:
    """One included population cell or other indivisible demand unit."""

    id: str
    label: str
    population: int
    longitude: float
    latitude: float
    district_id: str | None = None
    node_id: str | None = None
    snap_distance_m: float | None = None


@dataclass(frozen=True)
class CandidateSite:
    """One reviewed service site with an explicitly analyst-declared capacity."""

    id: str
    label: str
    capacity: int
    longitude: float
    latitude: float
    district_id: str | None = None
    node_id: str | None = None
    eligible: bool = True
    snap_distance_m: float | None = None


@dataclass(frozen=True)
class DistanceRecord:
    """Frozen shortest-path evidence for one demand-to-site relation."""

    demand_id: str
    site_id: str
    distance_m: float
    route: dict[str, Any] | None = None
    demand_connector_m: float | None = None
    network_distance_m: float | None = None
    site_connector_m: float | None = None
    route_node_ids: tuple[str, ...] = ()
    route_edge_ids: tuple[str, ...] = ()
    connector_method: str | None = None

    @property
    def distance_cm(self) -> int:
        return int(round(self.distance_m * 100))


@dataclass(frozen=True)
class WalkingEdge:
    """Optional frozen walking-graph edge used for a second distance check."""

    id: str
    source: str
    target: str
    length_m: float
    geometry: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class WalkingNode:
    """A frozen graph node with the display coordinate used by route evidence."""

    id: str
    longitude: float
    latitude: float


@dataclass(frozen=True)
class FrozenServiceCoverageScenario:
    """Frozen inputs for a capacitated service-allocation experiment.

    The distance matrix is the solver input. An optional walking graph lets the
    independent verifier recompute selected shortest paths instead of trusting the
    matrix alone. Coordinates and route GeoJSON are display evidence; the solver
    never derives distances from straight-line geometry.
    """

    scenario_id: str
    snapshot_id: str
    demand: tuple[DemandCell, ...]
    sites: tuple[CandidateSite, ...]
    distances: tuple[DistanceRecord, ...]
    distance_metric: str = "walking_network_m"
    analysis_crs: str | None = None
    display_crs: str = "EPSG:4326"
    network_snapshot_id: str | None = None
    network_nodes: tuple[WalkingNode, ...] = ()
    network_edges: tuple[WalkingEdge, ...] = ()
    network_directed: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_records(
        cls,
        *,
        scenario_id: str,
        demand: Sequence[DemandCell],
        sites: Sequence[CandidateSite],
        distances: Sequence[DistanceRecord],
        snapshot_id: str = "test-service-coverage",
        distance_metric: str = "walking_network_m",
        analysis_crs: str | None = None,
        display_crs: str = "EPSG:4326",
        network_snapshot_id: str | None = None,
        network_nodes: Sequence[WalkingNode | str] = (),
        network_edges: Sequence[WalkingEdge] = (),
        network_directed: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> FrozenServiceCoverageScenario:
        scenario = cls(
            scenario_id=scenario_id,
            snapshot_id=snapshot_id,
            demand=tuple(sorted(demand, key=lambda item: item.id)),
            sites=tuple(sorted(sites, key=lambda item: item.id)),
            distances=tuple(
                DistanceRecord(
                    demand_id=item.demand_id,
                    site_id=item.site_id,
                    distance_m=item.distance_m,
                    route=copy.deepcopy(item.route),
                    demand_connector_m=item.demand_connector_m,
                    network_distance_m=item.network_distance_m,
                    site_connector_m=item.site_connector_m,
                    route_node_ids=tuple(item.route_node_ids),
                    route_edge_ids=tuple(item.route_edge_ids),
                    connector_method=item.connector_method,
                )
                for item in sorted(
                    distances, key=lambda item: (item.demand_id, item.site_id)
                )
            ),
            distance_metric=distance_metric,
            analysis_crs=analysis_crs,
            display_crs=display_crs,
            network_snapshot_id=network_snapshot_id,
            network_nodes=tuple(
                sorted(
                    (
                        item
                        if isinstance(item, WalkingNode)
                        else WalkingNode(str(item), math.nan, math.nan)
                        for item in network_nodes
                    ),
                    key=lambda item: item.id,
                )
            ),
            network_edges=tuple(
                WalkingEdge(
                    id=item.id,
                    source=item.source,
                    target=item.target,
                    length_m=item.length_m,
                    geometry=tuple(tuple(point) for point in item.geometry),
                )
                for item in sorted(network_edges, key=lambda item: item.id)
            ),
            network_directed=network_directed,
            metadata=copy.deepcopy(dict(metadata or {})),
        )
        scenario.validate()
        return scenario

    @classmethod
    def from_artifact(
        cls, source: str | Path | Mapping[str, Any]
    ) -> FrozenServiceCoverageScenario:
        """Load the deterministic browser/preprocessor JSON contract.

        Points are ``[longitude, latitude]``. A GeoJSON Point is accepted as a
        convenience, but projected coordinates must not be put in these display
        fields. Optional route objects are preserved verbatim for map rendering.
        """

        payload = (
            json.loads(Path(source).read_text(encoding="utf-8"))
            if isinstance(source, (str, Path))
            else copy.deepcopy(dict(source))
        )

        def point(item: Mapping[str, Any]) -> tuple[float, float]:
            coordinates = item.get("point")
            if coordinates is None:
                geometry = item.get("geometry") or {}
                if geometry.get("type") == "Point":
                    coordinates = geometry.get("coordinates")
            if not isinstance(coordinates, Sequence) or len(coordinates) < 2:
                raise ValueError(f"{item.get('id', 'Record')} has no display point")
            return float(coordinates[0]), float(coordinates[1])

        parsed_demand: list[DemandCell] = []
        for item in payload.get("demand", []):
            longitude, latitude = point(item)
            parsed_demand.append(
                DemandCell(
                    id=str(item["id"]),
                    label=str(item.get("label") or item["id"]),
                    population=int(item["population"]),
                    longitude=longitude,
                    latitude=latitude,
                    district_id=(
                        str(item["district_id"])
                        if item.get("district_id") is not None
                        else None
                    ),
                    node_id=(
                        str(item["node_id"]) if item.get("node_id") is not None else None
                    ),
                    snap_distance_m=(
                        float(item["snap_distance_m"])
                        if item.get("snap_distance_m") is not None
                        else None
                    ),
                )
            )

        parsed_sites: list[CandidateSite] = []
        for item in payload.get("sites", []):
            longitude, latitude = point(item)
            parsed_sites.append(
                CandidateSite(
                    id=str(item["id"]),
                    label=str(item.get("label") or item["id"]),
                    capacity=int(item["capacity"]),
                    longitude=longitude,
                    latitude=latitude,
                    district_id=(
                        str(item["district_id"])
                        if item.get("district_id") is not None
                        else None
                    ),
                    node_id=(
                        str(item["node_id"]) if item.get("node_id") is not None else None
                    ),
                    eligible=bool(item.get("eligible", True)),
                    snap_distance_m=(
                        float(item["snap_distance_m"])
                        if item.get("snap_distance_m") is not None
                        else None
                    ),
                )
            )

        parsed_distances = [
            DistanceRecord(
                demand_id=str(item["demand_id"]),
                site_id=str(item["site_id"]),
                distance_m=float(item["distance_m"]),
                route=copy.deepcopy(item.get("route")),
                demand_connector_m=(
                    float(item["demand_connector_m"])
                    if item.get("demand_connector_m") is not None
                    else None
                ),
                network_distance_m=(
                    float(item["network_distance_m"])
                    if item.get("network_distance_m") is not None
                    else None
                ),
                site_connector_m=(
                    float(item["site_connector_m"])
                    if item.get("site_connector_m") is not None
                    else None
                ),
                route_node_ids=tuple(str(value) for value in item.get("route_node_ids", [])),
                route_edge_ids=tuple(str(value) for value in item.get("route_edge_ids", [])),
                connector_method=(
                    str(item["connector_method"])
                    if item.get("connector_method") is not None
                    else None
                ),
            )
            for item in payload.get("distances", [])
        ]

        network = payload.get("network") or {}
        network_nodes: list[WalkingNode | str] = []
        for item in network.get("nodes", []):
            if not isinstance(item, Mapping):
                network_nodes.append(str(item))
                continue
            longitude, latitude = point(item)
            network_nodes.append(
                WalkingNode(
                    id=str(item["id"]),
                    longitude=longitude,
                    latitude=latitude,
                )
            )
        parsed_edges = [
            WalkingEdge(
                id=str(item["id"]),
                source=str(item.get("from", item.get("source"))),
                target=str(item.get("to", item.get("target"))),
                length_m=float(item["length_m"]),
                geometry=_parse_line_coordinates(
                    item.get("geometry"), f"Walking edge {item.get('id', '')}"
                ),
            )
            for item in network.get("edges", [])
        ]
        crs = payload.get("crs")
        analysis_crs = crs.get("analysis") if isinstance(crs, Mapping) else crs
        display_crs = (
            str(crs.get("display", "EPSG:4326"))
            if isinstance(crs, Mapping)
            else "EPSG:4326"
        )
        return cls.from_records(
            scenario_id=str(payload["scenario_id"]),
            snapshot_id=str(payload["snapshot_id"]),
            demand=parsed_demand,
            sites=parsed_sites,
            distances=parsed_distances,
            distance_metric=str(payload.get("distance_metric", "walking_network_m")),
            analysis_crs=str(analysis_crs) if analysis_crs is not None else None,
            display_crs=display_crs,
            network_snapshot_id=(
                str(payload["network_snapshot_id"])
                if payload.get("network_snapshot_id") is not None
                else None
            ),
            network_nodes=network_nodes,
            network_edges=parsed_edges,
            network_directed=bool(network.get("directed", True)),
            metadata=payload.get("metadata") or {},
        )

    def validate(self) -> None:
        if not self.scenario_id or not self.snapshot_id:
            raise ValueError("Service-coverage scenario and snapshot IDs are required")
        if self.distance_metric != "walking_network_m":
            raise ValueError(
                "Version 1 supports only frozen walking routes with explicit snap connectors"
            )
        if not self.demand:
            raise ValueError("Service-coverage scenario has no demand cells")
        if not self.sites:
            raise ValueError("Service-coverage scenario has no candidate sites")
        demand_ids = [item.id for item in self.demand]
        site_ids = [item.id for item in self.sites]
        if len(set(demand_ids)) != len(demand_ids):
            raise ValueError("Duplicate demand-cell ID")
        if len(set(site_ids)) != len(site_ids):
            raise ValueError("Duplicate candidate-site ID")
        for item in self.demand:
            if item.population <= 0:
                raise ValueError(f"Demand {item.id} must have a positive population")
            _validate_coordinate(item.id, item.longitude, item.latitude)
            _validate_optional_distance(item.id, "snap_distance_m", item.snap_distance_m)
        for item in self.sites:
            if item.capacity <= 0:
                raise ValueError(f"Site {item.id} must have a positive declared capacity")
            _validate_coordinate(item.id, item.longitude, item.latitude)
            _validate_optional_distance(item.id, "snap_distance_m", item.snap_distance_m)
        known_demand = frozenset(demand_ids)
        known_sites = frozenset(site_ids)
        seen_pairs: set[tuple[str, str]] = set()
        for record in self.distances:
            pair = (record.demand_id, record.site_id)
            if pair in seen_pairs:
                raise ValueError(f"Duplicate distance-matrix pair: {pair}")
            seen_pairs.add(pair)
            if record.demand_id not in known_demand or record.site_id not in known_sites:
                raise ValueError(f"Distance-matrix pair references an unknown ID: {pair}")
            if not math.isfinite(record.distance_m) or record.distance_m < 0:
                raise ValueError(f"Distance for {pair} must be finite and non-negative")
            for field_name, value in (
                ("demand_connector_m", record.demand_connector_m),
                ("network_distance_m", record.network_distance_m),
                ("site_connector_m", record.site_connector_m),
            ):
                _validate_optional_distance(str(pair), field_name, value)
            if record.route is not None and (
                not isinstance(record.route, Mapping)
                or record.route.get("type") != "Feature"
            ):
                raise ValueError(f"Route for {pair} must be a GeoJSON Feature")
        if not self.distances:
            raise ValueError("Service-coverage scenario has no walking-distance evidence")
        if self.network_edges:
            if not self.network_nodes:
                raise ValueError("A verification graph with edges must list its nodes")
            node_ids = [node.id for node in self.network_nodes]
            if len(set(node_ids)) != len(node_ids):
                raise ValueError("Duplicate walking-node ID")
            node_by_id = {node.id: node for node in self.network_nodes}
            for node in self.network_nodes:
                _validate_coordinate(node.id, node.longitude, node.latitude)
            edge_ids: set[str] = set()
            for edge in self.network_edges:
                if edge.id in edge_ids:
                    raise ValueError(f"Duplicate walking-edge ID: {edge.id}")
                edge_ids.add(edge.id)
                if edge.source not in node_by_id or edge.target not in node_by_id:
                    raise ValueError(f"Walking edge {edge.id} references a missing node")
                if not math.isfinite(edge.length_m) or edge.length_m < 0:
                    raise ValueError(f"Walking edge {edge.id} has an invalid length")
                if len(edge.geometry) < 2:
                    raise ValueError(f"Walking edge {edge.id} has no auditable geometry")
                for longitude, latitude in edge.geometry:
                    _validate_coordinate(edge.id, longitude, latitude)
                source_point = (
                    node_by_id[edge.source].longitude,
                    node_by_id[edge.source].latitude,
                )
                target_point = (
                    node_by_id[edge.target].longitude,
                    node_by_id[edge.target].latitude,
                )
                endpoints_match = _coordinates_close(edge.geometry[0], source_point) and (
                    _coordinates_close(edge.geometry[-1], target_point)
                )
                if not self.network_directed:
                    endpoints_match = endpoints_match or (
                        _coordinates_close(edge.geometry[0], target_point)
                        and _coordinates_close(edge.geometry[-1], source_point)
                    )
                if not endpoints_match:
                    raise ValueError(
                        f"Walking edge {edge.id} geometry does not meet its graph nodes"
                    )
            for item in (*self.demand, *self.sites):
                if item.node_id not in node_by_id:
                    raise ValueError(
                        f"{item.id} needs a valid node_id when a verification graph is supplied"
                    )
                if item.snap_distance_m is None:
                    raise ValueError(
                        f"{item.id} needs snap_distance_m when a verification graph is supplied"
                    )
            for record in self.distances:
                evidence_errors = _route_evidence_errors(self, record)
                if evidence_errors:
                    raise ValueError(
                        "Distance evidence for "
                        f"{(record.demand_id, record.site_id)} failed: "
                        f"{evidence_errors[0]['kind']}"
                    )

    @property
    def demand_by_id(self) -> dict[str, DemandCell]:
        return {item.id: item for item in self.demand}

    @property
    def site_by_id(self) -> dict[str, CandidateSite]:

        return {item.id: item for item in self.sites}

    @property
    def distance_by_pair(self) -> dict[tuple[str, str], DistanceRecord]:
        return {(item.demand_id, item.site_id): item for item in self.distances}

    @property
    def network_node_by_id(self) -> dict[str, WalkingNode]:
        return {item.id: item for item in self.network_nodes}

    @property
    def network_edge_by_id(self) -> dict[str, WalkingEdge]:
        return {item.id: item for item in self.network_edges}


@dataclass(frozen=True)
class ServiceCoverageRequest:
    site_budget: int = 4
    max_distance_m: float = 1_200.0
    capacity_multiplier: float = 1.0
    forced_site_ids: tuple[str, ...] = ()
    banned_site_ids: tuple[str, ...] = ()
    timeout_seconds: float = 10.0
    excluded_site_sets: tuple[tuple[str, ...], ...] = ()
    fixed_objective_vector: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class _TrackedConstraint:
    id: str
    label: str
    expression: z3.BoolRef
    kind: str


def solve_service_coverage(
    scenario: FrozenServiceCoverageScenario,
    request: ServiceCoverageRequest,
    *,
    cancel_event: threading.Event | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Solve and freshly verify a capacitated walking-service assignment."""

    started = time.monotonic()
    cancel_event = cancel_event or threading.Event()
    control = _CoverageControl(
        deadline=started + max(0.0, request.timeout_seconds),
        cancel_event=cancel_event,
    )
    events: list[dict[str, Any]] = []

    def emit(event_type: str, message: str, **payload: Any) -> None:
        event = {
            "iteration": len(events) + 1,
            "type": event_type,
            "message": message,
            **payload,
        }
        events.append(event)
        if on_event is not None:
            on_event(copy.deepcopy(event))

    try:
        return _solve_service_coverage(
            scenario,
            request,
            started=started,
            control=control,
            events=events,
            emit=emit,
        )
    except _CoverageInterrupted as interruption:
        message = (
            "The service-allocation solve was cancelled; no feasibility claim has been made."
            if interruption.status == "cancelled"
            else "The service-allocation solve reached its time limit. This is not UNSAT."
        )
        return _terminal_result(
            interruption.status,
            message,
            scenario,
            started,
            events,
            diagnostics={"interrupted_phase": interruption.phase},
            assumptions=_request_payload(request),
        )
    except ValueError as error:
        return _terminal_result(
            "data_error",
            str(error),
            scenario,
            started,
            events,
            diagnostics={"finding": "invalid_request_or_scenario"},
            assumptions=_request_payload(request),
        )


def solve_next_service_coverage_solution(
    scenario: FrozenServiceCoverageScenario,
    request: ServiceCoverageRequest,
    previous_result: Mapping[str, Any],
    *,
    cancel_event: threading.Event | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Enumerate another structural site set with the exact same objective vector."""

    if previous_result.get("status") != "verified_optimal":
        return _terminal_result(
            "data_error",
            "An equally good alternative requires a previously verified optimal solution.",
            scenario,
            time.monotonic(),
            [],
            diagnostics={"finding": "alternative_requires_verified_optimum"},
            assumptions=_request_payload(request),
        )
    previous_assumptions = previous_result.get("assumptions")
    current_assumptions = _request_payload(request)
    if isinstance(previous_assumptions, Mapping) and any(
        previous_assumptions.get(key) != current_assumptions[key]
        for key in (
            "site_budget",
            "max_distance_m",
            "capacity_multiplier",
            "forced_site_ids",
            "banned_site_ids",
        )
    ):
        return _terminal_result(
            "data_error",
            "Equal-objective alternatives require the same coverage assumptions.",
            scenario,
            time.monotonic(),
            [],
            diagnostics={"finding": "alternative_assumptions_changed"},
            assumptions=current_assumptions,
        )
    selected = tuple(sorted(str(item) for item in previous_result["selected_site_ids"]))
    raw_vector = previous_result.get("objective_vector")
    if not isinstance(raw_vector, Sequence) or len(raw_vector) != 4:
        return _terminal_result(
            "data_error",
            "The previous result does not include its exact objective vector.",
            scenario,
            time.monotonic(),
            [],
            diagnostics={"finding": "missing_objective_vector"},
            assumptions=_request_payload(request),
        )
    next_request = replace(
        request,
        excluded_site_sets=(*request.excluded_site_sets, selected),
        fixed_objective_vector=tuple(int(item) for item in raw_vector),
    )
    return solve_service_coverage(
        scenario,
        next_request,
        cancel_event=cancel_event,
        on_event=on_event,
    )


def _solve_service_coverage(
    scenario: FrozenServiceCoverageScenario,
    request: ServiceCoverageRequest,
    *,
    started: float,
    control: _CoverageControl,
    events: list[dict[str, Any]],
    emit: Callable[..., None],
) -> dict[str, Any]:
    _validate_request(scenario, request)
    control.checkpoint("model_setup")
    demand = scenario.demand
    sites = scenario.sites
    distance_by_pair = scenario.distance_by_pair
    eligible_site_ids = frozenset(site.id for site in sites if site.eligible)
    effective_capacities = {
        site.id: math.floor(site.capacity * request.capacity_multiplier + 1e-9)
        for site in sites
    }

    open_variables = {
        site.id: z3.Bool(f"open__{site_index}")
        for site_index, site in enumerate(sites)
    }
    assignment_variables = {
        (cell.id, site.id): z3.Bool(f"assign__{cell_index}__{site_index}")
        for cell_index, cell in enumerate(demand)
        for site_index, site in enumerate(sites)
    }
    open_count = z3.Sum([z3.If(variable, 1, 0) for variable in open_variables.values()])
    worst_distance = z3.Int("objective__worst_distance_cm")
    weighted_distance = z3.Sum(
        [
            z3.If(
                assignment_variables[(cell.id, site.id)],
                cell.population
                * (
                    distance_by_pair[(cell.id, site.id)].distance_cm
                    if (cell.id, site.id) in distance_by_pair
                    else 0
                ),
                0,
            )
            for cell in demand
            for site in sites
        ]
    )
    total_population = sum(cell.population for cell in demand)
    site_loads = {
        site.id: z3.Sum(
            [
                z3.If(assignment_variables[(cell.id, site.id)], cell.population, 0)
                for cell in demand
            ]
        )
        for site in sites
    }
    maximum_load = z3.Int("objective__maximum_site_load")
    minimum_open_load = z3.Int("objective__minimum_open_site_load")
    load_imbalance = maximum_load - minimum_open_load
    objective_expressions = (
        open_count,
        worst_distance,
        weighted_distance,
        load_imbalance,
    )

    solver = z3.Solver()
    solver.set(random_seed=0)
    tracked: list[_TrackedConstraint] = []

    def track(constraint_id: str, label: str, expression: z3.BoolRef, kind: str) -> None:
        tracked.append(_TrackedConstraint(constraint_id, label, expression, kind))

    for site in sites:
        if site.id not in eligible_site_ids:
            solver.add(z3.Not(open_variables[site.id]))
        for cell in demand:
            assignment = assignment_variables[(cell.id, site.id)]
            solver.add(z3.Implies(assignment, open_variables[site.id]))
            record = distance_by_pair.get((cell.id, site.id))
            if record is None:
                solver.add(z3.Not(assignment))
            elif record.distance_m <= request.max_distance_m + 1e-9:
                solver.add(z3.Implies(assignment, worst_distance >= record.distance_cm))

    track(
        "complete_assignment",
        "Every included demand cell must be assigned to exactly one reviewed site.",
        z3.And(
            *[
                z3.PbEq(
                    [(assignment_variables[(cell.id, site.id)], 1) for site in sites], 1
                )
                for cell in demand
            ]
        ),
        "assignment",
    )
    over_distance = [
        assignment_variables[(cell.id, site.id)]
        for cell in demand
        for site in sites
        if (record := distance_by_pair.get((cell.id, site.id))) is not None
        and record.distance_m > request.max_distance_m + 1e-9
    ]
    track(
        "walking_distance_limit",
        (
            f"Every assignment must be within {request.max_distance_m:g} m by the "
            "frozen walking graph."
        ),
        z3.And(*[z3.Not(variable) for variable in over_distance]),
        "distance",
    )
    track(
        "site_budget",
        f"At most {request.site_budget} reviewed sites may be activated.",
        open_count <= request.site_budget,
        "budget",
    )
    capacity_constraints = [
        site_loads[site.id] <= effective_capacities[site.id] for site in sites
    ]
    track(
        "analytical_capacity",
        (
            "Assigned population must fit the analyst-declared site capacities at "
            f"the {request.capacity_multiplier:g}× sensitivity multiplier."
        ),
        z3.And(*capacity_constraints),
        "capacity",
    )
    for site_id in sorted(set(request.forced_site_ids)):
        track(
            f"force_site__{site_id}",
            f"{scenario.site_by_id[site_id].label} must be activated.",
            open_variables[site_id],
            "forced_site",
        )
    for site_id in sorted(set(request.banned_site_ids)):
        track(
            f"ban_site__{site_id}",
            f"{scenario.site_by_id[site_id].label} must remain inactive.",
            z3.Not(open_variables[site_id]),
            "banned_site",
        )

    for excluded in request.excluded_site_sets:
        selected = frozenset(excluded)
        solver.add(
            z3.Or(
                *[
                    z3.Not(open_variables[site.id])
                    if site.id in selected
                    else open_variables[site.id]
                    for site in sites
                ]
            )
        )
    solver.add(worst_distance >= 0, maximum_load >= 0, minimum_open_load >= 0)
    solver.add(maximum_load <= total_population, minimum_open_load <= total_population)
    solver.add(load_imbalance >= 0)
    optimisation_bounds: list[z3.BoolRef] = []
    admissible_records_by_demand = {
        cell.id: [
            record
            for site in sites
            if site.id in eligible_site_ids
            and (record := distance_by_pair.get((cell.id, site.id))) is not None
            and record.distance_m <= request.max_distance_m + 1e-9
        ]
        for cell in demand
    }
    if all(admissible_records_by_demand.values()):
        for cell in demand:
            optimisation_bounds.append(
                z3.Or(
                    *[
                        open_variables[record.site_id]
                        for record in admissible_records_by_demand[cell.id]
                    ]
                )
            )
        optimisation_bounds.append(
            z3.Sum(
                [
                    z3.If(open_variables[site.id], effective_capacities[site.id], 0)
                    for site in sites
                ]
            )
            >= total_population
        )
        optimisation_bounds.append(
            worst_distance
            >= max(
                min(record.distance_cm for record in records)
                for records in admissible_records_by_demand.values()
            )
        )
        optimisation_bounds.append(
            worst_distance
            <= max(
                record.distance_cm
                for records in admissible_records_by_demand.values()
                for record in records
            )
        )
        optimisation_bounds.append(
            weighted_distance
            >= sum(
                cell.population
                * min(
                    record.distance_cm
                    for record in admissible_records_by_demand[cell.id]
                )
                for cell in demand
            )
        )
    maximum_effective_capacity = max(
        (effective_capacities[site_id] for site_id in eligible_site_ids),
        default=0,
    )
    if maximum_effective_capacity > 0:
        cumulative_capacity = 0
        minimum_capacity_site_count = 0
        for capacity in sorted(
            (effective_capacities[site_id] for site_id in eligible_site_ids),
            reverse=True,
        ):
            cumulative_capacity += capacity
            minimum_capacity_site_count += 1
            if cumulative_capacity >= total_population:
                break
        optimisation_bounds.append(
            open_count >= minimum_capacity_site_count
        )
    else:
        minimum_capacity_site_count = 0
    for site in sites:
        solver.add(maximum_load >= site_loads[site.id])
        solver.add(
            minimum_open_load
            <= site_loads[site.id]
            + z3.If(open_variables[site.id], 0, total_population)
        )

    assumptions: list[z3.BoolRef] = []
    tracked_by_name: dict[str, _TrackedConstraint] = {}
    for index, item in enumerate(tracked):
        literal = z3.Bool(f"assumption__service_coverage__{index}")
        assumptions.append(literal)
        tracked_by_name[literal.decl().name()] = item
        solver.add(z3.Implies(literal, item.expression))

    if request.fixed_objective_vector is not None:
        for expression, value in zip(
            objective_expressions, request.fixed_objective_vector, strict=True
        ):
            solver.add(expression == value)

    emit(
        "matrix_compiled",
        "Compiled Boolean site and assignment choices with explicit policy constraints.",
        model={
            "open_boolean_count": len(open_variables),
            "assignment_boolean_count": len(assignment_variables),
            "open_variables": {
                site_id: str(variable) for site_id, variable in open_variables.items()
            },
            "demand_count": len(demand),
            "site_count": len(sites),
            "distance_record_count": len(scenario.distances),
            "tracked_constraints": [
                {"id": item.id, "kind": item.kind, "label": item.label} for item in tracked
            ],
            "objectives": list(_OBJECTIVE_KEYS),
        },
    )
    control.checkpoint("initial_feasibility")
    status = _cooperative_check(solver, assumptions, control)
    if status == z3.unsat:
        core = [
            tracked_by_name[item.decl().name()]
            for item in solver.unsat_core()
            if item.decl().name() in tracked_by_name
        ]
        diagnostics = _unsat_diagnostics(
            scenario,
            request,
            effective_capacities,
            core,
        )
        emit(
            "unsat_core",
            diagnostics["message"],
            unsat_core=diagnostics["unsat_core"],
            finding=diagnostics["finding"],
            witness_cell_id=diagnostics.get("witness_cell_id"),
        )
        return _terminal_result(
            "verified_unsat",
            diagnostics.pop("message"),
            scenario,
            started,
            events,
            diagnostics=diagnostics,
            assumptions=_request_payload(request),
            constraint_model=_constraint_model_payload(tracked, request),
        )
    if status != z3.sat:
        raise _CoverageInterrupted("timeout", "initial_z3_check")

    # UNSAT-core extraction is complete after feasibility. Making the tracked
    # assumptions ordinary facts substantially simplifies repeated optimization
    # and deterministic-selection checks without changing the active formula.
    model = solver.model()
    solver.add(*assumptions)
    solver.add(*optimisation_bounds)
    optimisation_assumptions: tuple[z3.BoolRef, ...] = ()
    initial_candidate = _model_candidate_payload(
        model,
        scenario,
        open_variables,
        assignment_variables,
        effective_capacities,
    )
    emit(
        "feasible_assignment",
        "Z3 found an assignment satisfying every hard constraint; optimisation is next.",
        **initial_candidate,
    )
    objective_vector: list[int] = []
    if request.fixed_objective_vector is None:
        admissible_distance_domain = sorted(
            {
                record.distance_cm
                for records in admissible_records_by_demand.values()
                for record in records
            }
        )
        open_domain = list(
            range(minimum_capacity_site_count, min(request.site_budget, len(sites)) + 1)
        )
        for index, (expression, domain) in enumerate(
            (
                (open_count, open_domain),
                (worst_distance, admissible_distance_domain),
            )
        ):
            model, optimum = _minimize_finite_domain(
                solver,
                optimisation_assumptions,
                expression,
                domain,
                control,
                f"objective_{_OBJECTIVE_KEYS[index]}",
            )
            solver.add(expression == optimum)
            if index == 1:
                for cell in demand:
                    within_optimum = [
                        record
                        for record in admissible_records_by_demand[cell.id]
                        if record.distance_cm <= optimum
                    ]
                    solver.add(
                        z3.Or(
                            *[
                                open_variables[record.site_id]
                                for record in within_optimum
                            ]
                        )
                    )
                    solver.add(
                        *[
                            z3.Not(assignment_variables[(cell.id, site.id)])
                            for site in sites
                            if (
                                record := distance_by_pair.get((cell.id, site.id))
                            )
                            is None
                            or record.distance_cm > optimum
                        ]
                    )
                viable_site_sets = _structurally_viable_site_sets(
                    scenario,
                    request,
                    effective_capacities,
                    site_count=objective_vector[0],
                    worst_distance_cm=optimum,
                )
                solver.add(
                    z3.Or(
                        *[
                            z3.And(
                                *[
                                    open_variables[site.id]
                                    if site.id in site_set
                                    else z3.Not(open_variables[site.id])
                                    for site in sites
                                ]
                            )
                            for site_set in viable_site_sets
                        ]
                    )
                )
            objective_vector.append(optimum)
            emit(
                "objective_improved",
                f"Proved the minimum value for {_OBJECTIVE_KEYS[index]}.",
                objective=_OBJECTIVE_KEYS[index],
                value=optimum,
                objective_index=index,
                **_model_candidate_payload(
                    model,
                    scenario,
                    open_variables,
                    assignment_variables,
                    effective_capacities,
                ),
            )
        optimizer = z3.Optimize()
        optimizer.set(priority="lex")
        optimizer.add(*solver.assertions())
        optimizer.minimize(weighted_distance)
        optimizer.minimize(load_imbalance)
        status = _cooperative_check(optimizer, optimisation_assumptions, control)
        if status != z3.sat:
            raise _CoverageInterrupted("timeout", "assignment_optimization")
        model = optimizer.model()
        remaining_values = [
            model.eval(expression, model_completion=True).as_long()
            for expression in (weighted_distance, load_imbalance)
        ]
        for index, (expression, optimum) in enumerate(
            zip((weighted_distance, load_imbalance), remaining_values, strict=True),
            start=2,
        ):
            solver.add(expression == optimum)
            objective_vector.append(optimum)
            emit(
                "objective_improved",
                f"Proved the minimum value for {_OBJECTIVE_KEYS[index]}.",
                objective=_OBJECTIVE_KEYS[index],
                value=optimum,
                objective_index=index,
                **_model_candidate_payload(
                    model,
                    scenario,
                    open_variables,
                    assignment_variables,
                    effective_capacities,
                ),
            )
    else:
        objective_vector = list(request.fixed_objective_vector)

    final_candidate = _model_candidate_payload(
        model,
        scenario,
        open_variables,
        assignment_variables,
        effective_capacities,
    )
    selected_site_ids = final_candidate["selected_site_ids"]
    assignments = final_candidate["assignments"]
    objective_payload = _objective_payload(tuple(objective_vector), total_population)
    emit(
        "objective_improved",
        "The complete lexicographic objective vector is optimal; verification is next.",
        **final_candidate,
        objective_values=objective_payload,
    )
    control.checkpoint("independent_verification")
    verification = verify_service_coverage_solution(
        scenario,
        request,
        selected_site_ids,
        assignments,
        objective_vector=tuple(objective_vector),
        _control=control,
    )
    if not verification["verified"]:
        emit(
            "verification_error",
            "Fresh evidence verification rejected the Z3 assignment.",
            errors=verification["errors"],
        )
        return _terminal_result(
            "data_error",
            "Fresh evidence verification disagreed with the solver candidate.",
            scenario,
            started,
            events,
            selected_site_ids=selected_site_ids,
            assignments=assignments,
            objective_vector=objective_vector,
            objective_values=objective_payload,
            verification=verification,
            diagnostics={"finding": "independent_verification_failed"},
            assumptions=_request_payload(request),
            constraint_model=_constraint_model_payload(tracked, request),
        )
    emit(
        "fresh_verification",
        "Every assignment was independently checked against the frozen evidence.",
        **final_candidate,
        summary=verification["summary"],
    )
    return _terminal_result(
        "verified_optimal",
        (
            "Every included demand cell is assigned within the stated walking-distance and "
            "analytical-capacity assumptions. This is a model result, not a service decision."
        ),
        scenario,
        started,
        events,
        selected_site_ids=selected_site_ids,
        assignments=assignments,
        objective_vector=objective_vector,
        objective_values=objective_payload,
        verification=verification,
        assumptions=_request_payload(request),
        constraint_model=_constraint_model_payload(tracked, request),
        site_loads=verification["site_loads"],
        district_summary=verification["district_summary"],
    )


def verify_service_coverage_solution(
    scenario: FrozenServiceCoverageScenario,
    request: ServiceCoverageRequest,
    selected_site_ids: Sequence[str],
    assignments: Sequence[Mapping[str, Any]],
    *,
    objective_vector: tuple[int, int, int, int] | None = None,
    _control: _CoverageControl | None = None,
) -> dict[str, Any]:
    """Reconstruct every hard requirement without consulting the Z3 model."""

    errors: list[dict[str, Any]] = []
    selected = frozenset(str(item) for item in selected_site_ids)
    known_sites = scenario.site_by_id
    known_demand = scenario.demand_by_id
    distance_by_pair = scenario.distance_by_pair
    effective_capacities = {
        site.id: math.floor(site.capacity * request.capacity_multiplier + 1e-9)
        for site in scenario.sites
    }
    unknown_selected = selected - known_sites.keys()
    if unknown_selected:
        errors.append({"kind": "unknown_site", "site_ids": sorted(unknown_selected)})
    ineligible = sorted(
        site_id
        for site_id in selected
        if site_id in known_sites and not known_sites[site_id].eligible
    )
    if ineligible:
        errors.append({"kind": "ineligible_site", "site_ids": ineligible})
    if len(selected) > request.site_budget:
        errors.append(
            {
                "kind": "site_budget_exceeded",
                "selected": len(selected),
                "budget": request.site_budget,
            }
        )
    missing_forced = sorted(set(request.forced_site_ids) - selected)
    selected_banned = sorted(set(request.banned_site_ids) & selected)
    if missing_forced:
        errors.append({"kind": "forced_site_missing", "site_ids": missing_forced})
    if selected_banned:
        errors.append({"kind": "banned_site_selected", "site_ids": selected_banned})

    assignment_by_demand: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    canonical_assignments: list[tuple[DemandCell, CandidateSite, DistanceRecord]] = []
    for index, assignment in enumerate(assignments):
        if _control is not None and index % 32 == 0:
            _control.checkpoint("verification_assignments")
        demand_id = str(assignment.get("demand_id", ""))
        site_id = str(assignment.get("site_id", ""))
        assignment_by_demand[demand_id].append(assignment)
        cell = known_demand.get(demand_id)
        site = known_sites.get(site_id)
        record = distance_by_pair.get((demand_id, site_id))
        if cell is None or site is None:
            errors.append(
                {"kind": "assignment_unknown_reference", "demand_id": demand_id, "site_id": site_id}
            )
            continue
        if site_id not in selected:
            errors.append(
                {"kind": "assignment_to_inactive_site", "demand_id": demand_id, "site_id": site_id}
            )
        if record is None:
            errors.append(
                {"kind": "missing_distance_evidence", "demand_id": demand_id, "site_id": site_id}
            )
            continue
        supplied_distance = assignment.get("distance_m")
        if supplied_distance is not None and not math.isclose(
            float(supplied_distance), record.distance_m, rel_tol=0, abs_tol=0.005
        ):
            errors.append(
                {
                    "kind": "assignment_distance_disagrees_with_matrix",
                    "demand_id": demand_id,
                    "site_id": site_id,
                }
            )
        if record.distance_m > request.max_distance_m + 1e-9:
            errors.append(
                {
                    "kind": "walking_distance_exceeded",
                    "demand_id": demand_id,
                    "site_id": site_id,
                    "distance_m": record.distance_m,
                    "limit_m": request.max_distance_m,
                }
            )
        canonical_assignments.append((cell, site, record))

    for cell in scenario.demand:
        count = len(assignment_by_demand.get(cell.id, []))
        if count != 1:
            errors.append(
                {"kind": "demand_assignment_count", "demand_id": cell.id, "count": count}
            )
    extra_demand = sorted(set(assignment_by_demand) - known_demand.keys())
    if extra_demand:
        errors.append({"kind": "unknown_demand", "demand_ids": extra_demand})

    loads = {site.id: 0 for site in scenario.sites}
    for cell, site, _record in canonical_assignments:
        loads[site.id] += cell.population
    for site_id in sorted(selected):
        if site_id in known_sites and loads[site_id] > effective_capacities[site_id]:
            errors.append(
                {
                    "kind": "capacity_exceeded",
                    "site_id": site_id,
                    "load": loads[site_id],
                    "effective_capacity": effective_capacities[site_id],
                }
            )

    graph_checks: list[dict[str, Any]] = []
    if scenario.network_edges:
        graph = _walking_graph(scenario)
        for index, (cell, site, record) in enumerate(canonical_assignments):
            if _control is not None and index % 16 == 0:
                _control.checkpoint("verification_graph_routes")
            evidence_errors = _route_evidence_errors(scenario, record)
            errors.extend(evidence_errors)
            if record.network_distance_m is None:
                continue
            try:
                graph_distance = _verified_shortest_path_length(
                    graph,
                    cell.node_id,
                    site.node_id,
                    _control,
                )
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                errors.append(
                    {
                        "kind": "verification_graph_unreachable",
                        "demand_id": cell.id,
                        "site_id": site.id,
                    }
                )
                continue
            matches = math.isclose(
                graph_distance,
                record.network_distance_m,
                rel_tol=0,
                abs_tol=0.01,
            )
            graph_checks.append(
                {
                    "demand_id": cell.id,
                    "site_id": site.id,
                    "matrix_total_distance_m": record.distance_m,
                    "matrix_network_distance_m": record.network_distance_m,
                    "recomputed_shortest_network_distance_m": round(graph_distance, 3),
                    "matches": matches,
                }
            )
            if not matches:
                errors.append(
                    {
                        "kind": "network_distance_shortest_path_mismatch",
                        "demand_id": cell.id,
                        "site_id": site.id,
                        "matrix_network_distance_m": record.network_distance_m,
                        "recomputed_shortest_network_distance_m": round(
                            graph_distance, 3
                        ),
                    }
                )

    recomputed_vector = _recompute_objective_vector(selected, canonical_assignments, loads)
    if objective_vector is not None and tuple(objective_vector) != recomputed_vector:
        errors.append(
            {
                "kind": "objective_mismatch",
                "reported": list(objective_vector),
                "recomputed": list(recomputed_vector),
            }
        )

    district_accumulator: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"population": 0, "weighted_distance_m_people": 0.0, "worst_distance_m": 0.0}
    )
    for cell, _site, record in canonical_assignments:
        district_id = cell.district_id or "unassigned-district"
        district_accumulator[district_id]["population"] += cell.population
        district_accumulator[district_id]["weighted_distance_m_people"] += (
            cell.population * record.distance_m
        )
        district_accumulator[district_id]["worst_distance_m"] = max(
            float(district_accumulator[district_id]["worst_distance_m"]), record.distance_m
        )
    district_summary = []
    for district_id, values in sorted(district_accumulator.items()):
        population = int(values["population"])
        district_summary.append(
            {
                "district_id": district_id,
                "population": population,
                "mean_distance_m": round(
                    float(values["weighted_distance_m_people"]) / population, 2
                ),
                "worst_distance_m": round(float(values["worst_distance_m"]), 2),
            }
        )
    site_load_payload = [
        {
            "site_id": site.id,
            "label": site.label,
            "selected": site.id in selected,
            "load": loads[site.id],
            "assigned_population": loads[site.id],
            "assigned_cell_count": sum(
                assigned_site.id == site.id
                for _cell, assigned_site, _record in canonical_assignments
            ),
            "declared_capacity": site.capacity,
            "effective_capacity": effective_capacities[site.id],
            "utilisation": (
                round(loads[site.id] / effective_capacities[site.id], 4)
                if effective_capacities[site.id]
                else None
            ),
        }
        for site in scenario.sites
    ]
    return {
        "verified": not errors,
        "status": "verified" if not errors else "verification_error",
        "all_cells_assigned": not any(
            item["kind"] in {"demand_assignment_count", "unknown_demand"}
            for item in errors
        ),
        "capacities_respected": not any(
            item["kind"] == "capacity_exceeded" for item in errors
        ),
        "distances_respected": not any(
            _is_distance_evidence_error(str(item["kind"]))
            for item in errors
        ),
        "selected_sites_eligible": not any(
            item["kind"] in {"unknown_site", "ineligible_site"} for item in errors
        ),
        "budget_respected": not any(
            item["kind"] == "site_budget_exceeded" for item in errors
        ),
        "errors": errors,
        "summary": {
            "demand_cells": len(scenario.demand),
            "population": sum(item.population for item in scenario.demand),
            "assigned_cells": len(canonical_assignments),
            "selected_sites": len(selected),
            "graph_routes_checked": len(graph_checks),
        },
        "objective_vector": list(recomputed_vector),
        "objective_values": _objective_payload(
            recomputed_vector, sum(item.population for item in scenario.demand)
        ),
        "site_loads": site_load_payload,
        "district_summary": district_summary,
        "graph_checks": graph_checks,
        "evidence_basis": (
            "frozen_distance_matrix_and_walking_graph"
            if scenario.network_edges
            else "frozen_distance_matrix"
        ),
    }


def _validate_request(
    scenario: FrozenServiceCoverageScenario, request: ServiceCoverageRequest
) -> None:
    if request.site_budget < 0:
        raise ValueError("The active-site budget cannot be negative")
    if not math.isfinite(request.max_distance_m) or request.max_distance_m < 0:
        raise ValueError("The walking-distance threshold must be finite and non-negative")
    if (
        not math.isfinite(request.capacity_multiplier)
        or request.capacity_multiplier < 0.1
        or request.capacity_multiplier > 5.0
    ):
        raise ValueError("The analytical capacity multiplier must be between 0.1 and 5")
    if request.timeout_seconds < 0 or not math.isfinite(request.timeout_seconds):
        raise ValueError("The solver timeout must be finite and non-negative")
    known_sites = scenario.site_by_id
    requested_ids = set(request.forced_site_ids) | set(request.banned_site_ids)
    unknown = requested_ids - known_sites.keys()
    if unknown:
        raise ValueError(f"Unknown requested site IDs: {sorted(unknown)}")
    ineligible_forced = [
        site_id for site_id in request.forced_site_ids if not known_sites[site_id].eligible
    ]
    if ineligible_forced:
        raise ValueError(f"Ineligible sites cannot be forced: {sorted(ineligible_forced)}")
    known_id_set = frozenset(known_sites)
    for excluded in request.excluded_site_sets:
        unknown_excluded = set(excluded) - known_id_set
        if unknown_excluded:
            raise ValueError(
                f"Excluded alternatives reference unknown sites: {sorted(unknown_excluded)}"
            )
    if request.fixed_objective_vector is not None:
        if len(request.fixed_objective_vector) != 4 or any(
            value < 0 for value in request.fixed_objective_vector
        ):
            raise ValueError("The fixed objective vector must contain four non-negative integers")


def _cooperative_check(
    solver: z3.Solver | z3.Optimize,
    assumptions: Sequence[z3.BoolRef],
    control: _CoverageControl,
) -> z3.CheckSatResult:
    control.checkpoint("z3_check")
    solver.set(timeout=max(1, int((control.deadline - time.monotonic()) * 1000)))
    finished = threading.Event()

    def interrupt_when_cancelled() -> None:
        while not finished.wait(0.01):
            if control.cancel_event.is_set():
                if isinstance(solver, z3.Solver):
                    solver.interrupt()
                else:
                    solver.ctx.interrupt()
                return

    watcher = threading.Thread(
        target=interrupt_when_cancelled,
        name="service-coverage-z3-cancel",
        daemon=True,
    )
    watcher.start()
    try:
        status = solver.check(*assumptions)
    finally:
        finished.set()
        watcher.join(timeout=0.1)
    if control.cancel_event.is_set():
        raise _CoverageInterrupted("cancelled", "z3_check")
    if time.monotonic() >= control.deadline:
        raise _CoverageInterrupted("timeout", "z3_check")
    if status == z3.unknown:
        raise _CoverageInterrupted("timeout", "z3_check")
    return status


def _minimize_finite_domain(
    solver: z3.Solver,
    assumptions: Sequence[z3.BoolRef],
    expression: z3.ArithRef,
    domain: Sequence[int],
    control: _CoverageControl,
    phase: str,
) -> tuple[z3.ModelRef, int]:
    values = sorted(set(domain))
    if not values:
        raise ValueError(f"No attainable values were supplied for {phase}")
    lower_index = 0
    upper_index = len(values) - 1
    while lower_index < upper_index:
        control.checkpoint(phase)
        middle_index = (lower_index + upper_index) // 2
        solver.push()
        solver.add(expression <= values[middle_index])
        status = _cooperative_check(solver, assumptions, control)
        solver.pop()
        if status == z3.sat:
            upper_index = middle_index
        else:
            lower_index = middle_index + 1
    optimum = values[lower_index]
    solver.push()
    solver.add(expression == optimum)
    status = _cooperative_check(solver, assumptions, control)
    if status != z3.sat:
        solver.pop()
        raise ValueError(f"Could not recover the proved optimum during {phase}")
    model = solver.model()
    solver.pop()
    return model, optimum


def _unsat_diagnostics(
    scenario: FrozenServiceCoverageScenario,
    request: ServiceCoverageRequest,
    effective_capacities: Mapping[str, int],
    core: Sequence[_TrackedConstraint],
) -> dict[str, Any]:
    eligible = [
        site
        for site in scenario.sites
        if site.eligible and site.id not in set(request.banned_site_ids)
    ]
    forced = set(request.forced_site_ids)
    total_population = sum(item.population for item in scenario.demand)
    available_slots = max(0, request.site_budget - len(forced))
    optional = [site for site in eligible if site.id not in forced]
    maximum_capacity = sum(
        effective_capacities[item.id] for item in eligible if item.id in forced
    )
    maximum_capacity += sum(
        sorted((effective_capacities[item.id] for item in optional), reverse=True)[
            :available_slots
        ]
    )
    forced_banned = sorted(forced & set(request.banned_site_ids))
    unreachable = [
        cell.id
        for cell in scenario.demand
        if not any(
            site.eligible
            and site.id not in set(request.banned_site_ids)
            and (
                record := scenario.distance_by_pair.get((cell.id, site.id))
            )
            is not None
            and record.distance_m <= request.max_distance_m + 1e-9
            for site in scenario.sites
        )
    ]
    if forced_banned:
        finding = "forced_and_banned_site_conflict"
        message = (
            f"{scenario.site_by_id[forced_banned[0]].label} is both forced active and banned. "
            "Remove one of those two assumptions."
        )
        suggestions = ["remove_force", "remove_ban"]
    elif len(forced) > request.site_budget:
        finding = "forced_sites_exceed_budget"
        message = (
            f"{len(forced)} sites are forced active but the budget permits only "
            f"{request.site_budget}. Increase the budget or release a forced site."
        )
        suggestions = ["increase_site_budget", "release_forced_site"]
    elif unreachable:
        finding = "distance_coverage_gap"
        label = scenario.demand_by_id[unreachable[0]].label
        message = (
            f"{label} has no eligible, non-banned site within {request.max_distance_m:g} m "
            "in total modelled walking distance, including snap connectors. Increase the "
            "threshold, unban a nearby site, or "
            "review another candidate."
        )
        suggestions = ["increase_distance_threshold", "unban_site", "review_candidate_site"]
    elif maximum_capacity < total_population:
        finding = "insufficient_capacity_under_budget"
        message = (
            f"At most {maximum_capacity} people fit in {request.site_budget} sites under the "
            f"{request.capacity_multiplier:g}× capacity assumption, but the included demand "
            f"is {total_population}. Increase the site budget or capacity assumption."
        )
        suggestions = ["increase_site_budget", "increase_capacity_multiplier"]
    elif request.fixed_objective_vector is not None and request.excluded_site_sets:
        finding = "no_equal_objective_alternative"
        message = (
            "No other structural site set has the same verified objective values under the "
            "current assumptions. This does not rule out a worse or differently prioritised plan."
        )
        suggestions = ["allow_different_objective_values", "change_assumptions"]
    else:
        finding = "incompatible_service_assumptions"
        message = (
            "No assignment satisfies the current site budget, walking-distance, capacity, "
            "force, and ban assumptions together. Relax one assumption shown in the core."
        )
        suggestions = [
            "increase_site_budget",
            "increase_distance_threshold",
            "increase_capacity_multiplier",
        ]
    return {
        "finding": finding,
        "message": message,
        "unsat_core": [
            {"id": item.id, "kind": item.kind, "label": item.label} for item in core
        ],
        "suggested_relaxations": suggestions,
        "capacity_bound": {
            "included_population": total_population,
            "maximum_capacity_under_budget": maximum_capacity,
        },
        "uncovered_demand_ids": unreachable,
        "witness_cell_id": unreachable[0] if unreachable else None,
    }


def _constraint_model_payload(
    tracked: Sequence[_TrackedConstraint], request: ServiceCoverageRequest
) -> dict[str, Any]:
    return {
        "variables": {
            "open": "open[site] is true when a reviewed site is activated.",
            "assign": "assign[demand,site] is true for the demand cell's one selected site.",
        },
        "hard_constraints": [
            {"id": item.id, "kind": item.kind, "plain_language": item.label}
            for item in tracked
        ],
        "objectives": [
            {"priority": 1, "key": "open_sites", "direction": "minimise"},
            {"priority": 2, "key": "worst_distance_m", "direction": "minimise"},
            {
                "priority": 3,
                "key": "population_weighted_total_distance_person_m",
                "direction": "minimise",
            },
            {"priority": 4, "key": "load_imbalance_people", "direction": "minimise"},
        ],
        "capacity_semantics": {
            "multiplier": request.capacity_multiplier,
            "rounding": "floor_to_whole_people",
            "claim": "analytical sensitivity assumption, not an observed operating capacity",
        },
        "district_rule": (
            "District fields are reported for inspection; version 1 has no district hard rule."
        ),
    }


def _request_payload(request: ServiceCoverageRequest) -> dict[str, Any]:
    return {
        "site_budget": request.site_budget,
        "max_distance_m": request.max_distance_m,
        "capacity_multiplier": request.capacity_multiplier,
        "forced_site_ids": sorted(set(request.forced_site_ids)),
        "banned_site_ids": sorted(set(request.banned_site_ids)),
        "timeout_seconds": request.timeout_seconds,
    }


def _model_candidate_payload(
    model: z3.ModelRef,
    scenario: FrozenServiceCoverageScenario,
    open_variables: Mapping[str, z3.BoolRef],
    assignment_variables: Mapping[tuple[str, str], z3.BoolRef],
    effective_capacities: Mapping[str, int],
) -> dict[str, Any]:
    selected_site_ids = sorted(
        site_id
        for site_id, variable in open_variables.items()
        if z3.is_true(model.eval(variable, model_completion=True))
    )
    assignments: list[dict[str, Any]] = []
    loads = {site.id: 0 for site in scenario.sites}
    assigned_cell_counts = {site.id: 0 for site in scenario.sites}
    distance_by_pair = scenario.distance_by_pair
    for cell in scenario.demand:
        site = next(
            site
            for site in scenario.sites
            if z3.is_true(
                model.eval(assignment_variables[(cell.id, site.id)], model_completion=True)
            )
        )
        record = distance_by_pair[(cell.id, site.id)]
        assignments.append(_assignment_payload(cell, site, record))
        loads[site.id] += cell.population
        assigned_cell_counts[site.id] += 1
    site_loads = [
        {
            "site_id": site.id,
            "assigned_population": loads[site.id],
            "load": loads[site.id],
            "effective_capacity": effective_capacities[site.id],
            "utilisation": (
                round(loads[site.id] / effective_capacities[site.id], 4)
                if effective_capacities[site.id]
                else None
            ),
            "assigned_cell_count": assigned_cell_counts[site.id],
        }
        for site in scenario.sites
    ]
    return {
        "selected_site_ids": selected_site_ids,
        "assignments": assignments,
        "site_loads": site_loads,
    }


def _assignment_payload(
    cell: DemandCell, site: CandidateSite, record: DistanceRecord
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "demand_cell_id": cell.id,
        "demand_id": cell.id,
        "demand_label": cell.label,
        "district_id": cell.district_id,
        "population": cell.population,
        "site_id": site.id,
        "site_label": site.label,
        "distance_m": round(record.distance_m, 2),
    }
    if record.demand_connector_m is not None:
        payload["demand_connector_m"] = round(record.demand_connector_m, 3)
    if record.network_distance_m is not None:
        payload["network_distance_m"] = round(record.network_distance_m, 3)
    if record.site_connector_m is not None:
        payload["site_connector_m"] = round(record.site_connector_m, 3)
    if record.route_node_ids:
        payload["route_node_ids"] = list(record.route_node_ids)
    if record.route_edge_ids:
        payload["route_edge_ids"] = list(record.route_edge_ids)
    if record.connector_method is not None:
        payload["connector_method"] = record.connector_method
    if record.route is not None:
        payload["route"] = copy.deepcopy(record.route)
    return payload


def _objective_payload(
    vector: tuple[int, int, int, int], total_population: int
) -> dict[str, Any]:
    open_sites, worst_cm, weighted_cm_people, imbalance = vector
    weighted_person_m = weighted_cm_people / 100
    return {
        "selected_site_count": open_sites,
        "open_sites": open_sites,
        "worst_distance_m": round(worst_cm / 100, 2),
        "population_weighted_distance_m": round(weighted_person_m, 2),
        "population_weighted_total_distance_person_m": round(weighted_person_m, 2),
        "population_weighted_mean_distance_m": round(
            weighted_person_m / total_population, 2
        ),
        "load_imbalance_people": imbalance,
    }


def _recompute_objective_vector(
    selected: frozenset[str],
    assignments: Sequence[tuple[DemandCell, CandidateSite, DistanceRecord]],
    loads: Mapping[str, int],
) -> tuple[int, int, int, int]:
    worst = max((record.distance_cm for _cell, _site, record in assignments), default=0)
    weighted = sum(
        cell.population * record.distance_cm for cell, _site, record in assignments
    )
    selected_loads = [loads[site_id] for site_id in selected if site_id in loads]
    imbalance = max(selected_loads, default=0) - min(selected_loads, default=0)
    return len(selected), worst, weighted, imbalance


def _structurally_viable_site_sets(
    scenario: FrozenServiceCoverageScenario,
    request: ServiceCoverageRequest,
    effective_capacities: Mapping[str, int],
    *,
    site_count: int,
    worst_distance_cm: int,
) -> list[frozenset[str]]:
    """Compile a small, sound site-set disjunction after objectives 1–2 are fixed."""

    forced = frozenset(request.forced_site_ids)
    banned = frozenset(request.banned_site_ids)
    excluded = {frozenset(site_set) for site_set in request.excluded_site_sets}
    candidates = [
        site.id
        for site in scenario.sites
        if site.eligible and site.id not in banned
    ]
    distance_by_pair = scenario.distance_by_pair
    total_population = sum(cell.population for cell in scenario.demand)
    viable: list[frozenset[str]] = []
    for raw_site_set in combinations(candidates, site_count):
        site_set = frozenset(raw_site_set)
        if not forced <= site_set or site_set in excluded:
            continue
        if sum(effective_capacities[site_id] for site_id in site_set) < total_population:
            continue
        if any(
            not any(
                (record := distance_by_pair.get((cell.id, site_id))) is not None
                and record.distance_cm <= worst_distance_cm
                for site_id in site_set
            )
            for cell in scenario.demand
        ):
            continue
        viable.append(site_set)
    return viable


def _walking_graph(
    scenario: FrozenServiceCoverageScenario,
) -> nx.MultiDiGraph | nx.MultiGraph:
    graph: nx.MultiDiGraph | nx.MultiGraph
    graph = nx.MultiDiGraph() if scenario.network_directed else nx.MultiGraph()
    graph.add_nodes_from(sorted(node.id for node in scenario.network_nodes))
    for edge in scenario.network_edges:
        graph.add_edge(
            edge.source,
            edge.target,
            key=edge.id,
            id=edge.id,
            length_m=edge.length_m,
        )
    return graph


def _route_evidence_errors(
    scenario: FrozenServiceCoverageScenario,
    record: DistanceRecord,
) -> list[dict[str, Any]]:
    """Audit one matrix relation against its exact frozen route evidence.

    This deliberately does not ask Z3 or search for a replacement route. The
    matrix record must explain itself through the stored connector lengths,
    ordered graph IDs, graph edge geometries, and source-point-to-site geometry.
    A separate verification step checks that its network component is shortest.
    """

    errors: list[dict[str, Any]] = []
    context = {"demand_id": record.demand_id, "site_id": record.site_id}

    def add(kind: str, **details: Any) -> None:
        errors.append({"kind": kind, **context, **details})

    cell = scenario.demand_by_id.get(record.demand_id)
    site = scenario.site_by_id.get(record.site_id)
    if cell is None or site is None:
        add("route_unknown_matrix_reference")
        return errors

    components = {
        "demand_connector_m": record.demand_connector_m,
        "network_distance_m": record.network_distance_m,
        "site_connector_m": record.site_connector_m,
    }
    missing_components = sorted(name for name, value in components.items() if value is None)
    if missing_components:
        add("distance_evidence_missing_component", fields=missing_components)
    if record.connector_method != "straight_line_projected_euclidean":
        add("route_connector_method_missing_or_unsupported")
    invalid_components = sorted(
        name
        for name, value in components.items()
        if value is not None and (not math.isfinite(value) or value < 0)
    )
    if invalid_components:
        add("distance_evidence_invalid_component", fields=invalid_components)

    if (
        record.demand_connector_m is not None
        and cell.snap_distance_m is not None
        and not math.isclose(
            record.demand_connector_m, cell.snap_distance_m, rel_tol=0, abs_tol=0.01
        )
    ):
        add(
            "demand_connector_snap_mismatch",
            connector_m=record.demand_connector_m,
            snap_distance_m=cell.snap_distance_m,
        )
    if (
        record.site_connector_m is not None
        and site.snap_distance_m is not None
        and not math.isclose(
            record.site_connector_m, site.snap_distance_m, rel_tol=0, abs_tol=0.01
        )
    ):
        add(
            "site_connector_snap_mismatch",
            connector_m=record.site_connector_m,
            snap_distance_m=site.snap_distance_m,
        )
    if all(value is not None and math.isfinite(value) for value in components.values()):
        component_total = sum(float(value) for value in components.values())
        if not math.isclose(record.distance_m, component_total, rel_tol=0, abs_tol=0.01):
            add(
                "distance_component_total_mismatch",
                distance_m=record.distance_m,
                component_total_m=round(component_total, 3),
            )

    node_by_id = scenario.network_node_by_id
    edge_by_id = scenario.network_edge_by_id
    route_nodes = record.route_node_ids
    route_edges = record.route_edge_ids
    if not route_nodes:
        add("route_node_sequence_missing")
    else:
        if route_nodes[0] != cell.node_id or route_nodes[-1] != site.node_id:
            add(
                "route_node_endpoint_mismatch",
                expected_start=cell.node_id,
                actual_start=route_nodes[0],
                expected_end=site.node_id,
                actual_end=route_nodes[-1],
            )
        missing_node_ids = sorted(set(route_nodes) - node_by_id.keys())
        if missing_node_ids:
            add("route_unknown_node", node_ids=missing_node_ids)
    if len(route_edges) != max(0, len(route_nodes) - 1):
        add(
            "route_edge_node_count_mismatch",
            node_count=len(route_nodes),
            edge_count=len(route_edges),
        )

    ordered_edge_geometries: list[tuple[tuple[float, float], ...]] = []
    accumulated_network_m = 0.0
    chain_is_valid = bool(route_nodes) and len(route_edges) == len(route_nodes) - 1
    if chain_is_valid:
        for index, (source, target, edge_id) in enumerate(
            zip(route_nodes[:-1], route_nodes[1:], route_edges, strict=True)
        ):
            edge = edge_by_id.get(edge_id)
            if edge is None:
                add("route_unknown_edge", edge_id=edge_id, edge_index=index)
                chain_is_valid = False
                continue
            forward = edge.source == source and edge.target == target
            reverse = (
                not scenario.network_directed
                and edge.source == target
                and edge.target == source
            )
            if not forward and not reverse:
                add(
                    "route_edge_chain_mismatch",
                    edge_id=edge_id,
                    edge_index=index,
                    expected_from=source,
                    expected_to=target,
                    actual_from=edge.source,
                    actual_to=edge.target,
                )
                chain_is_valid = False
                continue
            accumulated_network_m += edge.length_m
            geometry = edge.geometry if forward else tuple(reversed(edge.geometry))
            if len(geometry) < 2:
                add("route_edge_geometry_missing", edge_id=edge_id, edge_index=index)
                chain_is_valid = False
                continue
            source_node = node_by_id.get(source)
            target_node = node_by_id.get(target)
            if source_node is None or target_node is None:
                add("route_edge_references_unknown_node", edge_id=edge_id, edge_index=index)
                chain_is_valid = False
                continue
            if not _coordinates_close(
                geometry[0], (source_node.longitude, source_node.latitude)
            ) or not _coordinates_close(
                geometry[-1], (target_node.longitude, target_node.latitude)
            ):
                add("route_edge_geometry_endpoint_mismatch", edge_id=edge_id, edge_index=index)
                chain_is_valid = False
                continue
            ordered_edge_geometries.append(geometry)
    if (
        record.network_distance_m is not None
        and math.isfinite(record.network_distance_m)
        and chain_is_valid
        and not math.isclose(
            accumulated_network_m,
            record.network_distance_m,
            rel_tol=0,
            abs_tol=0.01,
        )
    ):
        add(
            "route_edge_length_sum_mismatch",
            network_distance_m=record.network_distance_m,
            edge_length_sum_m=round(accumulated_network_m, 3),
        )

    if record.route is None:
        add("route_geometry_missing")
        return errors
    if not isinstance(record.route, Mapping) or record.route.get("type") != "Feature":
        add("route_geometry_invalid_feature")
        return errors
    properties = record.route.get("properties")
    if not isinstance(properties, Mapping):
        add("route_properties_missing")
    else:
        if properties.get("demand_id") != record.demand_id:
            add("route_property_demand_mismatch")
        if properties.get("site_id") != record.site_id:
            add("route_property_site_mismatch")
        if properties.get("connector_method") != record.connector_method:
            add("route_connector_method_missing_or_unsupported")
        property_values = {
            "distance_m": record.distance_m,
            **components,
        }
        for name, expected in property_values.items():
            actual = properties.get(name)
            if (
                expected is None
                or isinstance(actual, bool)
                or not isinstance(actual, (int, float))
                or not math.isclose(float(actual), expected, rel_tol=0, abs_tol=0.01)
            ):
                add("route_property_distance_mismatch", field=name)

    geometry = record.route.get("geometry")
    if not isinstance(geometry, Mapping) or geometry.get("type") != "LineString":
        add("route_geometry_invalid_linestring")
        return errors
    try:
        actual_coordinates = _parse_line_coordinates(
            geometry, f"Route for {(record.demand_id, record.site_id)}"
        )
    except ValueError:
        add("route_geometry_invalid_coordinates")
        return errors

    if chain_is_valid and route_nodes and not missing_node_ids:
        network_coordinates: list[tuple[float, float]] = []
        if ordered_edge_geometries:
            for edge_geometry in ordered_edge_geometries:
                if network_coordinates and not _coordinates_close(
                    network_coordinates[-1], edge_geometry[0]
                ):
                    add("route_edge_geometry_discontinuity")
                    chain_is_valid = False
                    break
                _extend_without_duplicate(network_coordinates, edge_geometry)
        else:
            node = node_by_id[route_nodes[0]]
            network_coordinates.append((node.longitude, node.latitude))

        if chain_is_valid:
            expected_coordinates: list[tuple[float, float]] = []
            _extend_without_duplicate(
                expected_coordinates, ((cell.longitude, cell.latitude),)
            )
            _extend_without_duplicate(expected_coordinates, network_coordinates)
            _extend_without_duplicate(
                expected_coordinates, ((site.longitude, site.latitude),)
            )
            if len(actual_coordinates) != len(expected_coordinates) or any(
                not _coordinates_close(actual, expected)
                for actual, expected in zip(
                    actual_coordinates, expected_coordinates, strict=False
                )
            ):
                add(
                    "route_geometry_does_not_match_edge_chain",
                    expected_coordinate_count=len(expected_coordinates),
                    actual_coordinate_count=len(actual_coordinates),
                )

            demand_node = node_by_id[route_nodes[0]]
            site_node = node_by_id[route_nodes[-1]]
            connector_checks = (
                (
                    "demand_connector_geometry_mismatch",
                    (cell.longitude, cell.latitude),
                    (demand_node.longitude, demand_node.latitude),
                    record.demand_connector_m,
                ),
                (
                    "site_connector_geometry_mismatch",
                    (site_node.longitude, site_node.latitude),
                    (site.longitude, site.latitude),
                    record.site_connector_m,
                ),
            )
            for kind, start, end, expected_m in connector_checks:
                if expected_m is None or not math.isfinite(expected_m):
                    continue
                approximate_m = _haversine_distance_m(start, end)
                tolerance_m = max(0.75, expected_m * 0.01)
                if not math.isclose(
                    approximate_m, expected_m, rel_tol=0, abs_tol=tolerance_m
                ):
                    add(
                        kind,
                        declared_m=expected_m,
                        geometry_approximate_m=round(approximate_m, 3),
                        tolerance_m=round(tolerance_m, 3),
                    )
    return errors


def _parse_line_coordinates(
    value: Any,
    context: str,
) -> tuple[tuple[float, float], ...]:
    if isinstance(value, Mapping):
        if value.get("type") != "LineString":
            raise ValueError(f"{context} must be a LineString")
        value = value.get("coordinates")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{context} has no coordinate sequence")
    coordinates: list[tuple[float, float]] = []
    for raw_point in value:
        if (
            not isinstance(raw_point, Sequence)
            or isinstance(raw_point, (str, bytes))
            or len(raw_point) < 2
        ):
            raise ValueError(f"{context} contains an invalid coordinate")
        longitude = float(raw_point[0])
        latitude = float(raw_point[1])
        _validate_coordinate(context, longitude, latitude)
        coordinates.append((longitude, latitude))
    if not coordinates:
        raise ValueError(f"{context} has an empty coordinate sequence")
    return tuple(coordinates)


def _extend_without_duplicate(
    target: list[tuple[float, float]],
    coordinates: Sequence[tuple[float, float]],
) -> None:
    for coordinate in coordinates:
        if not target or not _coordinates_close(target[-1], coordinate):
            target.append(coordinate)


def _coordinates_close(
    first: tuple[float, float], second: tuple[float, float]
) -> bool:
    return math.isclose(first[0], second[0], rel_tol=0, abs_tol=1e-7) and math.isclose(
        first[1], second[1], rel_tol=0, abs_tol=1e-7
    )


def _haversine_distance_m(
    first: tuple[float, float], second: tuple[float, float]
) -> float:
    longitude_1, latitude_1 = map(math.radians, first)
    longitude_2, latitude_2 = map(math.radians, second)
    delta_longitude = longitude_2 - longitude_1
    delta_latitude = latitude_2 - latitude_1
    haversine = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(latitude_1)
        * math.cos(latitude_2)
        * math.sin(delta_longitude / 2) ** 2
    )
    return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(haversine)))


def _is_distance_evidence_error(kind: str) -> bool:
    return kind in {
        "missing_distance_evidence",
        "walking_distance_exceeded",
        "assignment_distance_disagrees_with_matrix",
        "verification_graph_unreachable",
    } or kind.startswith(
        (
            "distance_evidence_",
            "distance_component_",
            "demand_connector_",
            "site_connector_",
            "network_distance_",
            "route_",
        )
    )


def _verified_shortest_path_length(
    graph: nx.MultiDiGraph | nx.MultiGraph,
    source: str | None,
    target: str | None,
    control: _CoverageControl | None,
) -> float:
    weight_calls = 0

    def controlled_weight(
        _source: str,
        _target: str,
        parallel_edges: Mapping[str, Mapping[str, Any]],
    ) -> float:
        nonlocal weight_calls
        if control is not None and weight_calls % 128 == 0:
            control.checkpoint("verification_graph_routes")
        weight_calls += 1
        return min(float(data["length_m"]) for data in parallel_edges.values())

    return float(
        nx.shortest_path_length(
            graph,
            source=source,
            target=target,
            weight=controlled_weight,
        )
    )


def _validate_coordinate(record_id: str, longitude: float, latitude: float) -> None:
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise ValueError(f"{record_id} has non-finite coordinates")
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError(f"{record_id} display coordinates are outside EPSG:4326 bounds")


def _validate_optional_distance(
    record_id: str, field_name: str, value: float | None
) -> None:
    if value is not None and (not math.isfinite(value) or value < 0):
        raise ValueError(f"{record_id} {field_name} must be finite and non-negative")


def _terminal_result(
    status: CoverageStatus,
    message: str,
    scenario: FrozenServiceCoverageScenario,
    started: float,
    events: Sequence[Mapping[str, Any]],
    **payload: Any,
) -> dict[str, Any]:
    elapsed_ms = round((time.monotonic() - started) * 1000, 2)
    return {
        "status": status,
        "message": message,
        "claim_scope": (
            "The result applies only to the frozen walking-distance evidence, included demand, "
            "reviewed sites, and explicit analytical capacity and policy assumptions. It is not "
            "a siting, funding, accessibility, or operating recommendation."
        ),
        "snapshot": {
            "scenario_id": scenario.scenario_id,
            "snapshot_id": scenario.snapshot_id,
            "network_snapshot_id": scenario.network_snapshot_id,
            "distance_metric": scenario.distance_metric,
        },
        "snapshot_id": scenario.snapshot_id,
        "timing": {"elapsed_ms": elapsed_ms},
        "solver_timing_ms": elapsed_ms,
        "iteration_count": len(events),
        "iterations": [copy.deepcopy(dict(item)) for item in events],
        **payload,
    }
