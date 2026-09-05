"""Deterministic acquisition of two official SYKE coastal-flood hazard layers.

The adapter deliberately has narrow semantics.  It archives bounded WFS responses
for the 1-in-100 and 1-in-1000 sea-flood hazard polygons; it does not decide whether
a road is passable, claim that an empty response is safe, or accept caller-supplied
endpoints and query expressions.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from shapely.errors import GEOSException
from shapely.geometry import box, shape
from shapely.geometry.base import BaseGeometry

from .adapters import AdapterConfigurationError, SourceAcquisitionContext
from .models import (
    ANALYSIS_CRS,
    CoverageAssessment,
    LicenceRecord,
    ScenarioRecipe,
    SourceSnapshotMetadata,
)
from .osm import canonicalize_network_context

SYKE_WFS_ENDPOINT = "https://paikkatiedot.ymparisto.fi/geoserver/inspire_nz/wfs"
SYKE_ADAPTER_ID = "syke"
SYKE_ADAPTER_VERSION = "1.0.0"
SYKE_WFS_VERSION = "2.0.0"
SYKE_OUTPUT_FORMAT = "application/json"

SEA_FLOOD_1_IN_100 = "inspire_nz:NZ.Tulvavaaravyohykkeet_Meritulva_1_100a"
SEA_FLOOD_1_IN_1000 = "inspire_nz:NZ.Tulvavaaravyohykkeet_Meritulva_1_1000a"
SYKE_SEA_FLOOD_LAYERS = (SEA_FLOOD_1_IN_100, SEA_FLOOD_1_IN_1000)

_RETURN_PERIOD_BY_LAYER = {
    SEA_FLOOD_1_IN_100: 100,
    SEA_FLOOD_1_IN_1000: 1_000,
}
_ARTIFACT_STEM_BY_LAYER = {
    SEA_FLOOD_1_IN_100: "sea-flood-1-in-100",
    SEA_FLOOD_1_IN_1000: "sea-flood-1-in-1000",
}

DEFAULT_TIMEOUT_S = 60
MIN_TIMEOUT_S = 10
MAX_TIMEOUT_S = 120
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_FEATURES_PER_LAYER = 10_000
MAX_COORDINATES_PER_LAYER = 2_000_000
MAX_QUERY_EXTENT_M = 15_000.0
BBOX_DECIMALS = 3

FetchTransport = Callable[[str, int], bytes]
Clock = Callable[[], datetime]


class SykeArchiveError(ValueError):
    """Raised when a SYKE response or frozen archive cannot be verified."""


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


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SykeArchiveError("SYKE response contains non-finite or non-JSON values") from error
    return encoded + b"\n"


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


def _aware_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _valid_source_edition(value: Any) -> bool:
    """Accept an aware timestamp or an ISO date without inventing date precision."""

    if _aware_timestamp(value) is not None:
        return True
    if not isinstance(value, str):
        return False
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    return parsed.isoformat() == value


def _checked_clock(clock: Clock) -> datetime:
    moment = clock()
    if moment.tzinfo is None:
        raise ValueError("SYKE adapter clock must return a timezone-aware datetime")
    return moment


def _query_bbox(recipe: ScenarioRecipe) -> tuple[float, float, float, float]:
    context = canonicalize_network_context(recipe)
    minimum_x, minimum_y, maximum_x, maximum_y = context.analysis.bounds
    scale = 10**BBOX_DECIMALS
    bounded = (
        math.floor(minimum_x * scale) / scale,
        math.floor(minimum_y * scale) / scale,
        math.ceil(maximum_x * scale) / scale,
        math.ceil(maximum_y * scale) / scale,
    )
    width = bounded[2] - bounded[0]
    height = bounded[3] - bounded[1]
    if width <= 0 or height <= 0:
        raise ValueError("SYKE query context has an empty metric bounding box")
    if width > MAX_QUERY_EXTENT_M or height > MAX_QUERY_EXTENT_M:
        raise ValueError(
            "SYKE query context exceeds the fixed 15 km width/height acquisition limit"
        )
    return bounded


def _format_bbox(bbox: tuple[float, float, float, float]) -> str:
    coordinates = ",".join(f"{value:.{BBOX_DECIMALS}f}" for value in bbox)
    return f"{coordinates},{ANALYSIS_CRS}"


def derive_wfs_url(layer: str, bbox: tuple[float, float, float, float]) -> str:
    """Build one fixed-shape WFS query for an allowlisted coastal layer."""

    if layer not in _RETURN_PERIOD_BY_LAYER:
        raise AdapterConfigurationError(
            f"unsupported SYKE layer {layer!r}; only the two audited coastal layers are allowed"
        )
    parameters = (
        ("service", "WFS"),
        ("version", SYKE_WFS_VERSION),
        ("request", "GetFeature"),
        ("typeNames", layer),
        ("outputFormat", SYKE_OUTPUT_FORMAT),
        ("srsName", ANALYSIS_CRS),
        ("bbox", _format_bbox(bbox)),
        ("count", str(MAX_FEATURES_PER_LAYER)),
    )
    return f"{SYKE_WFS_ENDPOINT}?{urllib.parse.urlencode(parameters)}"


def _settings(
    context: SourceAcquisitionContext,
) -> tuple[tuple[str, ...], int]:
    parameters = context.declaration.parameters
    unknown = sorted(set(parameters) - {"layers", "wfs_timeout_s"})
    if unknown:
        raise AdapterConfigurationError(
            "unsupported syke source parameter(s): "
            + ", ".join(unknown)
            + "; endpoint, WFS request shape, CRS, and output format are fixed"
        )

    requested = parameters.get("layers", list(SYKE_SEA_FLOOD_LAYERS))
    if not isinstance(requested, list) or not requested:
        raise AdapterConfigurationError("syke layers must be a non-empty JSON array")
    if any(not isinstance(layer, str) for layer in requested):
        raise AdapterConfigurationError("every syke layer must be an exact string identifier")
    duplicates = sorted(layer for layer in set(requested) if requested.count(layer) > 1)
    if duplicates:
        raise AdapterConfigurationError(
            "syke layers contain duplicate identifier(s): " + ", ".join(duplicates)
        )
    invalid = sorted(set(requested) - set(SYKE_SEA_FLOOD_LAYERS))
    if invalid:
        raise AdapterConfigurationError(
            "unsupported SYKE layer(s): "
            + ", ".join(invalid)
            + "; only the audited 1-in-100 and 1-in-1000 sea-flood layers are allowed"
        )
    layers = tuple(layer for layer in SYKE_SEA_FLOOD_LAYERS if layer in requested)

    timeout_s = parameters.get("wfs_timeout_s", DEFAULT_TIMEOUT_S)
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, int):
        raise AdapterConfigurationError("syke wfs_timeout_s must be an integer")
    if not MIN_TIMEOUT_S <= timeout_s <= MAX_TIMEOUT_S:
        raise AdapterConfigurationError(
            f"syke wfs_timeout_s must be {MIN_TIMEOUT_S}--{MAX_TIMEOUT_S} seconds"
        )
    return layers, timeout_s


def _default_transport(url: str, timeout_s: int) -> bytes:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/geo+json, application/json",
            "User-Agent": "Geospatial-Constraint-Lab-Scenario-Builder/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise SykeArchiveError(
            f"SYKE response exceeds the fixed {MAX_RESPONSE_BYTES // (1024 * 1024)} MB limit"
        )
    return payload


def _coordinate_count(value: Any) -> int:
    """Validate finite numeric GeoJSON positions and return their count."""

    if not isinstance(value, list) or not value:
        raise SykeArchiveError("SYKE geometry coordinates must be non-empty arrays")
    if all(
        isinstance(component, (int, float)) and not isinstance(component, bool)
        for component in value
    ):
        if len(value) < 2 or not all(math.isfinite(component) for component in value):
            raise SykeArchiveError("SYKE geometry contains an invalid or non-finite position")
        if abs(float(value[0])) > 10_000_000 or abs(float(value[1])) > 10_000_000:
            raise SykeArchiveError("SYKE geometry position is outside a plausible metric range")
        return 1
    if any(isinstance(component, (int, float, str, dict)) for component in value):
        raise SykeArchiveError("SYKE geometry has an inconsistent coordinate nesting shape")
    return sum(_coordinate_count(component) for component in value)


def _feature_edition(feature: dict[str, Any]) -> str | None:
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        return None
    value = properties.get("muutospvm")
    return value if _valid_source_edition(value) else None


def _validate_feature(
    feature: Any,
    *,
    index: int,
    layer: str,
    query_geometry: BaseGeometry,
) -> tuple[str, int]:
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise SykeArchiveError(f"SYKE layer {layer} feature {index} is not a GeoJSON Feature")
    feature_id = feature.get("id")
    if not isinstance(feature_id, str) or not feature_id or len(feature_id) > 500:
        raise SykeArchiveError(f"SYKE layer {layer} feature {index} lacks a stable string ID")
    local_layer = layer.split(":", maxsplit=1)[1]
    if not feature_id.startswith(f"{local_layer}."):
        raise SykeArchiveError(
            f"SYKE feature ID {feature_id!r} does not advertise the requested layer {layer!r}"
        )
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        raise SykeArchiveError(f"SYKE feature {feature_id!r} properties must be an object")
    recurrence = properties.get("toistuvuus")
    # The live service currently includes one source-boundary feature per layer
    # whose thematic attributes are all null. Its type-qualified stable ID still
    # advertises the requested layer. Reject contradictory recurrence values, but
    # preserve that source feature rather than silently deleting it from the raw
    # archive.
    if recurrence not in {None, _RETURN_PERIOD_BY_LAYER[layer]}:
        raise SykeArchiveError(
            f"SYKE feature {feature_id!r} has recurrence {recurrence!r}, expected "
            f"{_RETURN_PERIOD_BY_LAYER[layer]}"
        )

    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise SykeArchiveError(
            f"SYKE feature {feature_id!r} must have Polygon or MultiPolygon geometry"
        )
    coordinate_count = _coordinate_count(geometry.get("coordinates"))
    try:
        parsed_geometry = shape(geometry)
    except (TypeError, ValueError, GEOSException) as error:
        raise SykeArchiveError(f"SYKE feature {feature_id!r} geometry cannot be decoded") from error
    if parsed_geometry.is_empty or not all(
        math.isfinite(value) for value in parsed_geometry.bounds
    ):
        raise SykeArchiveError(f"SYKE feature {feature_id!r} geometry is empty or non-finite")
    # WFS BBOX is an envelope predicate. Some official source-boundary
    # MultiPolygons have envelopes that meet the query even when their individual
    # parts do not. Preserve raw topology for a later, lineage-recorded repair
    # stage; this adapter promises finite decodable source geometry, not validity.
    if not box(*parsed_geometry.bounds).intersects(query_geometry):
        raise SykeArchiveError(
            f"SYKE feature {feature_id!r} envelope does not intersect the bounded WFS query"
        )
    return feature_id, coordinate_count


def _canonical_source_payload(
    payload: bytes,
    *,
    layer: str,
    bbox: tuple[float, float, float, float],
) -> tuple[bytes, dict[str, Any], list[str]]:
    if len(payload) > MAX_RESPONSE_BYTES:
        raise SykeArchiveError(
            f"SYKE response exceeds the fixed {MAX_RESPONSE_BYTES // (1024 * 1024)} MB limit"
        )
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SykeArchiveError("SYKE response is not valid JSON") from error
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        raise SykeArchiveError("SYKE response must be a GeoJSON FeatureCollection")
    features = document.get("features")
    if not isinstance(features, list):
        raise SykeArchiveError("SYKE FeatureCollection must contain a features array")
    if len(features) > MAX_FEATURES_PER_LAYER:
        raise SykeArchiveError(
            f"SYKE response exceeds the fixed {MAX_FEATURES_PER_LAYER}-feature layer limit"
        )

    crs = document.get("crs")
    crs_name = crs.get("properties", {}).get("name") if isinstance(crs, dict) else None
    accepted_crs_names = {
        "EPSG:3067",
        "urn:ogc:def:crs:EPSG::3067",
        "http://www.opengis.net/def/crs/EPSG/0/3067",
    }
    if crs_name not in accepted_crs_names:
        raise SykeArchiveError(
            f"SYKE response CRS is {crs_name!r}; expected an advertised EPSG:3067 CRS"
        )

    for count_field in ("numberMatched", "numberReturned"):
        count = document.get(count_field)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise SykeArchiveError(f"SYKE response has an invalid {count_field}")
    if document["numberReturned"] != len(features):
        raise SykeArchiveError("SYKE numberReturned does not equal the features array length")
    if document["numberMatched"] != len(features):
        raise SykeArchiveError(
            "SYKE bounded response was truncated; paging is intentionally unsupported in v1"
        )

    query_geometry = box(*bbox)
    identities: set[str] = set()
    coordinate_count = 0
    for index, feature in enumerate(features):
        identity, feature_coordinates = _validate_feature(
            feature,
            index=index,
            layer=layer,
            query_geometry=query_geometry,
        )
        if identity in identities:
            raise SykeArchiveError(f"SYKE response contains duplicate feature ID {identity!r}")
        identities.add(identity)
        coordinate_count += feature_coordinates
        if coordinate_count > MAX_COORDINATES_PER_LAYER:
            raise SykeArchiveError(
                "SYKE response exceeds the fixed coordinate-count limit for one layer"
            )

    document["features"] = sorted(features, key=lambda feature: feature["id"])
    edition_values = sorted(
        edition
        for edition in {_feature_edition(feature) for feature in features}
        if edition is not None
    )
    canonical = _canonical_json_bytes(document)
    return canonical, document, edition_values


def _archive_path_is_safe(workspace: Path, archive_name: Any) -> Path:
    if (
        not isinstance(archive_name, str)
        or Path(archive_name).name != archive_name
        or not archive_name.endswith(".geojson.gz")
    ):
        raise SykeArchiveError("SYKE pointer contains an unsafe archive filename")
    archive_path = workspace / archive_name
    if not archive_path.is_file():
        raise SykeArchiveError(f"SYKE archive is missing at {archive_path}")
    return archive_path


class SykeCoastalFloodAdapter:
    """Acquire and replay bounded official coastal-flood polygons."""

    adapter_id = SYKE_ADAPTER_ID

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
        self._manifest: dict[str, Any] | None = None
        self._archive_paths: dict[str, Path] = {}

    @property
    def archive_manifest(self) -> dict[str, Any]:
        if self._manifest is None:
            raise RuntimeError("SYKE source has not been acquired or loaded")
        return json.loads(json.dumps(self._manifest))

    @property
    def archive_paths(self) -> dict[str, Path]:
        if not self._archive_paths:
            raise RuntimeError("SYKE source has not been acquired or loaded")
        return dict(self._archive_paths)

    def assess_coverage(self, recipe: ScenarioRecipe) -> CoverageAssessment:
        bbox = _query_bbox(recipe)
        evidence: dict[str, Any] = {
            "endpoint_controlled_by_adapter": True,
            "allowlisted_layers": list(SYKE_SEA_FLOOD_LAYERS),
            "bounded_context_bbox_epsg3067": list(bbox),
            "maximum_features_per_layer": MAX_FEATURES_PER_LAYER,
        }
        if self._manifest is not None:
            evidence["validated_responses"] = [
                {
                    "layer": item["layer"],
                    "feature_count": item["feature_count"],
                }
                for item in self._manifest["layers"]
            ]
        return CoverageAssessment(
            adapter_id=self.adapter_id,
            status="unknown",
            message=(
                "SYKE coastal-hazard coverage is not inferred from a Finland envelope or from "
                "the absence of polygons. A validated response archives hazard evidence only; "
                "it does not establish road passability or flood safety."
            ),
            checked_at=_checked_clock(self._clock),
            evidence=evidence,
        )

    def archive_pointer_path(self, context: SourceAcquisitionContext) -> Path:
        """Return the expected local pointer without touching the filesystem."""

        if context.declaration.adapter_id != self.adapter_id:
            raise AdapterConfigurationError(
                f"SykeCoastalFloodAdapter cannot preflight "
                f"{context.declaration.adapter_id!r}"
            )
        if context.declaration.role != "flood_hazard":
            raise AdapterConfigurationError("syke adapter currently supports flood_hazard only")
        return context.workspace / f"{context.recipe.scenario_id}.syke-coastal-flood.archive.json"

    def acquire(self, context: SourceAcquisitionContext) -> SourceSnapshotMetadata:
        if context.declaration.adapter_id != self.adapter_id:
            raise AdapterConfigurationError(
                f"SykeCoastalFloodAdapter cannot acquire {context.declaration.adapter_id!r}"
            )
        if context.declaration.role != "flood_hazard":
            raise AdapterConfigurationError("syke adapter currently supports flood_hazard only")

        layers, timeout_s = _settings(context)
        bbox = _query_bbox(context.recipe)
        queries = {layer: derive_wfs_url(layer, bbox) for layer in layers}
        workspace = context.workspace
        workspace.mkdir(parents=True, exist_ok=True)
        pointer_path = self.archive_pointer_path(context)

        if self.refresh:
            layer_manifests: list[dict[str, Any]] = []
            for layer in layers:
                response = self._transport(queries[layer], timeout_s)
                canonical, document, edition_values = _canonical_source_payload(
                    response,
                    layer=layer,
                    bbox=bbox,
                )
                compressed = gzip.compress(canonical, compresslevel=9, mtime=0)
                raw_sha256 = _sha256(canonical)
                archive_name = (
                    f"{context.recipe.scenario_id}.{_ARTIFACT_STEM_BY_LAYER[layer]}."
                    f"{raw_sha256[:16]}.geojson.gz"
                )
                archive_path = workspace / archive_name
                if archive_path.exists():
                    if archive_path.read_bytes() != compressed:
                        raise SykeArchiveError(
                            f"content-addressed SYKE archive collision at {archive_path}"
                        )
                else:
                    _atomic_write(archive_path, compressed)
                layer_manifests.append(
                    {
                        "layer": layer,
                        "return_period_years": _RETURN_PERIOD_BY_LAYER[layer],
                        "query_url": queries[layer],
                        "query_sha256": _sha256(queries[layer].encode("utf-8")),
                        "archive_file": archive_name,
                        "archive_sha256": _sha256(compressed),
                        "raw_sha256": raw_sha256,
                        "byte_size": len(compressed),
                        "feature_count": len(document["features"]),
                        "response_timestamp": document.get("timeStamp"),
                        "edition_field": "muutospvm",
                        "edition_values": edition_values,
                    }
                )
            acquired_at = _checked_clock(self._clock)
            candidate_manifest: dict[str, Any] = {
                "schema_version": "1.0",
                "adapter_version": SYKE_ADAPTER_VERSION,
                "scenario_id": context.recipe.scenario_id,
                "recipe_sha256": context.recipe.sha256(),
                "endpoint": SYKE_WFS_ENDPOINT,
                "wfs_version": SYKE_WFS_VERSION,
                "output_format": SYKE_OUTPUT_FORMAT,
                "source_crs": ANALYSIS_CRS,
                "network_context_buffer_m": context.recipe.network_context_buffer_m,
                "bbox": list(bbox),
                "timeout_s": timeout_s,
                "acquired_at": acquired_at.isoformat(),
                "layers": layer_manifests,
            }
            # The archives are content addressed. If an explicit refresh returns
            # precisely the same canonical response/query identity, preserve the
            # first acquisition time and pointer bytes as immutable provenance.
            existing_manifest: Any = None
            if pointer_path.is_file():
                try:
                    existing_manifest = json.loads(pointer_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    existing_manifest = None
            existing_identity = (
                {key: value for key, value in existing_manifest.items() if key != "acquired_at"}
                if isinstance(existing_manifest, dict)
                else None
            )
            candidate_identity = {
                key: value for key, value in candidate_manifest.items() if key != "acquired_at"
            }
            if existing_identity == candidate_identity:
                manifest = existing_manifest
            else:
                manifest = candidate_manifest
                _atomic_write(pointer_path, _json_bytes(manifest))
        else:
            if not pointer_path.is_file():
                raise SykeArchiveError(
                    f"offline SYKE archive pointer is missing at {pointer_path}; "
                    "run acquisition once with refresh=True"
                )
            try:
                manifest = json.loads(pointer_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise SykeArchiveError(
                    f"cannot read SYKE archive pointer {pointer_path}"
                ) from error

        self._validate_manifest(
            manifest,
            context=context,
            layers=layers,
            bbox=bbox,
            timeout_s=timeout_s,
            queries=queries,
        )
        archive_paths: dict[str, Path] = {}
        feature_count = 0
        artifacts: list[dict[str, Any]] = []
        edition_timestamps: list[datetime] = []
        query_layers: list[dict[str, Any]] = []
        for item in manifest["layers"]:
            layer = item["layer"]
            archive_path = _archive_path_is_safe(workspace, item["archive_file"])
            compressed = archive_path.read_bytes()
            try:
                canonical = gzip.decompress(compressed)
            except (OSError, EOFError) as error:
                raise SykeArchiveError(f"SYKE archive is not valid gzip: {archive_path}") from error
            normalized, document, edition_values = _canonical_source_payload(
                canonical,
                layer=layer,
                bbox=bbox,
            )
            if normalized != canonical:
                raise SykeArchiveError("SYKE archive payload is not canonical GeoJSON")
            if _sha256(canonical) != item["raw_sha256"]:
                raise SykeArchiveError("SYKE archive raw checksum does not match its pointer")
            if len(document["features"]) != item["feature_count"]:
                raise SykeArchiveError("SYKE archive feature count does not match its pointer")
            if edition_values != item["edition_values"]:
                raise SykeArchiveError("SYKE archive edition values do not match its pointer")

            archive_paths[layer] = archive_path
            feature_count += item["feature_count"]
            artifacts.append(
                {
                    "path": f"raw/syke/{_ARTIFACT_STEM_BY_LAYER[layer]}.geojson.gz",
                    "sha256": _sha256(compressed),
                    "byte_size": len(compressed),
                    "media_type": "application/gzip",
                }
            )
            for edition in edition_values:
                parsed = _aware_timestamp(edition)
                if parsed is not None:
                    edition_timestamps.append(parsed)
            query_layers.append(
                {
                    "type_name": layer,
                    "return_period_years": item["return_period_years"],
                    "query_url": item["query_url"],
                    "query_sha256": item["query_sha256"],
                    "feature_count": item["feature_count"],
                    "response_timestamp": item["response_timestamp"],
                    "edition_field": item["edition_field"],
                    "edition_values": edition_values,
                }
            )

        acquired_at = datetime.fromisoformat(manifest["acquired_at"])
        source_timestamp = max(edition_timestamps) if edition_timestamps else None
        self._manifest = manifest
        self._archive_paths = archive_paths
        return SourceSnapshotMetadata(
            adapter_id=self.adapter_id,
            source_name="SYKE coastal flood hazard zones — basic sea-flood scenarios",
            endpoint=SYKE_WFS_ENDPOINT,
            acquired_at=acquired_at,
            source_timestamp=source_timestamp,
            query={
                "adapter_version": SYKE_ADAPTER_VERSION,
                "service": "WFS",
                "version": SYKE_WFS_VERSION,
                "request": "GetFeature",
                "output_format": SYKE_OUTPUT_FORMAT,
                "source_crs": ANALYSIS_CRS,
                "bounded_network_context_bbox": list(bbox),
                "network_context_buffer_m": context.recipe.network_context_buffer_m,
                "count_limit_per_layer": MAX_FEATURES_PER_LAYER,
                "timeout_s": timeout_s,
                "layers": query_layers,
                "hazard_semantics_only": True,
                "passability_not_inferred": True,
            },
            source_crs=ANALYSIS_CRS,
            normalized_crs=ANALYSIS_CRS,
            feature_count=feature_count,
            licence=LicenceRecord(
                name="Creative Commons Attribution 4.0 International (CC BY 4.0)",
                url="https://www.syke.fi/en/environmental-data/use-license-and-responsibilities",
                attribution="Source: Finnish Environment Institute (SYKE)",
                obligations=[
                    "Attribute the Finnish Environment Institute as the source.",
                    "State the licence and indicate modifications when distributing adapted data.",
                    "Use a SYKE application identifier for long-term or intensive WFS use.",
                ],
            ),
            artifacts=artifacts,
        )

    @staticmethod
    def _validate_manifest(
        manifest: Any,
        *,
        context: SourceAcquisitionContext,
        layers: tuple[str, ...],
        bbox: tuple[float, float, float, float],
        timeout_s: int,
        queries: dict[str, str],
    ) -> None:
        if not isinstance(manifest, dict):
            raise SykeArchiveError("SYKE archive pointer must be a JSON object")
        expected = {
            "schema_version": "1.0",
            "adapter_version": SYKE_ADAPTER_VERSION,
            "scenario_id": context.recipe.scenario_id,
            "recipe_sha256": context.recipe.sha256(),
            "endpoint": SYKE_WFS_ENDPOINT,
            "wfs_version": SYKE_WFS_VERSION,
            "output_format": SYKE_OUTPUT_FORMAT,
            "source_crs": ANALYSIS_CRS,
            "network_context_buffer_m": context.recipe.network_context_buffer_m,
            "bbox": list(bbox),
            "timeout_s": timeout_s,
        }
        differences = [
            key for key, expected_value in expected.items() if manifest.get(key) != expected_value
        ]
        if differences:
            raise SykeArchiveError(
                "offline SYKE archives do not match the current recipe/query ("
                + ", ".join(differences)
                + "); refresh explicitly"
            )
        manifest_layers = manifest.get("layers")
        if not isinstance(manifest_layers, list) or [
            item.get("layer") if isinstance(item, dict) else None for item in manifest_layers
        ] != list(layers):
            raise SykeArchiveError("SYKE pointer layer list does not match the recipe")
        try:
            acquired_at = datetime.fromisoformat(manifest["acquired_at"])
        except (KeyError, TypeError, ValueError) as error:
            raise SykeArchiveError("SYKE pointer has an invalid acquisition timestamp") from error
        if acquired_at.tzinfo is None:
            raise SykeArchiveError("SYKE pointer acquisition timestamp lacks a timezone")

        for item in manifest_layers:
            layer = item["layer"]
            item_expected = {
                "return_period_years": _RETURN_PERIOD_BY_LAYER[layer],
                "query_url": queries[layer],
                "query_sha256": _sha256(queries[layer].encode("utf-8")),
                "edition_field": "muutospvm",
            }
            differences = [
                key
                for key, expected_value in item_expected.items()
                if item.get(key) != expected_value
            ]
            if differences:
                raise SykeArchiveError(
                    f"SYKE pointer entry for {layer} has mismatched " + ", ".join(differences)
                )
            archive_path = _archive_path_is_safe(context.workspace, item.get("archive_file"))
            compressed = archive_path.read_bytes()
            if _sha256(compressed) != item.get("archive_sha256"):
                raise SykeArchiveError("SYKE archive checksum does not match its pointer")
            if len(compressed) != item.get("byte_size"):
                raise SykeArchiveError("SYKE archive size does not match its pointer")
            feature_count = item.get("feature_count")
            if (
                not isinstance(feature_count, int)
                or isinstance(feature_count, bool)
                or not 0 <= feature_count <= MAX_FEATURES_PER_LAYER
            ):
                raise SykeArchiveError("SYKE pointer has an invalid feature count")
            editions = item.get("edition_values")
            if not isinstance(editions, list) or any(
                not isinstance(value, str) or not _valid_source_edition(value)
                for value in editions
            ):
                raise SykeArchiveError("SYKE pointer has invalid source edition values")
            response_timestamp = item.get("response_timestamp")
            if response_timestamp is not None and _aware_timestamp(response_timestamp) is None:
                raise SykeArchiveError("SYKE pointer has an invalid response timestamp")


def load_syke_archive(path: Path, *, layer: str, bbox: Iterable[float]) -> dict[str, Any]:
    """Load and revalidate one canonical frozen SYKE GeoJSON archive."""

    if layer not in _RETURN_PERIOD_BY_LAYER:
        raise AdapterConfigurationError(f"unsupported SYKE layer {layer!r}")
    values = tuple(float(value) for value in bbox)
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        raise ValueError("SYKE archive bbox must contain four finite metric values")
    try:
        canonical = gzip.decompress(path.read_bytes())
    except (OSError, EOFError) as error:
        raise SykeArchiveError(f"cannot decompress SYKE archive {path}") from error
    normalized, document, _ = _canonical_source_payload(
        canonical,
        layer=layer,
        bbox=values,
    )
    if normalized != canonical:
        raise SykeArchiveError("SYKE archive payload is not canonical GeoJSON")
    return document
