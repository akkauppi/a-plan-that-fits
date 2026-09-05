"""Bounded, reproducible acquisition of audited City of Espoo WFS layers.

The adapter intentionally archives the exact GML response bytes.  XML attribute
order and whitespace are not safely canonicalized here, so snapshot identity is
the digest of those exact bytes, deterministically gzip-compressed with an mtime
of zero.  Replaying a frozen source never contacts the service.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.ops import transform

from .adapters import AdapterConfigurationError, SourceAcquisitionContext
from .models import (
    ANALYSIS_CRS,
    CoverageAssessment,
    LicenceRecord,
    ScenarioRecipe,
    SourceSnapshotMetadata,
)
from .osm import canonicalize_network_context

ESPOO_WFS_ENDPOINT = "https://kartat.espoo.fi/teklaogcweb/wfs.ashx"
ESPOO_ADAPTER_ID = "espoo_wfs"
ESPOO_ADAPTER_VERSION = "1.0.0"
ESPOO_WFS_VERSION = "1.1.0"
ESPOO_OUTPUT_FORMAT = "GML2"
ESPOO_SOURCE_CRS = "EPSG:3879"

ESPOO_LAYERS = (
    "GIS:Keskilinjat",
    "GIS:Pyorailykartta",
    "GIS:Rakennukset",
    "GIS:Osoitteet",
    "GIS:Vesialueet",
    "GIS:InfStreet",
)

_LAYER_STEMS = {
    "GIS:Keskilinjat": "street-centrelines",
    "GIS:Pyorailykartta": "cycling-map",
    "GIS:Rakennukset": "buildings",
    "GIS:Osoitteet": "addresses",
    "GIS:Vesialueet": "water-areas",
    "GIS:InfStreet": "public-street-areas",
}

WFS_NAMESPACE = "http://www.opengis.net/wfs"
GML_NAMESPACE = "http://www.opengis.net/gml"
ESPOO_GIS_NAMESPACE = "http://www.tekla.com/schemas/GIS"

DEFAULT_TIMEOUT_S = 60
MIN_TIMEOUT_S = 10
MAX_TIMEOUT_S = 120
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_FEATURES_PER_LAYER = 50_000
MAX_XML_ELEMENTS_PER_LAYER = 2_000_000
MAX_QUERY_EXTENT_M = 15_000.0
BBOX_DECIMALS = 3

FetchTransport = Callable[[str, int], bytes]
Clock = Callable[[], datetime]


class EspooArchiveError(ValueError):
    """Raised when an Espoo response or frozen archive cannot be verified."""


@dataclass(frozen=True)
class _GmlReport:
    feature_count: int
    declared_feature_count: int | None
    response_timestamp: str | None
    collection_bbox: tuple[float, float, float, float] | None
    feature_namespace: str | None
    stable_id_count: int
    stable_ids_sha256: str | None


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


def _checked_clock(clock: Clock) -> datetime:
    moment = clock()
    if moment.tzinfo is None:
        raise ValueError("Espoo adapter clock must return a timezone-aware datetime")
    return moment


def _settings(context: SourceAcquisitionContext) -> tuple[tuple[str, ...], int]:
    parameters = context.declaration.parameters
    unknown = sorted(set(parameters) - {"layers", "wfs_timeout_s"})
    if unknown:
        raise AdapterConfigurationError(
            "unsupported espoo_wfs source parameter(s): "
            + ", ".join(unknown)
            + "; endpoint, WFS query shape, BBOX, CRS, and output format are fixed"
        )

    requested = parameters.get("layers", list(ESPOO_LAYERS))
    if not isinstance(requested, list) or not requested:
        raise AdapterConfigurationError("espoo_wfs layers must be a non-empty JSON array")
    if any(not isinstance(layer, str) for layer in requested):
        raise AdapterConfigurationError("every espoo_wfs layer must be an exact string identifier")
    duplicates = sorted(layer for layer in set(requested) if requested.count(layer) > 1)
    if duplicates:
        raise AdapterConfigurationError(
            "espoo_wfs layers contain duplicate identifier(s): " + ", ".join(duplicates)
        )
    unsupported = sorted(set(requested) - set(ESPOO_LAYERS))
    if unsupported:
        raise AdapterConfigurationError(
            "unsupported Espoo WFS layer(s): "
            + ", ".join(unsupported)
            + "; only the six audited open layers are allowed"
        )
    layers = tuple(layer for layer in ESPOO_LAYERS if layer in requested)

    timeout_s = parameters.get("wfs_timeout_s", DEFAULT_TIMEOUT_S)
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, int):
        raise AdapterConfigurationError("espoo_wfs wfs_timeout_s must be an integer")
    if not MIN_TIMEOUT_S <= timeout_s <= MAX_TIMEOUT_S:
        raise AdapterConfigurationError(
            f"espoo_wfs wfs_timeout_s must be {MIN_TIMEOUT_S}--{MAX_TIMEOUT_S} seconds"
        )
    return layers, timeout_s


def _query_bbox(recipe: ScenarioRecipe) -> tuple[float, float, float, float]:
    context = canonicalize_network_context(recipe)
    transformer = Transformer.from_crs(ANALYSIS_CRS, ESPOO_SOURCE_CRS, always_xy=True)
    source_geometry = transform(transformer.transform, context.analysis)
    scale = 10**BBOX_DECIMALS
    minimum_x, minimum_y, maximum_x, maximum_y = source_geometry.bounds
    bounded = (
        math.floor(minimum_x * scale) / scale,
        math.floor(minimum_y * scale) / scale,
        math.ceil(maximum_x * scale) / scale,
        math.ceil(maximum_y * scale) / scale,
    )
    width = bounded[2] - bounded[0]
    height = bounded[3] - bounded[1]
    if width <= 0 or height <= 0:
        raise ValueError("Espoo WFS query context has an empty metric bounding box")
    if width > MAX_QUERY_EXTENT_M or height > MAX_QUERY_EXTENT_M:
        raise ValueError(
            "Espoo WFS query context exceeds the fixed 15 km width/height acquisition limit"
        )
    return bounded


def _format_bbox(bbox: tuple[float, float, float, float]) -> str:
    # Deliberately no `,EPSG:3879` suffix.  The audited service returned empty
    # collections when that otherwise valid WFS BBOX form was used.
    return ",".join(f"{value:.{BBOX_DECIMALS}f}" for value in bbox)


def _validate_query_bbox(bbox: tuple[float, float, float, float]) -> None:
    if len(bbox) != 4 or any(
        isinstance(value, bool) or not isinstance(value, (int, float)) for value in bbox
    ):
        raise ValueError("Espoo WFS bbox must contain four finite numeric values")
    if not all(math.isfinite(float(value)) for value in bbox):
        raise ValueError("Espoo WFS bbox must contain four finite numeric values")
    minimum_x, minimum_y, maximum_x, maximum_y = bbox
    if minimum_x >= maximum_x or minimum_y >= maximum_y:
        raise ValueError("Espoo WFS bbox minimum must be below its maximum")
    if maximum_x - minimum_x > MAX_QUERY_EXTENT_M or maximum_y - minimum_y > MAX_QUERY_EXTENT_M:
        raise ValueError("Espoo WFS bbox exceeds the fixed 15 km acquisition limit")


def derive_wfs_url(layer: str, bbox: tuple[float, float, float, float]) -> str:
    """Build the fixed-shape, native-CRS query for one allowlisted Espoo layer."""

    if layer not in ESPOO_LAYERS:
        raise AdapterConfigurationError(
            f"unsupported Espoo WFS layer {layer!r}; only the six audited layers are allowed"
        )
    _validate_query_bbox(bbox)
    parameters = (
        ("OUTPUTFORMAT", ESPOO_OUTPUT_FORMAT),
        ("SERVICE", "WFS"),
        ("VERSION", ESPOO_WFS_VERSION),
        ("REQUEST", "GetFeature"),
        ("TYPENAME", layer),
        ("BBOX", _format_bbox(bbox)),
    )
    return f"{ESPOO_WFS_ENDPOINT}?{urllib.parse.urlencode(parameters)}"


def _default_transport(url: str, timeout_s: int) -> bytes:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/gml+xml, application/xml, text/xml",
            "User-Agent": "Geospatial-Constraint-Lab-Scenario-Builder/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise EspooArchiveError(
            f"Espoo WFS response exceeds the fixed {MAX_RESPONSE_BYTES // (1024 * 1024)} MB limit"
        )
    return payload


def _split_qname(tag: str) -> tuple[str | None, str]:
    if tag.startswith("{") and "}" in tag:
        namespace, local_name = tag[1:].split("}", maxsplit=1)
        return namespace, local_name
    return None, tag


def _parse_aware_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise EspooArchiveError("Espoo FeatureCollection has a non-string timeStamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EspooArchiveError("Espoo FeatureCollection has an invalid timeStamp") from error
    if parsed.tzinfo is None:
        raise EspooArchiveError("Espoo FeatureCollection timeStamp lacks a timezone")
    return value


def _coordinate_pair(text: str, *, label: str) -> tuple[float, float]:
    values = text.replace(",", " ").split()
    if len(values) < 2:
        raise EspooArchiveError(f"Espoo boundedBy {label} must contain two coordinates")
    try:
        point = (float(values[0]), float(values[1]))
    except ValueError as error:
        raise EspooArchiveError(
            f"Espoo boundedBy {label} contains a non-numeric coordinate"
        ) from error
    if not all(math.isfinite(value) for value in point):
        raise EspooArchiveError(f"Espoo boundedBy {label} contains a non-finite coordinate")
    return point


def _is_epsg_3879(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip().lower()
    return bool(
        re.search(r"(?:epsg(?:\.xml)?[#:/]+|/epsg/(?:0/)?|::)3879$", normalized)
        or normalized == "epsg:3879"
    )


def _collection_bbox(
    root: ET.Element,
    *,
    feature_count: int,
    query_bbox: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    bounded_by = root.find(f"{{{GML_NAMESPACE}}}boundedBy")
    if bounded_by is None or len(bounded_by) != 1:
        raise EspooArchiveError("Espoo FeatureCollection must contain one gml:boundedBy")
    bounds = bounded_by[0]
    _, bounds_name = _split_qname(bounds.tag)
    if bounds_name == "null":
        if feature_count != 0:
            raise EspooArchiveError("non-empty Espoo response has a null boundedBy")
        return None

    if bounds_name == "Envelope":
        if not _is_epsg_3879(bounds.get("srsName")):
            raise EspooArchiveError(
                "Espoo boundedBy Envelope does not advertise the native EPSG:3879 CRS"
            )
        lower = bounds.find(f"{{{GML_NAMESPACE}}}lowerCorner")
        upper = bounds.find(f"{{{GML_NAMESPACE}}}upperCorner")
        if lower is None or upper is None:
            raise EspooArchiveError("Espoo boundedBy Envelope lacks lower/upper corners")
        minimum = _coordinate_pair(lower.text or "", label="lowerCorner")
        maximum = _coordinate_pair(upper.text or "", label="upperCorner")
    elif bounds_name == "Box":
        if not _is_epsg_3879(bounds.get("srsName")):
            raise EspooArchiveError(
                "Espoo boundedBy Box does not advertise the native EPSG:3879 CRS"
            )
        coordinates = bounds.find(f"{{{GML_NAMESPACE}}}coordinates")
        if coordinates is None:
            raise EspooArchiveError("Espoo boundedBy Box lacks gml:coordinates")
        tuples = (coordinates.text or "").split(coordinates.get("ts", " "))
        tuples = [item for item in tuples if item.strip()]
        if len(tuples) != 2:
            raise EspooArchiveError("Espoo boundedBy Box must contain two coordinate tuples")
        separator = coordinates.get("cs", ",")
        minimum = _coordinate_pair(tuples[0].replace(separator, " "), label="Box minimum")
        maximum = _coordinate_pair(tuples[1].replace(separator, " "), label="Box maximum")
    else:
        raise EspooArchiveError(f"Espoo boundedBy uses unsupported gml:{bounds_name} geometry")

    minimum_x, minimum_y = minimum
    maximum_x, maximum_y = maximum
    if minimum_x > maximum_x or minimum_y > maximum_y:
        raise EspooArchiveError("Espoo boundedBy minimum exceeds its maximum")
    # EPSG:3879 is a GK25 coordinate system.  Espoo responses should use the
    # zone-prefixed easting and Finnish northing, not accidentally swapped axes
    # or WGS84 degrees.
    if not (
        24_000_000 <= minimum_x <= 26_000_000
        and 24_000_000 <= maximum_x <= 26_000_000
        and 6_000_000 <= minimum_y <= 8_000_000
        and 6_000_000 <= maximum_y <= 8_000_000
    ):
        raise EspooArchiveError("Espoo boundedBy coordinates are implausible for EPSG:3879")
    query_min_x, query_min_y, query_max_x, query_max_y = query_bbox
    intersects = not (
        maximum_x < query_min_x
        or minimum_x > query_max_x
        or maximum_y < query_min_y
        or minimum_y > query_max_y
    )
    if feature_count and not intersects:
        raise EspooArchiveError(
            "non-empty Espoo response boundedBy does not intersect its bounded query"
        )
    return (minimum_x, minimum_y, maximum_x, maximum_y)


def _stable_feature_id(feature: ET.Element) -> str | None:
    candidates = (
        feature.get("fid"),
        feature.get(f"{{{GML_NAMESPACE}}}id"),
        feature.get("id"),
    )
    present = [candidate.strip() for candidate in candidates if candidate and candidate.strip()]
    if len(set(present)) > 1:
        raise EspooArchiveError("Espoo feature advertises conflicting stable identifiers")
    if not present:
        return None
    identity = present[0]
    if len(identity) > 500 or any(ord(character) < 32 for character in identity):
        raise EspooArchiveError("Espoo feature has an invalid stable identifier")
    return identity


def _validate_gml(
    payload: bytes,
    *,
    layer: str,
    query_bbox: tuple[float, float, float, float],
) -> _GmlReport:
    if len(payload) > MAX_RESPONSE_BYTES:
        raise EspooArchiveError(
            f"Espoo WFS response exceeds the fixed {MAX_RESPONSE_BYTES // (1024 * 1024)} MB limit"
        )
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise EspooArchiveError("Espoo WFS response must be UTF-8 XML") from error
    lowered = text.casefold()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise EspooArchiveError(
            "Espoo WFS response contains a prohibited DTD or entity declaration"
        )
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        raise EspooArchiveError("Espoo WFS response is not well-formed XML") from error

    root_namespace, root_name = _split_qname(root.tag)
    if root_name in {"ExceptionReport", "ServiceExceptionReport"}:
        details = " ".join(part.strip() for part in root.itertext() if part.strip())
        raise EspooArchiveError(
            "Espoo WFS returned an exception report" + (f": {details[:300]}" if details else "")
        )
    if root_namespace != WFS_NAMESPACE or root_name != "FeatureCollection":
        raise EspooArchiveError("Espoo WFS response must be a WFS FeatureCollection")

    element_count = sum(1 for _ in root.iter())
    if element_count > MAX_XML_ELEMENTS_PER_LAYER:
        raise EspooArchiveError("Espoo WFS response exceeds the fixed XML element limit")
    members = root.findall(f"{{{GML_NAMESPACE}}}featureMember")
    if any(element.tag == f"{{{GML_NAMESPACE}}}featureMembers" for element in root.iter()):
        raise EspooArchiveError(
            "Espoo response uses unsupported gml:featureMembers instead of GML2 featureMember"
        )
    nested_members = sum(
        1 for element in root.iter() if element.tag == f"{{{GML_NAMESPACE}}}featureMember"
    )
    if nested_members != len(members):
        raise EspooArchiveError("Espoo featureMember elements must be direct collection children")
    if len(members) > MAX_FEATURES_PER_LAYER:
        raise EspooArchiveError(
            f"Espoo response exceeds the fixed {MAX_FEATURES_PER_LAYER}-feature layer limit"
        )

    advertised_crs = [
        element.get("srsName") for element in root.iter() if element.get("srsName") is not None
    ]
    if any(not _is_epsg_3879(value) for value in advertised_crs):
        raise EspooArchiveError(
            "Espoo response contains geometry that does not advertise native EPSG:3879"
        )

    expected_local_name = layer.split(":", maxsplit=1)[1]
    stable_ids: list[str] = []
    for index, member in enumerate(members):
        if len(member) != 1:
            raise EspooArchiveError(
                f"Espoo layer {layer} featureMember {index} must contain one feature"
            )
        feature = member[0]
        namespace, local_name = _split_qname(feature.tag)
        if namespace != ESPOO_GIS_NAMESPACE or local_name != expected_local_name:
            raise EspooArchiveError(
                f"Espoo featureMember {index} is {feature.tag!r}, expected "
                f"{{{ESPOO_GIS_NAMESPACE}}}{expected_local_name}"
            )
        stable_id = _stable_feature_id(feature)
        if stable_id is not None:
            stable_ids.append(stable_id)
    if len(set(stable_ids)) != len(stable_ids):
        raise EspooArchiveError("Espoo response contains a duplicate stable feature ID")

    declared_text = root.get("numberOfFeatures")
    declared_count: int | None = None
    if declared_text is not None:
        if not re.fullmatch(r"[0-9]+", declared_text):
            raise EspooArchiveError("Espoo FeatureCollection has an invalid numberOfFeatures")
        declared_count = int(declared_text)
        if declared_count != len(members):
            raise EspooArchiveError("Espoo numberOfFeatures does not equal the featureMember count")
    response_timestamp = _parse_aware_timestamp(root.get("timeStamp"))
    collection_bbox = _collection_bbox(
        root,
        feature_count=len(members),
        query_bbox=query_bbox,
    )
    stable_ids_sha256 = None
    if stable_ids:
        stable_ids_sha256 = _sha256(("\n".join(sorted(stable_ids)) + "\n").encode("utf-8"))
    return _GmlReport(
        feature_count=len(members),
        declared_feature_count=declared_count,
        response_timestamp=response_timestamp,
        collection_bbox=collection_bbox,
        feature_namespace=ESPOO_GIS_NAMESPACE if members else None,
        stable_id_count=len(stable_ids),
        stable_ids_sha256=stable_ids_sha256,
    )


def _archive_path_is_safe(workspace: Path, archive_name: Any) -> Path:
    if (
        not isinstance(archive_name, str)
        or Path(archive_name).name != archive_name
        or not archive_name.endswith(".gml.gz")
    ):
        raise EspooArchiveError("Espoo pointer contains an unsafe archive filename")
    archive_path = workspace / archive_name
    if not archive_path.is_file():
        raise EspooArchiveError(f"Espoo archive is missing at {archive_path}")
    return archive_path


class EspooWfsAdapter:
    """Acquire and replay the six audited City of Espoo municipal context layers."""

    adapter_id = ESPOO_ADAPTER_ID

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
            raise RuntimeError("Espoo WFS source has not been acquired or loaded")
        return json.loads(json.dumps(self._manifest))

    @property
    def archive_paths(self) -> dict[str, Path]:
        if not self._archive_paths:
            raise RuntimeError("Espoo WFS source has not been acquired or loaded")
        return dict(self._archive_paths)

    def assess_coverage(self, recipe: ScenarioRecipe) -> CoverageAssessment:
        bbox = _query_bbox(recipe)
        evidence: dict[str, Any] = {
            "endpoint_controlled_by_adapter": True,
            "allowlisted_layers": list(ESPOO_LAYERS),
            "bounded_context_bbox_epsg3879": list(bbox),
            "bbox_crs_suffix_omitted": True,
            "nonempty_response_is_not_coverage_proof": True,
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
                "This adapter has no authoritative coverage polygon for the City of Espoo "
                "layers. Valid or non-empty WFS responses are source observations, not proof "
                "of complete municipal coverage."
            ),
            checked_at=_checked_clock(self._clock),
            evidence=evidence,
        )

    def archive_pointer_path(self, context: SourceAcquisitionContext) -> Path:
        """Return the expected local pointer without touching the filesystem."""

        if context.declaration.adapter_id != self.adapter_id:
            raise AdapterConfigurationError(
                f"EspooWfsAdapter cannot preflight {context.declaration.adapter_id!r}"
            )
        if context.declaration.role != "municipal_context":
            raise AdapterConfigurationError(
                "espoo_wfs adapter currently supports municipal_context only"
            )
        return context.workspace / f"{context.recipe.scenario_id}.espoo-wfs.archive.json"

    def acquire(self, context: SourceAcquisitionContext) -> SourceSnapshotMetadata:
        if context.declaration.adapter_id != self.adapter_id:
            raise AdapterConfigurationError(
                f"EspooWfsAdapter cannot acquire {context.declaration.adapter_id!r}"
            )
        if context.declaration.role != "municipal_context":
            raise AdapterConfigurationError(
                "espoo_wfs adapter currently supports municipal_context only"
            )

        layers, timeout_s = _settings(context)
        bbox = _query_bbox(context.recipe)
        queries = {layer: derive_wfs_url(layer, bbox) for layer in layers}
        workspace = context.workspace
        workspace.mkdir(parents=True, exist_ok=True)
        pointer_path = self.archive_pointer_path(context)

        if self.refresh:
            previous_manifest = self._load_previous_valid_manifest(
                pointer_path,
                context=context,
                layers=layers,
                bbox=bbox,
                timeout_s=timeout_s,
                queries=queries,
            )
            layer_manifests: list[dict[str, Any]] = []
            for layer in layers:
                response = self._transport(queries[layer], timeout_s)
                report = _validate_gml(response, layer=layer, query_bbox=bbox)
                compressed = gzip.compress(response, compresslevel=9, mtime=0)
                raw_sha256 = _sha256(response)
                archive_name = (
                    f"{context.recipe.scenario_id}.espoo-{_LAYER_STEMS[layer]}."
                    f"{raw_sha256[:16]}.gml.gz"
                )
                archive_path = workspace / archive_name
                if archive_path.exists():
                    if archive_path.read_bytes() != compressed:
                        raise EspooArchiveError(
                            f"content-addressed Espoo archive collision at {archive_path}"
                        )
                else:
                    _atomic_write(archive_path, compressed)
                layer_manifests.append(
                    {
                        "layer": layer,
                        "query_url": queries[layer],
                        "query_sha256": _sha256(queries[layer].encode("utf-8")),
                        "archive_file": archive_name,
                        "archive_sha256": _sha256(compressed),
                        "raw_sha256": raw_sha256,
                        "byte_size": len(compressed),
                        "feature_count": report.feature_count,
                        "declared_feature_count": report.declared_feature_count,
                        "response_timestamp": report.response_timestamp,
                        "collection_bbox": list(report.collection_bbox)
                        if report.collection_bbox is not None
                        else None,
                        "feature_namespace": report.feature_namespace,
                        "stable_id_count": report.stable_id_count,
                        "stable_ids_sha256": report.stable_ids_sha256,
                    }
                )

            acquired_at = _checked_clock(self._clock).isoformat()
            if previous_manifest is not None and [
                item["raw_sha256"] for item in previous_manifest["layers"]
            ] == [item["raw_sha256"] for item in layer_manifests]:
                # A later explicit check of byte-identical source data is the same
                # immutable snapshot. Preserve its first acquisition provenance.
                acquired_at = previous_manifest["acquired_at"]
            manifest: Any = {
                "schema_version": "1.0",
                "adapter_version": ESPOO_ADAPTER_VERSION,
                "scenario_id": context.recipe.scenario_id,
                "recipe_sha256": context.recipe.sha256(),
                "endpoint": ESPOO_WFS_ENDPOINT,
                "wfs_version": ESPOO_WFS_VERSION,
                "output_format": ESPOO_OUTPUT_FORMAT,
                "source_crs": ESPOO_SOURCE_CRS,
                "normalized_crs": ANALYSIS_CRS,
                "network_context_buffer_m": context.recipe.network_context_buffer_m,
                "bbox": list(bbox),
                "bbox_crs_suffix_omitted": True,
                "timeout_s": timeout_s,
                "acquired_at": acquired_at,
                "layers": layer_manifests,
            }
            pointer_bytes = _json_bytes(manifest)
            if not pointer_path.exists() or pointer_path.read_bytes() != pointer_bytes:
                _atomic_write(pointer_path, pointer_bytes)
        else:
            if not pointer_path.is_file():
                raise EspooArchiveError(
                    f"offline Espoo archive pointer is missing at {pointer_path}; "
                    "run acquisition once with refresh=True"
                )
            try:
                manifest = json.loads(pointer_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise EspooArchiveError(
                    f"cannot read Espoo archive pointer {pointer_path}"
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
        artifacts: list[dict[str, Any]] = []
        query_layers: list[dict[str, Any]] = []
        total_features = 0
        for item in manifest["layers"]:
            layer = item["layer"]
            archive_path = _archive_path_is_safe(workspace, item["archive_file"])
            compressed = archive_path.read_bytes()
            try:
                response = gzip.decompress(compressed)
            except (OSError, EOFError) as error:
                raise EspooArchiveError(
                    f"Espoo archive is not valid gzip: {archive_path}"
                ) from error
            report = _validate_gml(response, layer=layer, query_bbox=bbox)
            self._verify_report(item, report)
            if _sha256(response) != item["raw_sha256"]:
                raise EspooArchiveError("Espoo archive raw checksum does not match its pointer")

            archive_paths[layer] = archive_path
            total_features += report.feature_count
            artifacts.append(
                {
                    "path": f"raw/espoo/{_LAYER_STEMS[layer]}.gml.gz",
                    "sha256": _sha256(compressed),
                    "byte_size": len(compressed),
                    "media_type": "application/gzip",
                }
            )
            query_layers.append(
                {
                    "type_name": layer,
                    "query_url": item["query_url"],
                    "query_sha256": item["query_sha256"],
                    "raw_sha256": item["raw_sha256"],
                    "feature_count": item["feature_count"],
                    "declared_feature_count": item["declared_feature_count"],
                    "response_timestamp": item["response_timestamp"],
                    "collection_bbox": item["collection_bbox"],
                    "feature_namespace": item["feature_namespace"],
                    "stable_id_count": item["stable_id_count"],
                    "stable_ids_sha256": item["stable_ids_sha256"],
                }
            )

        acquired_at = datetime.fromisoformat(manifest["acquired_at"])
        self._manifest = manifest
        self._archive_paths = archive_paths
        return SourceSnapshotMetadata(
            adapter_id=self.adapter_id,
            source_name="City of Espoo open geographic data WFS",
            endpoint=ESPOO_WFS_ENDPOINT,
            acquired_at=acquired_at,
            source_timestamp=None,
            query={
                "adapter_version": ESPOO_ADAPTER_VERSION,
                "service": "WFS",
                "version": ESPOO_WFS_VERSION,
                "request": "GetFeature",
                "output_format": ESPOO_OUTPUT_FORMAT,
                "source_crs": ESPOO_SOURCE_CRS,
                "normalized_crs": ANALYSIS_CRS,
                "bounded_network_context_bbox": list(bbox),
                "network_context_buffer_m": context.recipe.network_context_buffer_m,
                "bbox_crs_suffix_omitted": True,
                "timeout_s": timeout_s,
                "layers": query_layers,
                "archive_representation": (
                    "Exact validated UTF-8 GML response bytes, without XML canonicalization, "
                    "gzip-compressed with mtime zero; exact raw-byte digests define source "
                    "snapshot identity."
                ),
                "response_timestamp_is_not_source_edition": True,
                "coverage_not_inferred_from_feature_count": True,
            },
            source_crs=ESPOO_SOURCE_CRS,
            normalized_crs=ANALYSIS_CRS,
            feature_count=total_features,
            licence=LicenceRecord(
                name="Creative Commons Attribution 4.0 International (CC BY 4.0)",
                url="https://creativecommons.org/licenses/by/4.0/",
                attribution="Source: City of Espoo",
                obligations=[
                    "Attribute the City of Espoo as the source.",
                    "State the CC BY 4.0 licence and indicate modifications.",
                    "Retain the exact layer, query, acquisition time, and snapshot provenance.",
                ],
            ),
            artifacts=artifacts,
        )

    @classmethod
    def _load_previous_valid_manifest(
        cls,
        pointer_path: Path,
        *,
        context: SourceAcquisitionContext,
        layers: tuple[str, ...],
        bbox: tuple[float, float, float, float],
        timeout_s: int,
        queries: dict[str, str],
    ) -> dict[str, Any] | None:
        if not pointer_path.is_file():
            return None
        try:
            previous = json.loads(pointer_path.read_text(encoding="utf-8"))
            cls._validate_manifest(
                previous,
                context=context,
                layers=layers,
                bbox=bbox,
                timeout_s=timeout_s,
                queries=queries,
            )
            for item in previous["layers"]:
                archive_path = _archive_path_is_safe(context.workspace, item["archive_file"])
                response = gzip.decompress(archive_path.read_bytes())
                if _sha256(response) != item.get("raw_sha256"):
                    raise EspooArchiveError(
                        "previous Espoo archive raw checksum does not match its pointer"
                    )
                report = _validate_gml(
                    response,
                    layer=item["layer"],
                    query_bbox=bbox,
                )
                cls._verify_report(item, report)
        except (OSError, EOFError, json.JSONDecodeError, EspooArchiveError):
            return None
        return previous

    @staticmethod
    def _verify_report(item: dict[str, Any], report: _GmlReport) -> None:
        expected = {
            "feature_count": report.feature_count,
            "declared_feature_count": report.declared_feature_count,
            "response_timestamp": report.response_timestamp,
            "collection_bbox": list(report.collection_bbox)
            if report.collection_bbox is not None
            else None,
            "feature_namespace": report.feature_namespace,
            "stable_id_count": report.stable_id_count,
            "stable_ids_sha256": report.stable_ids_sha256,
        }
        differences = [
            key for key, expected_value in expected.items() if item.get(key) != expected_value
        ]
        if differences:
            raise EspooArchiveError(
                "Espoo archive validation report does not match its pointer ("
                + ", ".join(differences)
                + ")"
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
            raise EspooArchiveError("Espoo archive pointer must be a JSON object")
        expected = {
            "schema_version": "1.0",
            "adapter_version": ESPOO_ADAPTER_VERSION,
            "scenario_id": context.recipe.scenario_id,
            "recipe_sha256": context.recipe.sha256(),
            "endpoint": ESPOO_WFS_ENDPOINT,
            "wfs_version": ESPOO_WFS_VERSION,
            "output_format": ESPOO_OUTPUT_FORMAT,
            "source_crs": ESPOO_SOURCE_CRS,
            "normalized_crs": ANALYSIS_CRS,
            "network_context_buffer_m": context.recipe.network_context_buffer_m,
            "bbox": list(bbox),
            "bbox_crs_suffix_omitted": True,
            "timeout_s": timeout_s,
        }
        differences = [
            key for key, expected_value in expected.items() if manifest.get(key) != expected_value
        ]
        if differences:
            raise EspooArchiveError(
                "offline Espoo archives do not match the current recipe/query ("
                + ", ".join(differences)
                + "); refresh explicitly"
            )
        manifest_layers = manifest.get("layers")
        if not isinstance(manifest_layers, list) or [
            item.get("layer") if isinstance(item, dict) else None for item in manifest_layers
        ] != list(layers):
            raise EspooArchiveError("Espoo pointer layer list does not match the recipe")
        try:
            acquired_at = datetime.fromisoformat(manifest["acquired_at"])
        except (KeyError, TypeError, ValueError) as error:
            raise EspooArchiveError("Espoo pointer has an invalid acquisition timestamp") from error
        if acquired_at.tzinfo is None:
            raise EspooArchiveError("Espoo pointer acquisition timestamp lacks a timezone")

        for item in manifest_layers:
            layer = item["layer"]
            expected_item = {
                "query_url": queries[layer],
                "query_sha256": _sha256(queries[layer].encode("utf-8")),
            }
            differences = [
                key
                for key, expected_value in expected_item.items()
                if item.get(key) != expected_value
            ]
            if differences:
                raise EspooArchiveError(
                    f"Espoo pointer entry for {layer} has mismatched " + ", ".join(differences)
                )
            archive_path = _archive_path_is_safe(context.workspace, item.get("archive_file"))
            compressed = archive_path.read_bytes()
            if _sha256(compressed) != item.get("archive_sha256"):
                raise EspooArchiveError("Espoo archive checksum does not match its pointer")
            if len(compressed) != item.get("byte_size"):
                raise EspooArchiveError("Espoo archive size does not match its pointer")
            feature_count = item.get("feature_count")
            if (
                not isinstance(feature_count, int)
                or isinstance(feature_count, bool)
                or not 0 <= feature_count <= MAX_FEATURES_PER_LAYER
            ):
                raise EspooArchiveError("Espoo pointer has an invalid feature count")
            declared_count = item.get("declared_feature_count")
            if declared_count is not None and (
                not isinstance(declared_count, int)
                or isinstance(declared_count, bool)
                or declared_count != feature_count
            ):
                raise EspooArchiveError("Espoo pointer has an invalid declared feature count")
            for digest_key in ("archive_sha256", "raw_sha256", "query_sha256"):
                digest = item.get(digest_key)
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise EspooArchiveError(f"Espoo pointer has an invalid {digest_key} digest")


def load_espoo_archive(
    path: Path,
    *,
    layer: str,
    bbox: tuple[float, float, float, float],
) -> bytes:
    """Load and revalidate one exact frozen Espoo GML response."""

    if layer not in ESPOO_LAYERS:
        raise AdapterConfigurationError(f"unsupported Espoo WFS layer {layer!r}")
    if len(bbox) != 4 or not all(math.isfinite(value) for value in bbox):
        raise ValueError("Espoo archive bbox must contain four finite metric values")
    try:
        payload = gzip.decompress(path.read_bytes())
    except (OSError, EOFError) as error:
        raise EspooArchiveError(f"cannot decompress Espoo archive {path}") from error
    _validate_gml(payload, layer=layer, query_bbox=bbox)
    return payload
