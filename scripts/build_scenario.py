#!/usr/bin/env python3
"""Build the frozen Kallio--Vallila modal-filter experiment scenario.

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
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import transform, unary_union

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
PORTAL_CLUSTER_MAX_DIAMETER_M = 60.0
PRIMARY_PORTALS_PER_SIDE = 2
CANDIDATE_BOUNDARY_SETBACK_M = 60.0
CANDIDATE_BOUNDARY_DISTANCE_METRIC = "projected_candidate_display_point_to_study_boundary"
PRIMARY_PORTAL_APPROACH_SETBACK_M = 120.0
PRIMARY_PORTAL_DISTANCE_METRIC = (
    "projected_candidate_display_point_to_nearest_primary_portal_crossing"
)
AUDITED_DEFAULT_PORTAL_PAIRS = (
    {
        "a": "p-east-01",
        "b": "p-south-04",
        "label": "Southern cross-neighbourhood permeability",
    },
    {
        "a": "p-north-03",
        "b": "p-west-01",
        "label": "Western cross-neighbourhood permeability",
    },
)
ACCESS_PENALTY_METRIC = "baseline_shortest_egress_route_cluster_count"
ACCESS_PENALTY_DEFINITION = (
    "Count of address clusters whose deterministic baseline directed shortest route from the "
    "cluster's snapped graph node to any permitted boundary portal traverses this candidate. "
    "Equal-distance routes are resolved lexicographically by stable edge-ID sequence; a cluster "
    "already snapped to a permitted portal has zero-length egress and contributes no exposure."
)

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
            "User-Agent": "Geospatial-Constraint-Lab/0.1 reproducible-research-scenario",
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


def orient_polygonal(geometry: Any) -> Any:
    """Apply RFC 7946 winding to polygonal geometry without changing its parts."""

    if geometry.geom_type == "Polygon":
        return orient(geometry, sign=1.0)
    if geometry.geom_type == "MultiPolygon":
        return MultiPolygon([orient(polygon, sign=1.0) for polygon in geometry.geoms])
    raise ValueError(f"Expected polygonal geometry, got {geometry.geom_type}")


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
    boundary_xy = transform_geometry(box(*BBOX), project.forward)

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
                display_point_xy = line_xy.interpolate(line_xy.length / 2)
                boundary_distance_m = display_point_xy.distance(boundary_xy.boundary)
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
                base_candidate_eligible = (
                    tags.get("highway") in CANDIDATE_HIGHWAYS
                    and not protected
                    and tags.get("bridge") in {None, "no"}
                    and tags.get("tunnel") in {None, "no"}
                    and line_xy.length >= 10
                )
                terminal_zone_ineligible = (
                    base_candidate_eligible and boundary_distance_m < CANDIDATE_BOUNDARY_SETBACK_M
                )
                candidate_eligible = base_candidate_eligible and not terminal_zone_ineligible
                base_candidate_ineligibility_reason = reason
                candidate_ineligibility_reason = base_candidate_ineligibility_reason
                if terminal_zone_ineligible:
                    candidate_ineligibility_reason = (
                        f"Within the {CANDIDATE_BOUNDARY_SETBACK_M:g} m analysis-boundary "
                        "terminal zone"
                    )
                elif not candidate_eligible and candidate_ineligibility_reason is None:
                    if tags.get("highway") not in CANDIDATE_HIGHWAYS:
                        candidate_ineligibility_reason = "Street class excluded from candidate set"
                    elif line_xy.length < 10:
                        candidate_ineligibility_reason = "Segment shorter than 10 m"
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
                        "base_candidate_ineligibility_reason": (
                            base_candidate_ineligibility_reason
                        ),
                        "candidate_ineligibility_reason": candidate_ineligibility_reason,
                        "boundary_distance_m": round(boundary_distance_m, 1),
                        "boundary_distance_metric": CANDIDATE_BOUNDARY_DISTANCE_METRIC,
                        "terminal_zone_ineligible": terminal_zone_ineligible,
                        "nearest_primary_portal_distance_m": None,
                        "nearest_primary_portal_distance_metric": PRIMARY_PORTAL_DISTANCE_METRIC,
                        "nearest_primary_portal_id": None,
                        "nearest_primary_portal_crossing_id": None,
                        "primary_portal_approach_ineligible": False,
                        "base_candidate_eligible": base_candidate_eligible,
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


def primary_portal_crossing_points(
    primary_portals: Sequence[dict[str, Any]], project: Projection
) -> list[dict[str, Any]]:
    """Return stable projected crossing points for the eight selectable portals."""

    records = [
        {
            "portal_id": portal["id"],
            "crossing_id": crossing["id"],
            "point_xy": Point(project.forward.transform(*crossing["point"])),
        }
        for portal in primary_portals
        for crossing in portal["member_crossings"]
    ]
    records.sort(key=lambda item: (item["portal_id"], item["crossing_id"]))
    if not records:
        raise ValueError("Primary portal selection has no crossing points")
    return records


def apply_primary_portal_approach_setback(
    physical_edges: list[dict[str, Any]],
    primary_portals: Sequence[dict[str, Any]],
    project: Projection,
) -> None:
    """Exclude base-eligible segment midpoints near any selectable portal crossing.

    The eight primary portals are selected before this rule is applied.  This keeps
    portal identities stable and prevents the exclusion itself from changing which
    portals define the exclusion.  Distances are Euclidean in EPSG:3067 and use the
    actual member crossing points, never the portal's display marker or centroid.
    """

    crossing_points = primary_portal_crossing_points(primary_portals, project)
    for physical in sorted(physical_edges, key=lambda item: item["id"]):
        line = physical["geometry_xy"]
        midpoint = line.interpolate(line.length / 2)
        nearest = min(
            crossing_points,
            key=lambda item: (
                midpoint.distance(item["point_xy"]),
                item["portal_id"],
                item["crossing_id"],
            ),
        )
        distance_m = midpoint.distance(nearest["point_xy"])
        approach_ineligible = bool(
            physical["base_candidate_eligible"] and distance_m < PRIMARY_PORTAL_APPROACH_SETBACK_M
        )
        terminal_ineligible = bool(physical["terminal_zone_ineligible"])
        physical["nearest_primary_portal_distance_m"] = round(distance_m, 1)
        physical["nearest_primary_portal_distance_metric"] = PRIMARY_PORTAL_DISTANCE_METRIC
        physical["nearest_primary_portal_id"] = nearest["portal_id"]
        physical["nearest_primary_portal_crossing_id"] = nearest["crossing_id"]
        physical["primary_portal_approach_ineligible"] = approach_ineligible
        physical["eligible_candidate"] = bool(
            physical["base_candidate_eligible"]
            and not terminal_ineligible
            and not approach_ineligible
        )
        if not physical["base_candidate_eligible"]:
            continue
        if terminal_ineligible and approach_ineligible:
            physical["candidate_ineligibility_reason"] = (
                f"Within both the {CANDIDATE_BOUNDARY_SETBACK_M:g} m analysis-boundary "
                f"terminal zone and the {PRIMARY_PORTAL_APPROACH_SETBACK_M:g} m primary-portal "
                "approach zone"
            )
        elif terminal_ineligible:
            physical["candidate_ineligibility_reason"] = (
                f"Within the {CANDIDATE_BOUNDARY_SETBACK_M:g} m analysis-boundary terminal zone"
            )
        elif approach_ineligible:
            physical["candidate_ineligibility_reason"] = (
                f"Within the {PRIMARY_PORTAL_APPROACH_SETBACK_M:g} m primary-portal approach zone"
            )
        else:
            physical["candidate_ineligibility_reason"] = None


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
                    "candidate_ineligibility_reason": physical["candidate_ineligibility_reason"],
                    "boundary_distance_m": physical["boundary_distance_m"],
                    "boundary_distance_metric": physical["boundary_distance_metric"],
                    "terminal_zone_ineligible": physical["terminal_zone_ineligible"],
                    "nearest_primary_portal_distance_m": physical[
                        "nearest_primary_portal_distance_m"
                    ],
                    "nearest_primary_portal_distance_metric": physical[
                        "nearest_primary_portal_distance_metric"
                    ],
                    "nearest_primary_portal_id": physical["nearest_primary_portal_id"],
                    "nearest_primary_portal_crossing_id": physical[
                        "nearest_primary_portal_crossing_id"
                    ],
                    "primary_portal_approach_ineligible": physical[
                        "primary_portal_approach_ineligible"
                    ],
                    "base_candidate_eligible": physical["base_candidate_eligible"],
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
                    "eligible_candidate": True,
                    "base_candidate_eligible": True,
                    "candidate_ineligibility_reason": None,
                    "boundary_distance_m": physical["boundary_distance_m"],
                    "boundary_distance_metric": physical["boundary_distance_metric"],
                    "terminal_zone_ineligible": False,
                    "nearest_primary_portal_distance_m": physical[
                        "nearest_primary_portal_distance_m"
                    ],
                    "nearest_primary_portal_distance_metric": physical[
                        "nearest_primary_portal_distance_metric"
                    ],
                    "nearest_primary_portal_id": physical["nearest_primary_portal_id"],
                    "nearest_primary_portal_crossing_id": physical[
                        "nearest_primary_portal_crossing_id"
                    ],
                    "primary_portal_approach_ineligible": False,
                    "blocks_modes": ["private_car"],
                    "passes_modes": ["walking", "cycling", "emergency"],
                }
            )
    return solver_nodes, directed_edges, candidates


def annotate_portal_adjacency(
    portals: Sequence[dict[str, Any]], physical_edges: Sequence[dict[str, Any]]
) -> None:
    """Refresh portal-neighbour provenance after each candidate-policy stage."""

    incident: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in physical_edges:
        incident[f"n{edge['u_osm']}"].append(edge)
        incident[f"n{edge['v_osm']}"].append(edge)
    for portal in portals:
        adjacent = [edge for node_id in portal["node_ids"] for edge in incident[node_id]]
        portal["adjacent_candidate_ids"] = sorted(
            {edge["candidate_id"] for edge in adjacent if edge.get("candidate_id")}
        )
        portal["adjacent_local_candidate_segment_ids"] = sorted(
            {edge["id"] for edge in adjacent if edge.get("base_candidate_eligible")}
        )
        portal["adjacent_terminal_zone_segment_ids"] = sorted(
            {edge["id"] for edge in adjacent if edge.get("terminal_zone_ineligible")}
        )
        portal["adjacent_primary_portal_approach_segment_ids"] = sorted(
            {edge["id"] for edge in adjacent if edge.get("primary_portal_approach_ineligible")}
        )
        portal["adjacent_protected"] = any(edge["protected"] for edge in adjacent)


def cluster_portals(
    crossing_records: Sequence[dict[str, Any]],
    project: Projection,
    physical_edges: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Create physically local portal clusters and retain every crossing record.

    Portal semantics are analytical, so visual marker count must not determine
    membership.  Crossings are first separated by boundary side and then put in
    deterministic contiguous complete-link clusters: a new crossing may join a
    cluster only when it lies within ``PORTAL_CLUSTER_MAX_DIAMETER_M`` of every
    existing member.  This prevents the former half-side sectors from silently
    treating streets hundreds of metres apart as one portal.
    """
    boundary_xy = transform_geometry(box(*BBOX), project.forward)
    by_side: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in sorted(
        crossing_records,
        key=lambda item: (item["way_id"], item["node_id"], tuple(item["point"])),
    ):
        x, y = project.point_xy(record["point"])
        enriched = {**record, "point_xy": Point(x, y)}
        enriched["side"] = boundary_side(enriched["point_xy"], boundary_xy)
        enriched["crossing_id"] = f"x-{record['way_id']}-{record['node_id']}"
        by_side[enriched["side"]].append(enriched)

    clusters: list[dict[str, Any]] = []
    crossing_exports: list[dict[str, Any]] = []
    for side in ("north", "east", "south", "west"):
        records = by_side[side]
        records.sort(
            key=lambda item: (
                item["point_xy"].x if side in {"north", "south"} else item["point_xy"].y,
                item["way_id"],
                item["node_id"],
            )
        )
        side_clusters: list[list[dict[str, Any]]] = []
        for record in records:
            if not side_clusters or any(
                record["point_xy"].distance(member["point_xy"]) > PORTAL_CLUSTER_MAX_DIAMETER_M
                for member in side_clusters[-1]
            ):
                side_clusters.append([record])
            else:
                side_clusters[-1].append(record)
        for index, members in enumerate(side_clusters, start=1):
            x = sum(item["point_xy"].x for item in members) / len(members)
            y = sum(item["point_xy"].y for item in members) / len(members)
            representative = min(
                members,
                key=lambda item: (item["point_xy"].distance(Point(x, y)), item["node_id"]),
            )
            names = sorted({item["name"] for item in members})
            primary_name = representative["name"]
            portal_id = f"p-{side}-{index:02d}"
            maximum_diameter = max(
                (
                    first["point_xy"].distance(second["point_xy"])
                    for member_index, first in enumerate(members)
                    for second in members[member_index + 1 :]
                ),
                default=0.0,
            )
            member_crossings: list[dict[str, Any]] = []
            for item in sorted(members, key=lambda value: value["crossing_id"]):
                exported = {
                    "id": item["crossing_id"],
                    "portal_id": portal_id,
                    "side": side,
                    "node_id": f"n{item['node_id']}",
                    "osm_node_id": item["node_id"],
                    "osm_way_id": item["way_id"],
                    "point": list(item["point"]),
                    "street_name": item["name"],
                    "highway": item["highway"],
                    "travel_direction": item["direction"],
                    "inside_after": item["inside_after"],
                }
                member_crossings.append(exported)
                crossing_exports.append(exported)
            clusters.append(
                {
                    "id": portal_id,
                    "label": f"{side.title()} boundary · {primary_name}",
                    "direction": side,
                    "side": side,
                    "node_ids": sorted({f"n{item['node_id']}" for item in members}),
                    "display_point": list(representative["point"]),
                    "point": list(representative["point"]),
                    "group_centroid": project.point_lonlat((x, y)),
                    "crossing_count": len(member_crossings),
                    "crossing_ids": [item["id"] for item in member_crossings],
                    "member_crossings": member_crossings,
                    "street_names": names,
                    "local_street_names": sorted(
                        {
                            item["name"]
                            for item in members
                            if item["highway"] in CANDIDATE_HIGHWAYS
                            and item["name"] != "Unnamed street"
                        }
                    ),
                    "highways": sorted({item["highway"] for item in members}),
                    "crossing_way_ids": sorted({item["way_id"] for item in members}),
                    "maximum_diameter_m": round(maximum_diameter, 1),
                    "primary": False,
                    "selectable": False,
                }
            )

    # Selectable portals are ranked from pre-approach-setback local eligibility.
    # This prevents the analytical anti-cap rule from changing the IDs that define it.
    annotate_portal_adjacency(clusters, physical_edges)
    return (
        sorted(clusters, key=lambda item: (item["direction"], item["id"])),
        sorted(crossing_exports, key=lambda item: item["id"]),
    )


