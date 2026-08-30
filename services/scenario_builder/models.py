from __future__ import annotations

import hashlib
import json
import math
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

RECIPE_SCHEMA_VERSION = "1.0"
SNAPSHOT_SCHEMA_VERSION = "1.0"
PROFILE_ID = "finland-resilient-access-v1"
ANALYSIS_CRS = "EPSG:3067"
INPUT_GEOMETRY_CRS = "EPSG:4326"

# This is an intentionally conservative preflight envelope, not an assertion that
# every point in the rectangle is inside Finland or covered by a particular source.
# Adapters must make the authoritative source-specific coverage decision.
FINLAND_BUILD_ENVELOPE = (19.0, 59.0, 32.0, 70.5)

MIN_RADIUS_M = 100.0
# Kept below the polygon ceiling as a deliberately simple preflight limit:
# π × (2.5 km)² is approximately 19.6 km².
MAX_RADIUS_M = 2_500.0
MAX_POLYGON_AREA_KM2 = 25.0
MAX_POLYGON_EXTENT_M = 10_000.0
MAX_POLYGON_VERTICES = 1_000
DEFAULT_NETWORK_CONTEXT_BUFFER_M = 750.0
MAX_NETWORK_CONTEXT_BUFFER_M = 2_000.0

Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    ),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def _inside_finland_envelope(longitude: float, latitude: float) -> bool:
    west, south, east, north = FINLAND_BUILD_ENVELOPE
    return west <= longitude <= east and south <= latitude <= north


def _ring_area_m2(ring: list[tuple[float, float]], reference_latitude: float) -> float:
    """Approximate a small WGS84 ring in local metres for a build-size guard."""

    metres_per_degree_latitude = 111_320.0
    metres_per_degree_longitude = metres_per_degree_latitude * math.cos(
        math.radians(reference_latitude)
    )
    projected = [
        (longitude * metres_per_degree_longitude, latitude * metres_per_degree_latitude)
        for longitude, latitude in ring
    ]
    signed_twice_area = sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(projected, projected[1:], strict=False)
    )
    return abs(signed_twice_area) / 2.0


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    mean_latitude = (a[1] + b[1]) / 2.0
    dx = (a[0] - b[0]) * 111_320.0 * math.cos(math.radians(mean_latitude))
    dy = (a[1] - b[1]) * 111_320.0
    return math.hypot(dx, dy)


