from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import networkx as nx
import pytest

from services.solver.scenario import AddressCluster, Candidate, Portal, Scenario


def synthetic_scenario(
    edge_specs: Sequence[tuple[str, str, str, str | None, bool]],
    *,
    candidate_costs: dict[str, int] | None = None,
    portals: dict[str, tuple[str, str]] | None = None,
    clusters: Sequence[tuple[str, str, Sequence[str]]] = (),
    scenario_id: str = "synthetic",
) -> Scenario:
    candidate_costs = candidate_costs or {}
    node_ids = sorted({node for _, u, v, _, _ in edge_specs for node in (u, v)})
    nodes = {
        node: {"id": node, "lon": 24.9 + index * 0.001, "lat": 60.19 + index * 0.001}
        for index, node in enumerate(node_ids)
    }
    by_candidate: dict[str, list[str]] = {}
    edges: dict[str, dict[str, Any]] = {}
    graph = nx.MultiDiGraph()
    graph.add_nodes_from((node_id, attributes) for node_id, attributes in nodes.items())
    for edge_id, u, v, candidate_id, protected in edge_specs:
        edge = {
            "id": edge_id,
            "physical_id": edge_id.removesuffix("-r"),
            "u": u,
            "v": v,
            "candidate_id": candidate_id,
            "protected": protected,
            "length_m": 100.0,
            "name": edge_id.split("-")[0].title() + " street",
            "geometry": [[nodes[u]["lon"], nodes[u]["lat"]], [nodes[v]["lon"], nodes[v]["lat"]]],
        }
        edges[edge_id] = edge
        graph.add_edge(u, v, key=edge_id, **edge)
        if candidate_id:
            by_candidate.setdefault(candidate_id, []).append(edge_id)
    candidates = {
        candidate_id: Candidate(
            candidate_id,
            tuple(sorted(edge_ids)),
            candidate_id.replace("_", " ").title(),
            candidate_costs.get(candidate_id, 100),
        )
        for candidate_id, edge_ids in sorted(by_candidate.items())
    }
    portal_defs = portals or {"west": ("West", "W"), "east": ("East", "E")}
    parsed_portals = {
        portal_id: Portal(
            portal_id, label, portal_id, (node,), (nodes[node]["lon"], nodes[node]["lat"])
        )
        for portal_id, (label, node) in portal_defs.items()
    }
    parsed_clusters = {
        cluster_id: AddressCluster(
            cluster_id,
            cluster_id.replace("_", " ").title(),
            node,
            tuple(allowed),
            (nodes[node]["lon"], nodes[node]["lat"]),
        )
        for cluster_id, node, allowed in clusters
    }
    portal_ids = list(parsed_portals)
    scenario = Scenario(
        id=scenario_id,
        metadata={"scenario_id": scenario_id, "snapshot_id": f"{scenario_id}-v1"},
        graph=graph,
        nodes=nodes,
        edges=edges,
        candidates=candidates,
        edge_to_candidate={
            edge_id: candidate_id
            for candidate_id, candidate_edges in by_candidate.items()
            for edge_id in candidate_edges
        },
        portals=parsed_portals,
        address_clusters=parsed_clusters,
        default_portal_pairs=[
            {"a": portal_ids[0], "b": portal_ids[1], "label": "Default crossing"}
        ],
    )
    scenario.validate()
    return scenario


def undirected(
    prefix: str, u: str, v: str, candidate: str | None = None, protected: bool = False
) -> list[tuple[str, str, str, str | None, bool]]:
    return [
        (prefix, u, v, candidate, protected),
        (f"{prefix}-r", v, u, candidate, protected),
    ]


@pytest.fixture
def one_cut_scenario() -> Scenario:
    return synthetic_scenario(
        [
            *undirected("west-a", "W", "A", "c1"),
            *undirected("a-east", "A", "E"),
        ],
        clusters=[("homes", "A", ["west", "east"])],
    )


@pytest.fixture
def two_cut_scenario() -> Scenario:
    return synthetic_scenario(
        [
            *undirected("west-a", "W", "A", "c1"),
            *undirected("a-east", "A", "E"),
            *undirected("west-b", "W", "B", "c2"),
            *undirected("b-east", "B", "E"),
        ]
    )
