from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOLVER_PATH = ROOT / "data" / "derived" / "helsinki-kallio-vallila" / "solver.json"
DEFAULT_BROWSER_PATH = ROOT / "data" / "derived" / "helsinki-kallio-vallila" / "scenario.json"


@dataclass(frozen=True)
class Candidate:
    id: str
    edge_ids: tuple[str, ...]
    street_name: str
    cost: int = 100
    access_penalty: int = 0
    point: tuple[float, float] | None = None


@dataclass(frozen=True)
class Portal:
    id: str
    label: str
    direction: str
    node_ids: tuple[str, ...]
    point: tuple[float, float] | None = None


@dataclass(frozen=True)
class AddressCluster:
    id: str
    label: str
    node_id: str
    allowed_portal_ids: tuple[str, ...]
    point: tuple[float, float] | None = None
    building_ids: tuple[str, ...] = ()


@dataclass
class Scenario:
    id: str
    metadata: dict[str, Any]
    graph: nx.MultiDiGraph
    nodes: dict[str, dict[str, Any]]
    edges: dict[str, dict[str, Any]]
    candidates: dict[str, Candidate]
    edge_to_candidate: dict[str, str]
    portals: dict[str, Portal]
    address_clusters: dict[str, AddressCluster]
    default_portal_pairs: list[dict[str, str]]
    browser_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def snapshot_id(self) -> str:
        return str(self.metadata.get("snapshot_id", self.id))

    def validate(self) -> None:
        errors: list[str] = []
        if not self.nodes or not self.edges:
            errors.append("scenario graph is empty")
        for edge_id, edge in self.edges.items():
            if edge["u"] not in self.nodes or edge["v"] not in self.nodes:
                errors.append(f"edge {edge_id} references a missing node")
            candidate_id = edge.get("candidate_id")
            if candidate_id and candidate_id not in self.candidates:
                errors.append(f"edge {edge_id} references missing candidate {candidate_id}")
            if edge.get("protected") and candidate_id:
                errors.append(f"protected edge {edge_id} is incorrectly selectable")
        for candidate in self.candidates.values():
            if not candidate.edge_ids:
                errors.append(f"candidate {candidate.id} has no directed edges")
            for edge_id in candidate.edge_ids:
                if edge_id not in self.edges:
                    errors.append(f"candidate {candidate.id} references missing edge {edge_id}")
                elif self.edges[edge_id].get("protected"):
                    errors.append(f"candidate {candidate.id} includes protected edge {edge_id}")
        for portal in self.portals.values():
            if not portal.node_ids or any(node not in self.nodes for node in portal.node_ids):
                errors.append(f"portal {portal.id} has no valid graph node")
        for cluster in self.address_clusters.values():
            if cluster.node_id not in self.nodes:
                errors.append(f"address cluster {cluster.id} references a missing node")
            missing = set(cluster.allowed_portal_ids) - set(self.portals)
            if missing:
                errors.append(
                    f"address cluster {cluster.id} references missing portals {sorted(missing)}"
                )
        for pair in self.default_portal_pairs:
            if pair["a"] not in self.portals or pair["b"] not in self.portals:
                errors.append(f"default portal pair references a missing portal: {pair}")
        if errors:
            raise ValueError("Invalid scenario:\n- " + "\n- ".join(errors))

    def public_payload(self) -> dict[str, Any]:
        payload = dict(self.browser_payload)
        metadata = self.metadata
        payload.setdefault("id", self.id)
        payload.setdefault("scenario_id", self.id)
        payload.setdefault("name", metadata.get("name", "Kallio–Vallila, Helsinki"))
        payload.setdefault(
            "description", metadata.get("description", "A frozen OpenStreetMap network")
        )
        for key in (
            "snapshot_id",
            "snapshot_timestamp",
            "acquired_at",
            "bbox",
            "center",
            "analysis_crs",
            "license",
            "attribution",
            "source_url",
            "source_query",
        ):
            if key in metadata:
                payload.setdefault(key, metadata[key])
        payload.setdefault("metadata", metadata)
        payload.setdefault(
            "portals",
            [
                {
                    "id": portal.id,
                    "label": portal.label,
                    "direction": portal.direction,
                    "node_ids": list(portal.node_ids),
                    "point": list(portal.point) if portal.point else None,
                }
                for portal in self.portals.values()
            ],
        )
        payload.setdefault(
            "candidates",
            [
                {
                    "id": candidate.id,
                    "edge_ids": list(candidate.edge_ids),
                    "name": candidate.street_name,
                    "street_name": candidate.street_name,
                    "point": list(candidate.point) if candidate.point else None,
                    "cost": candidate.cost / 100,
                    "eligible": True,
                }
                for candidate in self.candidates.values()
            ],
        )
        payload.setdefault(
            "address_clusters",
            [
                {
                    "id": cluster.id,
                    "label": cluster.label,
                    "node_id": cluster.node_id,
                    "point": list(cluster.point) if cluster.point else None,
                    "allowed_portal_ids": list(cluster.allowed_portal_ids),
                    "building_ids": list(cluster.building_ids),
                }
                for cluster in self.address_clusters.values()
            ],
        )
        payload.setdefault("default_portal_pairs", self.default_portal_pairs)
        payload.setdefault("default_budget", 4)
        payload.setdefault(
            "assumptions",
            {
                "private_car": (
                    "Selected modal filters remove their directed street edges from "
                    "the private-car graph."
                ),
                "local_access": (
                    "Every included address cluster retains a directed car route to "
                    "at least one permitted portal."
                ),
                "walking_cycling": (
                    "Filters do not remove edges from walking or cycling networks."
                ),
                "emergency": (
                    "The default assumes a removable or otherwise emergency-permeable "
                    "filter; it is not a claim about a literal fixed planter."
                ),
            },
        )
        payload.setdefault(
            "stats",
            {
                "nodes": len(self.nodes),
                "directed_edges": len(self.edges),
                "candidate_interventions": len(self.candidates),
                "portals": len(self.portals),
                "address_clusters": len(self.address_clusters),
                "protected_edges": sum(bool(edge.get("protected")) for edge in self.edges.values()),
            },
        )
        return payload