def select_primary_portals(
    portals: list[dict[str, Any]], project: Projection
) -> list[dict[str, Any]]:
    """Mark two spatially distributed, inspectable portal clusters per side."""

    primary: list[dict[str, Any]] = []
    for side in ("north", "east", "south", "west"):
        axis = 0 if side in {"north", "south"} else 1
        side_portals = sorted(
            (portal for portal in portals if portal["side"] == side),
            key=lambda portal: (project.point_xy(portal["group_centroid"])[axis], portal["id"]),
        )
        if len(side_portals) < PRIMARY_PORTALS_PER_SIDE:
            raise ValueError(f"Boundary side {side} has fewer than two analytical portals")
        positions = [project.point_xy(portal["group_centroid"])[axis] for portal in side_portals]
        midpoint = (positions[0] + positions[-1]) / 2
        halves = [
            [
                portal
                for portal in side_portals
                if project.point_xy(portal["group_centroid"])[axis] <= midpoint
            ],
            [
                portal
                for portal in side_portals
                if project.point_xy(portal["group_centroid"])[axis] > midpoint
            ],
        ]
        if not all(halves):
            split = len(side_portals) // 2
            halves = [side_portals[:split], side_portals[split:]]
        targets = [
            positions[0] + (positions[-1] - positions[0]) * 0.25,
            positions[0] + (positions[-1] - positions[0]) * 0.75,
        ]

        def rank(portal: dict[str, Any], target: float, axis_index: int = axis) -> tuple[Any, ...]:
            named_local = bool(portal.get("local_street_names"))
            coordinate = project.point_xy(portal["group_centroid"])[axis_index]
            return (
                not named_local,
                not bool(portal["adjacent_local_candidate_segment_ids"]),
                bool(portal["adjacent_protected"]),
                abs(coordinate - target),
                portal["maximum_diameter_m"],
                portal["id"],
            )

        chosen = [
            min(half, key=lambda portal, i=i: rank(portal, targets[i]))
            for i, half in enumerate(halves)
        ]
        chosen.sort(key=lambda portal: project.point_xy(portal["group_centroid"])[axis])
        for index, portal in enumerate(chosen, start=1):
            sector = {
                ("north", 1): "North-west",
                ("north", 2): "North-east",
                ("south", 1): "South-west",
                ("south", 2): "South-east",
                ("east", 1): "East-south",
                ("east", 2): "East-north",
                ("west", 1): "West-south",
                ("west", 2): "West-north",
            }[(side, index)]
            portal["primary"] = True
            portal["selectable"] = True
            portal["primary_order"] = index
            display_name = next(
                iter(portal.get("local_street_names") or portal["street_names"]),
                "Unnamed access",
            )
            portal["label"] = f"{sector} · {display_name}"
            primary.append(portal)
    if len(primary) != PRIMARY_PORTALS_PER_SIDE * 4:
        raise ValueError("Primary portal selection did not produce exactly eight portals")
    return sorted(primary, key=lambda item: (item["direction"], item["primary_order"], item["id"]))


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


