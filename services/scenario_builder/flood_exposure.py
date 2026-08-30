"""Deterministic coastal-flood exposure overlay for a frozen base network.

This module deliberately derives *exposure*, not road passability.  A positive
line/polygon intersection says only that the mapped horizontal road geometry
overlaps an official SYKE flood-hazard polygon.  Bridges, tunnels, layers,
covered ways, fords, depth thresholds, vehicle capability, and operational
closures require a later, explicit model.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely import make_valid, set_precision
from shapely.errors import GEOSException
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Polygon,
    mapping,
    shape,
)
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree

from .syke import (
    SEA_FLOOD_1_IN_100,
    SEA_FLOOD_1_IN_1000,
    SYKE_ADAPTER_VERSION,
    SYKE_WFS_ENDPOINT,
    SykeArchiveError,
    derive_wfs_url,
    load_syke_archive,
)

FLOOD_EXPOSURE_SCHEMA_VERSION = "1.0"
FLOOD_EXPOSURE_BUILDER_VERSION = "1.1.0"
ANALYSIS_CRS = "EPSG:3067"
DISPLAY_CRS = "EPSG:4326"

RETURN_PERIOD_BY_LAYER = {
    SEA_FLOOD_1_IN_100: 100,
    SEA_FLOOD_1_IN_1000: 1_000,
}
REQUIRED_LAYERS = tuple(RETURN_PERIOD_BY_LAYER)

# The classification is intentionally explicit rather than inferred from labels.
# IDs 1--5 are the published terrestrial depth bands.  The remaining published
# values below are not terrestrial inundation evidence for this overlay.
DEPTH_CLASSES: dict[int, dict[str, Any]] = {
    1: {"label": "0–0.5 m", "minimum_depth_m": 0.0, "maximum_depth_m": 0.5},
    2: {"label": "0.5–1 m", "minimum_depth_m": 0.5, "maximum_depth_m": 1.0},
    3: {"label": "1–2 m", "minimum_depth_m": 1.0, "maximum_depth_m": 2.0},
    4: {"label": "2–3 m", "minimum_depth_m": 2.0, "maximum_depth_m": 3.0},
    5: {"label": ">3 m", "minimum_depth_m": 3.0, "maximum_depth_m": None},
}
EXCLUDED_DEPTH_CLASSES = {
    0: "dry_land",
    12: "fixed_protection",
    99: "waterbody",
}
VERTICAL_TAGS = ("bridge", "tunnel", "layer", "covered", "ford")
TRUE_TAG_VALUES = {"yes", "true", "1"}
FALSE_TAG_VALUES = {"no", "false", "0"}
LENGTH_EPSILON_M = 0.001


class FloodExposureBuildError(ValueError):
    """Raised when exposure inputs or derived output cannot be verified."""


@dataclass(frozen=True)
class VerifiedSykeInput:
    manifest: dict[str, Any]
    pointer_path: Path
    pointer_sha256: str
    archive_paths: dict[str, Path]
    archive_sha256: dict[str, str]
    documents: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class FloodExposureBuildResult:
    snapshot_id: str
    snapshot_dir: Path
    latest_pointer: Path
    physical_segment_count: int
    exposed_segment_counts: dict[int, int]


@dataclass(frozen=True)
class HazardSpatialIndex:
    """One deterministic return-period index over included source polygons."""

    geometries: tuple[BaseGeometry, ...]
    records: tuple[dict[str, Any], ...]
    tree: STRtree


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: Any, *, compact: bool = False) -> bytes:
    options = {"separators": (",", ":")} if compact else {"indent": 2}
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            **options,
        )
    except (TypeError, ValueError) as error:
        raise FloodExposureBuildError("output contains a non-finite or non-JSON value") from error
    return (encoded + "\n").encode("utf-8")


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


def _safe_child(parent: Path, filename: Any, suffix: str) -> Path:
    if (
        not isinstance(filename, str)
        or Path(filename).name != filename
        or not filename.endswith(suffix)
    ):
        raise FloodExposureBuildError(f"unsafe source artifact filename {filename!r}")
    candidate = (parent / filename).resolve()
    if candidate.parent != parent.resolve() or not candidate.is_file():
        raise FloodExposureBuildError(f"source artifact is missing: {filename!r}")
    return candidate


def _finite_bbox(value: Any) -> tuple[float, float, float, float]:
    if not isinstance(value, list) or len(value) != 4:
        raise FloodExposureBuildError("SYKE pointer bbox must contain four values")
    try:
        result = tuple(float(component) for component in value)
    except (TypeError, ValueError) as error:
        raise FloodExposureBuildError("SYKE pointer bbox is not numeric") from error
    if not all(math.isfinite(component) for component in result):
        raise FloodExposureBuildError("SYKE pointer bbox contains a non-finite value")
    if result[0] >= result[2] or result[1] >= result[3]:
        raise FloodExposureBuildError("SYKE pointer bbox is empty")
    return result  # type: ignore[return-value]


def _parse_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise FloodExposureBuildError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise FloodExposureBuildError(f"{field} is not a valid ISO timestamp") from error
    if parsed.tzinfo is None:
        raise FloodExposureBuildError(f"{field} must include a timezone")
    return parsed


def _parse_source_edition(value: Any, feature_id: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise FloodExposureBuildError(
            f"SYKE feature {feature_id!r} muutospvm must be a date, timestamp, or null"
        )
    try:
        if "T" in value:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
        else:
            date.fromisoformat(value)
    except ValueError as error:
        raise FloodExposureBuildError(
            f"SYKE feature {feature_id!r} has invalid muutospvm {value!r}"
        ) from error
    return value


def _parse_integer(value: Any, *, field: str, feature_id: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise FloodExposureBuildError(f"SYKE feature {feature_id!r} {field} cannot be boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    raise FloodExposureBuildError(f"SYKE feature {feature_id!r} {field} must be an integer or null")


def _line_parts(geometry: BaseGeometry) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [geometry] if geometry.length > 0 else []
    if isinstance(geometry, MultiLineString):
        return [part for part in geometry.geoms if part.length > 0]
    if isinstance(geometry, GeometryCollection):
        return [part for child in geometry.geoms for part in _line_parts(child)]
    return []


def _polygon_parts(geometry: BaseGeometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry] if geometry.area > 0 else []
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if part.area > 0]
    if isinstance(geometry, GeometryCollection):
        return [part for child in geometry.geoms for part in _polygon_parts(child)]
    return []


def _rounded_mapping(geometry: BaseGeometry, decimals: int = 7) -> dict[str, Any]:
    # Independent coordinate rounding can make an otherwise valid polygon
    # self-intersect at the display grid. GEOS precision reduction nodes and
    # repairs topology while quantizing, so the browser artifact stays both
    # compact and valid for complex real SYKE multipolygons.
    try:
        quantized = set_precision(
            geometry,
            grid_size=10.0**-decimals,
            mode="valid_output",
        )
    except GEOSException as error:
        raise FloodExposureBuildError(
            "display geometry could not be reduced to the declared precision"
        ) from error
    if quantized.is_empty:
        raise FloodExposureBuildError(
            "display geometry collapsed at the declared coordinate precision"
        )
    document = mapping(quantized)

    def rounded(value: Any) -> Any:
        if isinstance(value, (tuple, list)):
            return [rounded(component) for component in value]
        if isinstance(value, float):
            return round(value, decimals)
        return value

    return {"type": document["type"], "coordinates": rounded(document["coordinates"])}


def _geometry_hash(line: LineString) -> str:
    forward = tuple((round(x, 3), round(y, 3)) for x, y in line.coords)
    reverse = tuple(reversed(forward))
    canonical = min(forward, reverse)
    return _sha256(repr(canonical).encode("ascii"))[:24]


def _edge_physical_id(edge: dict[str, Any], line: LineString) -> str:
    existing = edge.get("physical_segment_id")
    if isinstance(existing, str) and existing:
        return existing
    source = edge.get("source")
    if isinstance(source, dict):
        way = source.get("way_id")
        segment = source.get("segment_index")
        part = source.get("part_index")
        if isinstance(way, int) and isinstance(segment, int) and isinstance(part, int):
            return f"osm-way-{way}-segment-{segment:04d}-part-{part:02d}"
    return f"geometry-{_geometry_hash(line)}"


def _network_context_analysis(base_network: dict[str, Any]) -> BaseGeometry:
    geometry = base_network.get("network_context_boundary")
    if not isinstance(geometry, dict):
        raise FloodExposureBuildError("base network lacks network_context_boundary")
    try:
        parsed = shape(geometry)
        projected = transform(
            Transformer.from_crs(DISPLAY_CRS, ANALYSIS_CRS, always_xy=True).transform,
            parsed,
        )
    except (TypeError, ValueError, GEOSException) as error:
        raise FloodExposureBuildError("base network context geometry is invalid") from error
    if projected.is_empty or not projected.is_valid or not _polygon_parts(projected):
        raise FloodExposureBuildError("base network context must be a valid non-empty polygon")
    return projected


def _load_verified_base_network(path: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    path = path.resolve()
    if not path.is_file():
        raise FloodExposureBuildError(f"base-network input is missing: {path}")
    metadata_path = path.parent / "metadata.json"
    if not metadata_path.is_file():
        raise FloodExposureBuildError(
            "base-network input must be inside a snapshot with sibling metadata.json"
        )
    payload = path.read_bytes()
    metadata_payload = metadata_path.read_bytes()
    try:
        metadata = json.loads(metadata_payload)
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FloodExposureBuildError("base-network input or metadata is not valid JSON") from error
    artifacts = metadata.get("derived_artifacts") if isinstance(metadata, dict) else None
    if not isinstance(artifacts, list):
        raise FloodExposureBuildError("base snapshot metadata lacks derived_artifacts")
    digest = next(
        (item for item in artifacts if isinstance(item, dict) and item.get("path") == path.name),
        None,
    )
    if not isinstance(digest, dict):
        raise FloodExposureBuildError("base snapshot metadata does not reference base-network.json")
    if digest.get("sha256") != _sha256(payload) or digest.get("byte_size") != len(payload):
        raise FloodExposureBuildError("base-network checksum differs from snapshot metadata")
    if metadata.get("snapshot_id") != document.get("snapshot_id"):
        raise FloodExposureBuildError("base network and metadata snapshot IDs differ")
    _validate_base_network_document(document)
    return document, metadata, _sha256(payload)


def _validate_base_network_document(document: Any) -> None:
    if not isinstance(document, dict):
        raise FloodExposureBuildError("base network must be a JSON object")
    if document.get("artifact_type") != "resilient_access_base_network":
        raise FloodExposureBuildError("input is not a resilient-access base network")
    if document.get("analysis_crs") != ANALYSIS_CRS or document.get("display_crs") != DISPLAY_CRS:
        raise FloodExposureBuildError("base network must advertise EPSG:3067/EPSG:4326")
    if not isinstance(document.get("snapshot_id"), str) or not document["snapshot_id"]:
        raise FloodExposureBuildError("base network lacks snapshot_id")
    nodes = document.get("nodes")
    edges = document.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list) or not edges:
        raise FloodExposureBuildError("base network must contain node and edge arrays")
    node_ids = [node.get("id") for node in nodes if isinstance(node, dict)]
    if len(node_ids) != len(nodes) or any(not isinstance(value, str) for value in node_ids):
        raise FloodExposureBuildError("base network contains an invalid node ID")
    if len(node_ids) != len(set(node_ids)):
        raise FloodExposureBuildError("base network contains duplicate node IDs")
    node_set = set(node_ids)
    edge_ids: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            raise FloodExposureBuildError("base network contains a non-object edge")
        edge_id = edge.get("id")
        if not isinstance(edge_id, str) or not edge_id or edge_id in edge_ids:
            raise FloodExposureBuildError("base network contains an invalid or duplicate edge ID")
        edge_ids.add(edge_id)
        if edge.get("from") not in node_set or edge.get("to") not in node_set:
            raise FloodExposureBuildError(f"base edge {edge_id!r} references a missing node")
        coordinates = edge.get("geometry")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise FloodExposureBuildError(f"base edge {edge_id!r} has invalid geometry")
        try:
            line = LineString(coordinates)
        except (TypeError, ValueError, GEOSException) as error:
            raise FloodExposureBuildError(
                f"base edge {edge_id!r} geometry cannot be decoded"
            ) from error
        if line.is_empty or line.length <= 0 or not line.is_valid:
            raise FloodExposureBuildError(f"base edge {edge_id!r} geometry is empty or invalid")
    _network_context_analysis(document)


def load_verified_syke_input(pointer_path: Path) -> VerifiedSykeInput:
    """Verify a fixed SYKE pointer and every content-addressed archive offline."""

    pointer_path = pointer_path.resolve()
    if not pointer_path.is_file():
        raise FloodExposureBuildError(f"SYKE pointer is missing: {pointer_path}")
    pointer_payload = pointer_path.read_bytes()
    try:
        manifest = json.loads(pointer_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FloodExposureBuildError("SYKE pointer is not valid JSON") from error
    if not isinstance(manifest, dict):
        raise FloodExposureBuildError("SYKE pointer must be a JSON object")
    expected_header = {
        "schema_version": "1.0",
        "adapter_version": SYKE_ADAPTER_VERSION,
        "endpoint": SYKE_WFS_ENDPOINT,
        "source_crs": ANALYSIS_CRS,
    }
    mismatches = [key for key, value in expected_header.items() if manifest.get(key) != value]
    if mismatches:
        raise FloodExposureBuildError("SYKE pointer has incompatible " + ", ".join(mismatches))
    if not isinstance(manifest.get("scenario_id"), str) or not manifest["scenario_id"]:
        raise FloodExposureBuildError("SYKE pointer lacks scenario_id")
    _parse_datetime(manifest.get("acquired_at"), "SYKE acquired_at")
    bbox = _finite_bbox(manifest.get("bbox"))
    layers = manifest.get("layers")
    if not isinstance(layers, list) or [
        item.get("layer") if isinstance(item, dict) else None for item in layers
    ] != list(REQUIRED_LAYERS):
        raise FloodExposureBuildError(
            "SYKE pointer must contain the audited 1/100 and 1/1000 layers in canonical order"
        )

    archive_paths: dict[str, Path] = {}
    archive_sha256: dict[str, str] = {}
    documents: dict[str, dict[str, Any]] = {}
    for item in layers:
        layer = item["layer"]
        expected_period = RETURN_PERIOD_BY_LAYER[layer]
        if item.get("return_period_years") != expected_period:
            raise FloodExposureBuildError(f"SYKE pointer has wrong return period for {layer}")
        expected_url = derive_wfs_url(layer, bbox)
        if item.get("query_url") != expected_url:
            raise FloodExposureBuildError(f"SYKE pointer has a non-canonical query for {layer}")
        if item.get("query_sha256") != _sha256(expected_url.encode("utf-8")):
            raise FloodExposureBuildError(f"SYKE query checksum differs for {layer}")
        archive_path = _safe_child(pointer_path.parent, item.get("archive_file"), ".geojson.gz")
        compressed = archive_path.read_bytes()
        digest = _sha256(compressed)
        if digest != item.get("archive_sha256") or len(compressed) != item.get("byte_size"):
            raise FloodExposureBuildError(f"SYKE archive checksum or size differs for {layer}")
        try:
            raw = gzip.decompress(compressed)
        except (OSError, EOFError) as error:
            raise FloodExposureBuildError(
                f"SYKE archive cannot be decompressed for {layer}"
            ) from error
        if _sha256(raw) != item.get("raw_sha256"):
            raise FloodExposureBuildError(f"SYKE raw checksum differs for {layer}")
        try:
            document = load_syke_archive(archive_path, layer=layer, bbox=bbox)
        except (SykeArchiveError, ValueError) as error:
            raise FloodExposureBuildError(
                f"invalid frozen SYKE archive for {layer}: {error}"
            ) from error
        if len(document.get("features", [])) != item.get("feature_count"):
            raise FloodExposureBuildError(f"SYKE feature count differs for {layer}")
        archive_paths[layer] = archive_path
        archive_sha256[layer] = digest
        documents[layer] = document
    return VerifiedSykeInput(
        manifest=manifest,
        pointer_path=pointer_path,
        pointer_sha256=_sha256(pointer_payload),
        archive_paths=archive_paths,
        archive_sha256=archive_sha256,
        documents=documents,
    )


def _assert_syke_covers_context(
    base_network: dict[str, Any], manifest: dict[str, Any]
) -> BaseGeometry:
    context = _network_context_analysis(base_network)
    minimum_x, minimum_y, maximum_x, maximum_y = _finite_bbox(manifest.get("bbox"))
    context_bounds = context.bounds
    tolerance_m = 0.01
    if not (
        minimum_x <= context_bounds[0] + tolerance_m
        and minimum_y <= context_bounds[1] + tolerance_m
        and maximum_x >= context_bounds[2] - tolerance_m
        and maximum_y >= context_bounds[3] - tolerance_m
    ):
        raise FloodExposureBuildError(
            "SYKE archived bbox does not cover the full buffered base-network context"
        )
    return context


def _physical_segments(base_network: dict[str, Any]) -> list[dict[str, Any]]:
    to_analysis = Transformer.from_crs(DISPLAY_CRS, ANALYSIS_CRS, always_xy=True)
    grouped: dict[str, list[tuple[dict[str, Any], LineString]]] = defaultdict(list)
    for edge in base_network["edges"]:
        display_line = LineString(edge["geometry"])
        analysis_line = transform(to_analysis.transform, display_line)
        physical_id = _edge_physical_id(edge, analysis_line)
        grouped[physical_id].append((edge, analysis_line))

    segments: list[dict[str, Any]] = []
    for physical_id, members in sorted(grouped.items()):
        representative_edge, representative_line = min(members, key=lambda item: item[0]["id"])
        canonical_hash = _geometry_hash(representative_line)
        for _edge, line in members:
            if _geometry_hash(line) != canonical_hash:
                raise FloodExposureBuildError(
                    f"physical segment {physical_id!r} groups directed edges with "
                    "different geometry"
                )
        directed_ids = sorted(edge["id"] for edge, _ in members)
        tags: dict[str, str] = {}
        for edge, _ in members:
            edge_tags = edge.get("tags") if isinstance(edge.get("tags"), dict) else {}
            for key in VERTICAL_TAGS:
                value = edge_tags.get(key, edge.get(key))
                if value is not None:
                    normalized = str(value).strip().lower()
                    existing = tags.get(key)
                    if existing is not None and existing != normalized:
                        raise FloodExposureBuildError(
                            f"physical segment {physical_id!r} has conflicting {key} tags"
                        )
                    tags[key] = normalized
        vertical = _vertical_review(tags, base_network.get("builder_version"))
        segments.append(
            {
                "id": physical_id,
                "directed_edge_ids": directed_ids,
                "line": representative_line,
                "length_m": float(representative_line.length),
                "highway": representative_edge.get("highway"),
                "name": representative_edge.get("name"),
                "source": representative_edge.get("source", {}),
                "vertical_separation": vertical,
            }
        )
    return segments


def _vertical_review(tags: dict[str, str], builder_version: Any) -> dict[str, Any]:
    indicators: dict[str, str] = {}
    for key, value in sorted(tags.items()):
        if key == "layer":
            try:
                is_indicator = float(value) != 0
            except ValueError:
                is_indicator = True
        elif key in {"bridge", "tunnel", "covered", "ford"}:
            is_indicator = value not in FALSE_TAG_VALUES
        else:
            is_indicator = False
        if is_indicator:
            indicators[key] = value

    if indicators:
        return {
            "status": "review_required",
            "review_required": True,
            "indicators": indicators,
            "reason": (
                "OSM vertical-separation or ford tags are present; horizontal flood overlap "
                "must not be interpreted as deck/tunnel passability."
            ),
        }
    version_known = isinstance(builder_version, str) and tuple(
        int(part) if part.isdigit() else 0 for part in builder_version.split(".")[:2]
    ) >= (1, 1)
    if version_known:
        return {
            "status": "no_mapped_indicator",
            "review_required": False,
            "indicators": {},
            "reason": (
                "The retained OSM vertical tags contain no affirmative indicator; this is not "
                "field verification."
            ),
        }
    return {
        "status": "unknown",
        "review_required": None,
        "indicators": {},
        "reason": (
            "This base-network builder version does not establish that all relevant vertical "
            "tags were retained."
        ),
    }


def _prepare_hazards(
    documents: dict[str, dict[str, Any]], context: BaseGeometry
) -> tuple[
    dict[tuple[int, int], BaseGeometry],
    dict[int, BaseGeometry],
    dict[int, HazardSpatialIndex],
    list[dict[str, Any]],
    dict[str, Any],
    list[str],
]:
    geometries: dict[tuple[int, int], list[BaseGeometry]] = defaultdict(list)
    feature_records: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    lineage: list[dict[str, Any]] = []
    warnings: set[str] = set()
    excluded = Counter()
    source_counts: dict[int, int] = {}
    included_counts: dict[int, int] = {}
    repairs = 0
    clipped_empty = 0

    for layer in REQUIRED_LAYERS:
        period = RETURN_PERIOD_BY_LAYER[layer]
        document = documents.get(layer)
        if not isinstance(document, dict) or not isinstance(document.get("features"), list):
            raise FloodExposureBuildError(f"missing verified SYKE document for {layer}")
        source_counts[period] = len(document["features"])
        included_counts[period] = 0
        for feature in sorted(document["features"], key=lambda item: item["id"]):
            feature_id = feature["id"]
            properties = feature.get("properties")
            if not isinstance(properties, dict):
                raise FloodExposureBuildError(f"SYKE feature {feature_id!r} lacks properties")
            recurrence = _parse_integer(
                properties.get("toistuvuus"), field="toistuvuus", feature_id=feature_id
            )
            depth_id = _parse_integer(
                properties.get("syvsuojluokka_id"),
                field="syvsuojluokka_id",
                feature_id=feature_id,
            )
            depth_label_value = properties.get("syvsuojluokka")
            if depth_label_value is not None and not isinstance(depth_label_value, str):
                raise FloodExposureBuildError(
                    f"SYKE feature {feature_id!r} syvsuojluokka must be text or null"
                )
            source_label = depth_label_value.strip() if isinstance(depth_label_value, str) else None
            source_edition = _parse_source_edition(properties.get("muutospvm"), feature_id)
            bridge_value = properties.get("silta_id")
            if bridge_value is not None and not isinstance(bridge_value, (str, int, float)):
                raise FloodExposureBuildError(
                    f"SYKE feature {feature_id!r} silta_id must be scalar or null"
                )

            exclusion: str | None = None
            if (
                recurrence is None
                and depth_id is None
                and source_label is None
                and bridge_value is None
                and source_edition is None
            ):
                exclusion = "null_boundary_artifact"
            elif recurrence != period:
                raise FloodExposureBuildError(
                    f"SYKE feature {feature_id!r} recurrence {recurrence!r} does not match {period}"
                )
            elif depth_id in EXCLUDED_DEPTH_CLASSES:
                exclusion = EXCLUDED_DEPTH_CLASSES[depth_id]
            elif depth_id is None:
                exclusion = "missing_depth_class"
                warnings.add(
                    "One or more non-boundary SYKE features lacked a depth class and were excluded."
                )
            elif depth_id not in DEPTH_CLASSES:
                exclusion = "unsupported_depth_class"
                warnings.add(
                    "One or more SYKE features used an unrecognised depth class and were excluded."
                )

            repaired = False
            clipped_area_m2 = 0.0
            if exclusion is None:
                try:
                    geometry = shape(feature["geometry"])
                except (KeyError, TypeError, ValueError, GEOSException) as error:
                    raise FloodExposureBuildError(
                        f"SYKE feature {feature_id!r} geometry cannot be decoded"
                    ) from error
                if not geometry.is_valid:
                    geometry = make_valid(geometry)
                    repaired = True
                    repairs += 1
                polygon_parts = _polygon_parts(geometry)
                if not polygon_parts:
                    exclusion = "repair_produced_no_polygon"
                    warnings.add(
                        "One or more invalid SYKE geometries had no polygonal area after repair."
                    )
                else:
                    polygonal = unary_union(polygon_parts)
                    try:
                        clipped = polygonal.intersection(context)
                    except GEOSException as error:
                        raise FloodExposureBuildError(
                            f"SYKE feature {feature_id!r} could not be clipped"
                        ) from error
                    clipped_parts = _polygon_parts(clipped)
                    if not clipped_parts:
                        exclusion = "outside_network_context"
                        clipped_empty += 1
                    else:
                        clipped = unary_union(clipped_parts)
                        clipped_area_m2 = float(clipped.area)
                        key = (period, depth_id)
                        geometries[key].append(clipped)
                        record = {
                            "source_feature_id": feature_id,
                            "return_period_years": period,
                            "depth_class_id": depth_id,
                            "source_depth_label": source_label,
                            "source_bridge_id": None if bridge_value is None else str(bridge_value),
                            "source_edition": source_edition,
                            "geometry": clipped,
                        }
                        feature_records[key].append(record)
                        included_counts[period] += 1
            if exclusion is not None:
                excluded[exclusion] += 1
            lineage.append(
                {
                    "record_type": "hazard_feature_preparation",
                    "source_adapter_id": "syke",
                    "source_feature_id": feature_id,
                    "return_period_years": period,
                    "source_fields": {
                        "toistuvuus": recurrence,
                        "syvsuojluokka_id": depth_id,
                        "syvsuojluokka": source_label,
                        "silta_id": None if bridge_value is None else str(bridge_value),
                        "muutospvm": source_edition,
                    },
                    "included_as_terrestrial_exposure": exclusion is None,
                    "exclusion_reason": exclusion,
                    "geometry_repaired_with_make_valid": repaired,
                    "clipped_area_m2": round(clipped_area_m2, 3),
                    "operation": (
                        "classify documented SYKE depth ID; make_valid if needed; extract "
                        "polygonal parts; clip to buffered EPSG:3067 network context"
                    ),
                }
            )

    unions = {key: unary_union(parts) for key, parts in sorted(geometries.items()) if parts}
    feature_records_by_depth = {
        key: sorted(records, key=lambda item: item["source_feature_id"])
        for key, records in sorted(feature_records.items())
    }
    period_unions = {
        period: unary_union(
            [
                geometry
                for (candidate_period, _depth), geometry in unions.items()
                if candidate_period == period
            ]
        )
        for period in sorted(RETURN_PERIOD_BY_LAYER.values())
        if any(candidate_period == period for candidate_period, _depth in unions)
    }
    spatial_indexes: dict[int, HazardSpatialIndex] = {}
    for period in sorted(RETURN_PERIOD_BY_LAYER.values()):
        records = sorted(
            (
                record
                for (candidate_period, _depth), depth_records in feature_records_by_depth.items()
                if candidate_period == period
                for record in depth_records
            ),
            key=lambda item: (item["depth_class_id"], item["source_feature_id"]),
        )
        if records:
            indexed_geometries = tuple(record["geometry"] for record in records)
            spatial_indexes[period] = HazardSpatialIndex(
                geometries=indexed_geometries,
                records=tuple(records),
                tree=STRtree(indexed_geometries),
            )
    statistics = {
        "source_features_by_return_period": {
            str(period): source_counts[period] for period in sorted(source_counts)
        },
        "included_terrestrial_features_by_return_period": {
            str(period): included_counts[period] for period in sorted(included_counts)
        },
        "excluded_source_features_by_reason": dict(sorted(excluded.items())),
        "geometry_repairs_with_make_valid": repairs,
        "features_clipped_empty": clipped_empty,
    }
    return unions, period_unions, spatial_indexes, lineage, statistics, sorted(warnings)


def _scenario_exposure(
    line: LineString,
    *,
    period: int,
    unions: dict[tuple[int, int], BaseGeometry],
    period_unions: dict[int, BaseGeometry],
    spatial_indexes: dict[int, HazardSpatialIndex],
) -> tuple[dict[str, Any], BaseGeometry | None, int]:
    period_union = period_unions.get(period)
    if period_union is None:
        return (
            {
                "return_period_years": period,
                "exposed": False,
                "intersected_length_m": 0.0,
                "intersected_share": 0.0,
                "deepest_depth_class_id": None,
                "deepest_depth_class": None,
                "depth_class_lengths_m": {},
                "source_feature_ids": [],
            },
            None,
            0,
        )
    exposed_geometry = line.intersection(period_union)
    exposed_parts = _line_parts(exposed_geometry)
    exposed_geometry = unary_union(exposed_parts) if exposed_parts else None
    exposed_length = float(exposed_geometry.length) if exposed_geometry is not None else 0.0
    if exposed_length <= LENGTH_EPSILON_M:
        return (
            {
                "return_period_years": period,
                "exposed": False,
                "intersected_length_m": 0.0,
                "intersected_share": 0.0,
                "deepest_depth_class_id": None,
                "deepest_depth_class": None,
                "depth_class_lengths_m": {},
                "source_feature_ids": [],
            },
            None,
            0,
        )

    remaining: BaseGeometry = line
    depth_lengths: dict[str, float] = {}
    deepest: int | None = None
    source_ids: set[str] = set()
    for depth_id in sorted(DEPTH_CLASSES, reverse=True):
        hazard = unions.get((period, depth_id))
        if hazard is None:
            continue
        portion_parts = _line_parts(remaining.intersection(hazard))
        portion_length = sum(part.length for part in portion_parts)
        if portion_length > LENGTH_EPSILON_M:
            depth_lengths[str(depth_id)] = round(float(portion_length), 3)
            deepest = depth_id if deepest is None else max(deepest, depth_id)
        remaining = remaining.difference(hazard)

    candidate_checks = 0
    spatial_index = spatial_indexes.get(period)
    if spatial_index is not None:
        for candidate_index in spatial_index.tree.query(line):
            candidate_checks += 1
            index = int(candidate_index)
            if (
                sum(
                    part.length
                    for part in _line_parts(line.intersection(spatial_index.geometries[index]))
                )
                > LENGTH_EPSILON_M
            ):
                source_ids.add(spatial_index.records[index]["source_feature_id"])

    length_m = float(line.length)
    return (
        {
            "return_period_years": period,
            "exposed": True,
            "intersected_length_m": round(exposed_length, 3),
            "intersected_share": round(min(1.0, exposed_length / length_m), 6),
            "deepest_depth_class_id": deepest,
            "deepest_depth_class": DEPTH_CLASSES[deepest]["label"] if deepest else None,
            "depth_class_lengths_m": depth_lengths,
            "source_feature_ids": sorted(source_ids),
        },
        exposed_geometry,
        candidate_checks,
    )


def derive_flood_exposure_documents(
    base_network: dict[str, Any],
    syke_documents: dict[str, dict[str, Any]],
    *,
    scenario_id: str,
    snapshot_id: str,
    base_sha256: str,
    syke_pointer_sha256: str,
    syke_archive_sha256: dict[str, str],
    syke_manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Derive compact JSON, browser GeoJSON, and lineage from verified inputs."""

    _validate_base_network_document(base_network)
    context = _assert_syke_covers_context(base_network, syke_manifest)
    (
        unions,
        period_unions,
        spatial_indexes,
        lineage,
        hazard_statistics,
        warnings,
    ) = _prepare_hazards(syke_documents, context)
    physical_segments = _physical_segments(base_network)
    to_display = Transformer.from_crs(ANALYSIS_CRS, DISPLAY_CRS, always_xy=True)

    output_segments: list[dict[str, Any]] = []
    geojson_features: list[dict[str, Any]] = []
    exposed_counts = Counter()
    exposed_lengths = Counter()
    review_counts = Counter()
    spatial_candidate_checks = Counter()

    for (period, depth_id), geometry in sorted(unions.items()):
        display_geometry = transform(to_display.transform, geometry)
        geojson_features.append(
            {
                "type": "Feature",
                "id": f"hazard-rp-{period}-depth-{depth_id}",
                "geometry": _rounded_mapping(display_geometry),
                "properties": {
                    "layer": "coastal_flood_hazard",
                    "return_period_years": period,
                    "depth_class_id": depth_id,
                    "depth_class": DEPTH_CLASSES[depth_id]["label"],
                    "exposure_only": True,
                },
            }
        )

    for segment in physical_segments:
        scenario_records: list[dict[str, Any]] = []
        for period in sorted(RETURN_PERIOD_BY_LAYER.values()):
            scenario, exposed_geometry, candidate_checks = _scenario_exposure(
                segment["line"],
                period=period,
                unions=unions,
                period_unions=period_unions,
                spatial_indexes=spatial_indexes,
            )
            spatial_candidate_checks[period] += candidate_checks
            scenario_records.append(scenario)
            if scenario["exposed"]:
                exposed_counts[period] += 1
                exposed_lengths[period] += scenario["intersected_length_m"]
                if segment["vertical_separation"]["status"] != "no_mapped_indicator":
                    review_counts[period] += 1
                display_exposure = transform(to_display.transform, exposed_geometry)
                geojson_features.append(
                    {
                        "type": "Feature",
                        "id": f"exposure-rp-{period}-{segment['id']}",
                        "geometry": _rounded_mapping(display_exposure),
                        "properties": {
                            "layer": "network_flood_exposure",
                            "physical_segment_id": segment["id"],
                            "directed_edge_ids": segment["directed_edge_ids"],
                            "return_period_years": period,
                            "intersected_length_m": scenario["intersected_length_m"],
                            "intersected_share": scenario["intersected_share"],
                            "deepest_depth_class_id": scenario["deepest_depth_class_id"],
                            "vertical_review_status": segment["vertical_separation"]["status"],
                            "passability_not_inferred": True,
                        },
                    }
                )
            lineage.append(
                {
                    "record_type": "physical_segment_exposure",
                    "output_feature_id": segment["id"],
                    "return_period_years": period,
                    "base_directed_edge_ids": segment["directed_edge_ids"],
                    "source_feature_ids": scenario["source_feature_ids"],
                    "operation": (
                        "deduplicate directed base edges to one physical segment; intersect the "
                        "EPSG:3067 line once with depth-class hazard unions; do not infer "
                        "passability"
                    ),
                }
            )
        output_segments.append(
            {
                "id": segment["id"],
                "directed_edge_ids": segment["directed_edge_ids"],
                "length_m": round(segment["length_m"], 3),
                "highway": segment["highway"],
                "name": segment["name"],
                "source": segment["source"],
                "vertical_separation": segment["vertical_separation"],
                "scenarios": scenario_records,
            }
        )

    warnings.extend(
        [
            (
                "Horizontal line/polygon overlap is exposure evidence only. It does not establish "
                "water depth on the carriageway or whether any mode can pass."
            ),
            (
                "OSM and SYKE geometry, classification, and elevation errors remain possible; "
                "bridge, tunnel, layer, covered, and ford indicators require review."
            ),
            (
                "No closure, safe-route, emergency-access, traffic, drainage, wave, duration, "
                "velocity, or forecast claim is produced by this artifact."
            ),
        ]
    )
    directed_count = len(base_network["edges"])
    physical_count = len(output_segments)
    document = {
        "schema_version": FLOOD_EXPOSURE_SCHEMA_VERSION,
        "artifact_type": "resilient_access_flood_exposure",
        "builder_version": FLOOD_EXPOSURE_BUILDER_VERSION,
        "scope": "exposure_only",
        "scenario_id": scenario_id,
        "snapshot_id": snapshot_id,
        "analysis_crs": ANALYSIS_CRS,
        "display_crs": DISPLAY_CRS,
        "base_network": {
            "scenario_id": base_network.get("scenario_id"),
            "snapshot_id": base_network["snapshot_id"],
            "sha256": base_sha256,
        },
        "syke_source": {
            "adapter_version": syke_manifest["adapter_version"],
            "pointer_sha256": syke_pointer_sha256,
            "acquired_at": syke_manifest["acquired_at"],
            "bbox_epsg3067": syke_manifest["bbox"],
            "archive_sha256_by_layer": {
                layer: syke_archive_sha256[layer] for layer in REQUIRED_LAYERS
            },
        },
        "semantics": {
            "exposure_only": True,
            "passability_not_inferred": True,
            "closure_not_inferred": True,
            "safe_route_not_inferred": True,
        },
        "thematic_classification": {
            "source_depth_id_field": "syvsuojluokka_id",
            "source_depth_label_field": "syvsuojluokka",
            "included_terrestrial_depth_classes": {
                str(key): value for key, value in sorted(DEPTH_CLASSES.items())
            },
            "excluded_depth_classes": {
                str(key): value for key, value in sorted(EXCLUDED_DEPTH_CLASSES.items())
            },
            "null_thematic_features": "excluded_as_source_boundary_artifacts",
            "unknown_depth_classes": "excluded_with_warning",
        },
        "counts": {
            "base_directed_edges": directed_count,
            "physical_segments": physical_count,
            "deduplicated_directed_edge_records": directed_count - physical_count,
            **hazard_statistics,
            "exposed_physical_segments_by_return_period": {
                str(period): exposed_counts[period]
                for period in sorted(RETURN_PERIOD_BY_LAYER.values())
            },
            "exposed_length_m_by_return_period": {
                str(period): round(exposed_lengths[period], 3)
                for period in sorted(RETURN_PERIOD_BY_LAYER.values())
            },
            "exposed_segments_needing_vertical_review_by_return_period": {
                str(period): review_counts[period]
                for period in sorted(RETURN_PERIOD_BY_LAYER.values())
            },
            "spatial_index_candidate_checks_by_return_period": {
                str(period): spatial_candidate_checks[period]
                for period in sorted(RETURN_PERIOD_BY_LAYER.values())
            },
        },
        "warnings": sorted(set(warnings)),
        "segments": output_segments,
    }
    geojson = {
        "type": "FeatureCollection",
        "name": f"{scenario_id}-flood-exposure",
        "metadata": {
            "scenario_id": scenario_id,
            "snapshot_id": snapshot_id,
            "scope": "exposure_only",
            "passability_not_inferred": True,
            "attribution": (
                "Source: Finnish Environment Institute (SYKE); OpenStreetMap contributors"
            ),
        },
        "features": sorted(geojson_features, key=lambda item: str(item["id"])),
    }
    lineage.sort(
        key=lambda item: (
            item["record_type"],
            str(item.get("source_feature_id", item.get("output_feature_id", ""))),
            int(item.get("return_period_years", 0)),
        )
    )
    validate_flood_exposure_document(document, geojson, base_network, lineage)
    return document, geojson, lineage


