from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import os
import shutil
import tempfile
import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from pyproj import Transformer
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, shape
from shapely.ops import transform

from .adapters import SourceAcquisitionContext, source_adapter_workspace
from .models import (
    ArtifactDigest,
    FieldLineage,
    ScenarioRecipe,
    ScenarioSnapshotMetadata,
    SourceSnapshotMetadata,
)
from .osm import (
    CANONICAL_COORDINATE_DECIMALS,
    Clock,
    FetchTransport,
    OsmOverpassAdapter,
    canonicalize_area,
    canonicalize_network_context,
    load_osm_archive,
)

BASE_NETWORK_SCHEMA_VERSION = "1.1"
BASE_NETWORK_BUILDER_VERSION = "1.3.0"
DISPLAY_CRS = "EPSG:4326"

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
    "track",
}
WALK_DEFAULT_DENY = {"motorway", "motorway_link", "construction", "proposed", "raceway"}
CYCLE_DEFAULT_DENY = {
    "motorway",
    "motorway_link",
    "construction",
    "proposed",
    "raceway",
    "steps",
    "footway",
    "pedestrian",
    "corridor",
    "platform",
}
ACCESS_ALLOW = {"yes", "designated", "permissive", "destination", "delivery"}
ACCESS_DENY = {"no", "private", "customers", "permit"}
ONEWAY_YES = {"yes", "true", "1"}
ONEWAY_REVERSE = {"-1", "reverse"}
MODE_NAMES = ("private_car", "walking", "cycling")
TAG_FIELDS = (
    "name",
    "ref",
    "highway",
    "access",
    "vehicle",
    "motor_vehicle",
    "motorcar",
    "foot",
    "bicycle",
    "oneway",
    "oneway:bicycle",
    "junction",
    "cycleway",
    "cycleway:left",
    "cycleway:right",
    "surface",
    "maxspeed",
    "service",
    "bridge",
    "tunnel",
    "layer",
    "covered",
    "ford",
)


class BaseNetworkBuildError(ValueError):
    """Raised when a base network cannot be constructed or verified."""


@dataclass(frozen=True)
class BaseNetworkBuildResult:
    snapshot_id: str
    snapshot_dir: Path
    latest_pointer: Path
    node_count: int
    edge_count: int


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _compact_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _deterministic_gzip(payload: bytes) -> bytes:
    """Compress bytes without embedding a filename or wall-clock timestamp."""

    buffer = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        compresslevel=9,
        fileobj=buffer,
        mtime=0,
    ) as stream:
        stream.write(payload)
    return buffer.getvalue()