def assign_candidate_access_penalties(
    candidates: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    portals: Sequence[dict[str, Any]],
    nodes: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]],
) -> None:
    """Attach a deterministic baseline-egress exposure proxy to each candidate.

    This is deliberately not an estimate of post-filter detour.  For each address
    cluster, one baseline shortest directed route to any permitted portal is chosen
    using :func:`shortest_route`'s stable edge-ID tie-break.  Every candidate on that
    route receives one unit of exposure.  The final solver result separately computes
    actual shortest-path detours after applying the complete intervention set.
    """

    candidate_by_id = {candidate["id"]: candidate for candidate in candidates}
    portal_by_id = {portal["id"]: portal for portal in portals}
    cluster_usage: dict[str, list[str]] = {candidate_id: [] for candidate_id in candidate_by_id}

    for cluster in sorted(clusters, key=lambda item: item["id"]):
        target_nodes = sorted(
            {
                node_id
                for portal_id in cluster["allowed_portal_ids"]
                if portal_id in portal_by_id
                for node_id in portal_by_id[portal_id]["node_ids"]
            }
        )
        already_at_permitted_portal = cluster["node_id"] in target_nodes
        if already_at_permitted_portal:
            route = {
                "length_m": 0.0,
                "node_ids": [cluster["node_id"]],
                "candidate_ids": [],
            }
        else:
            route = shortest_route(nodes, edges, [cluster["node_id"]], target_nodes)
            if route is None:
                raise ValueError(
                    f"Address cluster {cluster['id']} has no baseline route to a permitted portal"
                )
        route_candidate_ids = sorted(set(route["candidate_ids"]))
        unknown = set(route_candidate_ids) - set(candidate_by_id)
        if unknown:
            raise ValueError(
                f"Address cluster {cluster['id']} baseline route references unknown candidates "
                f"{sorted(unknown)}"
            )
        terminal_node_id = route["node_ids"][-1]
        reached_portal_ids = sorted(
            portal_id
            for portal_id in cluster["allowed_portal_ids"]
            if portal_id in portal_by_id and terminal_node_id in portal_by_id[portal_id]["node_ids"]
        )
        cluster["baseline_egress"] = {
            "length_m": route["length_m"],
            "portal_id": reached_portal_ids[0] if reached_portal_ids else None,
            "source_node_id": cluster["node_id"],
            "terminal_node_id": terminal_node_id,
            "candidate_ids": route_candidate_ids,
            "metric": ACCESS_PENALTY_METRIC,
            "already_at_permitted_portal": already_at_permitted_portal,
        }
        for candidate_id in route_candidate_ids:
            cluster_usage[candidate_id].append(cluster["id"])

    for candidate_id, candidate in sorted(candidate_by_id.items()):
        affected_cluster_ids = sorted(cluster_usage[candidate_id])
        candidate["access_penalty"] = len(affected_cluster_ids)
        candidate["access_penalty_metric"] = ACCESS_PENALTY_METRIC
        candidate["access_penalty_cluster_ids"] = affected_cluster_ids