def validate_flood_exposure_document(
    document: Any,
    geojson: Any,
    base_network: dict[str, Any],
    lineage: Iterable[dict[str, Any]],
) -> None:
    """Validate counts, geometries, and cross-artifact references."""

    if (
        not isinstance(document, dict)
        or document.get("artifact_type") != "resilient_access_flood_exposure"
    ):
        raise FloodExposureBuildError("derived document is not a flood-exposure artifact")
    if document.get("scope") != "exposure_only":
        raise FloodExposureBuildError("derived flood artifact must be exposure_only")
    semantics = document.get("semantics")
    if not isinstance(semantics, dict) or semantics.get("passability_not_inferred") is not True:
        raise FloodExposureBuildError("derived flood artifact must disclaim passability inference")
    base_edge_ids = {edge["id"] for edge in base_network["edges"]}
    segments = document.get("segments")
    if not isinstance(segments, list):
        raise FloodExposureBuildError("derived flood artifact lacks segments")
    segment_ids: set[str] = set()
    referenced_edges: set[str] = set()
    exposure_count = Counter()
    exposure_length = Counter()
    source_refs: set[str] = set()
    for segment in segments:
        segment_id = segment.get("id") if isinstance(segment, dict) else None
        if not isinstance(segment_id, str) or not segment_id or segment_id in segment_ids:
            raise FloodExposureBuildError("derived flood artifact has invalid segment IDs")
        segment_ids.add(segment_id)
        edge_ids = segment.get("directed_edge_ids")
        if not isinstance(edge_ids, list) or not edge_ids or edge_ids != sorted(edge_ids):
            raise FloodExposureBuildError(f"segment {segment_id!r} has invalid edge references")
        if any(edge_id not in base_edge_ids for edge_id in edge_ids):
            raise FloodExposureBuildError(f"segment {segment_id!r} references a missing base edge")
        overlap = referenced_edges.intersection(edge_ids)
        if overlap:
            raise FloodExposureBuildError(
                f"directed base edge appears in multiple physical segments: {sorted(overlap)[0]}"
            )
        referenced_edges.update(edge_ids)
        scenarios = segment.get("scenarios")
        if not isinstance(scenarios, list) or [
            scenario.get("return_period_years")
            for scenario in scenarios
            if isinstance(scenario, dict)
        ] != [100, 1_000]:
            raise FloodExposureBuildError(f"segment {segment_id!r} lacks canonical scenarios")
        for scenario in scenarios:
            period = scenario["return_period_years"]
            length = scenario.get("intersected_length_m")
            share = scenario.get("intersected_share")
            if not isinstance(length, (int, float)) or not isinstance(share, (int, float)):
                raise FloodExposureBuildError(
                    f"segment {segment_id!r} has invalid exposure metrics"
                )
            if length < 0 or share < 0 or share > 1 or length > segment["length_m"] + 0.01:
                raise FloodExposureBuildError(
                    f"segment {segment_id!r} exposure metrics are out of range"
                )
            if bool(scenario.get("exposed")) != (length > 0):
                raise FloodExposureBuildError(
                    f"segment {segment_id!r} exposure flag and length differ"
                )
            if scenario["exposed"]:
                exposure_count[period] += 1
                exposure_length[period] += length
            refs = scenario.get("source_feature_ids")
            if not isinstance(refs, list) or refs != sorted(refs):
                raise FloodExposureBuildError(
                    f"segment {segment_id!r} source references are invalid"
                )
            source_refs.update(refs)
    if referenced_edges != base_edge_ids:
        missing = sorted(base_edge_ids - referenced_edges)
        raise FloodExposureBuildError(
            f"derived physical segments omit base directed edge {missing[0]!r}"
        )
    counts = document.get("counts")
    if not isinstance(counts, dict):
        raise FloodExposureBuildError("derived flood artifact lacks counts")
    if counts.get("physical_segments") != len(segments):
        raise FloodExposureBuildError("physical segment count does not match output")
    for period in (100, 1_000):
        if (
            counts["exposed_physical_segments_by_return_period"].get(str(period))
            != exposure_count[period]
        ):
            raise FloodExposureBuildError("exposed segment count does not match output")
        reported_length = counts["exposed_length_m_by_return_period"].get(str(period))
        if not math.isclose(reported_length, round(exposure_length[period], 3), abs_tol=0.001):
            raise FloodExposureBuildError("exposed segment length does not match output")

    lineage_items = list(lineage)
    known_source_ids = {
        item.get("source_feature_id")
        for item in lineage_items
        if item.get("record_type") == "hazard_feature_preparation"
    }
    if not source_refs.issubset(known_source_ids):
        missing = sorted(source_refs - known_source_ids)
        raise FloodExposureBuildError(
            f"segment exposure references missing source feature {missing[0]!r}"
        )
    expected_segment_lineage = {
        (segment_id, period) for segment_id in segment_ids for period in (100, 1_000)
    }
    actual_segment_lineage = {
        (item.get("output_feature_id"), item.get("return_period_years"))
        for item in lineage_items
        if item.get("record_type") == "physical_segment_exposure"
    }
    if actual_segment_lineage != expected_segment_lineage:
        raise FloodExposureBuildError("physical-segment exposure lineage is incomplete")

    if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
        raise FloodExposureBuildError("browser artifact is not a GeoJSON FeatureCollection")
    features = geojson.get("features")
    if not isinstance(features, list):
        raise FloodExposureBuildError("browser GeoJSON lacks features")
    feature_ids: set[str] = set()
    browser_exposure_refs: set[tuple[str, int]] = set()
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise FloodExposureBuildError("browser GeoJSON contains a non-Feature")
        feature_id = feature.get("id")
        if not isinstance(feature_id, str) or feature_id in feature_ids:
            raise FloodExposureBuildError("browser GeoJSON has invalid or duplicate feature IDs")
        feature_ids.add(feature_id)
        try:
            geometry = shape(feature.get("geometry"))
        except (TypeError, ValueError, GEOSException) as error:
            raise FloodExposureBuildError(
                f"browser feature {feature_id!r} has invalid geometry"
            ) from error
        if geometry.is_empty or not geometry.is_valid:
            raise FloodExposureBuildError(
                f"browser feature {feature_id!r} has empty/invalid geometry"
            )
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise FloodExposureBuildError(f"browser feature {feature_id!r} lacks properties")
        if properties.get("layer") == "network_flood_exposure":
            segment_id = properties.get("physical_segment_id")
            period = properties.get("return_period_years")
            if segment_id not in segment_ids or period not in {100, 1_000}:
                raise FloodExposureBuildError(
                    f"browser exposure feature {feature_id!r} has missing "
                    "segment/scenario reference"
                )
            browser_exposure_refs.add((segment_id, period))
    expected_browser_refs = {
        (segment["id"], scenario["return_period_years"])
        for segment in segments
        for scenario in segment["scenarios"]
        if scenario["exposed"]
    }
    if browser_exposure_refs != expected_browser_refs:
        raise FloodExposureBuildError("browser exposure features do not match compact output")


