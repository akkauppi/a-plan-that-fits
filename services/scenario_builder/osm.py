from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import Point, Polygon, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from .adapters import AdapterConfigurationError, SourceAcquisitionContext
from .models import (
    ANALYSIS_CRS,
    FINLAND_BUILD_ENVELOPE,
    CoverageAssessment,
    LicenceRecord,
    PointRadiusArea,
    ScenarioRecipe,
    SourceSnapshotMetadata,
)

OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
OVERPASS_ADAPTER_ID = "osm"
OVERPASS_ADAPTER_VERSION = "1.0.0"
OVERPASS_DEFAULT_TIMEOUT_S = 60
OVERPASS_MIN_TIMEOUT_S = 10
OVERPASS_MAX_TIMEOUT_S = 120
MAX_RESPONSE_BYTES = 50 * 1024 * 1024
CANONICAL_COORDINATE_DECIMALS = 7
POINT_RADIUS_QUAD_SEGS = 24

FetchTransport = Callable[[str, int], bytes]
Clock = Callable[[], datetime]


class OsmArchiveError(ValueError):
    """Raised when an OSM archive is missing, stale, malformed, or inconsistent."""


@dataclass(frozen=True)
class CanonicalArea:
    wgs84: Polygon
    analysis: Polygon
    geojson: dict[str, Any]

    @property
    def overpass_exterior(self) -> tuple[tuple[float, float], ...]:
        return tuple((float(x), float(y)) for x, y in self.wgs84.exterior.coords[:-1])


def _signed_twice_area(ring: list[tuple[float, float]]) -> float:
    return sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True)
    )


def _canonical_ring(
    coordinates: Any, *, counter_clockwise: bool
) -> list[tuple[float, float]]:
    rounded: list[tuple[float, float]] = []
    for coordinate in list(coordinates)[:-1]:
        point = (
            round(float(coordinate[0]), CANONICAL_COORDINATE_DECIMALS),
            round(float(coordinate[1]), CANONICAL_COORDINATE_DECIMALS),
        )
        if not rounded or point != rounded[-1]:
            rounded.append(point)
    if len(rounded) < 3:
        raise ValueError("canonical study polygon has fewer than three distinct exterior points")

    is_counter_clockwise = _signed_twice_area(rounded) > 0
    if is_counter_clockwise != counter_clockwise:
        rounded.reverse()

    start = min(range(len(rounded)), key=lambda index: rounded[index])
    rotated = rounded[start:] + rounded[:start]
    return [*rotated, rotated[0]]


def _canonical_polygon(polygon: Polygon) -> Polygon:
    exterior = _canonical_ring(polygon.exterior.coords, counter_clockwise=True)
    interiors = sorted(
        (
            _canonical_ring(interior.coords, counter_clockwise=False)
            for interior in polygon.interiors
        ),
        key=lambda ring: ring,
    )
    canonical = Polygon(exterior, interiors)
    if canonical.is_empty or not canonical.is_valid or canonical.area <= 0:
        raise ValueError("study area is not a valid polygon after canonicalization")
    return canonical


def canonicalize_area(recipe: ScenarioRecipe) -> CanonicalArea:
    """Return one deterministic bounded WGS84 polygon and its metric equivalent."""

    to_analysis = Transformer.from_crs("EPSG:4326", recipe.analysis_crs, always_xy=True)
    to_display = Transformer.from_crs(recipe.analysis_crs, "EPSG:4326", always_xy=True)

    if isinstance(recipe.area, PointRadiusArea):
        center = transform(
            to_analysis.transform,
            Point(recipe.area.center.longitude, recipe.area.center.latitude),
        )
        analysis_seed = center.buffer(
            recipe.area.radius_m,
            quad_segs=POINT_RADIUS_QUAD_SEGS,
        )
        display_seed = transform(to_display.transform, analysis_seed)
    else:
        display_seed = Polygon(
            recipe.area.geometry.coordinates[0],
            recipe.area.geometry.coordinates[1:],
        )

    display = _canonical_polygon(display_seed)
    analysis_geometry: BaseGeometry = transform(to_analysis.transform, display)
    if not isinstance(analysis_geometry, Polygon):
        raise ValueError("study area projection did not produce a polygon")
    if analysis_geometry.area > 25_000_000.0 + 1.0:
        raise ValueError("canonical study area exceeds the 25 km² v1 build limit")

    geojson = json.loads(json.dumps(mapping(display), separators=(",", ":")))
    return CanonicalArea(wgs84=display, analysis=analysis_geometry, geojson=geojson)