def default_portal_pairs(
    portals: Sequence[dict[str, Any]],
    nodes: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]],
) -> list[dict[str, str]]:
    """Return the scenario's explicitly audited, non-terminal default pairs.

    Automatic ranking previously favoured portal throats that could be capped by a
    filter almost on the analysis boundary.  The audited IDs below stay stable with
    the frozen snapshot, while these checks ensure preprocessing fails loudly if a
    future source refresh changes their primary status or removes every candidate
    from either directional baseline shortest route. Full feasibility is established
    later by the solver and independent graph verifier, not by this route audit.
    """

    portal_by_id = {portal["id"]: portal for portal in portals}
    result: list[dict[str, str]] = []
    for pair in AUDITED_DEFAULT_PORTAL_PAIRS:
        portal_a = portal_by_id.get(pair["a"])
        portal_b = portal_by_id.get(pair["b"])
        if portal_a is None or portal_b is None:
            raise ValueError(f"Audited default portal pair is missing: {pair['a']} ↔ {pair['b']}")
        if not portal_a.get("primary") or not portal_b.get("primary"):
            raise ValueError(
                f"Audited default portal pair is no longer primary: {pair['a']} ↔ {pair['b']}"
            )
        forward = shortest_route(nodes, edges, portal_a["node_ids"], portal_b["node_ids"])
        reverse = shortest_route(nodes, edges, portal_b["node_ids"], portal_a["node_ids"])
        if (
            not forward
            or not reverse
            or not forward["candidate_ids"]
            or not reverse["candidate_ids"]
        ):
            raise ValueError(
                "Audited default pair lacks a candidate-bearing baseline route in "
                f"both directions: {pair['a']} ↔ {pair['b']}"
            )
        result.append(dict(pair))
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
                "candidate_ineligibility_reason": edge["candidate_ineligibility_reason"],
                "boundary_distance_m": edge["boundary_distance_m"],
                "boundary_distance_metric": edge["boundary_distance_metric"],
                "terminal_zone_ineligible": edge["terminal_zone_ineligible"],
                "nearest_primary_portal_distance_m": edge["nearest_primary_portal_distance_m"],
                "nearest_primary_portal_distance_metric": edge[
                    "nearest_primary_portal_distance_metric"
                ],
                "nearest_primary_portal_id": edge["nearest_primary_portal_id"],
                "nearest_primary_portal_crossing_id": edge["nearest_primary_portal_crossing_id"],
                "primary_portal_approach_ineligible": edge["primary_portal_approach_ineligible"],
                "base_candidate_eligible": edge["base_candidate_eligible"],
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
    address_cluster_ids = [cluster["id"] for cluster in solver["address_clusters"]]
    crossing_ids = [crossing["id"] for crossing in solver.get("boundary_crossings", [])]
    primary_portal_ids = list(solver.get("primary_portal_ids", []))
    if len(node_ids) != len(set(node_ids)):
        errors.append("node IDs are not unique")
    if len(edge_ids) != len(set(edge_ids)):
        errors.append("edge IDs are not unique")
    if len(candidate_ids) != len(set(candidate_ids)):
        errors.append("candidate IDs are not unique")
    if len(portal_ids) != len(set(portal_ids)):
        errors.append("portal IDs are not unique")
    if len(address_cluster_ids) != len(set(address_cluster_ids)):
        errors.append("address-cluster IDs are not unique")
    if len(crossing_ids) != len(set(crossing_ids)):
        errors.append("boundary-crossing IDs are not unique")
    nodes = set(node_ids)
    edges = {edge["id"]: edge for edge in solver["edges"]}
    candidates = {candidate["id"]: candidate for candidate in solver["candidates"]}
    portals = set(portal_ids)
    portal_by_id = {portal["id"]: portal for portal in solver["portals"]}
    address_clusters = set(address_cluster_ids)
    crossings = set(crossing_ids)
    expected_candidate_usage: dict[str, list[str]] = defaultdict(list)
    validation_projection = projection()
    analysis_polygon_xy = transform_geometry(
        shape(scenario["boundary"]["geometry"]), validation_projection.forward
    )
    analysis_boundary_xy = analysis_polygon_xy.boundary
    primary_portal_records = [
        portal_by_id[portal_id] for portal_id in primary_portal_ids if portal_id in portal_by_id
    ]
    primary_crossing_points = primary_portal_crossing_points(
        primary_portal_records, validation_projection
    )
    primary_crossing_by_id = {record["crossing_id"]: record for record in primary_crossing_points}
    primary_crossing_ids = sorted(primary_crossing_by_id)
    candidate_policy = solver.get("metadata", {}).get("candidate_policy", {})
    if candidate_policy.get("analysis_boundary_setback_m") != CANDIDATE_BOUNDARY_SETBACK_M:
        errors.append("candidate-policy boundary setback disagrees with the build constant")
    if candidate_policy.get("boundary_distance_metric") != CANDIDATE_BOUNDARY_DISTANCE_METRIC:
        errors.append("candidate-policy boundary metric disagrees with the build constant")
    if (
        candidate_policy.get("primary_portal_approach_setback_m")
        != PRIMARY_PORTAL_APPROACH_SETBACK_M
    ):
        errors.append("candidate-policy portal setback disagrees with the build constant")
    if (
        candidate_policy.get("nearest_primary_portal_distance_metric")
        != PRIMARY_PORTAL_DISTANCE_METRIC
    ):
        errors.append("candidate-policy portal metric disagrees with the build constant")
    for cluster in solver["address_clusters"]:
        baseline = cluster.get("baseline_egress", {})
        permitted_target_nodes = {
            node_id
            for portal_id in cluster.get("allowed_portal_ids", [])
            if portal_id in portal_by_id
            for node_id in portal_by_id[portal_id]["node_ids"]
        }
        expected_at_portal = cluster["node_id"] in permitted_target_nodes
        if baseline.get("metric") != ACCESS_PENALTY_METRIC:
            errors.append(f"address cluster {cluster['id']} has an invalid access proxy metric")
        if baseline.get("source_node_id") != cluster["node_id"]:
            errors.append(f"address cluster {cluster['id']} has an invalid egress source node")
        if baseline.get("terminal_node_id") not in nodes:
            errors.append(f"address cluster {cluster['id']} has an invalid egress terminal node")
        if baseline.get("portal_id") not in cluster.get("allowed_portal_ids", []):
            errors.append(f"address cluster {cluster['id']} has an invalid baseline egress portal")
        elif (
            baseline.get("terminal_node_id") not in portal_by_id[baseline["portal_id"]]["node_ids"]
        ):
            errors.append(f"address cluster {cluster['id']} egress terminal and portal disagree")
        if float(baseline.get("length_m", -1)) < 0:
            errors.append(f"address cluster {cluster['id']} has an invalid baseline egress length")
        baseline_candidate_ids = list(baseline.get("candidate_ids", []))
        if len(baseline_candidate_ids) != len(set(baseline_candidate_ids)):
            errors.append(f"address cluster {cluster['id']} repeats a baseline route candidate")
        if not set(baseline_candidate_ids).issubset(candidates):
            errors.append(
                f"address cluster {cluster['id']} has an unknown baseline route candidate"
            )
        if bool(baseline.get("already_at_permitted_portal")) != expected_at_portal:
            errors.append(f"address cluster {cluster['id']} has an invalid portal-snap flag")
        if expected_at_portal and (
            float(baseline.get("length_m", -1)) != 0
            or baseline.get("terminal_node_id") != cluster["node_id"]
            or baseline_candidate_ids
        ):
            errors.append(
                f"address cluster {cluster['id']} portal snap is not zero-length and exposure-free"
            )
        for candidate_id in baseline_candidate_ids:
            expected_candidate_usage[candidate_id].append(cluster["id"])
    for edge in edges.values():
        if edge["u"] not in nodes or edge["v"] not in nodes:
            errors.append(f"edge {edge['id']} references a missing node")
        candidate_id = edge.get("candidate_id")
        if candidate_id and candidate_id not in candidates:
            errors.append(f"edge {edge['id']} references missing candidate")
        if edge["protected"] and candidate_id:
            errors.append(f"protected edge {edge['id']} is selectable")
        if edge.get("boundary_distance_metric") != CANDIDATE_BOUNDARY_DISTANCE_METRIC:
            errors.append(f"edge {edge['id']} has an invalid boundary-distance metric")
        geometry = shape({"type": "LineString", "coordinates": edge["geometry"]})
        if not geometry.is_valid or geometry.is_empty:
            errors.append(f"edge {edge['id']} has invalid geometry")
            continue
        geometry_xy = transform_geometry(geometry, validation_projection.forward)
        midpoint_xy = geometry_xy.interpolate(geometry_xy.length / 2)
        reconstructed_boundary_distance = midpoint_xy.distance(analysis_boundary_xy)
        if abs(float(edge.get("boundary_distance_m", -1)) - reconstructed_boundary_distance) > 0.2:
            errors.append(f"edge {edge['id']} boundary-distance provenance disagrees")
        nearest_primary = min(
            primary_crossing_points,
            key=lambda item: (
                midpoint_xy.distance(item["point_xy"]),
                item["portal_id"],
                item["crossing_id"],
            ),
        )
        reconstructed_primary_distance = midpoint_xy.distance(nearest_primary["point_xy"])
        if edge.get("nearest_primary_portal_distance_metric") != PRIMARY_PORTAL_DISTANCE_METRIC:
            errors.append(f"edge {edge['id']} has an invalid primary-portal distance metric")
        if (
            abs(
                float(edge.get("nearest_primary_portal_distance_m", -1))
                - reconstructed_primary_distance
            )
            > 0.2
        ):
            errors.append(f"edge {edge['id']} primary-portal distance provenance disagrees")
        if edge.get("nearest_primary_portal_id") != nearest_primary["portal_id"]:
            errors.append(f"edge {edge['id']} has the wrong nearest primary portal")
        if edge.get("nearest_primary_portal_crossing_id") != nearest_primary["crossing_id"]:
            errors.append(f"edge {edge['id']} has the wrong nearest primary crossing")
        expected_terminal_ineligible = bool(
            edge.get("base_candidate_eligible")
            and reconstructed_boundary_distance < CANDIDATE_BOUNDARY_SETBACK_M
        )
        expected_approach_ineligible = bool(
            edge.get("base_candidate_eligible")
            and reconstructed_primary_distance < PRIMARY_PORTAL_APPROACH_SETBACK_M
        )
        if bool(edge.get("terminal_zone_ineligible")) != expected_terminal_ineligible:
            errors.append(f"edge {edge['id']} has the wrong terminal-zone flag")
        if bool(edge.get("primary_portal_approach_ineligible")) != expected_approach_ineligible:
            errors.append(f"edge {edge['id']} has the wrong portal-approach flag")
        if edge.get("terminal_zone_ineligible"):
            if candidate_id or edge["protected"]:
                errors.append(
                    f"terminal-zone edge {edge['id']} is selectable or mislabelled protected"
                )
            if float(edge.get("boundary_distance_m", math.inf)) >= (
                CANDIDATE_BOUNDARY_SETBACK_M + 0.1
            ):
                errors.append(f"terminal-zone edge {edge['id']} lies outside the setback")
            if "analysis-boundary terminal zone" not in str(
                edge.get("candidate_ineligibility_reason")
            ):
                errors.append(f"terminal-zone edge {edge['id']} lacks its ineligibility reason")
        if edge.get("primary_portal_approach_ineligible"):
            if candidate_id or edge["protected"]:
                errors.append(
                    f"portal-approach edge {edge['id']} is selectable or mislabelled protected"
                )
            if float(edge.get("nearest_primary_portal_distance_m", math.inf)) >= (
                PRIMARY_PORTAL_APPROACH_SETBACK_M + 0.1
            ):
                errors.append(f"portal-approach edge {edge['id']} lies outside the setback")
            if "primary-portal approach zone" not in str(
                edge.get("candidate_ineligibility_reason")
            ):
                errors.append(f"portal-approach edge {edge['id']} lacks its ineligibility reason")
        expected_candidate = bool(
            edge.get("base_candidate_eligible")
            and not expected_terminal_ineligible
            and not expected_approach_ineligible
        )
        if bool(candidate_id) != expected_candidate:
            errors.append(f"edge {edge['id']} has inconsistent final candidate eligibility")
        if not edge.get("base_candidate_eligible") and (
            candidate_id
            or edge.get("terminal_zone_ineligible")
            or edge.get("primary_portal_approach_ineligible")
        ):
            errors.append(f"base-ineligible edge {edge['id']} has candidate eligibility")
    for candidate in candidates.values():
        if not candidate["edge_ids"]:
            errors.append(f"candidate {candidate['id']} has no directed edge")
        for edge_id in candidate["edge_ids"]:
            if edge_id not in edges:
                errors.append(f"candidate {candidate['id']} references missing edge {edge_id}")
            elif edges[edge_id]["protected"]:
                errors.append(f"candidate {candidate['id']} references protected edge {edge_id}")
            elif edges[edge_id].get("boundary_distance_m") != candidate.get(
                "boundary_distance_m"
            ) or edges[edge_id].get("boundary_distance_metric") != candidate.get(
                "boundary_distance_metric"
            ):
                errors.append(
                    f"candidate {candidate['id']} boundary distance differs from edge {edge_id}"
                )
            elif any(
                edges[edge_id].get(field) != candidate.get(field)
                for field in (
                    "candidate_ineligibility_reason",
                    "terminal_zone_ineligible",
                    "nearest_primary_portal_distance_m",
                    "nearest_primary_portal_distance_metric",
                    "nearest_primary_portal_id",
                    "nearest_primary_portal_crossing_id",
                    "primary_portal_approach_ineligible",
                    "base_candidate_eligible",
                )
            ):
                errors.append(
                    f"candidate {candidate['id']} primary-portal provenance differs from "
                    f"edge {edge_id}"
                )
        if not shape(candidate["cross_geometry"]).is_valid:
            errors.append(f"candidate {candidate['id']} has invalid cross geometry")
        if candidate.get("boundary_distance_metric") != CANDIDATE_BOUNDARY_DISTANCE_METRIC:
            errors.append(f"candidate {candidate['id']} has an invalid boundary-distance metric")
        exported_distance = float(candidate.get("boundary_distance_m", -1))
        candidate_point_xy = transform_geometry(
            Point(candidate["display_point"]), validation_projection.forward
        )
        reconstructed_distance = candidate_point_xy.distance(analysis_boundary_xy)
        if exported_distance < CANDIDATE_BOUNDARY_SETBACK_M:
            errors.append(f"candidate {candidate['id']} violates the boundary setback")
        if abs(exported_distance - reconstructed_distance) > 0.2:
            errors.append(f"candidate {candidate['id']} boundary-distance provenance disagrees")
        nearest_primary = min(
            primary_crossing_points,
            key=lambda item: (
                candidate_point_xy.distance(item["point_xy"]),
                item["portal_id"],
                item["crossing_id"],
            ),
        )
        reconstructed_primary_distance = candidate_point_xy.distance(nearest_primary["point_xy"])
        if (
            candidate.get("nearest_primary_portal_distance_metric")
            != PRIMARY_PORTAL_DISTANCE_METRIC
        ):
            errors.append(
                f"candidate {candidate['id']} has an invalid primary-portal distance metric"
            )
        if (
            abs(
                float(candidate.get("nearest_primary_portal_distance_m", -1))
                - reconstructed_primary_distance
            )
            > 0.2
        ):
            errors.append(
                f"candidate {candidate['id']} primary-portal distance provenance disagrees"
            )
        if candidate.get("nearest_primary_portal_id") != nearest_primary["portal_id"]:
            errors.append(f"candidate {candidate['id']} has the wrong nearest primary portal")
        if candidate.get("nearest_primary_portal_crossing_id") != nearest_primary["crossing_id"]:
            errors.append(f"candidate {candidate['id']} has the wrong nearest primary crossing")
        if reconstructed_primary_distance < PRIMARY_PORTAL_APPROACH_SETBACK_M:
            errors.append(f"candidate {candidate['id']} violates the primary-portal setback")
        if candidate.get("primary_portal_approach_ineligible") is not False:
            errors.append(f"candidate {candidate['id']} carries an ineligibility flag")
        if (
            candidate.get("eligible") is not True
            or candidate.get("eligible_candidate") is not True
            or candidate.get("base_candidate_eligible") is not True
            or candidate.get("terminal_zone_ineligible") is not False
            or candidate.get("candidate_ineligibility_reason") is not None
        ):
            errors.append(f"candidate {candidate['id']} has inconsistent eligibility flags")
        penalty_cluster_ids = list(candidate.get("access_penalty_cluster_ids", []))
        if candidate.get("access_penalty_metric") != ACCESS_PENALTY_METRIC:
            errors.append(f"candidate {candidate['id']} has an invalid access penalty metric")
        if len(penalty_cluster_ids) != len(set(penalty_cluster_ids)):
            errors.append(f"candidate {candidate['id']} repeats an access penalty cluster")
        if not set(penalty_cluster_ids).issubset(address_clusters):
            errors.append(f"candidate {candidate['id']} references an unknown penalty cluster")
        if int(candidate.get("access_penalty", -1)) != len(penalty_cluster_ids):
            errors.append(f"candidate {candidate['id']} access penalty count disagrees")
        if penalty_cluster_ids != sorted(expected_candidate_usage[candidate["id"]]):
            errors.append(f"candidate {candidate['id']} access penalty provenance disagrees")
    for portal in solver["portals"]:
        if not portal["node_ids"] or not set(portal["node_ids"]).issubset(nodes):
            errors.append(f"portal {portal['id']} has invalid nodes")
        if float(portal.get("maximum_diameter_m", math.inf)) > PORTAL_CLUSTER_MAX_DIAMETER_M + 0.1:
            errors.append(f"portal {portal['id']} exceeds the clustering diameter")
        member_ids = list(portal.get("crossing_ids", []))
        if len(member_ids) != len(set(member_ids)):
            errors.append(f"portal {portal['id']} repeats a boundary crossing")
        if not set(member_ids).issubset(crossings):
            errors.append(f"portal {portal['id']} references a missing boundary crossing")
        for field in (
            "adjacent_candidate_ids",
            "adjacent_local_candidate_segment_ids",
            "adjacent_terminal_zone_segment_ids",
            "adjacent_primary_portal_approach_segment_ids",
        ):
            values = list(portal.get(field, []))
            if len(values) != len(set(values)):
                errors.append(f"portal {portal['id']} repeats {field}")
        if not set(portal.get("adjacent_candidate_ids", [])).issubset(candidates):
            errors.append(f"portal {portal['id']} references an unknown adjacent candidate")
        portal_nodes = set(portal["node_ids"])
        adjacent_edges = [
            edge
            for edge in solver["edges"]
            if edge["u"] in portal_nodes or edge["v"] in portal_nodes
        ]
        expected_adjacency = {
            "adjacent_candidate_ids": sorted(
                {edge["candidate_id"] for edge in adjacent_edges if edge.get("candidate_id")}
            ),
            "adjacent_local_candidate_segment_ids": sorted(
                {
                    edge["physical_id"]
                    for edge in adjacent_edges
                    if edge.get("base_candidate_eligible")
                }
            ),
            "adjacent_terminal_zone_segment_ids": sorted(
                {
                    edge["physical_id"]
                    for edge in adjacent_edges
                    if edge.get("terminal_zone_ineligible")
                }
            ),
            "adjacent_primary_portal_approach_segment_ids": sorted(
                {
                    edge["physical_id"]
                    for edge in adjacent_edges
                    if edge.get("primary_portal_approach_ineligible")
                }
            ),
        }
        for field, expected_values in expected_adjacency.items():
            if portal.get(field) != expected_values:
                errors.append(f"portal {portal['id']} has stale {field}")
    portal_crossing_ids = [
        crossing_id for portal in solver["portals"] for crossing_id in portal["crossing_ids"]
    ]
    if len(portal_crossing_ids) != len(set(portal_crossing_ids)):
        errors.append("a boundary crossing belongs to more than one analytical portal")
    if set(portal_crossing_ids) != crossings:
        errors.append("analytical portals do not cover every retained boundary crossing")
    crossing_portal = {
        crossing["id"]: crossing.get("portal_id") for crossing in solver["boundary_crossings"]
    }
    if any(portal_id not in portals for portal_id in crossing_portal.values()):
        errors.append("a boundary crossing references a missing analytical portal")
    if any(crossing["node_id"] not in nodes for crossing in solver["boundary_crossings"]):
        errors.append("a boundary crossing references a missing graph node")
    for portal in solver["portals"]:
        if any(
            crossing_portal.get(crossing_id) != portal["id"]
            for crossing_id in portal["crossing_ids"]
        ):
            errors.append(f"portal {portal['id']} has inconsistent crossing provenance")
        member_crossings = portal.get("member_crossings", [])
        if {member["id"] for member in member_crossings} != set(portal["crossing_ids"]):
            errors.append(f"portal {portal['id']} member-crossing IDs disagree")
        if {member["node_id"] for member in member_crossings} != set(portal["node_ids"]):
            errors.append(f"portal {portal['id']} member nodes disagree with portal nodes")
        if any(
            member
            != next(
                crossing
                for crossing in solver["boundary_crossings"]
                if crossing["id"] == member["id"]
            )
            for member in member_crossings
        ):
            errors.append(f"portal {portal['id']} member provenance differs from source export")
    primary_by_side = {
        side: [
            portal
            for portal in solver["portals"]
            if portal["id"] in primary_portal_ids and portal["side"] == side
        ]
        for side in ("north", "east", "south", "west")
    }
    if len(primary_portal_ids) != PRIMARY_PORTALS_PER_SIDE * 4 or any(
        len(values) != PRIMARY_PORTALS_PER_SIDE for values in primary_by_side.values()
    ):
        errors.append("primary portal selection must contain exactly two portals per side")
    if len(primary_portal_ids) != len(set(primary_portal_ids)) or set(primary_portal_ids) != {
        portal["id"] for portal in solver["portals"] if portal.get("primary")
    }:
        errors.append("primary portal IDs and portal flags disagree")
    if candidate_policy.get("primary_portal_approach_source_portal_ids") != primary_portal_ids:
        errors.append("primary-portal setback metadata portal IDs disagree")
    if candidate_policy.get("primary_portal_approach_source_crossing_ids") != primary_crossing_ids:
        errors.append("primary-portal setback metadata crossing IDs disagree")
    browser_portal_ids = [portal["id"] for portal in scenario.get("portals", [])]
    if browser_portal_ids != primary_portal_ids:
        errors.append("browser portal export does not exactly match primary portal IDs")
    browser_candidate_ids = [candidate["id"] for candidate in scenario.get("candidates", [])]
    if browser_candidate_ids != candidate_ids:
        errors.append("browser candidate export does not exactly match solver candidate IDs")
    for cluster in solver["address_clusters"]:
        if cluster["node_id"] not in nodes:
            errors.append(f"address cluster {cluster['id']} has invalid snap node")
        if not cluster["allowed_portal_ids"]:
            errors.append(f"address cluster {cluster['id']} has no permitted portal")
        if not set(cluster["allowed_portal_ids"]).issubset(portals):
            errors.append(f"address cluster {cluster['id']} has invalid permitted portal")
    if solver["defaults"]["portal_pairs"] != [dict(pair) for pair in AUDITED_DEFAULT_PORTAL_PAIRS]:
        errors.append("default portal pairs differ from the explicitly audited pair set")
    if scenario.get("default_portal_pairs") != solver["defaults"]["portal_pairs"]:
        errors.append("browser and solver default portal pairs disagree")
    for pair in solver["defaults"]["portal_pairs"]:
        if pair["a"] not in portals or pair["b"] not in portals:
            errors.append("default pair references missing portal")
        if pair["a"] not in primary_portal_ids or pair["b"] not in primary_portal_ids:
            errors.append("default pair references a non-primary portal")
        portal_a = next(item for item in solver["portals"] if item["id"] == pair["a"])
        portal_b = next(item for item in solver["portals"] if item["id"] == pair["b"])
        forward = shortest_route(
            solver["nodes"], solver["edges"], portal_a["node_ids"], portal_b["node_ids"]
        )
        reverse = shortest_route(
            solver["nodes"], solver["edges"], portal_b["node_ids"], portal_a["node_ids"]
        )
        if not forward or not reverse:
            errors.append(
                f"default pair {pair['a']} ↔ {pair['b']} lacks a bidirectional baseline route"
            )
        elif not forward["candidate_ids"] or not reverse["candidate_ids"]:
            errors.append(
                f"default pair {pair['a']} ↔ {pair['b']} has a candidate-free baseline route"
            )
    for collection_name in ("streets", "buildings", "protected_corridors"):
        for feature in scenario[collection_name]["features"]:
            geometry = shape(feature["geometry"])
            if geometry.is_empty or not geometry.is_valid:
                errors.append(f"{collection_name} feature {feature.get('id')} is invalid")
    edges_by_physical_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in solver["edges"]:
        edges_by_physical_id[edge["physical_id"]].append(edge)
    street_features_by_id = {
        feature["properties"]["id"]: feature for feature in scenario["streets"]["features"]
    }
    if len(street_features_by_id) != len(scenario["streets"]["features"]):
        errors.append("browser street features repeat physical IDs")
    if set(street_features_by_id) != set(edges_by_physical_id):
        errors.append("browser street and solver physical-edge IDs disagree")
    provenance_fields = (
        "candidate_id",
        "eligible_candidate",
        "candidate_ineligibility_reason",
        "boundary_distance_m",
        "boundary_distance_metric",
        "terminal_zone_ineligible",
        "nearest_primary_portal_distance_m",
        "nearest_primary_portal_distance_metric",
        "nearest_primary_portal_id",
        "nearest_primary_portal_crossing_id",
        "primary_portal_approach_ineligible",
        "base_candidate_eligible",
    )
    for physical_id, feature in sorted(street_features_by_id.items()):
        matching_edges = edges_by_physical_id.get(physical_id, [])
        if not matching_edges:
            continue
        representative = matching_edges[0]
        properties = feature["properties"]
        for field in provenance_fields:
            if properties.get(field) != representative.get(field):
                errors.append(f"street {physical_id} differs from solver edge on {field}")
        if set(properties.get("edge_ids", [])) != {edge["id"] for edge in matching_edges}:
            errors.append(f"street {physical_id} directed-edge references disagree")
        street_geometry_xy = transform_geometry(
            shape(feature["geometry"]), validation_projection.forward
        )
        street_midpoint_xy = street_geometry_xy.interpolate(street_geometry_xy.length / 2)
        nearest_primary = min(
            primary_crossing_points,
            key=lambda item: (
                street_midpoint_xy.distance(item["point_xy"]),
                item["portal_id"],
                item["crossing_id"],
            ),
        )
        if (
            abs(
                float(properties.get("nearest_primary_portal_distance_m", -1))
                - street_midpoint_xy.distance(nearest_primary["point_xy"])
            )
            > 0.2
        ):
            errors.append(f"street {physical_id} primary-portal distance provenance disagrees")
        if properties.get("nearest_primary_portal_id") != nearest_primary["portal_id"]:
            errors.append(f"street {physical_id} has the wrong nearest primary portal")
        if properties.get("nearest_primary_portal_crossing_id") != nearest_primary["crossing_id"]:
            errors.append(f"street {physical_id} has the wrong nearest primary crossing")
    terminal_zone = scenario.get("terminal_zone")
    if not terminal_zone:
        errors.append("browser export is missing the candidate terminal zone")
    else:
        terminal_geometry = shape(terminal_zone["geometry"])
        if terminal_geometry.is_empty or not terminal_geometry.is_valid:
            errors.append("candidate terminal-zone geometry is empty or invalid")
        if float(terminal_zone.get("properties", {}).get("setback_m", -1)) != (
            CANDIDATE_BOUNDARY_SETBACK_M
        ):
            errors.append("candidate terminal-zone feature has the wrong setback")
        if terminal_zone.get("properties", {}).get("protected") is not False:
            errors.append("candidate terminal zone is incorrectly labelled protected")
        terminal_geometry_xy = transform_geometry(terminal_geometry, validation_projection.forward)
        expected_terminal_geometry_xy = analysis_polygon_xy.difference(
            analysis_polygon_xy.buffer(-CANDIDATE_BOUNDARY_SETBACK_M, join_style="mitre")
        )
        if terminal_geometry_xy.hausdorff_distance(expected_terminal_geometry_xy) > 0.05:
            errors.append("candidate terminal-zone geometry disagrees with the configured setback")
        terminal_polygons = (
            [terminal_geometry]
            if terminal_geometry.geom_type == "Polygon"
            else list(terminal_geometry.geoms)
        )
        if any(
            not polygon.exterior.is_ccw or any(ring.is_ccw for ring in polygon.interiors)
            for polygon in terminal_polygons
        ):
            errors.append("candidate terminal-zone rings do not follow RFC 7946 winding")
    portal_approach_zones = scenario.get("portal_approach_zones")
    if not portal_approach_zones:
        errors.append("browser export is missing the primary-portal approach zones")
    else:
        approach_properties = portal_approach_zones.get("properties", {})
        approach_geometry = shape(portal_approach_zones["geometry"])
        if approach_geometry.is_empty or not approach_geometry.is_valid:
            errors.append("primary-portal approach-zone geometry is empty or invalid")
        if float(approach_properties.get("setback_m", -1)) != (PRIMARY_PORTAL_APPROACH_SETBACK_M):
            errors.append("primary-portal approach-zone feature has the wrong setback")
        if (
            approach_properties.get("nearest_primary_portal_distance_metric")
            != PRIMARY_PORTAL_DISTANCE_METRIC
        ):
            errors.append("primary-portal approach-zone feature has the wrong metric")
        if approach_properties.get("primary_portal_ids") != primary_portal_ids:
            errors.append("primary-portal approach-zone portal IDs disagree")
        if approach_properties.get("primary_portal_crossing_ids") != primary_crossing_ids:
            errors.append("primary-portal approach-zone crossing IDs disagree")
        if approach_properties.get("protected") is not False:
            errors.append("primary-portal approach zones are incorrectly labelled protected")
        approach_geometry_xy = transform_geometry(approach_geometry, validation_projection.forward)
        expected_approach_geometry_xy = unary_union(
            [
                record["point_xy"].buffer(PRIMARY_PORTAL_APPROACH_SETBACK_M)
                for record in primary_crossing_points
            ]
        ).intersection(analysis_polygon_xy)
        if approach_geometry_xy.hausdorff_distance(expected_approach_geometry_xy) > 0.05:
            errors.append("primary-portal approach-zone geometry disagrees with its sources")
        if approach_geometry_xy.symmetric_difference(expected_approach_geometry_xy).area > 0.5:
            errors.append("primary-portal approach-zone area cannot be reconstructed")
        approach_polygons = (
            [approach_geometry]
            if approach_geometry.geom_type == "Polygon"
            else list(approach_geometry.geoms)
        )
        if any(
            not polygon.exterior.is_ccw or any(ring.is_ccw for ring in polygon.interiors)
            for polygon in approach_polygons
        ):
            errors.append("primary-portal approach-zone rings do not follow RFC 7946 winding")
    terminal_physical_ids = {
        edge["physical_id"] for edge in solver["edges"] if edge.get("terminal_zone_ineligible")
    }
    metadata_terminal_count = (
        solver.get("metadata", {})
        .get("candidate_policy", {})
        .get("terminal_zone_ineligible_physical_segments")
    )
    if metadata_terminal_count != len(terminal_physical_ids):
        errors.append("terminal-zone metadata count disagrees with solver edges")
    approach_physical_ids = {
        edge["physical_id"]
        for edge in solver["edges"]
        if edge.get("primary_portal_approach_ineligible")
    }
    overlap_physical_ids = terminal_physical_ids & approach_physical_ids
    additional_approach_physical_ids = approach_physical_ids - terminal_physical_ids
    candidate_physical_ids = {candidate["physical_id"] for candidate in solver["candidates"]}
    base_eligible_physical_ids = {
        edge["physical_id"] for edge in solver["edges"] if edge.get("base_candidate_eligible")
    }
    expected_metadata_counts = {
        "base_eligible_physical_segments": len(base_eligible_physical_ids),
        "terminal_zone_ineligible_physical_segments": len(terminal_physical_ids),
        "primary_portal_approach_ineligible_physical_segments": len(approach_physical_ids),
        "setback_overlap_ineligible_physical_segments": len(overlap_physical_ids),
        "additional_primary_portal_approach_exclusions": len(additional_approach_physical_ids),
        "total_setback_ineligible_physical_segments": len(
            terminal_physical_ids | approach_physical_ids
        ),
        "eligible_candidate_physical_segments": len(candidate_physical_ids),
    }
    for field, expected_count in expected_metadata_counts.items():
        if candidate_policy.get(field) != expected_count:
            errors.append(f"candidate-policy metadata count {field} disagrees")
    if base_eligible_physical_ids != (
        terminal_physical_ids | approach_physical_ids | candidate_physical_ids
    ):
        errors.append("base-eligible segments do not partition into setbacks and candidates")
    if errors:
        raise ValueError("Scenario validation failed:\n- " + "\n- ".join(errors[:50]))
    return {
        "status": "passed",
        "checks": [
            "unique stable identifiers",
            "all graph references resolve",
            "candidate edges are eligible and unprotected",
            "candidate display points satisfy the projected analysis-boundary setback",
            "candidate display points satisfy the primary-portal crossing setback",
            "terminal-zone ineligibility is distinct from protected transport infrastructure",
            "primary-portal approach ineligibility is reconstructed from crossing provenance",
            "candidate access penalties match deterministic baseline egress-route provenance",
            "portal and address-cluster graph references resolve",
            "every retained boundary crossing belongs to exactly one diameter-bounded portal",
            "browser export contains exactly two primary portals per boundary side",
            "all included address clusters have permitted portals",
            (
                "explicitly audited default portal pairs have candidate-bearing baseline "
                "routes in both directions"
            ),
            "all exported GeoJSON geometries are non-empty and valid",
        ],
        "counts": {
            "nodes": len(solver["nodes"]),
            "directed_edges": len(solver["edges"]),
            "candidates": len(solver["candidates"]),
            "portals": len(solver["portals"]),
            "primary_portals": len(primary_portal_ids),
            "boundary_crossings": len(crossing_ids),
            "address_clusters": len(solver["address_clusters"]),
            "buildings": len(scenario["buildings"]["features"]),
            "protected_features": len(scenario["protected_corridors"]["features"]),
            "terminal_zone_ineligible_physical_segments": len(
                {
                    edge["physical_id"]
                    for edge in solver["edges"]
                    if edge.get("terminal_zone_ineligible")
                }
            ),
            "primary_portal_approach_ineligible_physical_segments": len(approach_physical_ids),
            "setback_overlap_ineligible_physical_segments": len(overlap_physical_ids),
            "additional_primary_portal_approach_exclusions": len(additional_approach_physical_ids),
        },
    }