def _orientation(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _point_on_segment(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> bool:
    tolerance = 1e-12
    return (
        min(start[0], end[0]) - tolerance <= point[0] <= max(start[0], end[0]) + tolerance
        and min(start[1], end[1]) - tolerance
        <= point[1]
        <= max(start[1], end[1]) + tolerance
        and abs(_orientation(start, end, point)) <= tolerance
    )


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    tolerance = 1e-12
    orientations = (
        _orientation(a, b, c),
        _orientation(a, b, d),
        _orientation(c, d, a),
        _orientation(c, d, b),
    )
    if (
        orientations[0] * orientations[1] < -tolerance
        and orientations[2] * orientations[3] < -tolerance
    ):
        return True
    return (
        (abs(orientations[0]) <= tolerance and _point_on_segment(c, a, b))
        or (abs(orientations[1]) <= tolerance and _point_on_segment(d, a, b))
        or (abs(orientations[2]) <= tolerance and _point_on_segment(a, c, d))
        or (abs(orientations[3]) <= tolerance and _point_on_segment(b, c, d))
    )


def _ring_self_intersects(ring: list[tuple[float, float]]) -> bool:
    segment_count = len(ring) - 1
    for first in range(segment_count):
        a, b = ring[first], ring[first + 1]
        if a == b:
            return True
        for second in range(first + 1, segment_count):
            # Neighbouring edges legitimately meet at one vertex. The first and
            # final edges are neighbours too because the ring is closed.
            if second == first + 1 or (first == 0 and second == segment_count - 1):
                continue
            if _segments_intersect(a, b, ring[second], ring[second + 1]):
                return True
    return False


class ContractModel(BaseModel):
    """Strict base model so recipe typos fail instead of being silently ignored."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LonLat(ContractModel):
    longitude: float = Field(ge=-180.0, le=180.0)
    latitude: float = Field(ge=-90.0, le=90.0)

    @model_validator(mode="after")
    def within_supported_build_envelope(self) -> Self:
        if not _inside_finland_envelope(self.longitude, self.latitude):
            west, south, east, north = FINLAND_BUILD_ENVELOPE
            raise ValueError(
                "location is outside the Finland v1 build envelope "
                f"({west}--{east} E, {south}--{north} N)"
            )
        return self


class GeoJsonPolygon(ContractModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[tuple[float, float]]] = Field(min_length=1)

    @field_validator("coordinates")
    @classmethod
    def validate_rings(
        cls, coordinates: list[list[tuple[float, float]]]
    ) -> list[list[tuple[float, float]]]:
        if len(coordinates) != 1:
            raise ValueError(
                "polygon holes are not supported by the Finland v1 build profile; "
                "submit one simple exterior ring"
            )
        vertex_count = sum(len(ring) for ring in coordinates)
        if vertex_count > MAX_POLYGON_VERTICES:
            raise ValueError(
                f"polygon has {vertex_count} vertices; the v1 limit is "
                f"{MAX_POLYGON_VERTICES}"
            )

        for ring_number, ring in enumerate(coordinates):
            if len(ring) < 4:
                raise ValueError(f"polygon ring {ring_number} must contain at least four points")
            if ring[0] != ring[-1]:
                raise ValueError(
                    f"polygon ring {ring_number} is not closed; its first and last points differ"
                )
            for longitude, latitude in ring:
                if not math.isfinite(longitude) or not math.isfinite(latitude):
                    raise ValueError(f"polygon ring {ring_number} contains a non-finite coordinate")
                if not _inside_finland_envelope(longitude, latitude):
                    raise ValueError(
                        f"polygon coordinate ({longitude}, {latitude}) is outside the "
                        "Finland v1 build envelope"
                    )
            if _ring_self_intersects(ring):
                raise ValueError(f"polygon ring {ring_number} is self-intersecting")

        reference_latitude = sum(point[1] for point in coordinates[0][:-1]) / (
            len(coordinates[0]) - 1
        )
        exterior_area = _ring_area_m2(coordinates[0], reference_latitude)
        hole_area = sum(
            _ring_area_m2(ring, reference_latitude) for ring in coordinates[1:]
        )
        area_m2 = exterior_area - hole_area
        if area_m2 <= 0:
            raise ValueError("polygon has zero or negative usable area")
        area_km2 = area_m2 / 1_000_000.0
        if area_km2 > MAX_POLYGON_AREA_KM2:
            raise ValueError(
                f"polygon area is approximately {area_km2:.2f} km²; the v1 limit is "
                f"{MAX_POLYGON_AREA_KM2:.0f} km²"
            )

        exterior = coordinates[0][:-1]
        west = min(point[0] for point in exterior)
        east = max(point[0] for point in exterior)
        south = min(point[1] for point in exterior)
        north = max(point[1] for point in exterior)
        extent_m = _distance_m((west, south), (east, north))
        if extent_m > MAX_POLYGON_EXTENT_M:
            raise ValueError(
                f"polygon extent is approximately {extent_m:.0f} m; the v1 limit is "
                f"{MAX_POLYGON_EXTENT_M:.0f} m"
            )
        return coordinates


class PointRadiusArea(ContractModel):
    kind: Literal["point_radius"] = "point_radius"
    center: LonLat
    radius_m: float = Field(ge=MIN_RADIUS_M, le=MAX_RADIUS_M)
    coordinate_crs: Literal["EPSG:4326"] = INPUT_GEOMETRY_CRS

    @model_validator(mode="after")
    def within_supported_build_envelope(self) -> Self:
        latitude_margin = self.radius_m / 111_320.0
        longitude_margin = self.radius_m / (
            111_320.0 * math.cos(math.radians(self.center.latitude))
        )
        west, south, east, north = FINLAND_BUILD_ENVELOPE
        if not (
            west <= self.center.longitude - longitude_margin
            and self.center.longitude + longitude_margin <= east
            and south <= self.center.latitude - latitude_margin
            and self.center.latitude + latitude_margin <= north
        ):
            raise ValueError("point-radius area crosses outside the Finland v1 build envelope")
        return self


class PolygonArea(ContractModel):
    kind: Literal["polygon"] = "polygon"
    geometry: GeoJsonPolygon
    coordinate_crs: Literal["EPSG:4326"] = INPUT_GEOMETRY_CRS


StudyArea = Annotated[PointRadiusArea | PolygonArea, Field(discriminator="kind")]


class SourceDeclaration(ContractModel):
    adapter_id: Identifier
    role: Literal[
        "base_network",
        "elevation",
        "flood_hazard",
        "municipal_context",
        "roadworks",
    ]
    required: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def parameters_must_be_json_serializable(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError) as error:
            raise ValueError("source parameters must be finite JSON values") from error
        return value


class ScenarioRecipe(ContractModel):
    schema_version: Literal["1.0"] = RECIPE_SCHEMA_VERSION
    profile_id: Literal["finland-resilient-access-v1"] = PROFILE_ID
    scenario_id: Identifier
    name: str = Field(min_length=1, max_length=120)
    scenario_type: Literal["resilient_access"] = "resilient_access"
    analysis_crs: Literal["EPSG:3067"] = ANALYSIS_CRS
    network_context_buffer_m: float = Field(
        default=DEFAULT_NETWORK_CONTEXT_BUFFER_M,
        ge=0,
        le=MAX_NETWORK_CONTEXT_BUFFER_M,
        description=(
            "Metric buffer acquired around the user-selected core so meaningful exits and "
            "cross-boundary ways are not severed at the analysis boundary."
        ),
    )
    area: StudyArea
    sources: list[SourceDeclaration] = Field(min_length=1)

    @model_validator(mode="after")
    def source_adapter_ids_are_unique(self) -> Self:
        adapter_ids = [source.adapter_id for source in self.sources]
        duplicates = sorted(
            adapter_id for adapter_id in set(adapter_ids) if adapter_ids.count(adapter_id) > 1
        )
        if duplicates:
            raise ValueError(
                "source declarations contain duplicate adapter IDs: " + ", ".join(duplicates)
            )
        if not any(source.role == "base_network" and source.required for source in self.sources):
            raise ValueError("a required base_network source declaration is required")
        return self

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class LicenceRecord(ContractModel):
    name: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=1, max_length=500)
    attribution: str = Field(min_length=1, max_length=1_000)
    obligations: list[str] = Field(default_factory=list)


class ArtifactDigest(ContractModel):
    path: str = Field(min_length=1, max_length=500)
    sha256: Sha256
    byte_size: int = Field(ge=0)
    media_type: str | None = Field(default=None, max_length=120)

    @field_validator("path")
    @classmethod
    def path_is_snapshot_relative(cls, value: str) -> str:
        if value.startswith(("/", "\\")) or ".." in value.replace("\\", "/").split("/"):
            raise ValueError(
                "artifact path must be relative to the snapshot and cannot contain '..'"
            )
        return value


class SourceSnapshotMetadata(ContractModel):
    adapter_id: Identifier
    source_name: str = Field(min_length=1, max_length=160)
    endpoint: str = Field(min_length=1, max_length=1_000)
    acquired_at: AwareDatetime
    source_timestamp: AwareDatetime | None = None
    query: dict[str, Any]
    source_crs: str = Field(min_length=1, max_length=80)
    normalized_crs: Literal["EPSG:3067"] = ANALYSIS_CRS
    feature_count: int = Field(ge=0)
    licence: LicenceRecord
    artifacts: list[ArtifactDigest] = Field(min_length=1)

    @field_validator("query")
    @classmethod
    def query_must_be_json_serializable(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError) as error:
            raise ValueError("source query must contain only finite JSON values") from error
        return value

    @model_validator(mode="after")
    def artifact_paths_are_unique(self) -> Self:
        paths = [artifact.path for artifact in self.artifacts]
        duplicates = sorted(path for path in set(paths) if paths.count(path) > 1)
        if duplicates:
            raise ValueError(
                "source metadata contains duplicate artifact paths: " + ", ".join(duplicates)
            )
        return self


class FieldLineage(ContractModel):
    """One field-level provenance record stored in a snapshot's lineage artifact."""

    output_feature_id: str = Field(min_length=1, max_length=200)
    output_field: str = Field(min_length=1, max_length=200)
    adapter_id: Identifier
    source_feature_ids: list[str] = Field(min_length=1)
    operation: str = Field(min_length=1, max_length=500)
    precedence_rank: int = Field(ge=0)


class ScenarioSnapshotMetadata(ContractModel):
    schema_version: Literal["1.0"] = SNAPSHOT_SCHEMA_VERSION
    snapshot_id: Identifier
    scenario_id: Identifier
    recipe_schema_version: Literal["1.0"] = RECIPE_SCHEMA_VERSION
    recipe_sha256: Sha256
    created_at: AwareDatetime
    analysis_crs: Literal["EPSG:3067"] = ANALYSIS_CRS
    sources: list[SourceSnapshotMetadata] = Field(min_length=1)
    field_lineage_artifact: ArtifactDigest = Field(
        description=(
            "Snapshot-relative JSONL artifact containing serialized FieldLineage records; "
            "kept external because large scenarios can contain many records."
        )
    )
    derived_artifacts: list[ArtifactDigest] = Field(min_length=1)

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> Self:
        adapter_ids = [source.adapter_id for source in self.sources]
        duplicate_adapters = sorted(
            adapter_id for adapter_id in set(adapter_ids) if adapter_ids.count(adapter_id) > 1
        )
        if duplicate_adapters:
            raise ValueError(
                "snapshot metadata contains duplicate adapter IDs: "
                + ", ".join(duplicate_adapters)
            )
        artifact_paths = [
            *(artifact.path for source in self.sources for artifact in source.artifacts),
            self.field_lineage_artifact.path,
            *(artifact.path for artifact in self.derived_artifacts),
        ]
        duplicate_artifacts = sorted(
            path for path in set(artifact_paths) if artifact_paths.count(path) > 1
        )
        if duplicate_artifacts:
            raise ValueError(
                "snapshot metadata contains duplicate artifact paths: "
                + ", ".join(duplicate_artifacts)
            )
        return self

    def validate_against(self, recipe: ScenarioRecipe) -> None:
        errors: list[str] = []
        if self.scenario_id != recipe.scenario_id:
            errors.append(
                f"scenario_id is {self.scenario_id!r}, expected {recipe.scenario_id!r}"
            )
        expected_digest = recipe.sha256()
        if self.recipe_sha256 != expected_digest:
            errors.append(
                f"recipe_sha256 is {self.recipe_sha256}, expected {expected_digest}"
            )
        if self.analysis_crs != recipe.analysis_crs:
            errors.append(
                f"analysis_crs is {self.analysis_crs}, expected {recipe.analysis_crs}"
            )

        declared = {source.adapter_id: source for source in recipe.sources}
        acquired = {source.adapter_id for source in self.sources}
        undeclared = sorted(acquired - set(declared))
        if undeclared:
            errors.append("snapshot contains undeclared source adapters: " + ", ".join(undeclared))
        missing_required = sorted(
            adapter_id
            for adapter_id, declaration in declared.items()
            if declaration.required and adapter_id not in acquired
        )
        if missing_required:
            errors.append(
                "snapshot is missing required source adapters: " + ", ".join(missing_required)
            )
        if errors:
            raise ValueError("Snapshot does not match scenario recipe:\n- " + "\n- ".join(errors))


class CoverageAssessment(ContractModel):
    adapter_id: Identifier
    status: Literal["full", "partial", "none", "unknown"]
    message: str = Field(min_length=1, max_length=1_000)
    checked_at: AwareDatetime
    evidence: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence")
    @classmethod
    def evidence_must_be_json_serializable(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError) as error:
            raise ValueError("coverage evidence must contain only finite JSON values") from error
        return value