def canonicalize_network_context(
    recipe: ScenarioRecipe, core: CanonicalArea | None = None
) -> CanonicalArea:
    """Buffer the selected core in metric space for acquisition and graph continuity."""

    core = core or canonicalize_area(recipe)
    to_display = Transformer.from_crs(recipe.analysis_crs, "EPSG:4326", always_xy=True)
    if recipe.network_context_buffer_m == 0:
        return core
    context_seed = core.analysis.buffer(
        recipe.network_context_buffer_m,
        quad_segs=POINT_RADIUS_QUAD_SEGS,
    )
    display_seed = transform(to_display.transform, context_seed)
    if not isinstance(display_seed, Polygon):
        raise ValueError("network context buffer did not produce one polygon")
    display = _canonical_polygon(display_seed)
    west, south, east, north = FINLAND_BUILD_ENVELOPE
    min_x, min_y, max_x, max_y = display.bounds
    if min_x < west or max_x > east or min_y < south or max_y > north:
        raise ValueError("network context buffer crosses outside the Finland v1 build envelope")
    to_analysis = Transformer.from_crs("EPSG:4326", recipe.analysis_crs, always_xy=True)
    analysis_geometry = transform(to_analysis.transform, display)
    if not isinstance(analysis_geometry, Polygon):
        raise ValueError("network context projection did not produce one polygon")
    geojson = json.loads(json.dumps(mapping(display), separators=(",", ":")))
    return CanonicalArea(wgs84=display, analysis=analysis_geometry, geojson=geojson)


def _timeout_from_context(context: SourceAcquisitionContext) -> int:
    parameters = context.declaration.parameters
    unknown = sorted(set(parameters) - {"overpass_timeout_s"})
    if unknown:
        raise AdapterConfigurationError(
            "unsupported osm source parameter(s): "
            + ", ".join(unknown)
            + "; the endpoint and query shape are controlled by the adapter"
        )
    timeout = parameters.get("overpass_timeout_s", OVERPASS_DEFAULT_TIMEOUT_S)
    if isinstance(timeout, bool) or not isinstance(timeout, int):
        raise AdapterConfigurationError("osm overpass_timeout_s must be an integer")
    if not OVERPASS_MIN_TIMEOUT_S <= timeout <= OVERPASS_MAX_TIMEOUT_S:
        raise AdapterConfigurationError(
            f"osm overpass_timeout_s must be {OVERPASS_MIN_TIMEOUT_S}--"
            f"{OVERPASS_MAX_TIMEOUT_S} seconds"
        )
    return timeout


def derive_overpass_query(area: CanonicalArea, timeout_s: int) -> str:
    """Derive a bounded highway query; callers cannot inject QL or remote URLs."""

    polygon = " ".join(
        f"{latitude:.{CANONICAL_COORDINATE_DECIMALS}f} "
        f"{longitude:.{CANONICAL_COORDINATE_DECIMALS}f}"
        for longitude, latitude in area.overpass_exterior
    )
    return (
        f"[out:json][timeout:{timeout_s}];"
        f'(way["highway"](poly:"{polygon}"););'
        "(._;>;);"
        "out body qt;"
    )