def build(raw: bytes, acquired_at: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    nodes, ways, osm3s = osm_elements(raw)
    project = projection()
    tram_geojson, tram_wgs_lines = tram_features(ways, nodes)
    tram_xy_lines = [project.line_xy(list(line.coords)) for line in tram_wgs_lines]
    physical_edges, crossings = simplify_road_ways(ways, nodes, project, tram_xy_lines)
    portals, boundary_crossings = cluster_portals(crossings, project, physical_edges)
    primary_portals = select_primary_portals(portals, project)
    apply_primary_portal_approach_setback(physical_edges, primary_portals, project)
    solver_nodes, directed_edges, candidates = directed_graph_data(physical_edges, nodes, project)
    # Candidate IDs only exist after all eligibility policies have run.
    annotate_portal_adjacency(portals, physical_edges)
    buildings_geojson, buildings = building_features(ways, nodes, project)
    clusters = address_clusters(buildings, solver_nodes, portals, project)
    assign_candidate_access_penalties(
        candidates,
        clusters,
        portals,
        solver_nodes,
        directed_edges,
    )
    pairs = default_portal_pairs(primary_portals, solver_nodes, directed_edges)
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
    primary_portal_ids = [portal["id"] for portal in primary_portals]
    primary_crossing_ids = sorted(
        crossing["id"] for portal in primary_portals for crossing in portal["member_crossings"]
    )
    base_candidate_count = sum(bool(edge["base_candidate_eligible"]) for edge in physical_edges)
    terminal_zone_count = sum(bool(edge["terminal_zone_ineligible"]) for edge in physical_edges)
    portal_approach_count = sum(
        bool(edge["primary_portal_approach_ineligible"]) for edge in physical_edges
    )
    setback_overlap_count = sum(
        bool(edge["terminal_zone_ineligible"]) and bool(edge["primary_portal_approach_ineligible"])
        for edge in physical_edges
    )
    additional_portal_approach_count = sum(
        bool(edge["primary_portal_approach_ineligible"])
        and not bool(edge["terminal_zone_ineligible"])
        for edge in physical_edges
    )
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
            "base_eligible_physical_segments": base_candidate_count,
            "analysis_boundary_setback_m": CANDIDATE_BOUNDARY_SETBACK_M,
            "boundary_distance_field": "candidate.boundary_distance_m",
            "boundary_distance_export_records": ["edge", "street", "candidate"],
            "boundary_distance_metric": CANDIDATE_BOUNDARY_DISTANCE_METRIC,
            "boundary_distance_definition": (
                "Euclidean distance in EPSG:3067 from the physical segment midpoint used as "
                "the candidate display point to the projected study-polygon boundary. The "
                "unrounded distance is used for eligibility; the exported value is rounded "
                "to 0.1 metre."
            ),
            "terminal_zone_ineligible_physical_segments": terminal_zone_count,
            "primary_portal_approach_setback_m": PRIMARY_PORTAL_APPROACH_SETBACK_M,
            "nearest_primary_portal_distance_field": (
                "candidate.nearest_primary_portal_distance_m"
            ),
            "nearest_primary_portal_distance_export_records": [
                "edge",
                "street",
                "candidate",
            ],
            "nearest_primary_portal_distance_metric": PRIMARY_PORTAL_DISTANCE_METRIC,
            "nearest_primary_portal_distance_definition": (
                "Euclidean distance in EPSG:3067 from the physical segment midpoint used as "
                "the candidate display point to the nearest mapped boundary-crossing point "
                "belonging to any of the eight primary/selectable portals. Portal display "
                "markers and the other analytical portals are not distance origins. The "
                "unrounded distance is used for eligibility; the exported value is rounded "
                "to 0.1 metre. Equal-distance ties use portal ID then crossing ID."
            ),
            "primary_portal_approach_source_portal_ids": primary_portal_ids,
            "primary_portal_approach_source_crossing_ids": primary_crossing_ids,
            "primary_portal_approach_ineligible_physical_segments": portal_approach_count,
            "setback_overlap_ineligible_physical_segments": setback_overlap_count,
            "additional_primary_portal_approach_exclusions": (additional_portal_approach_count),
            "total_setback_ineligible_physical_segments": (
                terminal_zone_count + additional_portal_approach_count
            ),
            "eligible_candidate_physical_segments": len(candidates),
            "excluded_highways": sorted(PROTECTED_HIGHWAYS),
            "protected_conditions": [
                "motorway, trunk, primary or secondary street and links",
                "explicit bus/PSV lane tags or trolley wire",
                "road geometry following mapped tram/light-rail infrastructure",
            ],
            "ineligible_conditions": [
                "street class outside the eligible local-street classes",
                "bridge or tunnel",
                "physical segment shorter than 10 metres",
                (
                    "otherwise eligible segment midpoint less than "
                    f"{CANDIDATE_BOUNDARY_SETBACK_M:g} metres from the analysis boundary"
                ),
                (
                    "otherwise eligible segment midpoint less than "
                    f"{PRIMARY_PORTAL_APPROACH_SETBACK_M:g} metres from the nearest crossing "
                    "point of any primary/selectable portal"
                ),
            ],
            "terminal_zone_semantics": (
                "Otherwise eligible local segments with display points less than "
                f"{CANDIDATE_BOUNDARY_SETBACK_M:g} metres "
                "from the analysis boundary are ineligible, removing immediate boundary-adjacent "
                "filter points from the search. This is an analytical boundary-bias "
                "assumption, not public-transport protection or a site-feasibility finding."
            ),
            "primary_portal_approach_semantics": (
                "Otherwise eligible local segment midpoints less than "
                f"{PRIMARY_PORTAL_APPROACH_SETBACK_M:g} metres from any crossing point in the "
                "static eight-primary-portal set are ineligible. This reduces solutions that "
                "merely cap a selected portal approach. It is an analytical endpoint-bias "
                "control, not a physical or legal siting rule."
            ),
            "semantics": (
                "Each modal filter removes all directed private-car edges represented by its "
                "physical street segment. Walking and cycling remain unchanged; emergency passage "
                "assumes a removable or otherwise permeable treatment."
            ),
        },
        "access_policy": {
            "building_cluster_grid_m": 85,
            "snap_method": "projected representative-point cluster centroid to nearest graph node",
            "permitted_portals": (
                "all mapped private-car boundary-crossing clusters, including analytical portals "
                "not exposed in the compact browser selector"
            ),
            "optimization_proxy": {
                "field": "candidate.access_penalty",
                "metric": ACCESS_PENALTY_METRIC,
                "unit": "address clusters",
                "definition": ACCESS_PENALTY_DEFINITION,
                "aggregation": (
                    "The Z3 objective sums candidate values. A cluster can contribute to more "
                    "than one selected candidate when its baseline route traverses more than one."
                ),
                "limitation": (
                    "This marginal exposure proxy does not model alternate-route availability, "
                    "predict traffic, or equal the detour caused by an intervention set."
                ),
            },
            "post_solution_metrics": (
                "After applying the complete intervention set, the graph verifier recomputes "
                "directed shortest egress distance for every served cluster and reports actual "
                "additional distance relative to the unfiltered graph."
            ),
        },
        "portal_policy": {
            "semantics": (
                "Each portal is a physically local boundary-crossing cluster. A portal-pair "
                "requirement quantifies over every mapped private-car crossing node in both "
                "selected clusters."
            ),
            "grouping": (
                "deterministic contiguous complete-link clustering within each boundary side"
            ),
            "maximum_cluster_diameter_m": PORTAL_CLUSTER_MAX_DIAMETER_M,
            "display_point": "the member crossing nearest the group centroid",
            "crossings_retained": (
                "every detected private-car boundary crossing record in the retained graph; each "
                "belongs to exactly one analytical portal cluster"
            ),
            "primary_portals": (
                "two deterministic, spatially distributed portal clusters per side are exposed "
                "in the browser; all clusters remain permitted local-access exits in the solver"
            ),
            "primary_portal_count": len(primary_portals),
            "analytical_portal_count": len(portals),
            "boundary_crossing_count": len(boundary_crossings),
            "default_pair_selection": (
                "Explicit scenario-specific portal IDs audited against the frozen graph after "
                "applying both candidate-setback controls; preprocessing verifies that the IDs "
                "remain primary and that each deterministic directional baseline shortest route "
                "contains at least one eligible candidate."
            ),
            "audited_default_portal_pairs": [dict(pair) for pair in pairs],
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
        "boundary_crossings": boundary_crossings,
        "primary_portal_ids": primary_portal_ids,
        "address_clusters": clusters,
        "defaults": {
            "budget": 4,
            "portal_pairs": pairs,
            "objective_mode": "balanced",
            "timeout_seconds": 30,
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
            "default_mode": "balanced",
            "priority": [
                "intervention_count",
                "weighted_cost",
                "access_penalty",
                "adjacency_penalty",
            ],
            "mode_priorities": {
                "balanced": [
                    "intervention_count",
                    "weighted_cost",
                    "access_penalty",
                    "adjacency_penalty",
                ],
                "access": [
                    "intervention_count",
                    "access_penalty",
                    "weighted_cost",
                    "adjacency_penalty",
                ],
                "fewest": ["intervention_count"],
            },
            "candidate_costs": {
                "living_street": 90,
                "residential": 100,
                "unclassified": 115,
            },
            "access_penalty": {
                "field": "access_penalty",
                "metric": ACCESS_PENALTY_METRIC,
                "definition": ACCESS_PENALTY_DEFINITION,
                "is_exact_post_solution_detour": False,
            },
        },
    }

    boundary_feature = {
        "type": "Feature",
        "id": "study-boundary",
        "properties": {"id": "study-boundary", "name": SCENARIO_NAME, "area_km2": 1.33},
        "geometry": mapping(box(*BBOX)),
    }
    boundary_xy = transform_geometry(box(*BBOX), project.forward)
    terminal_zone_xy = orient_polygonal(
        boundary_xy.difference(
            boundary_xy.buffer(-CANDIDATE_BOUNDARY_SETBACK_M, join_style="mitre")
        )
    )
    terminal_zone_feature = {
        "type": "Feature",
        "id": "candidate-terminal-zone",
        "properties": {
            "id": "candidate-terminal-zone",
            "name": "Candidate terminal zone",
            "kind": "analysis_boundary_candidate_setback",
            "setback_m": CANDIDATE_BOUNDARY_SETBACK_M,
            "boundary_distance_metric": CANDIDATE_BOUNDARY_DISTANCE_METRIC,
            "candidate_eligible": False,
            "protected": False,
            "reason": (
                "Modal-filter points are excluded here to remove boundary-adjacent cuts; "
                "this is an analytical eligibility rule, not transport protection."
            ),
        },
        "geometry": mapping(transform_geometry(terminal_zone_xy, project.inverse)),
    }
    primary_crossing_points = primary_portal_crossing_points(primary_portals, project)
    portal_approach_zones_xy = orient_polygonal(
        unary_union(
            [
                record["point_xy"].buffer(PRIMARY_PORTAL_APPROACH_SETBACK_M)
                for record in primary_crossing_points
            ]
        ).intersection(boundary_xy)
    )
    portal_approach_zones_feature = {
        "type": "Feature",
        "id": "primary-portal-approach-zones",
        "properties": {
            "id": "primary-portal-approach-zones",
            "name": "Primary portal approach zones",
            "kind": "primary_portal_candidate_setback",
            "setback_m": PRIMARY_PORTAL_APPROACH_SETBACK_M,
            "nearest_primary_portal_distance_metric": PRIMARY_PORTAL_DISTANCE_METRIC,
            "primary_portal_ids": primary_portal_ids,
            "primary_portal_crossing_ids": primary_crossing_ids,
            "candidate_eligible": False,
            "protected": False,
            "reason": (
                "Modal-filter points are excluded near the eight selectable portal crossings "
                "to reduce endpoint-capping solutions; this is an analytical bias control, "
                "not a physical or legal siting rule."
            ),
        },
        "geometry": mapping(transform_geometry(portal_approach_zones_xy, project.inverse)),
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
        "terminal_zone": terminal_zone_feature,
        "portal_approach_zones": portal_approach_zones_feature,
        "streets": feature_collection(street_geojson),
        "buildings": feature_collection(buildings_geojson),
        "protected_corridors": feature_collection(protected_geojson),
        "portals": primary_portals,
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
        },
        {
            **terminal_zone_feature,
            "properties": {**terminal_zone_feature["properties"], "layer": "terminal_zone"},
        },
        {
            **portal_approach_zones_feature,
            "properties": {
                **portal_approach_zones_feature["properties"],
                "layer": "portal_approach_zones",
            },
        },
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