def _point(value: Any) -> tuple[float, float] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        if value.get("type") == "Point":
            value = value.get("coordinates")
        else:
            return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return (float(value[0]), float(value[1]))
    return None


def _normalise_pair(pair: Any) -> dict[str, str]:
    if isinstance(pair, (list, tuple)):
        return {"a": str(pair[0]), "b": str(pair[1]), "label": f"{pair[0]} ↔ {pair[1]}"}
    return {
        "a": str(pair["a"]),
        "b": str(pair["b"]),
        "label": str(pair.get("label") or f"{pair['a']} ↔ {pair['b']}"),
    }


def load_scenario(
    solver_path: str | Path = DEFAULT_SOLVER_PATH,
    browser_path: str | Path | None = DEFAULT_BROWSER_PATH,
) -> Scenario:
    solver_path = Path(solver_path)
    with solver_path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    metadata = dict(raw.get("metadata", {}))
    scenario_id = str(
        raw.get("scenario_id") or metadata.get("scenario_id") or solver_path.parent.name
    )
    raw_nodes = raw.get("nodes", [])
    if isinstance(raw_nodes, dict):
        raw_nodes = [{"id": key, **value} for key, value in raw_nodes.items()]
    nodes = {str(node["id"]): {**node, "id": str(node["id"])} for node in raw_nodes}

    raw_candidates = raw.get("candidates", [])
    if isinstance(raw_candidates, dict):
        raw_candidates = [{"id": key, **value} for key, value in raw_candidates.items()]
    candidates: dict[str, Candidate] = {}
    for item in sorted(raw_candidates, key=lambda value: str(value["id"])):
        candidate_id = str(item["id"])
        cost_value = item.get("cost", 1)
        cost = int(round(float(cost_value) * 100)) if float(cost_value) < 50 else int(cost_value)
        candidates[candidate_id] = Candidate(
            id=candidate_id,
            edge_ids=tuple(str(edge_id) for edge_id in item.get("edge_ids", [])),
            street_name=str(item.get("street_name") or item.get("name") or "Unnamed local street"),
            cost=max(1, cost),
            access_penalty=int(item.get("access_penalty", 0)),
            point=_point(item.get("display_point") or item.get("point")),
        )

    raw_edges = raw.get("edges", [])
    if isinstance(raw_edges, dict):
        raw_edges = [{"id": key, **value} for key, value in raw_edges.items()]
    edges: dict[str, dict[str, Any]] = {}
    edge_to_candidate: dict[str, str] = {}
    for candidate in candidates.values():
        for edge_id in candidate.edge_ids:
            edge_to_candidate[edge_id] = candidate.id
    graph = nx.MultiDiGraph()
    for node_id, node in sorted(nodes.items()):
        graph.add_node(node_id, **node)
    for item in sorted(raw_edges, key=lambda value: str(value["id"])):
        edge = dict(item)
        edge_id = str(edge["id"])
        edge["id"] = edge_id
        edge["u"] = str(edge["u"])
        edge["v"] = str(edge["v"])
        candidate_id = edge.get("candidate_id") or edge_to_candidate.get(edge_id)
        if candidate_id and str(candidate_id) in candidates:
            candidate_id = str(candidate_id)
            edge_to_candidate[edge_id] = candidate_id
        else:
            candidate_id = None
        edge["candidate_id"] = candidate_id
        edge["protected"] = bool(edge.get("protected", False))
        edge["length_m"] = float(edge.get("length_m", 1.0))
        edges[edge_id] = edge
        graph.add_edge(edge["u"], edge["v"], key=edge_id, **edge)

    raw_portals = raw.get("portals", [])
    if isinstance(raw_portals, dict):
        raw_portals = [{"id": key, **value} for key, value in raw_portals.items()]
    portals = {
        str(item["id"]): Portal(
            id=str(item["id"]),
            label=str(item.get("label") or item["id"]),
            direction=str(item.get("direction") or item.get("side") or "boundary"),
            node_ids=tuple(
                str(node)
                for node in item.get("node_ids", [item.get("node_id")])
                if node is not None
            ),
            point=_point(item.get("display_point") or item.get("point")),
        )
        for item in sorted(raw_portals, key=lambda value: str(value["id"]))
    }

    raw_clusters = raw.get("address_clusters", [])
    if isinstance(raw_clusters, dict):
        raw_clusters = [{"id": key, **value} for key, value in raw_clusters.items()]
    clusters = {
        str(item["id"]): AddressCluster(
            id=str(item["id"]),
            label=str(item.get("label") or item["id"]),
            node_id=str(item["node_id"]),
            allowed_portal_ids=tuple(
                str(portal) for portal in item.get("allowed_portal_ids", portals)
            ),
            point=_point(item.get("display_point") or item.get("point")),
            building_ids=tuple(str(value) for value in item.get("building_ids", [])),
        )
        for item in sorted(raw_clusters, key=lambda value: str(value["id"]))
    }
    defaults = raw.get("defaults", {})
    pairs = [
        _normalise_pair(pair)
        for pair in defaults.get("portal_pairs", raw.get("default_portal_pairs", []))
    ]

    browser_payload: dict[str, Any] = {}
    if browser_path is not None and Path(browser_path).exists():
        with Path(browser_path).open(encoding="utf-8") as handle:
            browser_payload = json.load(handle)

    scenario = Scenario(
        id=scenario_id,
        metadata=metadata,
        graph=graph,
        nodes=nodes,
        edges=edges,
        candidates=candidates,
        edge_to_candidate=edge_to_candidate,
        portals=portals,
        address_clusters=clusters,
        default_portal_pairs=pairs,
        browser_payload=browser_payload,
    )
    scenario.validate()
    return scenario


def distance_metres(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float:
    """Small-area equirectangular distance for objective spacing; input is lon/lat."""
    if a is None or b is None:
        return math.inf
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    x = (lon2 - lon1) * math.cos((lat1 + lat2) / 2)
    y = lat2 - lat1
    return math.hypot(x, y) * 6_371_000