def _input_identity(
    base_network: dict[str, Any], base_sha256: str, syke: VerifiedSykeInput
) -> dict[str, Any]:
    return {
        "builder_version": FLOOD_EXPOSURE_BUILDER_VERSION,
        "base_snapshot_id": base_network["snapshot_id"],
        "base_sha256": base_sha256,
        "syke_pointer_sha256": syke.pointer_sha256,
        "syke_archives": {layer: syke.archive_sha256[layer] for layer in REQUIRED_LAYERS},
    }


def build_flood_exposure_snapshot(
    *,
    base_network_path: Path,
    syke_pointer_path: Path,
    output_dir: Path,
) -> FloodExposureBuildResult:
    """Build and atomically publish an offline exposure-only snapshot."""

    base_network, base_metadata, base_sha256 = _load_verified_base_network(base_network_path)
    syke = load_verified_syke_input(syke_pointer_path)
    _assert_syke_covers_context(base_network, syke.manifest)
    identity = _input_identity(base_network, base_sha256, syke)
    snapshot_id = f"flood-{_sha256(_json_bytes(identity, compact=True))[:24]}"
    scenario_id = syke.manifest["scenario_id"]
    document, geojson, lineage = derive_flood_exposure_documents(
        base_network,
        syke.documents,
        scenario_id=scenario_id,
        snapshot_id=snapshot_id,
        base_sha256=base_sha256,
        syke_pointer_sha256=syke.pointer_sha256,
        syke_archive_sha256=syke.archive_sha256,
        syke_manifest=syke.manifest,
    )
    document_payload = _json_bytes(document, compact=True)
    geojson_payload = _json_bytes(geojson, compact=True)
    lineage_jsonl = b"".join(_json_bytes(item, compact=True) for item in lineage)
    lineage_payload = gzip.compress(lineage_jsonl, compresslevel=9, mtime=0)
    input_records = [
        {
            "role": "base_network",
            "artifact": "base-network.json",
            "snapshot_id": base_network["snapshot_id"],
            "metadata_sha256": _sha256(
                (base_network_path.resolve().parent / "metadata.json").read_bytes()
            ),
            "sha256": base_sha256,
            "byte_size": base_network_path.resolve().stat().st_size,
        },
        {
            "role": "flood_hazard_pointer",
            "artifact": syke.pointer_path.name,
            "adapter_version": syke.manifest["adapter_version"],
            "sha256": syke.pointer_sha256,
            "byte_size": syke.pointer_path.stat().st_size,
        },
    ]
    input_records.extend(
        {
            "role": "flood_hazard_archive",
            "layer": layer,
            "artifact": syke.archive_paths[layer].name,
            "sha256": syke.archive_sha256[layer],
            "byte_size": syke.archive_paths[layer].stat().st_size,
        }
        for layer in REQUIRED_LAYERS
    )
    derived = [
        {
            "path": "flood-exposure.json",
            "sha256": _sha256(document_payload),
            "byte_size": len(document_payload),
            "media_type": "application/json",
        },
        {
            "path": "flood-exposure.geojson",
            "sha256": _sha256(geojson_payload),
            "byte_size": len(geojson_payload),
            "media_type": "application/geo+json",
        },
        {
            "path": "provenance/flood-exposure-lineage.jsonl.gz",
            "sha256": _sha256(lineage_payload),
            "byte_size": len(lineage_payload),
            "media_type": "application/gzip",
        },
    ]
    metadata = {
        "schema_version": "1.0",
        "artifact_type": "flood_exposure_snapshot_metadata",
        "snapshot_id": snapshot_id,
        "scenario_id": scenario_id,
        "builder_version": FLOOD_EXPOSURE_BUILDER_VERSION,
        "created_at": syke.manifest["acquired_at"],
        "analysis_crs": ANALYSIS_CRS,
        "scope": "exposure_only",
        "passability_not_inferred": True,
        "inputs": input_records,
        "derived_artifacts": derived,
        "licences": [
            {
                "source": "OpenStreetMap contributors",
                "licence": "ODbL 1.0",
                "url": "https://www.openstreetmap.org/copyright",
            },
            {
                "source": "Finnish Environment Institute (SYKE)",
                "licence": "CC BY 4.0",
                "url": "https://www.syke.fi/en/environmental-data/use-license-and-responsibilities",
            },
        ],
        "base_snapshot_created_at": base_metadata.get("created_at"),
    }
    metadata_payload = _json_bytes(metadata)
    output_dir = output_dir.resolve()
    snapshots_dir = output_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=output_dir))
    final = snapshots_dir / snapshot_id
    files = {
        "flood-exposure.json": document_payload,
        "flood-exposure.geojson": geojson_payload,
        "provenance/flood-exposure-lineage.jsonl.gz": lineage_payload,
        "metadata.json": metadata_payload,
    }
    try:
        for relative, payload in files.items():
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        _validate_snapshot_files(staging, base_network)
        if final.exists():
            _validate_snapshot_files(final, base_network)
            for relative, payload in files.items():
                if (final / relative).read_bytes() != payload:
                    raise FloodExposureBuildError(
                        f"immutable exposure snapshot {snapshot_id} already has different bytes"
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
            "scenario_id": scenario_id,
            "snapshot_id": snapshot_id,
            "snapshot_path": f"snapshots/{snapshot_id}",
            "metadata_sha256": _sha256(metadata_payload),
        }
    )
    latest = output_dir / "latest.json"
    _atomic_write(latest, latest_payload)
    return FloodExposureBuildResult(
        snapshot_id=snapshot_id,
        snapshot_dir=final,
        latest_pointer=latest,
        physical_segment_count=len(document["segments"]),
        exposed_segment_counts={
            period: document["counts"]["exposed_physical_segments_by_return_period"][str(period)]
            for period in (100, 1_000)
        },
    )