def _canonical_source_payload(payload: bytes) -> tuple[bytes, dict[str, Any]]:
    if len(payload) > MAX_RESPONSE_BYTES:
        raise OsmArchiveError(
            f"Overpass response exceeds the fixed {MAX_RESPONSE_BYTES // (1024 * 1024)} MB limit"
        )
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OsmArchiveError("Overpass response is not valid JSON") from error
    if not isinstance(document, dict) or not isinstance(document.get("elements"), list):
        raise OsmArchiveError("Overpass response must contain an elements array")
    if "remark" in document:
        raise OsmArchiveError(
            "Overpass response contains a remark and may be partial or timed out; "
            "no archive will be accepted"
        )
    osm3s = document.get("osm3s")
    source_timestamp = (
        _parse_timestamp(osm3s.get("timestamp_osm_base")) if isinstance(osm3s, dict) else None
    )
    if source_timestamp is None:
        raise OsmArchiveError(
            "Overpass response lacks a valid timezone-aware osm3s.timestamp_osm_base"
        )

    seen: set[tuple[str, int]] = set()
    for index, element in enumerate(document["elements"]):
        if not isinstance(element, dict):
            raise OsmArchiveError(f"Overpass element {index} is not an object")
        element_type = element.get("type")
        element_id = element.get("id")
        if element_type not in {"node", "way", "relation"} or not isinstance(element_id, int):
            raise OsmArchiveError(f"Overpass element {index} has an invalid type or integer ID")
        identity = (element_type, element_id)
        if identity in seen:
            raise OsmArchiveError(
                f"Overpass response contains duplicate {element_type} {element_id}"
            )
        seen.add(identity)

    document["elements"] = sorted(
        document["elements"],
        key=lambda element: ({"node": 0, "way": 1, "relation": 2}[element["type"]], element["id"]),
    )
    try:
        normalized = json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise OsmArchiveError("Overpass response contains non-finite or non-JSON values") from error
    return normalized + b"\n", document


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


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


