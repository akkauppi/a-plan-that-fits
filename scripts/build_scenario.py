#!/usr/bin/env python3
"""Build the frozen Four Planters Kallio--Vallila OSM scenario.

The default command rebuilds the derived files from the checked-in, compressed
Overpass response.  Pass ``--refresh`` to acquire a newer bounded response, or
``--input PATH --archive-source`` when importing a response acquired elsewhere.

The analytical graph is deliberately small and inspectable: OSM shape points
are collapsed into geometry on edges, while intersections, way endpoints, and
boundary crossings remain graph nodes.  Parallel ways and directed one-way
semantics are retained.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import heapq
import json
import math
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import networkx as nx
import pyproj
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon, box, mapping, shape
from shapely.ops import transform

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_ID = "helsinki-kallio-vallila"
SCENARIO_NAME = "Kallio–Vallila, Helsinki"
OUTPUT_DIR = ROOT / "data" / "derived" / SCENARIO_ID
SOURCE_PATH = ROOT / "data" / "source" / f"{SCENARIO_ID}.osm.json.gz"
SOURCE_META_PATH = ROOT / "data" / "source" / f"{SCENARIO_ID}.source.json"

# WGS84 west, south, east, north.  The 1.33 km² rectangle is intentionally
# legible: Helsinginkatu/Kallio in the south and western Vallila in the north.
BBOX = (24.9435, 60.1854, 24.9635, 60.1962)
CENTER = ((BBOX[0] + BBOX[2]) / 2, (BBOX[1] + BBOX[3]) / 2)
ANALYSIS_CRS = "EPSG:3067"  # ETRS89 / TM35FIN, metres
DISPLAY_CRS = "EPSG:4326"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

CAR_HIGHWAYS = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "residential",
    "living_street",
    "unclassified",
    "service",
    "road",
}
CANDIDATE_HIGHWAYS = {"residential", "living_street", "unclassified"}
PROTECTED_HIGHWAYS = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
}
ACCESS_DENY = {"no", "private", "customers", "permit"}
ONEWAY_YES = {"yes", "true", "1"}
ONEWAY_REVERSE = {"-1", "reverse"}


def overpass_query() -> str:
    south, west, north, east = BBOX[1], BBOX[0], BBOX[3], BBOX[2]
    bounds = f"{south},{west},{north},{east}"
    return (
        "[out:json][timeout:90];"
        f'(way["highway"]({bounds});'
        f'way["building"]({bounds});'
        f'way["railway"~"^(tram|light_rail)$"]({bounds}););'
        "out meta;>;out meta qt;"
    )


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_bytes(path: Path) -> bytes:
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as handle:
            return handle.read()
    return path.read_bytes()


def write_json(path: Path, value: Any, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        if compact:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        else:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")


def fetch_overpass() -> bytes:
    body = urllib.parse.urlencode({"data": overpass_query()}).encode()
    request = urllib.request.Request(
        OVERPASS_URL,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "FourPlanters/0.1 reproducible-research-scenario",
        },
    )
    with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310
        return response.read()


def archive_source(raw: bytes, acquired_at: str) -> None:
    SOURCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 makes the gzip byte stream deterministic.
    with SOURCE_PATH.open("wb") as raw_handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as handle:
            handle.write(raw)
    write_json(
        SOURCE_META_PATH,
        {
            "acquired_at": acquired_at,
            "overpass_endpoint": OVERPASS_URL,
            "query": overpass_query(),
            "raw_sha256": sha256_bytes(raw),
        },
    )


def source_bytes(args: argparse.Namespace) -> tuple[bytes, str]:
    if args.input:
        raw = read_bytes(Path(args.input))
        acquired_at = args.acquired_at or utc_now()
        if args.archive_source:
            archive_source(raw, acquired_at)
        return raw, acquired_at
    if args.refresh:
        raw = fetch_overpass()
        acquired_at = args.acquired_at or utc_now()
        archive_source(raw, acquired_at)
        return raw, acquired_at
    if not SOURCE_PATH.exists():
        raise SystemExit(
            f"Frozen source missing: {SOURCE_PATH}. Use --refresh or --input PATH --archive-source."
        )
    raw = read_bytes(SOURCE_PATH)
    acquired_at = args.acquired_at
    if SOURCE_META_PATH.exists():
        descriptor = json.loads(SOURCE_META_PATH.read_text(encoding="utf-8"))
        expected = descriptor.get("raw_sha256")
        if expected and expected != sha256_bytes(raw):
            raise ValueError("Frozen source checksum does not match its descriptor")
        acquired_at = acquired_at or descriptor.get("acquired_at")
    return raw, acquired_at or utc_now()


@dataclass(frozen=True)
class Projection:
    forward: Transformer
    inverse: Transformer

    def point_xy(self, coordinate: Sequence[float]) -> tuple[float, float]:
        x, y = self.forward.transform(float(coordinate[0]), float(coordinate[1]))
        return (round(x, 3), round(y, 3))

    def point_lonlat(self, coordinate: Sequence[float]) -> list[float]:
        lon, lat = self.inverse.transform(float(coordinate[0]), float(coordinate[1]))
        return [round(lon, 7), round(lat, 7)]

    def line_xy(self, coordinates: Sequence[Sequence[float]]) -> LineString:
        return LineString([self.forward.transform(*coordinate) for coordinate in coordinates])


def projection() -> Projection:
    return Projection(
        forward=Transformer.from_crs(DISPLAY_CRS, ANALYSIS_CRS, always_xy=True),
        inverse=Transformer.from_crs(ANALYSIS_CRS, DISPLAY_CRS, always_xy=True),
    )


def transform_geometry(geometry: Any, transformer: Transformer) -> Any:
    return transform(transformer.transform, geometry)


def is_inside(coordinate: tuple[float, float]) -> bool:
    return BBOX[0] <= coordinate[0] <= BBOX[2] and BBOX[1] <= coordinate[1] <= BBOX[3]


def private_car_way(tags: dict[str, str]) -> bool:
    highway = tags.get("highway", "")
    if highway not in CAR_HIGHWAYS:
        return False
    if tags.get("motor_vehicle", "").lower() in ACCESS_DENY:
        return False
    if tags.get("motorcar", "").lower() in ACCESS_DENY:
        return False
    if tags.get("vehicle", "").lower() in ACCESS_DENY:
        return False
    return tags.get("access", "").lower() not in ACCESS_DENY


def walking_allowed(tags: dict[str, str]) -> bool:
    if tags.get("foot", "").lower() in ACCESS_DENY:
        return False
    return tags.get("highway") not in {"motorway", "motorway_link", "trunk", "trunk_link"}


def cycling_allowed(tags: dict[str, str]) -> bool:
    if tags.get("bicycle", "").lower() in ACCESS_DENY:
        return False
    return tags.get("highway") not in {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "steps",
    }


def explicit_transit(tags: dict[str, str]) -> bool:
    return (
        any(
            key in tags
            for key in (
                "busway",
                "bus:lanes",
                "bus:lanes:forward",
                "bus:lanes:backward",
                "psv:lanes",
                "psv:lanes:forward",
                "psv:lanes:backward",
            )
        )
        or tags.get("trolley_wire") == "yes"
    )


def direction_for_way(tags: dict[str, str]) -> str:
    oneway = tags.get("oneway", "").lower()
    if oneway in ONEWAY_REVERSE:
        return "reverse"
    if oneway in ONEWAY_YES or tags.get("junction") == "roundabout":
        return "forward"
    return "both"


def osm_elements(
    raw: bytes,
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    payload = json.loads(raw)
    nodes = {
        int(element["id"]): element
        for element in payload.get("elements", [])
        if element.get("type") == "node" and "lon" in element and "lat" in element
    }
    ways = [element for element in payload.get("elements", []) if element.get("type") == "way"]
    if not nodes or not ways:
        raise ValueError("Overpass response contains no usable nodes or ways")
    return nodes, ways, payload.get("osm3s", {})


def coordinates_for_way(
    way: dict[str, Any], nodes: dict[int, dict[str, Any]]
) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for node_id in way.get("nodes", []):
        node = nodes.get(int(node_id))
        if node is None:
            return []
        result.append((float(node["lon"]), float(node["lat"])))
    return result


def contiguous_inside_runs(
    node_ids: Sequence[int], nodes: dict[int, dict[str, Any]]
) -> list[list[int]]:
    runs: list[list[int]] = []
    current: list[int] = []
    for node_id in node_ids:
        node = nodes.get(int(node_id))
        inside = bool(node and is_inside((float(node["lon"]), float(node["lat"]))))
        if inside:
            current.append(int(node_id))
        else:
            if len(current) >= 2:
                runs.append(current)
            current = []
    if len(current) >= 2:
        runs.append(current)
    return runs


def boundary_side(point: Point, boundary_xy: Polygon) -> str:
    minx, miny, maxx, maxy = boundary_xy.bounds
    distances = {
        "west": abs(point.x - minx),
        "east": abs(point.x - maxx),
        "south": abs(point.y - miny),
        "north": abs(point.y - maxy),
    }
    return min(distances, key=lambda key: (distances[key], key))


def segment_heading(line: LineString, distance: float | None = None) -> float:
    if line.length == 0:
        return 0.0
    location = line.length / 2 if distance is None else min(max(distance, 0), line.length)
    radius = min(8.0, max(1.0, line.length / 4))
    before = line.interpolate(max(0, location - radius))
    after = line.interpolate(min(line.length, location + radius))
    return math.atan2(after.y - before.y, after.x - before.x)


def parallel_angle(a: float, b: float) -> float:
    delta = abs((a - b) % math.pi)
    return min(delta, math.pi - delta)


def line_follows_tram(line: LineString, tram_lines: Sequence[LineString]) -> bool:
    midpoint = line.interpolate(line.length / 2)
    road_heading = segment_heading(line)
    for tram in tram_lines:
        if midpoint.distance(tram) > 10:
            continue
        location = tram.project(midpoint)
        if parallel_angle(road_heading, segment_heading(tram, location)) > math.radians(28):
            continue
        overlap = line.intersection(tram.buffer(7, cap_style="flat")).length
        if overlap >= min(18.0, line.length * 0.42):
            return True
    return False


def road_hierarchy(highway: str) -> str:
    if highway in PROTECTED_HIGHWAYS:
        return "major"
    if highway in {"tertiary", "tertiary_link"}:
        return "connector"
    if highway == "service":
        return "service"
    return "local"


def simplify_road_ways(
    ways: Sequence[dict[str, Any]],
    nodes: dict[int, dict[str, Any]],
    project: Projection,
    tram_lines_xy: Sequence[LineString],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    road_ways = [way for way in ways if private_car_way(way.get("tags", {}))]
    neighbours: dict[int, set[int]] = defaultdict(set)
    node_ways: dict[int, set[int]] = defaultdict(set)
    boundary_nodes: set[int] = set()
    crossing_records: list[dict[str, Any]] = []
    boundary_wgs = box(*BBOX).boundary

    for way in road_ways:
        way_nodes = [int(value) for value in way.get("nodes", [])]
        tags = dict(way.get("tags", {}))
        for first, second in zip(way_nodes, way_nodes[1:], strict=False):
            a = nodes.get(first)
            b = nodes.get(second)
            if a is None or b is None:
                continue
            ca = (float(a["lon"]), float(a["lat"]))
            cb = (float(b["lon"]), float(b["lat"]))
            a_inside = is_inside(ca)
            b_inside = is_inside(cb)
            if a_inside and b_inside:
                neighbours[first].add(second)
                neighbours[second].add(first)
                node_ways[first].add(int(way["id"]))
                node_ways[second].add(int(way["id"]))
            elif a_inside != b_inside:
                inside_node = first if a_inside else second
                crossing = LineString([ca, cb]).intersection(boundary_wgs)
                points = []
                if crossing.geom_type == "Point":
                    points = [crossing]
                elif hasattr(crossing, "geoms"):
                    points = [item for item in crossing.geoms if item.geom_type == "Point"]
                if points:
                    point = min(points, key=lambda item: Point(ca).distance(item))
                    boundary_nodes.add(inside_node)
                    crossing_records.append(
                        {
                            "node_id": inside_node,
                            "way_id": int(way["id"]),
                            "point": [round(point.x, 7), round(point.y, 7)],
                            "name": tags.get("name") or tags.get("ref") or "Unnamed street",
                            "highway": tags.get("highway", "road"),
                            "direction": direction_for_way(tags),
                            "inside_after": b_inside,
                        }
                    )

    decision_nodes = {
        node_id
        for node_id, adjacent in neighbours.items()
        if len(adjacent) != 2 or len(node_ways[node_id]) > 1
    } | boundary_nodes

    physical_edges: list[dict[str, Any]] = []
    for way in sorted(road_ways, key=lambda item: int(item["id"])):
        tags = dict(way.get("tags", {}))
        for run in contiguous_inside_runs(way.get("nodes", []), nodes):
            breaks = {0, len(run) - 1}
            breaks.update(index for index, node_id in enumerate(run) if node_id in decision_nodes)
            ordered = sorted(breaks)
            for ordinal, (start, end) in enumerate(zip(ordered, ordered[1:], strict=False)):
                if end <= start:
                    continue
                subnodes = run[start : end + 1]
                coordinates = [
                    [float(nodes[node_id]["lon"]), float(nodes[node_id]["lat"])]
                    for node_id in subnodes
                ]
                line_xy = project.line_xy(coordinates)
                if line_xy.length < 0.5:
                    continue
                way_id = int(way["id"])
                physical_id = f"seg-{way_id}-{subnodes[0]}-{subnodes[-1]}-{ordinal:02d}"
                major = tags.get("highway") in PROTECTED_HIGHWAYS
                transit = explicit_transit(tags) or line_follows_tram(line_xy, tram_lines_xy)
                protected = major or transit
                reason = None
                if major:
                    reason = "Major through street remains open"
                elif transit:
                    reason = "Mapped public-transport corridor remains open"
                elif tags.get("bridge") not in {None, "no"}:
                    reason = "Bridge excluded from candidate set"
                elif tags.get("tunnel") not in {None, "no"}:
                    reason = "Tunnel excluded from candidate set"
                candidate_eligible = (
                    tags.get("highway") in CANDIDATE_HIGHWAYS
                    and not protected
                    and tags.get("bridge") in {None, "no"}
                    and tags.get("tunnel") in {None, "no"}
                    and line_xy.length >= 10
                )
                physical_edges.append(
                    {
                        "id": physical_id,
                        "way_id": way_id,
                        "u_osm": subnodes[0],
                        "v_osm": subnodes[-1],
                        "geometry": coordinates,
                        "geometry_xy": line_xy,
                        "length_m": round(line_xy.length, 2),
                        "name": tags.get("name") or tags.get("ref") or "Unnamed local street",
                        "highway": tags.get("highway", "road"),
                        "hierarchy": road_hierarchy(tags.get("highway", "road")),
                        "oneway": direction_for_way(tags),
                        "protected": protected,
                        "protection_reason": reason,
                        "eligible_candidate": candidate_eligible,
                        "modes": {
                            "private_car": True,
                            "walking": walking_allowed(tags),
                            "cycling": cycling_allowed(tags),
                            "emergency": True,
                            "service": True,
                        },
                        "tags": {
                            key: tags[key]
                            for key in (
                                "name",
                                "name:fi",
                                "name:sv",
                                "ref",
                                "highway",
                                "oneway",
                                "access",
                                "motor_vehicle",
                                "maxspeed",
                                "lanes",
                                "bridge",
                                "tunnel",
                                "busway",
                                "psv:lanes",
                            )
                            if key in tags
                        },
                    }
                )

    graph = nx.Graph()
    for edge in physical_edges:
        graph.add_edge(edge["u_osm"], edge["v_osm"])
    if not graph:
        raise ValueError("No private-car graph could be derived")
    main_nodes = max(
        nx.connected_components(graph), key=lambda component: (len(component), min(component))
    )
    physical_edges = [
        edge
        for edge in physical_edges
        if edge["u_osm"] in main_nodes and edge["v_osm"] in main_nodes
    ]
    crossing_records = [record for record in crossing_records if record["node_id"] in main_nodes]
    return physical_edges, crossing_records


def directed_graph_data(
    physical_edges: list[dict[str, Any]],
    nodes: dict[int, dict[str, Any]],
    project: Projection,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    used_nodes = sorted(
        {edge["u_osm"] for edge in physical_edges} | {edge["v_osm"] for edge in physical_edges}
    )
    solver_nodes = []
    for osm_id in used_nodes:
        node = nodes[osm_id]
        lon = float(node["lon"])
        lat = float(node["lat"])
        x, y = project.point_xy((lon, lat))
        solver_nodes.append(
            {
                "id": f"n{osm_id}",
                "osm_node_id": osm_id,
                "lon": round(lon, 7),
                "lat": round(lat, 7),
                "x_m": x,
                "y_m": y,
            }
        )

    directed_edges: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for physical in sorted(physical_edges, key=lambda item: item["id"]):
        candidate_id = None
        if physical["eligible_candidate"]:
            candidate_id = f"c-{physical['id'][4:]}"
        direction_specs: list[tuple[str, int, int, list[list[float]]]] = []
        if physical["oneway"] in {"both", "forward"}:
            direction_specs.append(
                ("f", physical["u_osm"], physical["v_osm"], physical["geometry"])
            )
        if physical["oneway"] in {"both", "reverse"}:
            direction_specs.append(
                ("r", physical["v_osm"], physical["u_osm"], list(reversed(physical["geometry"])))
            )
        edge_ids: list[str] = []
        for suffix, u_osm, v_osm, geometry in direction_specs:
            edge_id = f"e-{physical['id'][4:]}-{suffix}"
            edge_ids.append(edge_id)
            directed_edges.append(
                {
                    "id": edge_id,
                    "physical_id": physical["id"],
                    "u": f"n{u_osm}",
                    "v": f"n{v_osm}",
                    "way_id": physical["way_id"],
                    "name": physical["name"],
                    "highway": physical["highway"],
                    "oneway": physical["oneway"] != "both",
                    "length_m": physical["length_m"],
                    "eligible_candidate": candidate_id is not None,
                    "candidate_id": candidate_id,
                    "protected": physical["protected"],
                    "protection_reason": physical["protection_reason"],
                    "modes": physical["modes"],
                    "geometry": geometry,
                }
            )
        physical["directed_edge_ids"] = edge_ids
        physical["candidate_id"] = candidate_id
        if candidate_id:
            line = physical["geometry_xy"]
            midpoint = line.interpolate(line.length / 2)
            heading = segment_heading(line)
            perpendicular = (-math.sin(heading), math.cos(heading))
            half_width = 6.5
            start = (
                midpoint.x - perpendicular[0] * half_width,
                midpoint.y - perpendicular[1] * half_width,
            )
            end = (
                midpoint.x + perpendicular[0] * half_width,
                midpoint.y + perpendicular[1] * half_width,
            )
            point = project.point_lonlat((midpoint.x, midpoint.y))
            cost = {"living_street": 90, "residential": 100, "unclassified": 115}.get(
                physical["highway"], 125
            )
            candidates.append(
                {
                    "id": candidate_id,
                    "physical_id": physical["id"],
                    "edge_ids": edge_ids,
                    "street_name": physical["name"],
                    "display_point": point,
                    "point": point,
                    "cross_geometry": {
                        "type": "LineString",
                        "coordinates": [project.point_lonlat(start), project.point_lonlat(end)],
                    },
                    "cost": cost,
                    "access_penalty": 0,
                    "eligible": True,
                    "blocks_modes": ["private_car"],
                    "passes_modes": ["walking", "cycling", "emergency"],
                }
            )
    return solver_nodes, directed_edges, candidates


def cluster_portals(
    crossing_records: Sequence[dict[str, Any]],
    project: Projection,
    physical_edges: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    boundary_xy = transform_geometry(box(*BBOX), project.forward)
    by_side: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in crossing_records:
        if record["highway"] == "service" and record["name"] == "Unnamed street":
            continue
        x, y = project.point_xy(record["point"])
        enriched = {**record, "point_xy": Point(x, y)}
        enriched["side"] = boundary_side(enriched["point_xy"], boundary_xy)
        by_side[enriched["side"]].append(enriched)

    clusters: list[dict[str, Any]] = []
    for side in ("north", "east", "south", "west"):
        records = by_side[side]
        records.sort(
            key=lambda item: (
                item["point_xy"].x if side in {"north", "south"} else item["point_xy"].y,
                item["way_id"],
                item["node_id"],
            )
        )
        # Portals are analytical boundary-crossing groups, not individual map
        # markers. Two contiguous sectors per side retain every crossing node
        # while keeping the interaction legible at neighbourhood scale. Choose
        # the strongest spatial break near the middle rather than an arbitrary
        # fixed-distance chain that can create dozens of near-overlapping dots.
        side_clusters: list[list[dict[str, Any]]]
        if len(records) <= 1:
            side_clusters = [records] if records else []
        else:
            axis = "x" if side in {"north", "south"} else "y"
            lower = max(1, len(records) // 4)
            upper = min(len(records) - 1, math.ceil(3 * len(records) / 4))
            split_index = max(
                range(lower, upper + 1),
                key=lambda index: (
                    abs(
                        getattr(records[index]["point_xy"], axis)
                        - getattr(records[index - 1]["point_xy"], axis)
                    ),
                    -abs(index - len(records) / 2),
                    -index,
                ),
            )
            side_clusters = [records[:split_index], records[split_index:]]
        for index, members in enumerate(side_clusters, start=1):
            x = sum(item["point_xy"].x for item in members) / len(members)
            y = sum(item["point_xy"].y for item in members) / len(members)
            representative = min(
                members,
                key=lambda item: (item["point_xy"].distance(Point(x, y)), item["node_id"]),
            )
            names = sorted({item["name"] for item in members})
            primary_name = representative["name"]
            sector = {
                ("north", 1): "North-west",
                ("north", 2): "North-east",
                ("south", 1): "South-west",
                ("south", 2): "South-east",
                ("east", 1): "East-south",
                ("east", 2): "East-north",
                ("west", 1): "West-south",
                ("west", 2): "West-north",
            }.get((side, index), side.title())
            clusters.append(
                {
                    "id": f"p-{side}-{index:02d}",
                    "label": f"{sector} · {primary_name}",
                    "direction": side,
                    "side": side,
                    "node_ids": sorted({f"n{item['node_id']}" for item in members}),
                    "display_point": list(representative["point"]),
                    "point": list(representative["point"]),
                    "group_centroid": project.point_lonlat((x, y)),
                    "crossing_count": len({item["node_id"] for item in members}),
                    "street_names": names,
                    "crossing_way_ids": sorted({item["way_id"] for item in members}),
                }
            )

    # Record how selectable each portal's immediate graph neighbourhood is.  This
    # supports deterministic default-pair selection without changing semantics.
    incident: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in physical_edges:
        incident[f"n{edge['u_osm']}"].append(edge)
        incident[f"n{edge['v_osm']}"].append(edge)
    for portal in clusters:
        adjacent = [edge for node_id in portal["node_ids"] for edge in incident[node_id]]
        portal["adjacent_candidate_ids"] = sorted(
            {edge["candidate_id"] for edge in adjacent if edge.get("candidate_id")}
        )
        portal["adjacent_protected"] = any(edge["protected"] for edge in adjacent)
    return sorted(clusters, key=lambda item: (item["direction"], item["id"]))


def building_features(
    ways: Sequence[dict[str, Any]],
    nodes: dict[int, dict[str, Any]],
    project: Projection,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    boundary = box(*BBOX)
    boundary_xy = transform_geometry(boundary, project.forward)
    features: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for way in sorted(ways, key=lambda item: int(item["id"])):
        tags = dict(way.get("tags", {}))
        if "building" not in tags:
            continue
        coordinates = coordinates_for_way(way, nodes)
        if len(coordinates) < 4 or coordinates[0] != coordinates[-1]:
            continue
        geometry = Polygon(coordinates)
        if not geometry.is_valid:
            geometry = shapely.make_valid(geometry)
        geometry = geometry.intersection(boundary)
        if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            continue
        geometry_xy = transform_geometry(geometry, project.forward)
        if geometry_xy.area < 8:
            continue
        representative = geometry_xy.representative_point()
        building_id = f"b{int(way['id'])}"
        properties = {
            "id": building_id,
            "osm_way_id": int(way["id"]),
            "building": tags.get("building", "yes"),
            "name": tags.get("name"),
            "address": " ".join(
                value for value in (tags.get("addr:street"), tags.get("addr:housenumber")) if value
            )
            or None,
        }
        features.append(
            {
                "type": "Feature",
                "id": building_id,
                "properties": properties,
                "geometry": mapping(geometry),
            }
        )
        records.append(
            {
                "id": building_id,
                "point_xy": representative,
                "point": project.point_lonlat((representative.x, representative.y)),
                "area_m2": round(geometry_xy.area, 1),
                "inside": representative.within(boundary_xy),
            }
        )
    return features, records


def address_clusters(
    buildings: Sequence[dict[str, Any]],
    solver_nodes: Sequence[dict[str, Any]],
    portals: Sequence[dict[str, Any]],
    project: Projection,
) -> list[dict[str, Any]]:
    cells: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for building in buildings:
        point = building["point_xy"]
        cells[(math.floor(point.x / 85), math.floor(point.y / 85))].append(building)
    node_points = [
        (node["id"], Point(float(node["x_m"]), float(node["y_m"]))) for node in solver_nodes
    ]
    portal_ids = sorted(portal["id"] for portal in portals)
    clusters: list[dict[str, Any]] = []
    for index, (cell, members) in enumerate(sorted(cells.items()), start=1):
        x = sum(item["point_xy"].x for item in members) / len(members)
        y = sum(item["point_xy"].y for item in members) / len(members)
        representative = Point(x, y)
        node_id, node_point = min(
            node_points,
            key=lambda item: (representative.distance(item[1]), item[0]),
        )
        clusters.append(
            {
                "id": f"a-{cell[0]}-{cell[1]}",
                "label": f"Address cluster {index:02d} · {len(members)} buildings",
                "node_id": node_id,
                "display_point": project.point_lonlat((x, y)),
                "point": project.point_lonlat((x, y)),
                "snap_distance_m": round(representative.distance(node_point), 1),
                "building_ids": sorted(item["id"] for item in members),
                "building_count": len(members),
                "allowed_portal_ids": portal_ids,
            }
        )
    return clusters


def shortest_route(
    nodes: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]],
    source_ids: Sequence[str],
    target_ids: Sequence[str],
) -> dict[str, Any] | None:
    edge_lookup = {edge["id"]: edge for edge in edges}
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in sorted(edges, key=lambda item: item["id"]):
        adjacency[edge["u"]].append(edge)
    targets = set(target_ids)
    queue: list[tuple[float, tuple[str, ...], str, tuple[str, ...]]] = []
    best: dict[str, tuple[float, tuple[str, ...]]] = {}
    for source in sorted(set(source_ids)):
        heapq.heappush(queue, (0.0, (), source, (source,)))
        best[source] = (0.0, ())
    while queue:
        distance, edge_ids, node_id, node_ids = heapq.heappop(queue)
        if best.get(node_id) != (distance, edge_ids):
            continue
        if node_id in targets and edge_ids:
            coordinates: list[list[float]] = []
            street_names: list[str] = []
            candidate_ids: list[str] = []
            for edge_id in edge_ids:
                edge = edge_lookup[edge_id]
                points = [list(point) for point in edge["geometry"]]
                if coordinates and coordinates[-1] == points[0]:
                    points = points[1:]
                coordinates.extend(points)
                if edge["name"] not in street_names:
                    street_names.append(edge["name"])
                if edge.get("candidate_id") and edge["candidate_id"] not in candidate_ids:
                    candidate_ids.append(edge["candidate_id"])
            return {
                "length_m": round(distance, 1),
                "node_ids": list(node_ids),
                "edge_ids": list(edge_ids),
                "candidate_ids": candidate_ids,
                "street_names": street_names,
                "geometry": {"type": "LineString", "coordinates": coordinates},
            }
        for edge in adjacency[node_id]:
            next_distance = distance + float(edge["length_m"])
            next_edges = edge_ids + (edge["id"],)
            state = (next_distance, next_edges)
            if edge["v"] not in best or state < best[edge["v"]]:
                best[edge["v"]] = state
                heapq.heappush(
                    queue,
                    (next_distance, next_edges, edge["v"], node_ids + (edge["v"],)),
                )
    return None


def default_portal_pairs(
    portals: Sequence[dict[str, Any]],
    nodes: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]],
) -> list[dict[str, str]]:
    by_side: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for portal in portals:
        by_side[portal["direction"]].append(portal)

    def rank(portal: dict[str, Any]) -> tuple[Any, ...]:
        # Prefer a single, selectable local ingress and avoid protected arteries.
        point = portal["point"]
        axis_distance = abs(point[0] - CENTER[0]) + abs(point[1] - CENTER[1])
        return (
            not bool(portal["adjacent_candidate_ids"]),
            bool(portal["adjacent_protected"]),
            len(portal["node_ids"]),
            len(portal["adjacent_candidate_ids"]),
            axis_distance,
            portal["id"],
        )

    result: list[dict[str, str]] = []
    for first_side, second_side, label in (
        ("north", "south", "North ↔ south permeability"),
        ("west", "east", "West ↔ east permeability"),
    ):
        candidates_a = sorted(by_side[first_side], key=rank)
        candidates_b = sorted(by_side[second_side], key=rank)
        selected = None
        for portal_a in candidates_a:
            for portal_b in candidates_b:
                forward = shortest_route(nodes, edges, portal_a["node_ids"], portal_b["node_ids"])
                reverse = shortest_route(nodes, edges, portal_b["node_ids"], portal_a["node_ids"])
                if forward and reverse and forward["candidate_ids"] and reverse["candidate_ids"]:
                    selected = (portal_a, portal_b)
                    break
            if selected:
                break
        if selected:
            result.append({"a": selected[0]["id"], "b": selected[1]["id"], "label": label})
    if len(result) < 2:
        raise ValueError("Could not choose two connected, blockable opposing default portal pairs")
    return result


def tram_features(
    ways: Sequence[dict[str, Any]],
    nodes: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[LineString]]:
    boundary = box(*BBOX)
    features: list[dict[str, Any]] = []
    lines: list[LineString] = []
    for way in sorted(ways, key=lambda item: int(item["id"])):
        tags = dict(way.get("tags", {}))
        if tags.get("railway") not in {"tram", "light_rail"}:
            continue
        coordinates = coordinates_for_way(way, nodes)
        if len(coordinates) < 2:
            continue
        geometry = LineString(coordinates).intersection(boundary)
        if geometry.is_empty:
            continue
        pieces = [geometry] if geometry.geom_type == "LineString" else list(geometry.geoms)
        for index, piece in enumerate(pieces):
            if piece.geom_type != "LineString" or piece.length == 0:
                continue
            feature_id = f"tram-{int(way['id'])}-{index:02d}"
            features.append(
                {
                    "type": "Feature",
                    "id": feature_id,
                    "properties": {
                        "id": feature_id,
                        "kind": "tram",
                        "railway": tags.get("railway"),
                        "name": tags.get("name") or "Mapped tram infrastructure",
                        "protected": True,
                    },
                    "geometry": mapping(piece),
                }
            )
            lines.append(piece)
    return features, lines


def street_features(physical_edges: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "Feature",
            "id": edge["id"],
            "properties": {
                "id": edge["id"],
                "edge_ids": edge["directed_edge_ids"],
                "candidate_id": edge["candidate_id"],
                "name": edge["name"],
                "highway": edge["highway"],
                "road_class": edge["highway"],
                "hierarchy": edge["hierarchy"],
                "oneway": edge["oneway"] != "both",
                "protected": edge["protected"],
                "eligible_candidate": edge["eligible_candidate"],
                "length_m": edge["length_m"],
            },
            "geometry": {"type": "LineString", "coordinates": edge["geometry"]},
        }
        for edge in sorted(physical_edges, key=lambda item: item["id"])
    ]


def protected_features(
    physical_edges: Sequence[dict[str, Any]], tram: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    roads = [
        {
            "type": "Feature",
            "id": f"protected-{edge['id']}",
            "properties": {
                "id": f"protected-{edge['id']}",
                "kind": "protected_street",
                "name": edge["name"],
                "highway": edge["highway"],
                "reason": edge["protection_reason"],
                "protected": True,
            },
            "geometry": {"type": "LineString", "coordinates": edge["geometry"]},
        }
        for edge in physical_edges
        if edge["protected"]
    ]
    return sorted([*roads, *tram], key=lambda item: str(item["id"]))


def feature_collection(features: Iterable[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": list(features)}


def validate_exports(solver: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    node_ids = [node["id"] for node in solver["nodes"]]
    edge_ids = [edge["id"] for edge in solver["edges"]]
    candidate_ids = [candidate["id"] for candidate in solver["candidates"]]
    portal_ids = [portal["id"] for portal in solver["portals"]]
    if len(node_ids) != len(set(node_ids)):
        errors.append("node IDs are not unique")
    if len(edge_ids) != len(set(edge_ids)):
        errors.append("edge IDs are not unique")
    if len(candidate_ids) != len(set(candidate_ids)):
        errors.append("candidate IDs are not unique")
    if len(portal_ids) != len(set(portal_ids)):
        errors.append("portal IDs are not unique")
    nodes = set(node_ids)
    edges = {edge["id"]: edge for edge in solver["edges"]}
    candidates = {candidate["id"]: candidate for candidate in solver["candidates"]}
    portals = set(portal_ids)
    for edge in edges.values():
        if edge["u"] not in nodes or edge["v"] not in nodes:
            errors.append(f"edge {edge['id']} references a missing node")
        candidate_id = edge.get("candidate_id")
        if candidate_id and candidate_id not in candidates:
            errors.append(f"edge {edge['id']} references missing candidate")
        if edge["protected"] and candidate_id:
            errors.append(f"protected edge {edge['id']} is selectable")
        geometry = shape({"type": "LineString", "coordinates": edge["geometry"]})
        if not geometry.is_valid or geometry.is_empty:
            errors.append(f"edge {edge['id']} has invalid geometry")
    for candidate in candidates.values():
        if not candidate["edge_ids"]:
            errors.append(f"candidate {candidate['id']} has no directed edge")
        for edge_id in candidate["edge_ids"]:
            if edge_id not in edges:
                errors.append(f"candidate {candidate['id']} references missing edge {edge_id}")
            elif edges[edge_id]["protected"]:
                errors.append(f"candidate {candidate['id']} references protected edge {edge_id}")
        if not shape(candidate["cross_geometry"]).is_valid:
            errors.append(f"candidate {candidate['id']} has invalid cross geometry")
    for portal in solver["portals"]:
        if not portal["node_ids"] or not set(portal["node_ids"]).issubset(nodes):
            errors.append(f"portal {portal['id']} has invalid nodes")
    for cluster in solver["address_clusters"]:
        if cluster["node_id"] not in nodes:
            errors.append(f"address cluster {cluster['id']} has invalid snap node")
        if not cluster["allowed_portal_ids"]:
            errors.append(f"address cluster {cluster['id']} has no permitted portal")
        if not set(cluster["allowed_portal_ids"]).issubset(portals):
            errors.append(f"address cluster {cluster['id']} has invalid permitted portal")
    for pair in solver["defaults"]["portal_pairs"]:
        if pair["a"] not in portals or pair["b"] not in portals:
            errors.append("default pair references missing portal")
        portal_a = next(item for item in solver["portals"] if item["id"] == pair["a"])
        portal_b = next(item for item in solver["portals"] if item["id"] == pair["b"])
        if not shortest_route(
            solver["nodes"], solver["edges"], portal_a["node_ids"], portal_b["node_ids"]
        ):
            errors.append(f"default pair {pair['a']} ↔ {pair['b']} has no baseline route")
    for collection_name in ("streets", "buildings", "protected_corridors"):
        for feature in scenario[collection_name]["features"]:
            geometry = shape(feature["geometry"])
            if geometry.is_empty or not geometry.is_valid:
                errors.append(f"{collection_name} feature {feature.get('id')} is invalid")
    if errors:
        raise ValueError("Scenario validation failed:\n- " + "\n- ".join(errors[:50]))
    return {
        "status": "passed",
        "checks": [
            "unique stable identifiers",
            "all graph references resolve",
            "candidate edges are eligible and unprotected",
            "portal and address-cluster graph references resolve",
            "all included address clusters have permitted portals",
            "default portal pairs have baseline directed routes",
            "all exported GeoJSON geometries are non-empty and valid",
        ],
        "counts": {
            "nodes": len(solver["nodes"]),
            "directed_edges": len(solver["edges"]),
            "candidates": len(solver["candidates"]),
            "portals": len(solver["portals"]),
            "address_clusters": len(solver["address_clusters"]),
            "buildings": len(scenario["buildings"]["features"]),
            "protected_features": len(scenario["protected_corridors"]["features"]),
        },
    }


def build(raw: bytes, acquired_at: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    nodes, ways, osm3s = osm_elements(raw)
    project = projection()
    tram_geojson, tram_wgs_lines = tram_features(ways, nodes)
    tram_xy_lines = [project.line_xy(list(line.coords)) for line in tram_wgs_lines]
    physical_edges, crossings = simplify_road_ways(ways, nodes, project, tram_xy_lines)
    solver_nodes, directed_edges, candidates = directed_graph_data(physical_edges, nodes, project)
    portals = cluster_portals(crossings, project, physical_edges)
    buildings_geojson, buildings = building_features(ways, nodes, project)
    clusters = address_clusters(buildings, solver_nodes, portals, project)
    pairs = default_portal_pairs(portals, solver_nodes, directed_edges)
    portal_by_id = {portal["id"]: portal for portal in portals}
    initial_pair = pairs[0]
    initial_route = shortest_route(
        solver_nodes,
        directed_edges,
        portal_by_id[initial_pair["a"]]["node_ids"],
        portal_by_id[initial_pair["b"]]["node_ids"],
    )
    if initial_route is None:
        raise ValueError("Initial through-route could not be derived")

    raw_hash = sha256_bytes(raw)
    snapshot_timestamp = osm3s.get("timestamp_osm_base")
    if not snapshot_timestamp:
        timestamps = [
            element.get("timestamp")
            for element in json.loads(raw).get("elements", [])
            if element.get("timestamp")
        ]
        snapshot_timestamp = max(timestamps)
    snapshot_compact = str(snapshot_timestamp).replace("-", "").replace(":", "").replace("Z", "Z")
    snapshot_id = f"osm-{snapshot_compact}-{raw_hash[:12]}"
    source_query = overpass_query()
    metadata = {
        "scenario_id": SCENARIO_ID,
        "name": SCENARIO_NAME,
        "description": (
            "A frozen, OSM-derived 1.33 km² private-car network covering Kallio, "
            "Alppiharju and western Vallila."
        ),
        "snapshot_id": snapshot_id,
        "snapshot_timestamp": snapshot_timestamp,
        "acquired_at": acquired_at,
        "bbox": list(BBOX),
        "center": list(CENTER),
        "boundary_polygon_wgs84": [
            [BBOX[0], BBOX[1]],
            [BBOX[2], BBOX[1]],
            [BBOX[2], BBOX[3]],
            [BBOX[0], BBOX[3]],
            [BBOX[0], BBOX[1]],
        ],
        "approximate_area_km2": 1.33,
        "analysis_crs": ANALYSIS_CRS,
        "display_crs": DISPLAY_CRS,
        "source": "OpenStreetMap via Overpass API",
        "source_url": OVERPASS_URL,
        "source_query": source_query,
        "source_file": str(SOURCE_PATH.relative_to(ROOT)),
        "source_sha256": raw_hash,
        "attribution": "© OpenStreetMap contributors",
        "license": "Open Data Commons Open Database License (ODbL) 1.0",
        "license_url": "https://www.openstreetmap.org/copyright",
        "pipeline": {
            "script": "scripts/build_scenario.py",
            "python": sys.version.split()[0],
            "networkx": nx.__version__,
            "shapely": shapely.__version__,
            "pyproj": pyproj.__version__,
            "topology": (
                "OSM shape points are collapsed between intersections, way endpoints and boundary "
                "crossings; parallel ways and one-way directions remain distinct."
            ),
        },
        "candidate_policy": {
            "eligible_highways": sorted(CANDIDATE_HIGHWAYS),
            "minimum_segment_length_m": 10,
            "excluded_highways": sorted(PROTECTED_HIGHWAYS),
            "protected_conditions": [
                "motorway, trunk, primary or secondary street and links",
                "explicit bus/PSV lane tags or trolley wire",
                "road geometry following mapped tram/light-rail infrastructure",
                "bridge or tunnel",
            ],
            "semantics": (
                "Each modal filter removes all directed private-car edges represented by its "
                "physical street segment. Walking and cycling remain unchanged; emergency passage "
                "assumes a removable or otherwise permeable treatment."
            ),
        },
        "access_policy": {
            "building_cluster_grid_m": 85,
            "snap_method": "projected representative-point cluster centroid to nearest graph node",
            "permitted_portals": "all mapped boundary portals",
        },
        "portal_policy": {
            "semantics": (
                "Each displayed portal is a contiguous boundary-crossing group. A portal-pair "
                "requirement quantifies over every mapped private-car crossing node in both groups."
            ),
            "grouping": "two spatially contiguous sectors per boundary side",
            "display_point": "the member crossing nearest the group centroid",
            "crossings_retained": "all detected non-service boundary crossing nodes",
        },
        "known_data_scope": [
            "Building ways are included; multipolygon building relations are not expanded.",
            "OSM access tags are interpreted conservatively but may be incomplete or incorrect.",
            (
                "Mapped tram geometry is protected; this is not a complete public-transport "
                "operations model."
            ),
        ],
    }

    solver = {
        "schema_version": "1.0.0",
        "scenario_id": SCENARIO_ID,
        "metadata": metadata,
        "nodes": solver_nodes,
        "edges": directed_edges,
        "candidates": candidates,
        "portals": portals,
        "address_clusters": clusters,
        "defaults": {
            "budget": 4,
            "portal_pairs": pairs,
            "objective_mode": "balanced",
            "timeout_seconds": 10,
            "emergency_permeable": True,
        },
        "mode_assumptions": {
            "private_car": "candidate directed edges are removed when selected",
            "walking": "unchanged by selected modal filters",
            "cycling": "unchanged by selected modal filters",
            "emergency": "passable only under the explicit removable-filter assumption",
            "service": "not enabled by default",
        },
        "objective": {
            "priority": [
                "intervention_count",
                "weighted_intervention_cost",
                "local_access_detour",
                "significantly_affected_clusters",
                "spacing",
            ],
            "candidate_costs": {
                "living_street": 90,
                "residential": 100,
                "unclassified": 115,
            },
        },
    }

    boundary_feature = {
        "type": "Feature",
        "id": "study-boundary",
        "properties": {"id": "study-boundary", "name": SCENARIO_NAME, "area_km2": 1.33},
        "geometry": mapping(box(*BBOX)),
    }
    street_geojson = street_features(physical_edges)
    protected_geojson = protected_features(physical_edges, tram_geojson)
    initial_feature = {
        "type": "Feature",
        "id": "initial-through-route",
        "properties": {
            "portal_pair": {"a": initial_pair["a"], "b": initial_pair["b"]},
            "name": initial_pair["label"],
            "length_m": initial_route["length_m"],
            "street_names": initial_route["street_names"],
            "provenance": "deterministic directed shortest path in the frozen private-car graph",
        },
        "geometry": initial_route["geometry"],
    }
    scenario = {
        "schema_version": "1.0.0",
        "id": SCENARIO_ID,
        "scenario_id": SCENARIO_ID,
        "name": SCENARIO_NAME,
        "description": metadata["description"],
        "snapshot_id": snapshot_id,
        "snapshot_timestamp": snapshot_timestamp,
        "acquired_at": acquired_at,
        "bbox": list(BBOX),
        "center": list(CENTER),
        "analysis_crs": ANALYSIS_CRS,
        "attribution": metadata["attribution"],
        "license": metadata["license"],
        "license_url": metadata["license_url"],
        "source_url": OVERPASS_URL,
        "source": {
            "name": "OpenStreetMap",
            "snapshot_timestamp": snapshot_timestamp,
            "licence": metadata["license"],
            "url": metadata["license_url"],
        },
        "metadata": metadata,
        "boundary": boundary_feature,
        "streets": feature_collection(street_geojson),
        "buildings": feature_collection(buildings_geojson),
        "protected_corridors": feature_collection(protected_geojson),
        "portals": portals,
        "candidates": candidates,
        "address_clusters": clusters,
        "default_portal_pairs": pairs,
        "default_budget": 4,
        "initial_through_route": initial_feature,
        "assumptions": {
            "proof_claim": (
                "Under the current graph, mode, candidate-intervention and portal assumptions, "
                "no private-car route remains between the selected portal pairs."
            ),
            "private_car": "Modal filters remove their selected private-car graph edges.",
            "local_access": (
                "Every included building cluster must retain a directed route to at least one "
                "permitted boundary portal."
            ),
            "walking_cycling": "Selected filters do not remove walking or cycling links.",
            "emergency": (
                "Default results assume removable or emergency-permeable filters; a literal fixed "
                "planter does not satisfy that assumption."
            ),
            "limitations": (
                "This network-permeability result is not a traffic forecast, legal feasibility "
                "assessment, emergency-service approval, or operational traffic plan."
            ),
        },
    }
    combined_features: list[dict[str, Any]] = [
        {
            **boundary_feature,
            "properties": {**boundary_feature["properties"], "layer": "boundary"},
        }
    ]
    for layer_name, features in (
        ("streets", street_geojson),
        ("buildings", buildings_geojson),
        ("protected_corridors", protected_geojson),
    ):
        combined_features.extend(
            {
                **feature,
                "properties": {**feature.get("properties", {}), "layer": layer_name},
            }
            for feature in features
        )
    combined = feature_collection(combined_features)
    validation = validate_exports(solver, scenario)
    metadata_document = {**metadata, "validation": validation}
    return solver, scenario, {"metadata": metadata_document, "combined": combined}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Existing Overpass JSON or .json.gz response")
    parser.add_argument(
        "--refresh", action="store_true", help="Fetch a new bounded Overpass response"
    )
    parser.add_argument(
        "--archive-source",
        action="store_true",
        help="Archive --input as the default reproducible compressed source",
    )
    parser.add_argument("--acquired-at", help="Override acquisition timestamp (ISO 8601)")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw, acquired_at = source_bytes(args)
    solver, scenario, extra = build(raw, acquired_at)
    output_dir: Path = args.output_dir
    if not args.validate_only:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "solver.json", solver, compact=True)
        write_json(output_dir / "scenario.json", scenario, compact=True)
        write_json(output_dir / "scenario.geojson", extra["combined"], compact=True)
        write_json(output_dir / "metadata.json", extra["metadata"])
    counts = extra["metadata"]["validation"]["counts"]
    print(
        f"{SCENARIO_ID}: validation passed; "
        + ", ".join(f"{key}={value}" for key, value in counts.items())
    )
    print(f"snapshot={solver['metadata']['snapshot_id']}")
    if not args.validate_only:
        print(f"wrote {output_dir}")


if __name__ == "__main__":
    main()
