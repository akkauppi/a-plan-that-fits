#!/usr/bin/env python3
"""Build the frozen Otaniemi–Tapiola service-coverage experiment.

The default path is offline: it validates archived HSY and Service Map source
responses, joins them to the already frozen OSM walking graph, and writes a
deterministic browser/solver artifact. ``--refresh`` is deliberately explicit.
It republishes the bounded official responses before rebuilding the snapshot.

This pipeline does not infer real facility capacity. Every capacity value in the
output is copied from the versioned recipe and marked as an analytical declaration.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import networkx as nx
from pyproj import Transformer
from shapely.geometry import LineString, Point, mapping, shape

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECIPE = ROOT / "data" / "recipes" / "service-coverage-otaniemi-tapiola-v1.json"
DEFAULT_SOURCE = (
    ROOT / "data" / "source" / "service-coverage" / "otaniemi-tapiola-v1"
)
DEFAULT_OUTPUT = ROOT / "data" / "derived" / "service-coverage-otaniemi-tapiola-v1"

HSY_WFS_URL = "https://kartta.hsy.fi/geoserver/wfs"
SERVICE_MAP_UNIT_URL = "https://api.hel.fi/servicemap/v2/unit/"
USER_AGENT = "GeospatialConstraintLab/0.1 (+offline evidence builder)"
SNAPSHOT_ID_PLACEHOLDER = "pending"
PUBLISHED_ARTIFACT_NAMES = ("scenario.json", "solver.json", "browser.json")
SNAP_CONNECTOR_METHOD = "straight_line_projected_euclidean"


class BuildError(RuntimeError):
    """Raised when frozen inputs or derived references are inconsistent."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise BuildError(f"expected a JSON object in {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical_bytes(value) + b"\n")


def localized(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    for language in ("en", "fi", "sv"):
        text = value.get(language)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


def request_bytes(url: str, *, timeout_s: int = 120) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.read()
    except OSError as error:
        raise BuildError(f"source refresh failed for {url}: {error}") from error


def refresh_sources(recipe: dict[str, Any], source_dir: Path) -> None:
    """Refresh the bounded official archives selected by the recipe.

    Refresh intentionally uses fixed endpoints, fields and a bounding box. The
    Service Map candidates are retrieved by exact unit ID after analyst review.
    This avoids silently treating a broad service classification as physical-host
    eligibility and makes each frozen source request independently reproducible.
    """

    source_dir.mkdir(parents=True, exist_ok=True)
    hsy_dir = source_dir / "hsy"
    service_dir = source_dir / "servicemap"
    hsy_dir.mkdir(parents=True, exist_ok=True)
    service_dir.mkdir(parents=True, exist_ok=True)

    hsy_query = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "1.0.0",
            "request": "GetFeature",
            "typeName": recipe["population"]["layer"],
            "outputFormat": "application/json",
            "srsName": "EPSG:4326",
            "bbox": "24.79,60.16,24.86,60.21,EPSG:4326",
        }
    )
    capabilities_query = urllib.parse.urlencode(
        {"service": "WFS", "version": "1.0.0", "request": "GetCapabilities"}
    )
    population_path = hsy_dir / "population-grid-2025.geojson"
    population_path.write_bytes(request_bytes(f"{HSY_WFS_URL}?{hsy_query}"))
    (hsy_dir / "wfs-capabilities.xml").write_bytes(
        request_bytes(f"{HSY_WFS_URL}?{capabilities_query}")
    )

    for unit_id in recipe["candidate_sites"]["selected_unit_ids"]:
        target = service_dir / f"unit-{int(unit_id)}.json"
        target.write_bytes(request_bytes(f"{SERVICE_MAP_UNIT_URL}{int(unit_id)}/?format=json"))

    manifest_path = source_dir / "source-manifest.json"
    manifest = read_json(manifest_path)
    refreshed_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    population_response = read_json(population_path)
    response_timestamp = str(population_response.get("timeStamp") or refreshed_at)
    update_dates = sorted(
        {
            str(feature.get("properties", {}).get("paivitys_pvm"))
            for feature in population_response.get("features", [])
            if feature.get("properties", {}).get("paivitys_pvm")
        }
    )
    manifest["acquired_at"] = refreshed_at
    manifest["acquisition_window_utc"] = [response_timestamp, refreshed_at]
    by_name = {
        Path(artifact["path"]).name: artifact for artifact in manifest.get("artifacts", [])
    }
    refreshed_paths = [
        population_path,
        hsy_dir / "wfs-capabilities.xml",
        *[
            service_dir / f"unit-{int(unit_id)}.json"
            for unit_id in recipe["candidate_sites"]["selected_unit_ids"]
        ],
    ]
    for path in refreshed_paths:
        artifact = by_name.get(path.name)
        if artifact is None:
            raise BuildError(f"source manifest has no entry for refreshed archive {path.name}")
        artifact["byte_size"] = path.stat().st_size
        artifact["sha256"] = sha256_file(path)
        artifact["acquired_at"] = refreshed_at
        if path == population_path:
            artifact["response_timestamp"] = response_timestamp
            artifact["data_update_timestamp"] = (
                update_dates[0] if len(update_dates) == 1 else update_dates
            )
    write_json(manifest_path, manifest)