def _default_transport(query: str, timeout_s: int) -> bytes:
    encoded = urllib.parse.urlencode({"data": query}).encode("utf-8")
    request = urllib.request.Request(
        OVERPASS_ENDPOINT,
        data=encoded,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "User-Agent": "Four-Planters-Scenario-Builder/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_s + 15) as response:
        payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise OsmArchiveError(
            f"Overpass response exceeds the fixed {MAX_RESPONSE_BYTES // (1024 * 1024)} MB limit"
        )
    return payload


class OsmOverpassAdapter:
    """Bounded OSM acquisition with explicit refresh and deterministic offline archives."""

    adapter_id = OVERPASS_ADAPTER_ID

    def __init__(
        self,
        *,
        refresh: bool = False,
        transport: FetchTransport | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.refresh = refresh
        self._transport = transport or _default_transport
        self._clock = clock or (lambda: datetime.now(UTC))
        self._archive_path: Path | None = None
        self._manifest: dict[str, Any] | None = None

    @property
    def archive_path(self) -> Path:
        if self._archive_path is None:
            raise RuntimeError("OSM source has not been acquired or loaded")
        return self._archive_path

    @property
    def archive_manifest(self) -> dict[str, Any]:
        if self._manifest is None:
            raise RuntimeError("OSM source has not been acquired or loaded")
        return dict(self._manifest)

    def assess_coverage(self, recipe: ScenarioRecipe) -> CoverageAssessment:
        canonicalize_area(recipe)
        return CoverageAssessment(
            adapter_id=self.adapter_id,
            status="unknown",
            message=(
                "The requested area is within the bounded Finland build profile; "
                "OpenStreetMap completeness is not asserted by this adapter."
            ),
            checked_at=self._clock(),
            evidence={
                "endpoint_controlled_by_adapter": True,
                "maximum_response_bytes": MAX_RESPONSE_BYTES,
            },
        )

    def archive_pointer_path(self, context: SourceAcquisitionContext) -> Path:
        """Return the expected local pointer without touching the filesystem."""

        if context.declaration.adapter_id != self.adapter_id:
            raise AdapterConfigurationError(
                f"OsmOverpassAdapter cannot preflight {context.declaration.adapter_id!r}"
            )
        if context.declaration.role != "base_network":
            raise AdapterConfigurationError("osm adapter currently supports base_network only")
        return context.workspace / f"{context.recipe.scenario_id}.osm-overpass.archive.json"

    def acquire(self, context: SourceAcquisitionContext) -> SourceSnapshotMetadata:
        if context.declaration.adapter_id != self.adapter_id:
            raise AdapterConfigurationError(
                f"OsmOverpassAdapter cannot acquire {context.declaration.adapter_id!r}"
            )
        if context.declaration.role != "base_network":
            raise AdapterConfigurationError("osm adapter currently supports base_network only")

        core_area = canonicalize_area(context.recipe)
        area = canonicalize_network_context(context.recipe, core_area)
        timeout_s = _timeout_from_context(context)
        query = derive_overpass_query(area, timeout_s)
        query_sha256 = _sha256(query.encode("utf-8"))
        source_root = context.workspace
        source_root.mkdir(parents=True, exist_ok=True)
        pointer_path = self.archive_pointer_path(context)

        if self.refresh:
            response = self._transport(query, timeout_s)
            normalized, document = _canonical_source_payload(response)
            compressed = gzip.compress(normalized, compresslevel=9, mtime=0)
            raw_sha256 = _sha256(normalized)
            archive_name = (
                f"{context.recipe.scenario_id}.osm-overpass.{raw_sha256[:16]}.json.gz"
            )
            archive_path = source_root / archive_name
            if archive_path.exists():
                if archive_path.read_bytes() != compressed:
                    raise OsmArchiveError(
                        f"content-addressed archive collision at {archive_path}"
                    )
            else:
                _atomic_write(archive_path, compressed)
            source_timestamp = _parse_timestamp(
                document.get("osm3s", {}).get("timestamp_osm_base")
                if isinstance(document.get("osm3s"), dict)
                else None
            )
            previous_manifest: Any = None
            if pointer_path.exists():
                try:
                    previous_manifest = json.loads(pointer_path.read_text(encoding="utf-8"))
                    self._validate_manifest(
                        previous_manifest,
                        context=context,
                        query=query,
                        query_sha256=query_sha256,
                    )
                except (OSError, json.JSONDecodeError, OsmArchiveError):
                    previous_manifest = None
            if (
                isinstance(previous_manifest, dict)
                and previous_manifest.get("raw_sha256") == raw_sha256
                and previous_manifest.get("archive_file") == archive_name
            ):
                # A repeated refresh of identical source content retains the first
                # observation metadata. This keeps a content-identical immutable
                # snapshot byte-identical instead of manufacturing a timestamp-only
                # variant each time the remote endpoint is contacted.
                manifest = previous_manifest
            else:
                acquired_at = self._clock()
                if acquired_at.tzinfo is None:
                    raise ValueError("OSM adapter clock must return a timezone-aware datetime")
                manifest = {
                    "schema_version": "1.0",
                    "adapter_version": OVERPASS_ADAPTER_VERSION,
                    "scenario_id": context.recipe.scenario_id,
                    "recipe_sha256": context.recipe.sha256(),
                    "endpoint": OVERPASS_ENDPOINT,
                    "query": query,
                    "query_sha256": query_sha256,
                    "archive_file": archive_name,
                    "archive_sha256": _sha256(compressed),
                    "raw_sha256": raw_sha256,
                    "byte_size": len(compressed),
                    "feature_count": len(document["elements"]),
                    "acquired_at": acquired_at.isoformat(),
                    "source_timestamp": source_timestamp.isoformat(),
                }
                _atomic_write(pointer_path, _json_bytes(manifest))
        else:
            if not pointer_path.exists():
                raise OsmArchiveError(
                    f"offline OSM archive pointer is missing at {pointer_path}; "
                    "run the same command once with --refresh"
                )
            try:
                manifest = json.loads(pointer_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise OsmArchiveError(f"cannot read OSM archive pointer {pointer_path}") from error

        self._validate_manifest(
            manifest,
            context=context,
            query=query,
            query_sha256=query_sha256,
        )
        archive_path = source_root / manifest["archive_file"]
        compressed = archive_path.read_bytes()
        try:
            normalized = gzip.decompress(compressed)
        except (OSError, EOFError) as error:
            raise OsmArchiveError(f"OSM archive is not valid gzip: {archive_path}") from error
        canonical, document = _canonical_source_payload(normalized)
        if canonical != normalized:
            raise OsmArchiveError("OSM archive payload is not in canonical JSON form")
        if _sha256(normalized) != manifest["raw_sha256"]:
            raise OsmArchiveError("OSM archive raw checksum does not match its pointer")
        if len(document["elements"]) != manifest["feature_count"]:
            raise OsmArchiveError("OSM archive feature count does not match its pointer")

        acquired_at = datetime.fromisoformat(manifest["acquired_at"])
        source_timestamp = (
            datetime.fromisoformat(manifest["source_timestamp"])
            if manifest.get("source_timestamp")
            else None
        )
        self._archive_path = archive_path
        self._manifest = manifest
        return SourceSnapshotMetadata(
            adapter_id=self.adapter_id,
            source_name="OpenStreetMap via Overpass API",
            endpoint=OVERPASS_ENDPOINT,
            acquired_at=acquired_at,
            source_timestamp=source_timestamp,
            query={
                "adapter_version": OVERPASS_ADAPTER_VERSION,
                "language": "Overpass QL",
                "query": query,
                "query_sha256": query_sha256,
                "core_area": core_area.geojson,
                "bounded_network_context": area.geojson,
                "network_context_buffer_m": context.recipe.network_context_buffer_m,
                "timeout_s": timeout_s,
                "local_clip_includes_polygon_holes": True,
                "archive_representation": (
                    "The acquired JSON object is key-sorted, its elements are sorted by type/ID, "
                    "then it is gzip-compressed with mtime zero."
                ),
                "selection_semantics": (
                    "Highway-tagged OSM ways selected by an Overpass polygon covering the "
                    "buffered network context, followed by child-node expansion and local clipping."
                ),
            },
            source_crs="EPSG:4326",
            normalized_crs=ANALYSIS_CRS,
            feature_count=len(document["elements"]),
            licence=LicenceRecord(
                name="Open Data Commons Open Database License (ODbL) 1.0",
                url="https://www.openstreetmap.org/copyright",
                attribution="© OpenStreetMap contributors",
                obligations=[
                    "Attribute OpenStreetMap and link to the copyright and licence notice.",
                    (
                        "Comply with ODbL requirements when publicly using or distributing "
                        "the database."
                    ),
                ],
            ),
            artifacts=[
                {
                    "path": "raw/osm-overpass.json.gz",
                    "sha256": _sha256(compressed),
                    "byte_size": len(compressed),
                    "media_type": "application/gzip",
                }
            ],
        )

    @staticmethod
    def _validate_manifest(
        manifest: Any,
        *,
        context: SourceAcquisitionContext,
        query: str,
        query_sha256: str,
    ) -> None:
        if not isinstance(manifest, dict):
            raise OsmArchiveError("OSM archive pointer must be a JSON object")
        expected = {
            "schema_version": "1.0",
            "adapter_version": OVERPASS_ADAPTER_VERSION,
            "scenario_id": context.recipe.scenario_id,
            "recipe_sha256": context.recipe.sha256(),
            "endpoint": OVERPASS_ENDPOINT,
            "query": query,
            "query_sha256": query_sha256,
        }
        differences = [
            key for key, expected_value in expected.items() if manifest.get(key) != expected_value
        ]
        if differences:
            raise OsmArchiveError(
                "offline OSM archive does not match the current recipe/query ("
                + ", ".join(differences)
                + "); refresh explicitly"
            )
        archive_name = manifest.get("archive_file")
        if (
            not isinstance(archive_name, str)
            or Path(archive_name).name != archive_name
            or not archive_name.endswith(".json.gz")
        ):
            raise OsmArchiveError("OSM archive pointer contains an unsafe archive filename")
        archive_path = context.workspace / archive_name
        if not archive_path.is_file():
            raise OsmArchiveError(f"OSM archive is missing at {archive_path}")
        compressed = archive_path.read_bytes()
        if not isinstance(manifest.get("archive_sha256"), str) or _sha256(
            compressed
        ) != manifest.get("archive_sha256"):
            raise OsmArchiveError("OSM archive checksum does not match its pointer")
        if len(compressed) != manifest.get("byte_size"):
            raise OsmArchiveError("OSM archive size does not match its pointer")
        if not isinstance(manifest.get("feature_count"), int) or manifest["feature_count"] < 0:
            raise OsmArchiveError("OSM archive pointer has an invalid feature count")
        try:
            acquired_at = datetime.fromisoformat(manifest["acquired_at"])
        except (KeyError, TypeError, ValueError) as error:
            raise OsmArchiveError(
                "OSM archive pointer has an invalid acquisition timestamp"
            ) from error
        if acquired_at.tzinfo is None:
            raise OsmArchiveError("OSM archive acquisition timestamp lacks a timezone")


def load_osm_archive(path: Path) -> dict[str, Any]:
    try:
        normalized = gzip.decompress(path.read_bytes())
    except (OSError, EOFError) as error:
        raise OsmArchiveError(f"cannot decompress OSM archive {path}") from error
    _, document = _canonical_source_payload(normalized)
    return document
