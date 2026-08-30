from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from services.scenario_builder import (
    RoadworksFeatureCollection,
    RoadworksValidationError,
    load_roadworks_geojson,
    parse_roadworks_geojson,
)


def fixed_feature(
    work_id: str = "work-001",
    geometry: dict | None = None,
) -> dict:
    return {
        "type": "Feature",
        "id": work_id,
        "geometry": geometry
        or {
            "type": "LineString",
            "coordinates": [[24.823, 60.183], [24.825, 60.184]],
        },
        "properties": {
            "source_feature_ids": [f"espoo:{work_id}"],
            "affected_modes": ["private_car", "service"],
            "effect": "closed",
            "direction": "both",
            "restriction_basis": "explicit_source_declaration",
            "schedule": {
                "kind": "fixed",
                "start": "2026-10-02T07:00:00+03:00",
                "end": "2026-10-02T19:00:00+03:00",
            },
            "label": "Explicitly declared test closure",
        },
    }


def flexible_feature(work_id: str = "work-002") -> dict:
    return {
        "type": "Feature",
        "id": work_id,
        "geometry": {
            "type": "MultiLineString",
            "coordinates": [
                [[24.827, 60.182], [24.829, 60.183]],
                [[24.829, 60.183], [24.831, 60.184]],
            ],
        },
        "properties": {
            "source_feature_ids": [f"permit:{work_id}", f"segment:{work_id}"],
            "affected_modes": ["cycling", "walking"],
            "effect": "restricted",
            "direction": "both",
            "restriction_description": "One side remains passable under site control.",
            "restriction_basis": "explicit_source_declaration",
            "schedule": {
                "kind": "flexible",
                "earliest_start": "2026-11-01T00:00:00+02:00",
                "latest_end": "2026-11-05T00:00:00+02:00",
                "duration_minutes": 1_440,
            },
        },
    }


def roadworks_document(features: list[dict] | None = None) -> dict:
    return {
        "type": "FeatureCollection",
        "schema_version": "1.0",
        "coordinate_crs": "EPSG:4326",
        "source": {
            "name": "Frozen user-supplied planned street works",
            "source_document_id": "otaniemi-roadworks-2026-08-30.geojson",
            "snapshot_timestamp": "2026-08-30T12:00:00+03:00",
            "licence": {
                "name": "CC BY 4.0",
                "url": "https://creativecommons.org/licenses/by/4.0/",
                "attribution": "Example input prepared for Four Planters",
            },
            "restriction_interpretation": "explicit_declared_effects_only",
            "generic_event_inference": "prohibited",
        },
        "features": features if features is not None else [fixed_feature()],
    }


def test_valid_fixed_roadwork_is_parsed_with_explicit_semantics() -> None:
    document = parse_roadworks_geojson(roadworks_document())

    feature = document.features[0]
    assert feature.id == "work-001"
    assert feature.properties.schedule.kind == "fixed"
    assert feature.properties.affected_modes == ["private_car", "service"]
    assert document.source.generic_event_inference == "prohibited"
    assert document.source.restriction_interpretation == "explicit_declared_effects_only"


def test_schema_version_must_be_explicit() -> None:
    payload = roadworks_document()
    payload.pop("schema_version")

    with pytest.raises(ValidationError, match="schema_version"):
        parse_roadworks_geojson(payload)


def test_valid_flexible_roadwork_requires_a_duration_that_fits_its_window() -> None:
    document = RoadworksFeatureCollection.model_validate(roadworks_document([flexible_feature()]))

    schedule = document.features[0].properties.schedule
    assert schedule.kind == "flexible"
    assert schedule.duration_minutes == 1_440


def test_valid_polygon_geometry_is_accepted() -> None:
    polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [24.823, 60.183],
                [24.826, 60.183],
                [24.826, 60.185],
                [24.823, 60.185],
                [24.823, 60.183],
            ]
        ],
    }

    document = parse_roadworks_geojson(roadworks_document([fixed_feature(geometry=polygon)]))

    assert document.features[0].geometry.type == "Polygon"


def test_direction_can_follow_a_single_linestring_orientation() -> None:
    feature = fixed_feature()
    feature["properties"]["direction"] = "against_geometry"

    document = parse_roadworks_geojson(roadworks_document([feature]))

    assert document.features[0].properties.direction == "against_geometry"


@pytest.mark.parametrize("feature", [flexible_feature(), fixed_feature()])
def test_directional_effects_reject_ambiguous_multipart_or_area_geometry(feature: dict) -> None:
    feature = deepcopy(feature)
    if feature["geometry"]["type"] == "LineString":
        feature["geometry"] = {
            "type": "Polygon",
            "coordinates": [
                [
                    [24.823, 60.183],
                    [24.826, 60.183],
                    [24.826, 60.185],
                    [24.823, 60.185],
                    [24.823, 60.183],
                ]
            ],
        }
    feature["properties"]["direction"] = "along_geometry"

    with pytest.raises(ValidationError, match="must use direction='both'"):
        parse_roadworks_geojson(roadworks_document([feature]))