def validate_sources(recipe: dict[str, Any], manifest: dict[str, Any]) -> None:
    for artifact in manifest.get("artifacts", []):
        path = ROOT / artifact["path"]
        if not path.is_file():
            raise BuildError(f"missing frozen source archive: {path}")
        actual = sha256_file(path)
        if actual != artifact["sha256"]:
            raise BuildError(
                f"source checksum mismatch for {path}: expected {artifact['sha256']}, got {actual}"
            )

    population = read_json(ROOT / recipe["population"]["archive"])
    if population.get("type") != "FeatureCollection":
        raise BuildError("HSY population archive is not a GeoJSON FeatureCollection")
    if int(population.get("numberReturned", -1)) != len(population.get("features", [])):
        raise BuildError("HSY response count does not match its feature array")


def build_walking_graph(base: dict[str, Any]) -> tuple[nx.DiGraph, dict[str, dict[str, Any]]]:
    nodes = {node["id"]: node for node in base.get("nodes", [])}
    graph = nx.DiGraph()
    for node_id, node in nodes.items():
        graph.add_node(node_id, node=node)

    for edge in sorted(base.get("edges", []), key=lambda candidate: candidate["id"]):
        if not edge.get("permissions", {}).get("walking", False):
            continue
        source = edge["from"]
        target = edge["to"]
        length = float(edge["length_m"])
        current = graph.get_edge_data(source, target)
        if current is None or (length, edge["id"]) < (current["weight"], current["edge"]["id"]):
            graph.add_edge(source, target, weight=length, edge=edge)

    graph.remove_nodes_from(list(nx.isolates(graph)))
    components = list(nx.weakly_connected_components(graph))
    largest = min(components, key=lambda component: (-len(component), min(component)))
    graph = graph.subgraph(largest).copy()
    nodes = {node_id: nodes[node_id] for node_id in graph.nodes}
    if not graph:
        raise BuildError("the frozen base network contains no walkable graph")
    return graph, nodes


def nearest_node(
    point: Point,
    nodes: dict[str, dict[str, Any]],
    transformer: Transformer,
) -> tuple[str, float]:
    x, y = transformer.transform(point.x, point.y)
    node_id, distance_sq = min(
        (
            (node_id, (float(node["x"]) - x) ** 2 + (float(node["y"]) - y) ** 2)
            for node_id, node in nodes.items()
        ),
        key=lambda item: (item[1], item[0]),
    )
    return node_id, math.sqrt(distance_sq)


def district_for(longitude: float, recipe: dict[str, Any]) -> tuple[str, str]:
    for district in recipe["analysis_districts"]:
        if longitude <= float(district["maximum_longitude"]):
            return district["id"], district["label"]
    raise BuildError(f"no analysis district covers longitude {longitude}")


def build_demand(
    recipe: dict[str, Any],
    study_area: Any,
    graph_nodes: dict[str, dict[str, Any]],
    transformer: Transformer,
) -> list[dict[str, Any]]:
    archive = read_json(ROOT / recipe["population"]["archive"])
    population_field = recipe["population"]["population_field"]
    stable_id_field = recipe["population"]["stable_id_field"]
    max_snap = float(recipe["population"]["max_snap_distance_m"])
    demand: list[dict[str, Any]] = []

    for feature in archive["features"]:
        geometry = shape(feature["geometry"])
        point = geometry.representative_point()
        if not study_area.covers(point):
            continue
        population = int(feature["properties"].get(population_field, 0))
        if population <= 0:
            continue
        grid_id = feature["properties"].get(stable_id_field)
        if grid_id is None:
            raise BuildError("HSY population feature is missing its stable grid index")
        node_id, snap_distance = nearest_node(point, graph_nodes, transformer)
        if snap_distance > max_snap:
            raise BuildError(
                f"population grid {grid_id} is {snap_distance:.1f} m from the walking graph"
            )
        district_id, district_label = district_for(point.x, recipe)
        demand_id = f"hsy-grid-{int(grid_id)}"
        coordinates = [round(point.x, 7), round(point.y, 7)]
        polygon = mapping(geometry)
        demand.append(
            {
                "id": demand_id,
                "label": f"Population cell {int(grid_id)}",
                "population": population,
                "district_id": district_id,
                "district_label": district_label,
                "district": district_label,
                "point": coordinates,
                "node_id": node_id,
                "snap_distance_m": round(snap_distance, 3),
                "source_grid_id": int(grid_id),
                "feature": {
                    "type": "Feature",
                    "id": demand_id,
                    "properties": {
                        "id": demand_id,
                        "population": population,
                        "district_id": district_id,
                    },
                    "geometry": polygon,
                },
            }
        )
    demand.sort(key=lambda item: item["id"])
    if not demand:
        raise BuildError("the selected study area contains no published HSY population cells")
    return demand


def load_candidate_units(recipe: dict[str, Any]) -> dict[int, dict[str, Any]]:
    config = recipe["candidate_sites"]
    units: dict[int, dict[str, Any]] = {}
    for raw_id in config["selected_unit_ids"]:
        unit_id = int(raw_id)
        pattern = config["individual_archive_pattern"]
        unit = read_json(ROOT / pattern.format(unit_id=unit_id))
        if int(unit.get("id", -1)) != unit_id:
            raise BuildError(f"individual Service Map archive does not describe unit {unit_id}")
        units[unit_id] = unit
    return units