def _load_lineage(path: Path) -> list[dict[str, Any]]:
    try:
        payload = gzip.decompress(path.read_bytes()).decode("utf-8")
    except (OSError, EOFError, UnicodeDecodeError) as error:
        raise FloodExposureBuildError("flood lineage is not valid UTF-8 gzip") from error
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(payload.splitlines(), 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise FloodExposureBuildError(
                f"invalid flood lineage JSON on line {line_number}"
            ) from error
        if not isinstance(record, dict):
            raise FloodExposureBuildError(f"flood lineage line {line_number} is not an object")
        records.append(record)
    return records


def _validate_snapshot_files(snapshot_dir: Path, base_network: dict[str, Any]) -> None:
    try:
        metadata_payload = (snapshot_dir / "metadata.json").read_bytes()
        metadata = json.loads(metadata_payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FloodExposureBuildError("invalid flood-exposure snapshot metadata") from error
    if not isinstance(metadata, dict) or metadata.get("scope") != "exposure_only":
        raise FloodExposureBuildError("invalid flood-exposure snapshot metadata scope")
    artifacts = metadata.get("derived_artifacts")
    if not isinstance(artifacts, list):
        raise FloodExposureBuildError("flood metadata lacks derived artifacts")
    for artifact in artifacts:
        relative = artifact.get("path") if isinstance(artifact, dict) else None
        if not isinstance(relative, str) or ".." in relative.replace("\\", "/").split("/"):
            raise FloodExposureBuildError("flood metadata contains unsafe artifact path")
        path = (snapshot_dir / relative).resolve()
        if snapshot_dir.resolve() not in path.parents or not path.is_file():
            raise FloodExposureBuildError(f"flood snapshot artifact is missing: {relative}")
        payload = path.read_bytes()
        if artifact.get("sha256") != _sha256(payload) or artifact.get("byte_size") != len(payload):
            raise FloodExposureBuildError(f"flood snapshot artifact checksum differs: {relative}")
    try:
        document = json.loads((snapshot_dir / "flood-exposure.json").read_text(encoding="utf-8"))
        geojson = json.loads((snapshot_dir / "flood-exposure.geojson").read_text(encoding="utf-8"))
        lineage = _load_lineage(snapshot_dir / "provenance/flood-exposure-lineage.jsonl.gz")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FloodExposureBuildError("cannot decode a flood-exposure snapshot artifact") from error
    if document.get("snapshot_id") != metadata.get("snapshot_id"):
        raise FloodExposureBuildError("flood document and metadata snapshot IDs differ")
    validate_flood_exposure_document(document, geojson, base_network, lineage)


def validate_latest_flood_exposure(
    *,
    output_dir: Path,
    base_network_path: Path,
    syke_pointer_path: Path,
) -> Path:
    """Revalidate a latest pointer, source checksums, and all output references."""

    base_network, _, base_sha256 = _load_verified_base_network(base_network_path)
    syke = load_verified_syke_input(syke_pointer_path)
    pointer_path = output_dir.resolve() / "latest.json"
    try:
        pointer_payload = pointer_path.read_bytes()
        pointer = json.loads(pointer_payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FloodExposureBuildError("cannot read latest flood-exposure pointer") from error
    relative = pointer.get("snapshot_path") if isinstance(pointer, dict) else None
    if not isinstance(relative, str):
        raise FloodExposureBuildError("latest flood pointer lacks snapshot_path")
    snapshot_dir = (output_dir.resolve() / relative).resolve()
    if output_dir.resolve() not in snapshot_dir.parents:
        raise FloodExposureBuildError("latest flood pointer escapes output directory")
    metadata_payload = (snapshot_dir / "metadata.json").read_bytes()
    if pointer.get("metadata_sha256") != _sha256(metadata_payload):
        raise FloodExposureBuildError("latest flood pointer metadata checksum differs")
    if pointer.get("snapshot_id") != snapshot_dir.name:
        raise FloodExposureBuildError("latest flood pointer snapshot ID and path differ")
    _validate_snapshot_files(snapshot_dir, base_network)
    document = json.loads((snapshot_dir / "flood-exposure.json").read_text(encoding="utf-8"))
    if document["base_network"]["sha256"] != base_sha256:
        raise FloodExposureBuildError("flood output was built from a different base network")
    if document["syke_source"]["pointer_sha256"] != syke.pointer_sha256:
        raise FloodExposureBuildError("flood output was built from a different SYKE pointer")
    return snapshot_dir