def _artifact(path: str, payload: bytes, media_type: str) -> ArtifactDigest:
    return ArtifactDigest(
        path=path,
        sha256=_sha256(payload),
        byte_size=len(payload),
        media_type=media_type,
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _tag(tags: dict[str, Any], key: str) -> str | None:
    value = tags.get(key)
    return value.strip().lower() if isinstance(value, str) else None


def _apply_access(
    base: bool,
    tags: dict[str, Any],
    keys: Iterable[str],
    *,
    explicit_override_keys: Iterable[str],
) -> bool:
    """Apply OSM's access hierarchy without promoting a mode from ``access=*``.

    A generic ``access=destination`` or ``access=permissive`` describes who may
    use an otherwise mode-appropriate way; it does not turn steps, an indoor
    corridor, or a footway into a motor road. More-specific mode/vehicle tags may
    deliberately override the highway default and an earlier generic denial.
    """

    allowed = base
    override_keys = set(explicit_override_keys)
    for key in keys:
        value = _tag(tags, key)
        if value in ACCESS_DENY:
            allowed = False
        elif value in ACCESS_ALLOW and (allowed or key in override_keys):
            allowed = True
    return allowed


def _base_permissions(tags: dict[str, Any]) -> dict[str, bool]:
    highway = _tag(tags, "highway") or ""
    if highway in {"construction", "proposed"}:
        return {mode: False for mode in MODE_NAMES}

    private_car = _apply_access(
        highway in CAR_HIGHWAYS,
        tags,
        ("access", "vehicle", "motor_vehicle", "motorcar"),
        explicit_override_keys=("vehicle", "motor_vehicle", "motorcar"),
    )
    walking = _apply_access(
        highway not in WALK_DEFAULT_DENY,
        tags,
        ("access", "foot"),
        explicit_override_keys=("foot",),
    )
    cycling = _apply_access(
        highway not in CYCLE_DEFAULT_DENY,
        tags,
        ("access", "vehicle", "bicycle"),
        explicit_override_keys=("vehicle", "bicycle"),
    )
    return {
        "private_car": private_car,
        "walking": walking,
        "cycling": cycling,
    }


def _directed_permissions(
    tags: dict[str, Any], base: dict[str, bool]
) -> tuple[dict[str, bool], dict[str, bool]]:
    forward = dict(base)
    reverse = dict(base)
    oneway = _tag(tags, "oneway")
    if oneway is None and _tag(tags, "junction") == "roundabout":
        oneway = "yes"

    if oneway in ONEWAY_YES:
        reverse["private_car"] = False
        reverse["cycling"] = False
    elif oneway in ONEWAY_REVERSE:
        forward["private_car"] = False
        forward["cycling"] = False

    bicycle_oneway = _tag(tags, "oneway:bicycle")
    has_opposite_cycleway = any(
        (_tag(tags, key) or "").startswith("opposite")
        for key in ("cycleway", "cycleway:left", "cycleway:right")
    )
    if bicycle_oneway == "no" or has_opposite_cycleway:
        forward["cycling"] = base["cycling"]
        reverse["cycling"] = base["cycling"]
    return forward, reverse


def _line_parts(geometry: Any) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [geometry] if geometry.length > 0 else []
    if isinstance(geometry, MultiLineString):
        return [part for part in geometry.geoms if part.length > 0]
    if isinstance(geometry, GeometryCollection):
        return [part for child in geometry.geoms for part in _line_parts(child)]
    return []


def _rounded_wgs84(line: LineString, to_display: Transformer) -> list[list[float]]:
    display = transform(to_display.transform, line)
    return [
        [
            round(float(longitude), CANONICAL_COORDINATE_DECIMALS),
            round(float(latitude), CANONICAL_COORDINATE_DECIMALS),
        ]
        for longitude, latitude in display.coords
    ]


def _boundary_node_id(longitude: float, latitude: float) -> str:
    material = f"{longitude:.7f},{latitude:.7f}".encode("ascii")
    return f"osm-boundary-{hashlib.sha256(material).hexdigest()[:16]}"


def _source_node_id(osm_node_id: int) -> str:
    return f"osm-node-{osm_node_id}"


def _mode_permissions_assumptions() -> dict[str, Any]:
    return {
        "version": "1.0",
        "private_car": (
            "OSM highway defaults plus access, vehicle, motor_vehicle, and motorcar tags; "
            "oneway and roundabout directionality are applied. Generic access tags may "
            "restrict but do not promote a non-car highway; explicit vehicle, motor_vehicle, "
            "or motorcar tags may override the highway default."
        ),
        "walking": (
            "Bidirectional unless highway defaults or access/foot tags deny walking; ordinary "
            "vehicle oneway tags do not make walking one-way. Generic access tags do not "
            "promote a non-walking highway; an explicit foot tag may."
        ),
        "cycling": (
            "OSM highway defaults plus access, vehicle, and bicycle tags; vehicle oneway is "
            "applied unless oneway:bicycle=no or an opposite cycleway is tagged. Generic "
            "access tags do not promote a non-cycling highway; explicit vehicle or bicycle "
            "tags may."
        ),
        "limitations": [
            (
                "Turn restrictions, conditional access, lanes, schedules, and barriers are not "
                "yet modeled."
            ),
            (
                "The permissions are reproducible routing assumptions, not legal or field "
                "verification."
            ),
            "Emergency, public-transport, and service-vehicle semantics are not emitted in v1.",
        ],
    }


def _edge_physical_segment_id(edge: dict[str, Any]) -> str:
    direction = edge.get("direction")
    suffix = {"forward": "-f", "reverse": "-r"}.get(direction)
    edge_id = edge.get("id")
    if suffix is None or not isinstance(edge_id, str) or not edge_id.endswith(suffix):
        raise BaseNetworkBuildError(f"edge {edge_id!r} has inconsistent ID and direction")
    physical_segment_id = edge_id[: -len(suffix)]
    if not physical_segment_id:
        raise BaseNetworkBuildError(f"edge {edge_id!r} has no physical segment ID")
    return physical_segment_id


def _browser_segment_features(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse directed analytical edges into one display feature per source segment part."""

    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for edge in edges:
        physical_segment_id = _edge_physical_segment_id(edge)
        direction = edge["direction"]
        directions = grouped.setdefault(physical_segment_id, {})
        if direction in directions:
            raise BaseNetworkBuildError(
                f"physical segment {physical_segment_id} has duplicate {direction} edges"
            )
        directions[direction] = edge

    features: list[dict[str, Any]] = []
    for physical_segment_id, directions in sorted(grouped.items()):
        forward = directions.get("forward")
        reverse = directions.get("reverse")
        if forward is None and reverse is None:  # pragma: no cover - grouping guarantees this
            raise BaseNetworkBuildError(
                f"physical segment {physical_segment_id} has no directed edge"
            )
        reference = forward or reverse
        assert reference is not None
        if forward is not None:
            geometry = forward["geometry"]
            canonical_from = forward["from"]
            canonical_to = forward["to"]
        else:
            assert reverse is not None
            geometry = list(reversed(reverse["geometry"]))
            canonical_from = reverse["to"]
            canonical_to = reverse["from"]

        if reverse is not None and (
            reverse["geometry"] != list(reversed(geometry))
            or reverse["from"] != canonical_to
            or reverse["to"] != canonical_from
        ):
            raise BaseNetworkBuildError(
                f"directed edges for {physical_segment_id} do not share opposite geometry"
            )
        for edge in directions.values():
            if any(
                edge[field] != reference[field]
                for field in ("length_m", "highway", "name", "source", "tags")
            ):
                raise BaseNetworkBuildError(
                    f"directed edges for {physical_segment_id} disagree on source attributes"
                )

        properties: dict[str, Any] = {
            "layer": "base_network",
            "physical_segment_id": physical_segment_id,
            "forward_edge_id": forward["id"] if forward is not None else None,
            "reverse_edge_id": reverse["id"] if reverse is not None else None,
            "from": canonical_from,
            "to": canonical_to,
            "length_m": reference["length_m"],
            "highway": reference["highway"],
            "name": reference["name"],
        }
        for mode in MODE_NAMES:
            properties[f"{mode}_forward"] = bool(
                forward is not None and forward["permissions"][mode]
            )
            properties[f"{mode}_reverse"] = bool(
                reverse is not None and reverse["permissions"][mode]
            )
        features.append(
            {
                "type": "Feature",
                "id": physical_segment_id,
                "geometry": {"type": "LineString", "coordinates": geometry},
                "properties": properties,
            }
        )
    return features


def build_network_document(
    recipe: ScenarioRecipe,
    source_document: dict[str, Any],
    *,
    snapshot_id: str,
    raw_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], list[FieldLineage]]:
    core_area = canonicalize_area(recipe)
    network_area = canonicalize_network_context(recipe, core_area)
    to_analysis = Transformer.from_crs(DISPLAY_CRS, recipe.analysis_crs, always_xy=True)
    to_display = Transformer.from_crs(recipe.analysis_crs, DISPLAY_CRS, always_xy=True)

    source_nodes: dict[int, tuple[float, float, float, float]] = {}
    ways: list[dict[str, Any]] = []
    for element in source_document["elements"]:
        if element["type"] == "node":
            node_id = element["id"]
            longitude = element.get("lon")
            latitude = element.get("lat")
            if not isinstance(longitude, (int, float)) or not isinstance(latitude, (int, float)):
                raise BaseNetworkBuildError(f"OSM node {node_id} lacks numeric lon/lat")
            if not math.isfinite(longitude) or not math.isfinite(latitude):
                raise BaseNetworkBuildError(f"OSM node {node_id} has non-finite lon/lat")
            x, y = to_analysis.transform(float(longitude), float(latitude))
            source_nodes[node_id] = (float(longitude), float(latitude), float(x), float(y))
        elif element["type"] == "way" and isinstance(element.get("tags"), dict):
            if _tag(element["tags"], "highway") is not None:
                ways.append(element)

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    lineage: list[FieldLineage] = []
    clipped_part_count = 0

    def register_node(
        coordinate: list[float],
        analysis_coordinate: tuple[float, float],
        source_ref: int | None,
    ) -> str:
        node_id = (
            _source_node_id(source_ref)
            if source_ref is not None
            else _boundary_node_id(coordinate[0], coordinate[1])
        )
        node = {
            "id": node_id,
            "longitude": coordinate[0],
            "latitude": coordinate[1],
            "x": round(float(analysis_coordinate[0]), 3),
            "y": round(float(analysis_coordinate[1]), 3),
            "source": {"adapter_id": "osm", "node_id": source_ref}
            if source_ref is not None
            else {"adapter_id": "osm", "node_id": None, "derived": "polygon_clip"},
        }
        existing = nodes.get(node_id)
        if existing is not None and (
            existing["longitude"] != node["longitude"] or existing["latitude"] != node["latitude"]
        ):
            raise BaseNetworkBuildError(f"stable node ID collision for {node_id}")
        nodes[node_id] = node
        return node_id

    for way in sorted(ways, key=lambda item: item["id"]):
        way_id = way["id"]
        refs = way.get("nodes")
        if (
            not isinstance(refs, list)
            or len(refs) < 2
            or not all(isinstance(ref, int) for ref in refs)
        ):
            raise BaseNetworkBuildError(f"OSM highway way {way_id} has invalid node references")
        missing = sorted(ref for ref in refs if ref not in source_nodes)
        if missing:
            raise BaseNetworkBuildError(
                f"OSM highway way {way_id} references missing node(s): "
                + ", ".join(str(ref) for ref in missing[:8])
            )

        tags = way["tags"]
        base_permissions = _base_permissions(tags)
        forward_permissions, reverse_permissions = _directed_permissions(tags, base_permissions)
        selected_tags = {
            key: tags[key]
            for key in TAG_FIELDS
            if isinstance(tags.get(key), str) and tags[key].strip()
        }
        highway = _tag(tags, "highway") or "unknown"

        for segment_index, (start_ref, end_ref) in enumerate(zip(refs, refs[1:], strict=False)):
            start = source_nodes[start_ref]
            end = source_nodes[end_ref]
            source_line = LineString([(start[2], start[3]), (end[2], end[3])])
            if source_line.length <= 0:
                continue
            parts = _line_parts(source_line.intersection(network_area.analysis))
            oriented_parts: list[LineString] = []
            for part in parts:
                coordinates = list(part.coords)
                if source_line.project(Point(coordinates[0])) > source_line.project(
                    Point(coordinates[-1])
                ):
                    coordinates.reverse()
                oriented_parts.append(LineString(coordinates))
            oriented_parts.sort(key=lambda part: source_line.project(Point(part.coords[0])))

            for part_index, part in enumerate(oriented_parts):
                if part.length < 0.01:
                    continue
                clipped_part_count += 1
                geometry = _rounded_wgs84(part, to_display)
                if len(set(map(tuple, geometry))) < 2:
                    continue
                part_start = Point(part.coords[0])
                part_end = Point(part.coords[-1])
                source_start_ref = (
                    start_ref if part_start.distance(Point(source_line.coords[0])) < 0.01 else None
                )
                source_end_ref = (
                    end_ref if part_end.distance(Point(source_line.coords[-1])) < 0.01 else None
                )
                from_id = register_node(geometry[0], part.coords[0], source_start_ref)
                to_id = register_node(geometry[-1], part.coords[-1], source_end_ref)
                if from_id == to_id:
                    continue

                base_edge_id = f"osm-way-{way_id}-segment-{segment_index:04d}-part-{part_index:02d}"
                source_feature_id = f"osm-way-{way_id}"
                length_m = round(float(part.length), 3)

                for direction, edge_from, edge_to, edge_geometry, permissions in (
                    ("forward", from_id, to_id, geometry, forward_permissions),
                    ("reverse", to_id, from_id, list(reversed(geometry)), reverse_permissions),
                ):
                    if not any(permissions.values()):
                        continue
                    suffix = "f" if direction == "forward" else "r"
                    edge_id = f"{base_edge_id}-{suffix}"
                    edge = {
                        "id": edge_id,
                        "from": edge_from,
                        "to": edge_to,
                        "geometry": edge_geometry,
                        "length_m": length_m,
                        "permissions": {mode: bool(permissions[mode]) for mode in MODE_NAMES},
                        "highway": highway,
                        "name": selected_tags.get("name"),
                        "direction": direction,
                        "source": {
                            "adapter_id": "osm",
                            "way_id": way_id,
                            "segment_index": segment_index,
                            "part_index": part_index,
                            "node_ids": [start_ref, end_ref],
                        },
                        "tags": selected_tags,
                    }
                    edges.append(edge)
                    for output_field, operation in (
                        (
                            "geometry",
                            "clip source segment to network context polygon; transform to "
                            "EPSG:4326",
                        ),
                        ("length_m", f"measure clipped geometry in {recipe.analysis_crs}"),
                        (
                            "permissions.private_car",
                            "derive from documented OSM highway/access/oneway assumptions",
                        ),
                        (
                            "permissions.walking",
                            "derive from documented OSM highway/access assumptions",
                        ),
                        (
                            "permissions.cycling",
                            "derive from documented OSM highway/access/oneway assumptions",
                        ),
                    ):
                        lineage.append(
                            FieldLineage(
                                output_feature_id=edge_id,
                                output_field=output_field,
                                adapter_id="osm",
                                source_feature_ids=[source_feature_id],
                                operation=operation,
                                precedence_rank=0,
                            )
                        )

    edges.sort(key=lambda edge: edge["id"])
    referenced_node_ids = {
        node_id for edge in edges for node_id in (edge["from"], edge["to"])
    }
    ordered_nodes = sorted(
        (nodes[node_id] for node_id in referenced_node_ids),
        key=lambda node: node["id"],
    )
    lineage.sort(key=lambda item: (item.output_feature_id, item.output_field))
    if not ordered_nodes or not edges:
        raise BaseNetworkBuildError(
            "OSM response produced no usable nodes or directed edges in the network context"
        )
    browser_segment_features = _browser_segment_features(edges)

    network = {
        "schema_version": BASE_NETWORK_SCHEMA_VERSION,
        "artifact_type": "resilient_access_base_network",
        "builder_version": BASE_NETWORK_BUILDER_VERSION,
        "scope": "base_network_only",
        "scenario_id": recipe.scenario_id,
        "snapshot_id": snapshot_id,
        "analysis_crs": recipe.analysis_crs,
        "display_crs": DISPLAY_CRS,
        "core_boundary": core_area.geojson,
        "network_context_boundary": network_area.geojson,
        "network_context_buffer_m": recipe.network_context_buffer_m,
        "capabilities": {
            "available": ["base_network"],
            "not_built": ["flood_hazard", "roadworks", "origins", "destinations", "actions"],
        },
        "source": {"adapter_id": "osm", "raw_sha256": raw_sha256},
        "permission_assumptions": _mode_permissions_assumptions(),
        "counts": {
            "nodes": len(ordered_nodes),
            "directed_edges": len(edges),
            "physical_segments": len(browser_segment_features),
            "clipped_source_segment_parts": clipped_part_count,
        },
        "nodes": ordered_nodes,
        "edges": edges,
    }
    geojson_features = [
        {
            "type": "Feature",
            "id": "network-context",
            "geometry": network_area.geojson,
            "properties": {
                "layer": "network_context",
                "scenario_id": recipe.scenario_id,
                "snapshot_id": snapshot_id,
                "buffer_m": recipe.network_context_buffer_m,
            },
        },
        {
            "type": "Feature",
            "id": "study-core",
            "geometry": core_area.geojson,
            "properties": {
                "layer": "study_core",
                "scenario_id": recipe.scenario_id,
                "snapshot_id": snapshot_id,
            },
        },
    ]
    geojson = {
        "type": "FeatureCollection",
        "schema_version": BASE_NETWORK_SCHEMA_VERSION,
        "builder_version": BASE_NETWORK_BUILDER_VERSION,
        "name": f"{recipe.scenario_id}-base-network",
        "features": [*geojson_features, *browser_segment_features],
    }
    return network, geojson, lineage


def _validate_recipe_for_base_network(recipe: ScenarioRecipe) -> Any:
    base_sources = [source for source in recipe.sources if source.role == "base_network"]
    if len(base_sources) != 1 or base_sources[0].adapter_id != "osm":
        raise BaseNetworkBuildError(
            "the v1 base-network builder requires exactly one base_network source with "
            "adapter_id 'osm'"
        )
    unsupported_required = [
        source.adapter_id
        for source in recipe.sources
        if source.required and source is not base_sources[0]
    ]
    if unsupported_required:
        raise BaseNetworkBuildError(
            "this base_network-only build cannot satisfy required non-network source(s): "
            + ", ".join(sorted(unsupported_required))
        )
    return base_sources[0]


def _snapshot_id(recipe: ScenarioRecipe, source_manifest: dict[str, Any]) -> str:
    identity = {
        "builder_version": BASE_NETWORK_BUILDER_VERSION,
        "recipe_sha256": recipe.sha256(),
        "adapter_version": source_manifest["adapter_version"],
        "query_sha256": source_manifest["query_sha256"],
        "raw_sha256": source_manifest["raw_sha256"],
        "acquired_at": source_manifest["acquired_at"],
        "source_timestamp": source_manifest.get("source_timestamp"),
    }
    material = _compact_json_bytes(identity)
    return f"base-{_sha256(material)[:24]}"


def build_base_network_snapshot(
    recipe: ScenarioRecipe,
    *,
    source_dir: Path,
    output_dir: Path,
    refresh: bool = False,
    transport: FetchTransport | None = None,
    clock: Clock | None = None,
) -> BaseNetworkBuildResult:
    declaration = _validate_recipe_for_base_network(recipe)
    source_root = source_dir.resolve()
    source_workspace = source_adapter_workspace(source_root, recipe, declaration)
    output_dir = output_dir.resolve()
    adapter = OsmOverpassAdapter(refresh=refresh, transport=transport, clock=clock)
    source_metadata = adapter.acquire(
        SourceAcquisitionContext(
            recipe=recipe,
            declaration=declaration,
            workspace=source_workspace,
        )
    )
    source_document = load_osm_archive(adapter.archive_path)
    source_manifest = adapter.archive_manifest
    raw_sha256 = source_manifest["raw_sha256"]
    snapshot_id = _snapshot_id(recipe, source_manifest)
    network, geojson, lineage = build_network_document(
        recipe,
        source_document,
        snapshot_id=snapshot_id,
        raw_sha256=raw_sha256,
    )

    recipe_payload = _json_bytes(recipe.model_dump(mode="json", exclude_none=True))
    network_payload = _compact_json_bytes(network)
    geojson_payload = _compact_json_bytes(geojson)
    lineage_jsonl_payload = b"".join(
        _compact_json_bytes(record.model_dump(mode="json", exclude_none=True)) for record in lineage
    )
    lineage_payload = _deterministic_gzip(lineage_jsonl_payload)
    raw_payload = adapter.archive_path.read_bytes()

    field_lineage_artifact = _artifact(
        "provenance/field-lineage.jsonl.gz",
        lineage_payload,
        "application/gzip",
    )
    derived_artifacts = [
        _artifact("recipe.json", recipe_payload, "application/json"),
        _artifact("base-network.json", network_payload, "application/json"),
        _artifact("base-network.geojson", geojson_payload, "application/geo+json"),
    ]
    source_metadata = SourceSnapshotMetadata(
        **source_metadata.model_dump(exclude={"artifacts"}),
        artifacts=[_artifact("raw/osm-overpass.json.gz", raw_payload, "application/gzip")],
    )
    metadata = ScenarioSnapshotMetadata(
        snapshot_id=snapshot_id,
        scenario_id=recipe.scenario_id,
        recipe_sha256=recipe.sha256(),
        created_at=source_metadata.acquired_at,
        analysis_crs=recipe.analysis_crs,
        sources=[source_metadata],
        field_lineage_artifact=field_lineage_artifact,
        derived_artifacts=derived_artifacts,
    )
    metadata.validate_against(recipe)
    metadata_payload = _json_bytes(metadata.model_dump(mode="json", exclude_none=True))

    snapshots_dir = output_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=output_dir))
    final = snapshots_dir / snapshot_id
    try:
        files = {
            "recipe.json": recipe_payload,
            "raw/osm-overpass.json.gz": raw_payload,
            "base-network.json": network_payload,
            "base-network.geojson": geojson_payload,
            "provenance/field-lineage.jsonl.gz": lineage_payload,
            "metadata.json": metadata_payload,
        }
        for relative_path, payload in files.items():
            destination = staging / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        validate_base_network_snapshot(staging, recipe)

        if final.exists():
            validate_base_network_snapshot(final, recipe)
            for relative_path, payload in files.items():
                if (final / relative_path).read_bytes() != payload:
                    raise BaseNetworkBuildError(
                        f"immutable snapshot {snapshot_id} already exists with different bytes"
                    )
            shutil.rmtree(staging)
        else:
            os.replace(staging, final)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise

    latest_payload = _json_bytes(
        {
            "schema_version": "1.0",
            "scenario_id": recipe.scenario_id,
            "snapshot_id": snapshot_id,
            "snapshot_path": f"snapshots/{snapshot_id}",
            "metadata_sha256": _sha256(metadata_payload),
        }
    )
    latest_pointer = output_dir / "latest.json"
    _atomic_write(latest_pointer, latest_payload)
    return BaseNetworkBuildResult(
        snapshot_id=snapshot_id,
        snapshot_dir=final,
        latest_pointer=latest_pointer,
        node_count=len(network["nodes"]),
        edge_count=len(network["edges"]),
    )


def _validated_artifact_path(snapshot_dir: Path, relative_path: str) -> Path:
    root = snapshot_dir.resolve()
    path = (root / relative_path).resolve()
    if path != root and root not in path.parents:
        raise BaseNetworkBuildError(f"artifact path escapes snapshot: {relative_path}")
    if not path.is_file():
        raise BaseNetworkBuildError(f"snapshot artifact is missing: {relative_path}")
    return path


def validate_base_network_snapshot(snapshot_dir: Path, recipe: ScenarioRecipe) -> None:
    snapshot_dir = snapshot_dir.resolve()
    try:
        metadata = ScenarioSnapshotMetadata.model_validate_json(
            (snapshot_dir / "metadata.json").read_text(encoding="utf-8")
        )
        metadata.validate_against(recipe)
    except (OSError, ValidationError, ValueError) as error:
        raise BaseNetworkBuildError(
            f"invalid snapshot metadata in {snapshot_dir}: {error}"
        ) from error

    if (
        metadata.field_lineage_artifact.path != "provenance/field-lineage.jsonl.gz"
        or metadata.field_lineage_artifact.media_type != "application/gzip"
    ):
        raise BaseNetworkBuildError(
            "field-lineage artifact must be provenance/field-lineage.jsonl.gz with "
            "application/gzip media type"
        )
    expected_derived_media = {
        "recipe.json": "application/json",
        "base-network.json": "application/json",
        "base-network.geojson": "application/geo+json",
    }
    actual_derived_media = {
        artifact.path: artifact.media_type for artifact in metadata.derived_artifacts
    }
    if actual_derived_media != expected_derived_media:
        raise BaseNetworkBuildError("snapshot derived-artifact declarations are inconsistent")

    artifacts = [
        *(artifact for source in metadata.sources for artifact in source.artifacts),
        metadata.field_lineage_artifact,
        *metadata.derived_artifacts,
    ]
    for artifact in artifacts:
        path = _validated_artifact_path(snapshot_dir, artifact.path)
        payload = path.read_bytes()
        if len(payload) != artifact.byte_size or _sha256(payload) != artifact.sha256:
            raise BaseNetworkBuildError(
                f"snapshot artifact checksum/size mismatch: {artifact.path}"
            )

    try:
        frozen_recipe = ScenarioRecipe.model_validate_json(
            (snapshot_dir / "recipe.json").read_text(encoding="utf-8")
        )
        network = json.loads((snapshot_dir / "base-network.json").read_text(encoding="utf-8"))
        geojson = json.loads((snapshot_dir / "base-network.geojson").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise BaseNetworkBuildError(f"cannot parse snapshot artifacts: {error}") from error
    if frozen_recipe.sha256() != recipe.sha256():
        raise BaseNetworkBuildError("frozen recipe differs from the requested recipe")
    if network.get("schema_version") != BASE_NETWORK_SCHEMA_VERSION:
        raise BaseNetworkBuildError("unsupported base-network schema version")
    if network.get("builder_version") != BASE_NETWORK_BUILDER_VERSION:
        raise BaseNetworkBuildError("base-network builder version does not match this validator")
    if network.get("scope") != "base_network_only":
        raise BaseNetworkBuildError("network scope must be base_network_only")
    if network.get("snapshot_id") != metadata.snapshot_id:
        raise BaseNetworkBuildError("network and metadata snapshot IDs differ")
    if network.get("scenario_id") != recipe.scenario_id:
        raise BaseNetworkBuildError("network and recipe scenario IDs differ")
    if (
        network.get("analysis_crs") != recipe.analysis_crs
        or network.get("display_crs") != DISPLAY_CRS
    ):
        raise BaseNetworkBuildError("network CRS declarations are inconsistent")
    core_area = canonicalize_area(recipe)
    network_area = canonicalize_network_context(recipe, core_area)
    if network.get("core_boundary") != core_area.geojson:
        raise BaseNetworkBuildError("network core boundary differs from the recipe")
    if network.get("network_context_boundary") != network_area.geojson:
        raise BaseNetworkBuildError("network context boundary differs from the recipe")
    if network.get("network_context_buffer_m") != recipe.network_context_buffer_m:
        raise BaseNetworkBuildError("network context buffer differs from the recipe")

    nodes = network.get("nodes")
    edges = network.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise BaseNetworkBuildError("network nodes and edges must be arrays")
    to_analysis = Transformer.from_crs(DISPLAY_CRS, recipe.analysis_crs, always_xy=True)
    node_by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            raise BaseNetworkBuildError("network contains a malformed node")
        if node["id"] in node_by_id:
            raise BaseNetworkBuildError(f"duplicate node ID {node['id']}")
        if not all(
            isinstance(node.get(field), (int, float)) and math.isfinite(float(node[field]))
            for field in ("longitude", "latitude", "x", "y")
        ):
            raise BaseNetworkBuildError(f"node {node['id']} has invalid coordinates")
        projected_x, projected_y = to_analysis.transform(
            float(node["longitude"]), float(node["latitude"])
        )
        if abs(projected_x - float(node["x"])) > 0.05 or abs(projected_y - float(node["y"])) > 0.05:
            raise BaseNetworkBuildError(f"node {node['id']} metric and display coordinates differ")
        node_by_id[node["id"]] = node

    edge_by_id: dict[str, dict[str, Any]] = {}
    edges_by_physical_segment: dict[str, dict[str, dict[str, Any]]] = {}
    for edge in edges:
        if not isinstance(edge, dict) or not isinstance(edge.get("id"), str):
            raise BaseNetworkBuildError("network contains a malformed edge")
        edge_id = edge["id"]
        if edge_id in edge_by_id:
            raise BaseNetworkBuildError(f"duplicate edge ID {edge_id}")
        direction = edge.get("direction")
        if direction not in {"forward", "reverse"}:
            raise BaseNetworkBuildError(f"edge {edge_id} has invalid direction")
        physical_segment_id = _edge_physical_segment_id(edge)
        physical_directions = edges_by_physical_segment.setdefault(physical_segment_id, {})
        if direction in physical_directions:
            raise BaseNetworkBuildError(
                f"physical segment {physical_segment_id} has duplicate {direction} edges"
            )
        physical_directions[direction] = edge
        if edge.get("from") not in node_by_id or edge.get("to") not in node_by_id:
            raise BaseNetworkBuildError(f"edge {edge_id} references a missing node")
        permissions = edge.get("permissions")
        if (
            not isinstance(permissions, dict)
            or set(permissions) != set(MODE_NAMES)
            or not all(isinstance(permissions[mode], bool) for mode in MODE_NAMES)
        ):
            raise BaseNetworkBuildError(f"edge {edge_id} lacks explicit mode permissions")
        if not any(permissions.values()):
            raise BaseNetworkBuildError(f"edge {edge_id} is unusable by every emitted mode")
        geometry = edge.get("geometry")
        if not isinstance(geometry, list) or len(geometry) < 2:
            raise BaseNetworkBuildError(f"edge {edge_id} has invalid geometry")
        try:
            display_line = LineString(geometry)
            analysis_line = transform(to_analysis.transform, display_line)
        except (TypeError, ValueError) as error:
            raise BaseNetworkBuildError(f"edge {edge_id} has invalid geometry") from error
        if not network_area.analysis.buffer(0.1).covers(analysis_line):
            raise BaseNetworkBuildError(f"edge {edge_id} extends outside the network context")
        length = edge.get("length_m")
        if not isinstance(length, (int, float)) or length <= 0:
            raise BaseNetworkBuildError(f"edge {edge_id} has invalid length")
        if abs(float(length) - analysis_line.length) > 0.1:
            raise BaseNetworkBuildError(f"edge {edge_id} length does not match its geometry")
        start_node = node_by_id[edge["from"]]
        end_node = node_by_id[edge["to"]]
        if list(geometry[0]) != [start_node["longitude"], start_node["latitude"]] or list(
            geometry[-1]
        ) != [end_node["longitude"], end_node["latitude"]]:
            raise BaseNetworkBuildError(f"edge {edge_id} endpoints do not match its nodes")
        edge_by_id[edge_id] = edge

    for physical_segment_id, directions in edges_by_physical_segment.items():
        forward = directions.get("forward")
        reverse = directions.get("reverse")
        if forward is None or reverse is None:
            continue
        if (
            reverse["from"] != forward["to"]
            or reverse["to"] != forward["from"]
            or reverse["geometry"] != list(reversed(forward["geometry"]))
        ):
            raise BaseNetworkBuildError(
                f"directed edges for {physical_segment_id} are not exact opposites"
            )
        if any(
            reverse[field] != forward[field]
            for field in ("length_m", "highway", "name", "source", "tags")
        ):
            raise BaseNetworkBuildError(
                f"directed edges for {physical_segment_id} disagree on source attributes"
            )

    referenced_node_ids = {
        node_id for edge in edges for node_id in (edge["from"], edge["to"])
    }
    orphan_node_ids = sorted(set(node_by_id) - referenced_node_ids)
    if orphan_node_ids:
        raise BaseNetworkBuildError(
            f"network contains unreferenced node {orphan_node_ids[0]}"
        )

    counts = network.get("counts", {})
    if counts.get("nodes") != len(nodes) or counts.get("directed_edges") != len(edges):
        raise BaseNetworkBuildError("network counts do not match node/edge arrays")
    if counts.get("physical_segments") != len(edges_by_physical_segment):
        raise BaseNetworkBuildError("network physical-segment count is inconsistent")
    if geojson.get("type") != "FeatureCollection" or not isinstance(geojson.get("features"), list):
        raise BaseNetworkBuildError("browser artifact is not a GeoJSON FeatureCollection")
    if (
        geojson.get("schema_version") != BASE_NETWORK_SCHEMA_VERSION
        or geojson.get("builder_version") != BASE_NETWORK_BUILDER_VERSION
    ):
        raise BaseNetworkBuildError("browser artifact version differs from the network")
    core_features = [
        feature
        for feature in geojson["features"]
        if feature.get("properties", {}).get("layer") == "study_core"
    ]
    context_features = [
        feature
        for feature in geojson["features"]
        if feature.get("properties", {}).get("layer") == "network_context"
    ]
    if len(core_features) != 1 or shape(core_features[0]["geometry"]) != core_area.wgs84:
        raise BaseNetworkBuildError("browser GeoJSON lacks the canonical study-core feature")
    if len(context_features) != 1 or shape(context_features[0]["geometry"]) != network_area.wgs84:
        raise BaseNetworkBuildError("browser GeoJSON lacks the canonical network-context feature")
    segment_features = [
        feature
        for feature in geojson["features"]
        if feature.get("properties", {}).get("layer") == "base_network"
    ]
    if len(segment_features) != len(edges_by_physical_segment):
        raise BaseNetworkBuildError("browser GeoJSON must contain one feature per physical segment")
    seen_physical_segments: set[str] = set()
    seen_directed_edges: set[str] = set()
    for feature in segment_features:
        properties = feature.get("properties", {})
        physical_segment_id = properties.get("physical_segment_id")
        if physical_segment_id not in edges_by_physical_segment:
            raise BaseNetworkBuildError(
                f"browser feature references unknown physical segment {physical_segment_id!r}"
            )
        if physical_segment_id in seen_physical_segments:
            raise BaseNetworkBuildError(
                f"browser duplicates physical segment {physical_segment_id}"
            )
        seen_physical_segments.add(physical_segment_id)
        if feature.get("id") != physical_segment_id:
            raise BaseNetworkBuildError(
                f"browser feature ID differs for physical segment {physical_segment_id}"
            )

        directions = edges_by_physical_segment[physical_segment_id]
        forward = directions.get("forward")
        reverse = directions.get("reverse")
        if forward is not None:
            expected_geometry = forward["geometry"]
            expected_from = forward["from"]
            expected_to = forward["to"]
        elif reverse is not None:
            expected_geometry = list(reversed(reverse["geometry"]))
            expected_from = reverse["to"]
            expected_to = reverse["from"]
        else:  # pragma: no cover - every group is populated from an edge
            raise BaseNetworkBuildError(
                f"physical segment {physical_segment_id} has no directed edge"
            )
        if feature.get("geometry") != {
            "type": "LineString",
            "coordinates": expected_geometry,
        }:
            raise BaseNetworkBuildError(
                f"browser geometry orientation differs for {physical_segment_id}"
            )

        reference = forward or reverse
        assert reference is not None
        expected_properties = {
            "from": expected_from,
            "to": expected_to,
            "length_m": reference["length_m"],
            "highway": reference["highway"],
            "name": reference["name"],
        }
        if any(properties.get(key) != value for key, value in expected_properties.items()):
            raise BaseNetworkBuildError(
                f"browser source attributes differ for {physical_segment_id}"
            )

        for direction, edge in (("forward", forward), ("reverse", reverse)):
            edge_id_property = f"{direction}_edge_id"
            expected_edge_id = edge["id"] if edge is not None else None
            if properties.get(edge_id_property) != expected_edge_id:
                raise BaseNetworkBuildError(
                    f"browser {edge_id_property} differs for {physical_segment_id}"
                )
            if edge is not None:
                if edge["id"] in seen_directed_edges:
                    raise BaseNetworkBuildError(
                        f"browser maps directed edge {edge['id']} more than once"
                    )
                seen_directed_edges.add(edge["id"])
            for mode in MODE_NAMES:
                expected_available = bool(edge is not None and edge["permissions"][mode])
                availability_property = f"{mode}_{direction}"
                if properties.get(availability_property) is not expected_available:
                    raise BaseNetworkBuildError(
                        f"browser {availability_property} differs for {physical_segment_id}"
                    )

    if seen_physical_segments != set(edges_by_physical_segment):
        raise BaseNetworkBuildError("browser omits a physical segment")
    if seen_directed_edges != set(edge_by_id):
        raise BaseNetworkBuildError("browser does not map every directed edge exactly once")

    lineage_path = snapshot_dir / metadata.field_lineage_artifact.path
    compressed_lineage = lineage_path.read_bytes()
    if len(compressed_lineage) < 10 or compressed_lineage[4:8] != b"\x00\x00\x00\x00":
        raise BaseNetworkBuildError("field lineage is not a deterministic mtime=0 gzip stream")
    try:
        lineage_text = gzip.decompress(compressed_lineage).decode("utf-8")
    except (EOFError, OSError, UnicodeDecodeError, zlib.error) as error:
        raise BaseNetworkBuildError(f"cannot decompress field-lineage artifact: {error}") from error
    seen_lineage: set[tuple[str, str]] = set()
    for line_number, line in enumerate(lineage_text.splitlines(), 1):
        try:
            record = FieldLineage.model_validate_json(line)
        except ValidationError as error:
            raise BaseNetworkBuildError(
                f"invalid field-lineage record on line {line_number}: {error}"
            ) from error
        if record.output_feature_id not in edge_by_id:
            raise BaseNetworkBuildError(
                f"lineage references unknown edge {record.output_feature_id}"
            )
        identity = (record.output_feature_id, record.output_field)
        if identity in seen_lineage:
            raise BaseNetworkBuildError(f"duplicate field-lineage record {identity}")
        seen_lineage.add(identity)
    expected_lineage = {
        (edge_id, field)
        for edge_id in edge_by_id
        for field in (
            "geometry",
            "length_m",
            "permissions.private_car",
            "permissions.walking",
            "permissions.cycling",
        )
    }
    if seen_lineage != expected_lineage:
        raise BaseNetworkBuildError("field lineage is incomplete for emitted edge fields")


def validate_latest_base_network(output_dir: Path, recipe: ScenarioRecipe) -> Path:
    pointer_path = output_dir.resolve() / "latest.json"
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BaseNetworkBuildError(
            f"cannot read latest snapshot pointer {pointer_path}"
        ) from error
    if pointer.get("scenario_id") != recipe.scenario_id:
        raise BaseNetworkBuildError("latest pointer scenario differs from the recipe")
    relative = pointer.get("snapshot_path")
    if not isinstance(relative, str):
        raise BaseNetworkBuildError("latest pointer lacks snapshot_path")
    snapshot_dir = (output_dir.resolve() / relative).resolve()
    if output_dir.resolve() not in snapshot_dir.parents:
        raise BaseNetworkBuildError("latest pointer escapes the output directory")
    validate_base_network_snapshot(snapshot_dir, recipe)
    metadata_payload = (snapshot_dir / "metadata.json").read_bytes()
    if _sha256(metadata_payload) != pointer.get("metadata_sha256"):
        raise BaseNetworkBuildError("latest pointer metadata checksum differs from the snapshot")
    if pointer.get("snapshot_id") != snapshot_dir.name:
        raise BaseNetworkBuildError("latest pointer snapshot ID and path differ")
    return snapshot_dir