@pytest.mark.parametrize(
    ("schedule", "message"),
    [
        (
            {
                "kind": "fixed",
                "start": "2026-10-02T19:00:00+03:00",
                "end": "2026-10-02T19:00:00+03:00",
            },
            "end must be later than start",
        ),
        (
            {
                "kind": "fixed",
                "start": "2026-10-02T07:00:00",
                "end": "2026-10-02T19:00:00+03:00",
            },
            "timezone",
        ),
        (
            {
                "kind": "flexible",
                "earliest_start": "2026-11-01T00:00:00+02:00",
                "latest_end": "2026-11-01T12:00:00+02:00",
                "duration_minutes": 1_440,
            },
            "duration does not fit",
        ),
    ],
)
def test_invalid_temporal_semantics_are_rejected(schedule: dict, message: str) -> None:
    payload = roadworks_document()
    payload["features"][0]["properties"]["schedule"] = schedule

    with pytest.raises(ValidationError, match=message):
        RoadworksFeatureCollection.model_validate(payload)


@pytest.mark.parametrize(
    "geometry",
    [
        {
            "type": "LineString",
            "coordinates": [[24.823, 60.183]],
        },
        {
            "type": "LineString",
            "coordinates": [[24.823, 60.183], [40.0, 60.184]],
        },
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [24.823, 60.183],
                    [24.826, 60.185],
                    [24.826, 60.183],
                    [24.823, 60.185],
                    [24.823, 60.183],
                ]
            ],
        },
    ],
)
def test_invalid_or_unbounded_geometry_is_rejected(geometry: dict) -> None:
    with pytest.raises(ValidationError):
        RoadworksFeatureCollection.model_validate(
            roadworks_document([fixed_feature(geometry=geometry)])
        )


def test_duplicate_stable_work_ids_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate stable roadwork IDs"):
        RoadworksFeatureCollection.model_validate(
            roadworks_document([fixed_feature("same-id"), flexible_feature("same-id")])
        )


@pytest.mark.parametrize("modes", [[], ["hovercraft"], ["walking", "walking"]])
def test_empty_unknown_or_duplicate_affected_modes_are_rejected(modes: list[str]) -> None:
    payload = roadworks_document()
    payload["features"][0]["properties"]["affected_modes"] = modes

    with pytest.raises(ValidationError):
        RoadworksFeatureCollection.model_validate(payload)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.update({"unexpected": True}),
        lambda payload: payload["features"][0]["properties"].update({"inferred_from_event": True}),
    ],
)
def test_unsupported_document_and_feature_properties_are_rejected(mutator) -> None:
    payload = roadworks_document()
    mutator(payload)

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RoadworksFeatureCollection.model_validate(payload)


def test_generic_events_cannot_be_silently_promoted_to_closures() -> None:
    payload = roadworks_document()
    payload["source"]["generic_event_inference"] = "allowed"
    payload["features"][0]["properties"].pop("restriction_basis")

    with pytest.raises(ValidationError):
        RoadworksFeatureCollection.model_validate(payload)


def test_remote_source_references_and_remote_loads_are_rejected() -> None:
    payload = roadworks_document()
    payload["source"]["source_document_id"] = "https://example.test/events.geojson"

    with pytest.raises(ValidationError, match="remote URLs are not accepted"):
        RoadworksFeatureCollection.model_validate(payload)
    with pytest.raises(RoadworksValidationError, match="remote URLs are not accepted"):
        load_roadworks_geojson("https://example.test/events.geojson")


def test_local_frozen_geojson_can_be_loaded(tmp_path: Path) -> None:
    source_path = tmp_path / "roadworks.geojson"
    source_path.write_text(json.dumps(roadworks_document()), encoding="utf-8")

    document = load_roadworks_geojson(source_path)

    assert document.features[0].id == "work-001"


def test_canonical_hash_is_independent_of_keys_feature_order_and_datetime_offset() -> None:
    first = roadworks_document([fixed_feature(), flexible_feature()])
    second = deepcopy(first)
    second["features"].reverse()
    second["features"][1]["properties"]["affected_modes"].reverse()
    second["features"][0]["properties"]["source_feature_ids"].reverse()
    second["source"]["snapshot_timestamp"] = "2026-08-30T09:00:00Z"

    first_document = RoadworksFeatureCollection.model_validate(first)
    second_document = RoadworksFeatureCollection.model_validate(second)

    assert first_document.canonical_json() == second_document.canonical_json()
    assert first_document.sha256() == second_document.sha256()
    assert len(first_document.sha256()) == 64