def site_category(unit: dict[str, Any]) -> str:
    service_ids = {int(value) for value in unit.get("services", [])}
    if 813 in service_ids:
        return "library"
    if 468 in service_ids:
        return "youth_centre"
    if 400 in service_ids:
        return "indoor_sports"
    if service_ids.intersection({601, 602, 661, 662, 816}):
        return "education"
    return "reviewed_public_facility"


def build_sites(
    recipe: dict[str, Any],
    study_area: Any,
    graph_nodes: dict[str, dict[str, Any]],
    transformer: Transformer,
) -> list[dict[str, Any]]:
    config = recipe["candidate_sites"]
    units = load_candidate_units(recipe)
    max_snap = float(config["max_snap_distance_m"])
    capacity = int(config["capacity"])
    sites: list[dict[str, Any]] = []

    for unit_id in sorted(int(value) for value in config["selected_unit_ids"]):
        unit = units.get(unit_id)
        if unit is None:
            raise BuildError(f"selected Service Map unit {unit_id} is absent from the archives")
        location = unit.get("location")
        if not isinstance(location, dict) or location.get("type") != "Point":
            raise BuildError(f"Service Map unit {unit_id} has no usable Point location")
        point = shape(location)
        if not study_area.covers(point):
            raise BuildError(f"selected Service Map unit {unit_id} lies outside the study area")
        node_id, snap_distance = nearest_node(point, graph_nodes, transformer)
        if snap_distance > max_snap:
            raise BuildError(
                f"Service Map unit {unit_id} is {snap_distance:.1f} m from the walking graph"
            )
        district_id, district_label = district_for(point.x, recipe)
        site_id = f"servicemap-unit-{unit_id}"
        label = localized(unit.get("name")) or f"Service Map unit {unit_id}"
        source_services = sorted({int(value) for value in unit.get("services", [])})
        coordinates = [round(point.x, 7), round(point.y, 7)]
        sites.append(
            {
                "id": site_id,
                "label": label,
                "category": site_category(unit),
                "capacity": capacity,
                "capacity_default": capacity,
                "capacity_status": "declared",
                "capacity_basis": "analyst_declared_not_source_fact",
                "capacity_note": (
                    "5,000 people is a deliberately declared assignment bound for this "
                    "demonstrator, not an observed venue capacity or throughput."
                ),
                "eligible": True,
                "district_id": district_id,
                "district_label": district_label,
                "point": coordinates,
                "node_id": node_id,
                "snap_distance_m": round(snap_distance, 3),
                "source": {
                    "provider": "Helsinki metropolitan area Service Map",
                    "unit_id": unit_id,
                    "service_ids": source_services,
                    "municipality": unit.get("municipality"),
                    "data_source": unit.get("data_source"),
                    "last_modified_time": unit.get("last_modified_time"),
                    "displayed_owner": localized(unit.get("displayed_service_owner")),
                },
                "feature": {
                    "type": "Feature",
                    "id": site_id,
                    "properties": {
                        "id": site_id,
                        "label": label,
                        "category": site_category(unit),
                        "capacity_default": capacity,
                        "capacity_status": "declared",
                    },
                    "geometry": {"type": "Point", "coordinates": coordinates},
                },
            }
        )
    return sites


def route_coordinates(
    graph: nx.DiGraph,
    route_nodes: list[str],
) -> tuple[list[list[float]], list[str]]:
    coordinates: list[list[float]] = []
    edge_ids: list[str] = []
    for source, target in zip(route_nodes, route_nodes[1:], strict=False):
        edge = graph[source][target]["edge"]
        segment = [[float(x), float(y)] for x, y in edge["geometry"]]
        if not coordinates:
            coordinates.extend(segment)
        elif coordinates[-1] == segment[0]:
            coordinates.extend(segment[1:])
        elif coordinates[-1] == segment[-1]:
            coordinates.extend(reversed(segment[:-1]))
        else:
            raise BuildError(f"route geometry is discontinuous at edge {edge['id']}")
        edge_ids.append(edge["id"])
    if len(route_nodes) == 1:
        node = graph.nodes[route_nodes[0]]["node"]
        coordinate = [float(node["longitude"]), float(node["latitude"])]
        coordinates = [coordinate, coordinate]
    return coordinates, edge_ids


def route_coordinates_with_connectors(
    demand_point: list[float],
    network_coordinates: list[list[float]],
    site_point: list[float],
) -> list[list[float]]:
    """Join source points to their snapped network route for map display.

    The first and last legs are straight lines from each source point to its
    deterministic nearest graph node. They are analytical snap approximations,
    not observed paths or evidence of a walkable entrance.
    """

    coordinates: list[list[float]] = []
    for raw_coordinate in [demand_point, *network_coordinates, site_point]:
        coordinate = [float(raw_coordinate[0]), float(raw_coordinate[1])]
        if not coordinates or coordinates[-1] != coordinate:
            coordinates.append(coordinate)
    if len(coordinates) == 1:
        coordinates.append(coordinates[0].copy())
    return coordinates


