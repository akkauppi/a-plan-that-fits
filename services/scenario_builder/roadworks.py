"""Strict interchange for frozen, explicitly interpreted roadworks data.

The interchange intentionally does not fetch remote data and does not convert a
generic event, permit, or project record into a road restriction.  Every feature
must carry an explicit restriction basis and affected modes supplied by the data
preparer.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .models import FINLAND_BUILD_ENVELOPE, LicenceRecord

ROADWORKS_SCHEMA_VERSION = "1.0"
ROADWORKS_CRS = "EPSG:4326"
MAX_FEATURES = 10_000
MAX_COORDINATES_PER_GEOMETRY = 20_000

WorkIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
SourceFeatureIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]
Position = tuple[float, float]
AffectedMode = Literal[
    "private_car",
    "walking",
    "cycling",
    "public_transport",
    "emergency",
    "service",
]

_MODE_ORDER = {
    "private_car": 0,
    "walking": 1,
    "cycling": 2,
    "public_transport": 3,
    "emergency": 4,
    "service": 5,
}


class RoadworksValidationError(ValueError):
    """Raised when a local interchange document cannot be decoded or loaded."""


class RoadworksModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _position_is_supported(position: Position) -> bool:
    longitude, latitude = position
    west, south, east, north = FINLAND_BUILD_ENVELOPE
    return (
        math.isfinite(longitude)
        and math.isfinite(latitude)
        and west <= longitude <= east
        and south <= latitude <= north
    )


def _validate_positions(positions: list[Position], *, minimum: int, label: str) -> None:
    if len(positions) < minimum:
        raise ValueError(f"{label} must contain at least {minimum} positions")
    if len(positions) > MAX_COORDINATES_PER_GEOMETRY:
        raise ValueError(
            f"{label} contains more than the v1 limit of {MAX_COORDINATES_PER_GEOMETRY} positions"
        )
    for index, position in enumerate(positions):
        if not _position_is_supported(position):
            west, south, east, north = FINLAND_BUILD_ENVELOPE
            raise ValueError(
                f"{label} position {index} is non-finite or outside the Finland v1 "
                f"WGS84 envelope ({west}--{east} E, {south}--{north} N)"
            )
    if any(first == second for first, second in zip(positions, positions[1:], strict=False)):
        raise ValueError(f"{label} contains consecutive duplicate positions")


def _orientation(a: Position, b: Position, c: Position) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _point_on_segment(point: Position, start: Position, end: Position) -> bool:
    tolerance = 1e-12
    return (
        min(start[0], end[0]) - tolerance <= point[0] <= max(start[0], end[0]) + tolerance
        and min(start[1], end[1]) - tolerance <= point[1] <= max(start[1], end[1]) + tolerance
        and abs(_orientation(start, end, point)) <= tolerance
    )


def _segments_intersect(a: Position, b: Position, c: Position, d: Position) -> bool:
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


def _ring_self_intersects(ring: list[Position]) -> bool:
    segment_count = len(ring) - 1
    for first in range(segment_count):
        for second in range(first + 1, segment_count):
            if second == first + 1 or (first == 0 and second == segment_count - 1):
                continue
            if _segments_intersect(
                ring[first],
                ring[first + 1],
                ring[second],
                ring[second + 1],
            ):
                return True
    return False


def _ring_signed_area(ring: list[Position]) -> float:
    return (
        sum(
            first[0] * second[1] - second[0] * first[1]
            for first, second in zip(ring, ring[1:], strict=False)
        )
        / 2.0
    )


def _point_in_ring(point: Position, ring: list[Position]) -> bool:
    """Return true only for a point strictly inside a simple ring."""

    if any(
        _point_on_segment(point, start, end) for start, end in zip(ring, ring[1:], strict=False)
    ):
        return False
    inside = False
    x, y = point
    for start, end in zip(ring, ring[1:], strict=False):
        if (start[1] > y) == (end[1] > y):
            continue
        intersection_x = start[0] + (y - start[1]) * (end[0] - start[0]) / (end[1] - start[1])
        if intersection_x > x:
            inside = not inside
    return inside


def _rings_intersect(first: list[Position], second: list[Position]) -> bool:
    return any(
        _segments_intersect(a, b, c, d)
        for a, b in zip(first, first[1:], strict=False)
        for c, d in zip(second, second[1:], strict=False)
    )


class LineStringGeometry(RoadworksModel):
    type: Literal["LineString"] = "LineString"
    coordinates: list[Position]

    @field_validator("coordinates")
    @classmethod
    def valid_line(cls, coordinates: list[Position]) -> list[Position]:
        _validate_positions(coordinates, minimum=2, label="LineString")
        return coordinates


class MultiLineStringGeometry(RoadworksModel):
    type: Literal["MultiLineString"] = "MultiLineString"
    coordinates: list[list[Position]] = Field(min_length=1)

    @field_validator("coordinates")
    @classmethod
    def valid_lines(cls, coordinates: list[list[Position]]) -> list[list[Position]]:
        total = sum(len(line) for line in coordinates)
        if total > MAX_COORDINATES_PER_GEOMETRY:
            raise ValueError(
                "MultiLineString contains more than the v1 limit of "
                f"{MAX_COORDINATES_PER_GEOMETRY} positions"
            )
        for index, line in enumerate(coordinates):
            _validate_positions(line, minimum=2, label=f"MultiLineString part {index}")
        return coordinates


class PolygonGeometry(RoadworksModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[Position]] = Field(min_length=1)

    @field_validator("coordinates")
    @classmethod
    def valid_polygon(cls, coordinates: list[list[Position]]) -> list[list[Position]]:
        total = sum(len(ring) for ring in coordinates)
        if total > MAX_COORDINATES_PER_GEOMETRY:
            raise ValueError(
                "Polygon contains more than the v1 limit of "
                f"{MAX_COORDINATES_PER_GEOMETRY} positions"
            )
        for index, ring in enumerate(coordinates):
            _validate_positions(ring, minimum=4, label=f"Polygon ring {index}")
            if ring[0] != ring[-1]:
                raise ValueError(f"Polygon ring {index} is not closed")
            if len(set(ring[:-1])) < 3:
                raise ValueError(f"Polygon ring {index} has fewer than three distinct vertices")
            if abs(_ring_signed_area(ring)) <= 1e-15:
                raise ValueError(f"Polygon ring {index} has zero area")
            if _ring_self_intersects(ring):
                raise ValueError(f"Polygon ring {index} is self-intersecting")

        exterior = coordinates[0]
        holes = coordinates[1:]
        for index, hole in enumerate(holes, start=1):
            if _rings_intersect(exterior, hole) or not _point_in_ring(hole[0], exterior):
                raise ValueError(f"Polygon hole {index} is not strictly inside the exterior ring")
        for first in range(len(holes)):
            for second in range(first + 1, len(holes)):
                if (
                    _rings_intersect(holes[first], holes[second])
                    or _point_in_ring(holes[first][0], holes[second])
                    or _point_in_ring(holes[second][0], holes[first])
                ):
                    raise ValueError("Polygon holes overlap, touch, or contain one another")
        return coordinates


RoadworksGeometry = Annotated[
    LineStringGeometry | MultiLineStringGeometry | PolygonGeometry,
    Field(discriminator="type"),
]


class FixedSchedule(RoadworksModel):
    kind: Literal["fixed"] = "fixed"
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def end_follows_start(self) -> Self:
        if self.end <= self.start:
            raise ValueError("fixed roadwork end must be later than start")
        return self


class FlexibleSchedule(RoadworksModel):
    kind: Literal["flexible"] = "flexible"
    earliest_start: AwareDatetime
    latest_end: AwareDatetime
    duration_minutes: int = Field(ge=1, le=525_600)

    @model_validator(mode="after")
    def duration_fits_window(self) -> Self:
        if self.latest_end <= self.earliest_start:
            raise ValueError("flexible roadwork latest_end must be later than earliest_start")
        duration = timedelta(minutes=self.duration_minutes)
        if self.earliest_start + duration > self.latest_end:
            raise ValueError("flexible roadwork duration does not fit its earliest/latest window")
        return self


RoadworksSchedule = Annotated[
    FixedSchedule | FlexibleSchedule,
    Field(discriminator="kind"),
]


class RoadworkProperties(RoadworksModel):
    source_feature_ids: list[SourceFeatureIdentifier] = Field(min_length=1)
    affected_modes: list[AffectedMode] = Field(min_length=1)
    effect: Literal["closed", "restricted"]
    direction: Literal["both", "along_geometry", "against_geometry"]
    restriction_description: str | None = Field(default=None, min_length=1, max_length=1_000)
    restriction_basis: Literal["explicit_source_declaration"]
    schedule: RoadworksSchedule
    label: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("source_feature_ids")
    @classmethod
    def unique_sorted_source_ids(cls, source_feature_ids: list[str]) -> list[str]:
        if len(set(source_feature_ids)) != len(source_feature_ids):
            raise ValueError("source_feature_ids must be unique within a roadwork")
        return sorted(source_feature_ids)

    @field_validator("affected_modes")
    @classmethod
    def unique_sorted_modes(cls, modes: list[AffectedMode]) -> list[AffectedMode]:
        if len(set(modes)) != len(modes):
            raise ValueError("affected_modes must not contain duplicates")
        return sorted(modes, key=_MODE_ORDER.__getitem__)

    @model_validator(mode="after")
    def restricted_effect_is_explained(self) -> Self:
        if self.effect == "restricted" and self.restriction_description is None:
            raise ValueError("a restricted roadwork requires restriction_description")
        return self


class RoadworkFeature(RoadworksModel):
    type: Literal["Feature"]
    id: WorkIdentifier
    geometry: RoadworksGeometry
    properties: RoadworkProperties

    @model_validator(mode="after")
    def direction_is_unambiguous(self) -> Self:
        if self.geometry.type != "LineString" and self.properties.direction != "both":
            raise ValueError(
                "directional roadwork effects require a single LineString; Polygon and "
                "MultiLineString geometries must use direction='both'"
            )
        return self


class RoadworksSource(RoadworksModel):
    name: str = Field(min_length=1, max_length=200)
    source_document_id: str = Field(min_length=1, max_length=300)
    snapshot_timestamp: AwareDatetime
    licence: LicenceRecord
    restriction_interpretation: Literal["explicit_declared_effects_only"]
    generic_event_inference: Literal["prohibited"]

    @field_validator("source_document_id")
    @classmethod
    def source_document_is_not_remote(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or value.startswith("//"):
            raise ValueError(
                "source_document_id must identify a frozen local input; remote URLs are not "
                "accepted and generic event feeds are never inferred as closures"
            )
        return value


class RoadworksFeatureCollection(RoadworksModel):
    type: Literal["FeatureCollection"]
    schema_version: Literal["1.0"]
    coordinate_crs: Literal["EPSG:4326"]
    source: RoadworksSource
    features: list[RoadworkFeature] = Field(max_length=MAX_FEATURES)

    @model_validator(mode="after")
    def work_ids_are_unique(self) -> Self:
        work_ids = [feature.id for feature in self.features]
        duplicates = sorted(work_id for work_id in set(work_ids) if work_ids.count(work_id) > 1)
        if duplicates:
            raise ValueError("duplicate stable roadwork IDs: " + ", ".join(duplicates))
        return self

    def canonical_json(self) -> str:
        """Return canonical JSON, independent of object keys and feature input order."""

        payload = self.model_dump(mode="python", exclude_none=True)
        payload["features"] = sorted(payload["features"], key=lambda feature: feature["id"])
        canonical = _canonical_value(payload)
        return json.dumps(
            canonical,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {key: _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


def parse_roadworks_geojson(
    payload: str | bytes | bytearray | dict[str, Any],
) -> RoadworksFeatureCollection:
    """Decode and validate a frozen GeoJSON interchange document without I/O."""

    if isinstance(payload, dict):
        document = payload
    else:
        try:
            document = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise RoadworksValidationError(f"roadworks input is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise RoadworksValidationError("roadworks input must be a GeoJSON FeatureCollection object")
    return RoadworksFeatureCollection.model_validate(document)


def load_roadworks_geojson(path: str | Path) -> RoadworksFeatureCollection:
    """Load one local frozen document; URLs are deliberately never dereferenced."""

    raw_path = str(path)
    parsed = urlsplit(raw_path)
    if parsed.scheme or parsed.netloc or raw_path.startswith("//"):
        raise RoadworksValidationError(
            "roadworks inputs must be frozen local files; remote URLs are not accepted"
        )
    file_path = Path(path)
    try:
        payload = file_path.read_bytes()
    except OSError as error:
        raise RoadworksValidationError(
            f"could not read frozen roadworks input {file_path}: {error}"
        ) from error
    return parse_roadworks_geojson(payload)