def build_distances(
    graph: nx.DiGraph,
    demand: list[dict[str, Any]],
    sites: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    distances: list[dict[str, Any]] = []
    route_edge_ids: set[str] = set()
    for item in demand:
        path_lengths, paths = nx.single_source_dijkstra(
            graph, item["node_id"], weight="weight"
        )
        for site in sites:
            target = site["node_id"]
            if target not in path_lengths:
                raise BuildError(f"no walking route from {item['id']} to {site['id']}")
            route_nodes = paths[target]
            network_coordinates, edge_ids = route_coordinates(graph, route_nodes)
            coordinates = route_coordinates_with_connectors(
                item["point"], network_coordinates, site["point"]
            )
            route_edge_ids.update(edge_ids)
            demand_connector = float(item["snap_distance_m"])
            network_distance = round(float(path_lengths[target]), 3)
            site_connector = float(site["snap_distance_m"])
            distance = round(demand_connector + network_distance + site_connector, 3)
            distances.append(
                {
                    "demand_id": item["id"],
                    "site_id": site["id"],
                    "distance_m": distance,
                    "demand_connector_m": demand_connector,
                    "network_distance_m": network_distance,
                    "site_connector_m": site_connector,
                    "connector_method": SNAP_CONNECTOR_METHOD,
                    "route_node_ids": route_nodes,
                    "route_edge_ids": edge_ids,
                    "route": {
                        "type": "Feature",
                        "properties": {
                            "demand_id": item["id"],
                            "site_id": site["id"],
                            "distance_m": distance,
                            "demand_connector_m": demand_connector,
                            "network_distance_m": network_distance,
                            "site_connector_m": site_connector,
                            "connector_method": SNAP_CONNECTOR_METHOD,
                        },
                        "geometry": {"type": "LineString", "coordinates": coordinates},
                    },
                }
            )
    distances.sort(key=lambda item: (item["demand_id"], item["site_id"]))
    return distances, route_edge_ids


def compact_solver_network(
    graph: nx.DiGraph,
    graph_nodes: dict[str, dict[str, Any]],
    route_edge_ids: set[str],
    required_node_ids: set[str],
) -> dict[str, Any]:
    edges: list[dict[str, Any]] = []
    used_nodes = set(required_node_ids)
    for source, target, data in graph.edges(data=True):
        edge = data["edge"]
        if edge["id"] not in route_edge_ids:
            continue
        used_nodes.update((source, target))
        edges.append(
            {
                "id": edge["id"],
                "from": source,
                "to": target,
                "length_m": round(float(edge["length_m"]), 3),
                "geometry": edge["geometry"],
            }
        )
    edges.sort(key=lambda item: item["id"])
    nodes = [
        {
            "id": node_id,
            "point": [
                float(graph_nodes[node_id]["longitude"]),
                float(graph_nodes[node_id]["latitude"]),
            ],
            "x": float(graph_nodes[node_id]["x"]),
            "y": float(graph_nodes[node_id]["y"]),
        }
        for node_id in sorted(used_nodes)
    ]
    return {"directed": True, "nodes": nodes, "edges": edges}


def browser_network(
    graph: nx.DiGraph,
    study_area: Any,
) -> dict[str, Any]:
    physical: dict[tuple[Any, ...], dict[str, Any]] = {}
    for _source, _target, data in graph.edges(data=True):
        edge = data["edge"]
        geometry = LineString(edge["geometry"])
        if not geometry.intersects(study_area):
            continue
        source = edge.get("source", {})
        key = (
            source.get("way_id"),
            source.get("segment_index"),
            source.get("part_index"),
        )
        current = physical.get(key)
        if current is None or edge["id"] < current["id"]:
            physical[key] = edge
    features = []
    for edge in sorted(physical.values(), key=lambda item: item["id"]):
        features.append(
            {
                "type": "Feature",
                "id": edge["id"],
                "properties": {
                    "id": edge["id"],
                    "name": edge.get("name"),
                    "highway": edge.get("highway"),
                    "length_m": round(float(edge["length_m"]), 3),
                },
                "geometry": {"type": "LineString", "coordinates": edge["geometry"]},
            }
        )
    return {"type": "FeatureCollection", "features": features}


def clean_solver_demand(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in (
            "id",
            "label",
            "population",
            "district_id",
            "point",
            "node_id",
            "snap_distance_m",
        )
    }


def clean_solver_site(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in (
            "id",
            "label",
            "capacity",
            "point",
            "eligible",
            "district_id",
            "node_id",
            "snap_distance_m",
        )
    }


def normalized_snapshot_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    """Return the exact content-fingerprint form of a scenario artifact.

    The published snapshot identifier occurs at the top level and in both consumer
    payloads. Replacing all three occurrences avoids a self-referential digest while
    leaving every other byte of semantic content, including attribution, bound to
    the identifier.
    """

    normalized = copy.deepcopy(artifact)
    try:
        normalized["snapshot_id"] = SNAPSHOT_ID_PLACEHOLDER
        normalized["solver"]["snapshot_id"] = SNAPSHOT_ID_PLACEHOLDER
        normalized["browser"]["snapshot_id"] = SNAPSHOT_ID_PLACEHOLDER
    except (KeyError, TypeError) as error:
        raise BuildError("artifact is missing a required snapshot identifier") from error
    return normalized


def computed_snapshot_id(artifact: dict[str, Any]) -> str:
    fingerprint = normalized_snapshot_artifact(artifact)
    return f"coverage-{sha256_bytes(canonical_bytes(fingerprint))[:24]}"


def build_snapshot(
    recipe: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    base_path = ROOT / recipe["base_network"]["path"]
    base = read_json(base_path)
    if base.get("snapshot_id") != recipe["base_network"]["snapshot_id"]:
        raise BuildError("frozen OSM network snapshot does not match the recipe")
    graph, graph_nodes = build_walking_graph(base)
    study_area = shape(recipe["study_area"])
    if not study_area.is_valid:
        raise BuildError("study-area polygon is invalid")
    transformer = Transformer.from_crs("EPSG:4326", recipe["analysis_crs"], always_xy=True)
    demand = build_demand(recipe, study_area, graph_nodes, transformer)
    sites = build_sites(recipe, study_area, graph_nodes, transformer)
    distances, route_edge_ids = build_distances(graph, demand, sites)
    solver_network = compact_solver_network(
        graph,
        graph_nodes,
        route_edge_ids,
        {item["node_id"] for item in [*demand, *sites]},
    )
    display_network = browser_network(graph, study_area)

    min_x, min_y, max_x, max_y = study_area.bounds
    center = [round((min_x + max_x) / 2, 7), round((min_y + max_y) / 2, 7)]
    source_timestamp = str(manifest["acquired_at"])
    boundary = {
        "type": "Feature",
        "properties": {"id": "service-coverage-study-boundary"},
        "geometry": mapping(study_area),
    }
    methodology = {
        "question": (
            "Which reviewed sites should host a hypothetical temporary neighbourhood-support "
            "service, and which published population cells should each site serve?"
        ),
        "distance": (
            "Total analytical distance is the population-cell representative's straight snap "
            "connector, plus shortest-path length on the frozen OSM walking graph, plus the "
            "site's straight snap connector. Connector segments are projected Euclidean "
            "approximations, not observed walkable entrances. The total is not a travel-time or "
            "accessibility model. Routes may use the archived context buffer outside the "
            "displayed study boundary."
        ),
        "capacity": recipe["candidate_sites"]["eligibility_assumption"],
        "demand": (
            "Each published HSY 250 m population cell is represented at its interior point and "
            "assigned as an indivisible cell in this first slice. Suppressed residents are not "
            "estimated or redistributed."
        ),
        "districts": (
            "District IDs are three transparent longitude bands made for this experiment; they "
            "are not official neighbourhood or administrative boundaries."
        ),
        "proof_scope": (
            "A verified result proves only that the encoded assignment, distance, capacity, "
            "eligibility, district, and budget rules hold for this frozen graph and evidence."
        ),
    }
    attribution = [
        {
            "label": "Population grid: Helsinki Region Environmental Services HSY",
            "licence": "Creative Commons Attribution 4.0",
            "licence_url": "https://creativecommons.org/licenses/by/4.0/",
            "url": "https://hri.fi/data/en/dataset/vaestotietoruudukko",
            "modifications": (
                "Published cells are selected by representative point and snapped to the "
                "analytical walking graph; published population totals are retained unchanged."
            ),
        },
        {
            "label": "Candidate units: Helsinki metropolitan area Service Map",
            "licence": "Creative Commons Attribution 4.0",
            "licence_url": "https://creativecommons.org/licenses/by/4.0/",
            "url": (
                "https://hri.fi/data/en/dataset/"
                "paakaupunkiseudun-palvelukartan-rest-rajapinta"
            ),
            "modifications": (
                "Ten reviewed source units are snapped to the analytical walking graph; the "
                "hypothetical service and declared capacity are separate model assumptions."
            ),
        },
        {
            "label": "Walking network: © OpenStreetMap contributors",
            "licence": "Open Data Commons Open Database License 1.0",
            "licence_url": "https://opendatacommons.org/licenses/odbl/1-0/",
            "url": "https://www.openstreetmap.org/copyright",
            "modifications": (
                "Walking-permitted edges are extracted from the frozen network and used to "
                "derive shortest-path distances and display routes."
            ),
        },
    ]

    solver = {
        "scenario_id": recipe["scenario_id"],
        "snapshot_id": SNAPSHOT_ID_PLACEHOLDER,
        "distance_metric": "walking_network_m",
        "crs": recipe["analysis_crs"],
        "network_snapshot_id": recipe["base_network"]["snapshot_id"],
        "demand": [clean_solver_demand(item) for item in demand],
        "sites": [clean_solver_site(item) for item in sites],
        "distances": distances,
        "network": solver_network,
        "defaults": recipe["defaults"],
        "assumptions": {
            "capacity_status": "analyst_declared_not_source_fact",
            "candidate_eligibility": recipe["candidate_sites"]["eligibility_assumption"],
            "population_privacy": recipe["population"]["privacy_rule"],
            "snap_connectors": (
                "Each source point is joined to its nearest network node by a straight projected "
                "Euclidean connector. The connector is an analytical approximation, not an "
                "observed walking link or verified entrance."
            ),
        },
    }
    browser = {
        "id": recipe["scenario_id"],
        "name": recipe["name"],
        "description": recipe["description"],
        "snapshot_id": SNAPSHOT_ID_PLACEHOLDER,
        "snapshot_timestamp": source_timestamp,
        "bbox": [min_x, min_y, max_x, max_y],
        "center": center,
        "boundary": boundary,
        "network": display_network,
        "buildings": {"type": "FeatureCollection", "features": []},
        "population_cells": demand,
        "candidate_sites": sites,
        "defaults": recipe["defaults"],
        "methodology": (
            "GIS compiles each published HSY population-cell representative's straight snap "
            "connector, frozen walking-network shortest path, and reviewed Service Map venue "
            "snap connector. Z3 then chooses sites and assigns every whole cell under the stated "
            "budget, total-distance, and declared-capacity rules; NetworkX freshly verifies the "
            "returned network routes and connector arithmetic."
        ),
        "methodology_details": methodology,
        "attribution": (
            "Population grid © Helsinki Region Environmental Services HSY, CC BY 4.0 · "
            "candidate units © Helsinki metropolitan area Service Map, CC BY 4.0 · walking "
            "network © OpenStreetMap contributors, ODbL 1.0"
        ),
        "attribution_sources": attribution,
        "derived_processing": (
            "The laboratory selects and snaps source features, derives walking routes and "
            "straight-line snap connectors, and adds declared scenario assumptions. Source "
            "identities, licences, and unmodified published population totals remain explicit."
        ),
    }
    artifact = {
        "schema_version": "1.0",
        "artifact_type": "service_coverage_experiment",
        "scenario_id": recipe["scenario_id"],
        "snapshot_id": SNAPSHOT_ID_PLACEHOLDER,
        "solver": solver,
        "browser": browser,
        "provenance": {
            "recipe": "data/recipes/service-coverage-otaniemi-tapiola-v1.json",
            "source_manifest": (
                "data/source/service-coverage/otaniemi-tapiola-v1/source-manifest.json"
            ),
            "source_manifest_canonical_sha256": sha256_bytes(canonical_bytes(manifest)),
            "source_acquired_at": source_timestamp,
            "source_artifacts": manifest["artifacts"],
            "base_network": {
                "scenario_id": recipe["base_network"]["scenario_id"],
                "snapshot_id": recipe["base_network"]["snapshot_id"],
                "path": recipe["base_network"]["path"],
                "sha256": sha256_file(base_path),
            },
            "determinism": (
                "Stable source IDs, sorted arrays, canonical JSON, fixed recipe assumptions, "
                "and deterministic shortest-path tie-breaking."
            ),
        },
    }
    snapshot_id = computed_snapshot_id(artifact)
    artifact["snapshot_id"] = snapshot_id
    artifact["solver"]["snapshot_id"] = snapshot_id
    artifact["browser"]["snapshot_id"] = snapshot_id
    return artifact


def require_close(actual: float, expected: float, message: str, tolerance: float = 0.01) -> None:
    if not math.isfinite(actual) or abs(actual - expected) > tolerance:
        raise BuildError(f"{message}: expected {expected:.3f}, got {actual:.3f}")


def require_same_coordinates(
    actual: Any,
    expected: list[list[float]],
    message: str,
) -> None:
    if not isinstance(actual, list) or len(actual) != len(expected):
        raise BuildError(f"{message}: coordinate count is inconsistent")
    for index, (actual_coordinate, expected_coordinate) in enumerate(
        zip(actual, expected, strict=True)
    ):
        if not isinstance(actual_coordinate, list) or len(actual_coordinate) < 2:
            raise BuildError(f"{message}: coordinate {index} is malformed")
        if any(
            abs(float(actual_coordinate[axis]) - expected_coordinate[axis]) > 1e-8
            for axis in (0, 1)
        ):
            raise BuildError(f"{message}: coordinate {index} does not match the audited route")


def validate_artifact(artifact: dict[str, Any]) -> None:
    solver = artifact["solver"]
    browser = artifact["browser"]
    snapshot_ids = {
        artifact.get("snapshot_id"),
        solver.get("snapshot_id"),
        browser.get("snapshot_id"),
    }
    if len(snapshot_ids) != 1 or None in snapshot_ids:
        raise BuildError("top-level, solver, and browser snapshot identifiers disagree")
    actual_snapshot_id = artifact["snapshot_id"]
    expected_snapshot_id = computed_snapshot_id(artifact)
    if actual_snapshot_id != expected_snapshot_id:
        raise BuildError(
            "snapshot identifier does not match normalized artifact content: "
            f"expected {expected_snapshot_id}, got {actual_snapshot_id}"
        )
    scenario_ids = {
        artifact.get("scenario_id"),
        solver.get("scenario_id"),
        browser.get("id"),
    }
    if len(scenario_ids) != 1 or None in scenario_ids:
        raise BuildError("top-level, solver, and browser scenario identifiers disagree")

    attribution_sources = browser.get("attribution_sources")
    if not isinstance(attribution_sources, list) or not attribution_sources:
        raise BuildError("browser attribution sources are missing")
    for source in attribution_sources:
        if not all(source.get(key) for key in ("label", "licence", "licence_url", "url")):
            raise BuildError("a browser attribution source is incomplete")
        if not source.get("modifications"):
            raise BuildError("a browser attribution source lacks its processing note")
    if not browser.get("derived_processing"):
        raise BuildError("browser derived-processing note is missing")

    demand = solver["demand"]
    sites = solver["sites"]
    distances = solver["distances"]
    if len({item["id"] for item in demand}) != len(demand):
        raise BuildError("demand IDs are not unique")
    if len({item["id"] for item in sites}) != len(sites):
        raise BuildError("site IDs are not unique")
    if [clean_solver_demand(item) for item in browser["population_cells"]] != demand:
        raise BuildError("browser and solver demand payloads disagree")
    if [clean_solver_site(item) for item in browser["candidate_sites"]] != sites:
        raise BuildError("browser and solver site payloads disagree")
    expected = {(item["id"], site["id"]) for item in demand for site in sites}
    actual = {(item["demand_id"], item["site_id"]) for item in distances}
    if actual != expected or len(distances) != len(expected):
        raise BuildError("distance matrix is incomplete or contains duplicate references")
    if any(site["capacity"] <= 0 or not site["eligible"] for site in sites):
        raise BuildError("selected sites must be eligible with positive declared capacities")

    network = solver["network"]
    graph = nx.DiGraph()
    nodes = network["nodes"]
    node_ids = {node["id"] for node in nodes}
    if len(node_ids) != len(nodes):
        raise BuildError("compact network node IDs are not unique")
    node_by_id = {node["id"]: node for node in nodes}
    for node in nodes:
        point = node["point"]
        graph.add_node(
            node["id"],
            node={"longitude": float(point[0]), "latitude": float(point[1])},
        )
    edges = network["edges"]
    edge_ids = {edge["id"] for edge in edges}
    if len(edge_ids) != len(edges):
        raise BuildError("compact network edge IDs are not unique")
    edge_by_id = {edge["id"]: edge for edge in edges}
    for edge in edges:
        if edge["from"] not in node_ids or edge["to"] not in node_ids:
            raise BuildError(f"compact edge {edge['id']} references an unknown node")
        graph.add_edge(
            edge["from"],
            edge["to"],
            weight=float(edge["length_m"]),
            edge=edge,
        )
    if any(item["node_id"] not in node_ids for item in [*demand, *sites]):
        raise BuildError("a demand or site snap node is absent from the compact solver graph")

    projector = Transformer.from_crs("EPSG:4326", solver["crs"], always_xy=True)
    for endpoint in [*demand, *sites]:
        node = node_by_id[endpoint["node_id"]]
        point_x, point_y = projector.transform(*endpoint["point"])
        measured_snap = math.hypot(
            float(node["x"]) - point_x,
            float(node["y"]) - point_y,
        )
        require_close(
            float(endpoint["snap_distance_m"]),
            measured_snap,
            f"snap distance mismatch for {endpoint['id']}",
        )

    demand_by_id = {item["id"]: item for item in demand}
    site_by_id = {item["id"]: item for item in sites}
    shortest_by_source = {
        source: nx.single_source_dijkstra_path_length(graph, source, weight="weight")
        for source in sorted({item["node_id"] for item in demand})
    }
    for item in distances:
        demand_item = demand_by_id[item["demand_id"]]
        site_item = site_by_id[item["site_id"]]
        source = demand_item["node_id"]
        target = site_item["node_id"]
        route_nodes = item.get("route_node_ids")
        route_edges = item.get("route_edge_ids")
        if not isinstance(route_nodes, list) or not route_nodes:
            raise BuildError("a distance record has no auditable route node chain")
        if route_nodes[0] != source or route_nodes[-1] != target:
            raise BuildError("a distance record route does not join its snapped endpoints")
        if not isinstance(route_edges, list) or len(route_edges) != len(route_nodes) - 1:
            raise BuildError("a distance record route edge/node chain has inconsistent length")
        for route_source, route_target, edge_id in zip(
            route_nodes[:-1],
            route_nodes[1:],
            route_edges,
            strict=True,
        ):
            edge = edge_by_id.get(edge_id)
            if edge is None or edge["from"] != route_source or edge["to"] != route_target:
                raise BuildError(f"route edge {edge_id} is not the declared directed node step")

        measured_network = sum(float(edge_by_id[edge_id]["length_m"]) for edge_id in route_edges)
        shortest_network = shortest_by_source[source][target]
        require_close(
            float(item["network_distance_m"]),
            measured_network,
            f"route edge length mismatch for {item['demand_id']} / {item['site_id']}",
        )
        require_close(
            measured_network,
            float(shortest_network),
            f"route is not shortest for {item['demand_id']} / {item['site_id']}",
        )
        require_close(
            float(item["demand_connector_m"]),
            float(demand_item["snap_distance_m"]),
            f"demand connector mismatch for {item['demand_id']} / {item['site_id']}",
        )
        require_close(
            float(item["site_connector_m"]),
            float(site_item["snap_distance_m"]),
            f"site connector mismatch for {item['demand_id']} / {item['site_id']}",
        )
        if item.get("connector_method") != SNAP_CONNECTOR_METHOD:
            raise BuildError("a distance record has an unsupported connector method")
        expected_total = (
            float(item["demand_connector_m"])
            + float(item["network_distance_m"])
            + float(item["site_connector_m"])
        )
        require_close(
            float(item["distance_m"]),
            expected_total,
            f"total distance mismatch for {item['demand_id']} / {item['site_id']}",
        )

        network_coordinates, audited_edge_ids = route_coordinates(graph, route_nodes)
        if audited_edge_ids != route_edges:
            raise BuildError("route edge IDs disagree with the audited node chain")
        expected_coordinates = route_coordinates_with_connectors(
            demand_item["point"], network_coordinates, site_item["point"]
        )
        route = item.get("route")
        if not isinstance(route, dict) or route.get("type") != "Feature":
            raise BuildError("a distance record route is not a GeoJSON Feature")
        geometry = route.get("geometry", {})
        if geometry.get("type") != "LineString":
            raise BuildError("a distance record route is not a GeoJSON LineString")
        require_same_coordinates(
            geometry.get("coordinates"),
            expected_coordinates,
            f"route geometry mismatch for {item['demand_id']} / {item['site_id']}",
        )
        properties = route.get("properties", {})
        for key in (
            "demand_id",
            "site_id",
            "distance_m",
            "demand_connector_m",
            "network_distance_m",
            "site_connector_m",
            "connector_method",
        ):
            if properties.get(key) != item.get(key):
                raise BuildError(f"route property {key} disagrees with its distance record")


def artifact_counts(artifact: dict[str, Any]) -> dict[str, int]:
    return {
        "demand_cells": len(artifact["solver"]["demand"]),
        "population": sum(item["population"] for item in artifact["solver"]["demand"]),
        "candidate_sites": len(artifact["solver"]["sites"]),
        "distance_pairs": len(artifact["solver"]["distances"]),
        "solver_network_nodes": len(artifact["solver"]["network"]["nodes"]),
        "solver_network_edges": len(artifact["solver"]["network"]["edges"]),
        "display_network_features": len(artifact["browser"]["network"]["features"]),
    }


def validate_published_snapshot(output_dir: Path) -> dict[str, Any]:
    """Validate the canonical artifact and every published consumer file."""

    artifact_paths = {name: output_dir / name for name in PUBLISHED_ARTIFACT_NAMES}
    metadata_path = output_dir / "metadata.json"
    artifact = read_json(artifact_paths["scenario.json"])
    solver = read_json(artifact_paths["solver.json"])
    browser = read_json(artifact_paths["browser.json"])
    metadata = read_json(metadata_path)

    validate_artifact(artifact)
    if solver != artifact["solver"]:
        raise BuildError("published solver.json disagrees with scenario.json")
    if browser != artifact["browser"]:
        raise BuildError("published browser.json disagrees with scenario.json")
    if metadata.get("scenario_id") != artifact["scenario_id"]:
        raise BuildError("metadata scenario identifier disagrees with scenario.json")
    if metadata.get("snapshot_id") != artifact["snapshot_id"]:
        raise BuildError("metadata snapshot identifier disagrees with scenario.json")
    if metadata.get("counts") != artifact_counts(artifact):
        raise BuildError("metadata counts disagree with scenario.json")

    records = metadata.get("artifacts")
    if not isinstance(records, list):
        raise BuildError("metadata artifact records are missing")
    record_names = [record.get("path") for record in records]
    if len(record_names) != len(set(record_names)):
        raise BuildError("metadata artifact paths are duplicated")
    if set(record_names) != set(PUBLISHED_ARTIFACT_NAMES):
        raise BuildError("metadata does not describe the exact published artifact set")
    for record in records:
        name = record["path"]
        path = artifact_paths[name]
        actual_size = path.stat().st_size
        if record.get("byte_size") != actual_size:
            raise BuildError(
                f"published artifact size mismatch for {name}: "
                f"expected {record.get('byte_size')}, got {actual_size}"
            )
        actual_sha256 = sha256_file(path)
        if record.get("sha256") != actual_sha256:
            raise BuildError(
                f"published artifact checksum mismatch for {name}: "
                f"expected {record.get('sha256')}, got {actual_sha256}"
            )
    return artifact


def publish_snapshot(artifact: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="coverage-build-", dir=output_dir) as temp_name:
        temp_dir = Path(temp_name)
        write_json(temp_dir / "scenario.json", artifact)
        write_json(temp_dir / "solver.json", artifact["solver"])
        write_json(temp_dir / "browser.json", artifact["browser"])
        metadata = {
            "schema_version": "1.0",
            "scenario_id": artifact["scenario_id"],
            "snapshot_id": artifact["snapshot_id"],
            "counts": artifact_counts(artifact),
            "artifacts": [],
        }
        for name in PUBLISHED_ARTIFACT_NAMES:
            path = temp_dir / name
            metadata["artifacts"].append(
                {
                    "path": name,
                    "byte_size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        write_json(temp_dir / "metadata.json", metadata)
        for name in ("scenario.json", "solver.json", "browser.json", "metadata.json"):
            shutil.move(str(temp_dir / name), output_dir / name)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, default=DEFAULT_RECIPE)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.refresh and arguments.validate_only:
        parser.error("--refresh and --validate-only cannot be combined")
    return arguments


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        recipe = read_json(arguments.recipe.resolve())
        if arguments.refresh:
            refresh_sources(recipe, arguments.source_dir.resolve())
        manifest_path = arguments.source_dir.resolve() / "source-manifest.json"
        manifest = read_json(manifest_path)
        validate_sources(recipe, manifest)
        if arguments.validate_only:
            artifact = validate_published_snapshot(arguments.output_dir.resolve())
            print(
                f"Validated service-coverage snapshot {artifact['snapshot_id']} "
                f"({len(artifact['solver']['demand'])} demand cells, "
                f"{len(artifact['solver']['sites'])} sites)"
            )
            return 0
        artifact = build_snapshot(recipe, manifest)
        validate_artifact(artifact)
        publish_snapshot(artifact, arguments.output_dir.resolve())
        validate_published_snapshot(arguments.output_dir.resolve())
        print(
            f"Built {artifact['snapshot_id']}: {len(artifact['solver']['demand'])} demand "
            f"cells, {len(artifact['solver']['sites'])} sites, "
            f"{len(artifact['solver']['distances'])} walking routes"
        )
        print(f"Snapshot: {arguments.output_dir.resolve() / 'scenario.json'}")
        return 0
    except (BuildError, KeyError, ValueError, nx.NetworkXError) as error:
        print(f"Service-coverage build failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
