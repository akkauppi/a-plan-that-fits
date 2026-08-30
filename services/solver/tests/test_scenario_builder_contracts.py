from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from services.scenario_builder import (
    AdapterConfigurationError,
    AdapterRegistry,
    ArtifactDigest,
    CoverageAssessment,
    LicenceRecord,
    ScenarioRecipe,
    ScenarioSnapshotMetadata,
    SourceAcquisitionContext,
    SourceDeclaration,
    SourceSnapshotMetadata,
)

NOW = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)
ZERO_SHA = "0" * 64
ONE_SHA = "1" * 64


def point_recipe(**overrides) -> ScenarioRecipe:
    payload = {
        "scenario_id": "otaniemi-access-v1",
        "name": "Otaniemi resilient access",
        "area": {
            "kind": "point_radius",
            "center": {"longitude": 24.827, "latitude": 60.185},
            "radius_m": 2_000,
        },
        "sources": [
            {"adapter_id": "osm", "role": "base_network"},
            {"adapter_id": "mml-elevation", "role": "elevation"},
        ],
    }
    payload.update(overrides)
    return ScenarioRecipe.model_validate(payload)


def polygon_recipe(**overrides) -> ScenarioRecipe:
    payload = {
        "scenario_id": "otaniemi-polygon-v1",
        "name": "Otaniemi polygon",
        "area": {
            "kind": "polygon",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [24.80, 60.17],
                        [24.86, 60.17],
                        [24.86, 60.20],
                        [24.80, 60.20],
                        [24.80, 60.17],
                    ]
                ],
            },
        },
        "sources": [{"adapter_id": "osm", "role": "base_network"}],
    }
    payload.update(overrides)
    return ScenarioRecipe.model_validate(payload)


def source_snapshot(adapter_id: str = "osm") -> SourceSnapshotMetadata:
    return SourceSnapshotMetadata(
        adapter_id=adapter_id,
        source_name="OpenStreetMap",
        endpoint="https://overpass-api.de/api/interpreter",
        acquired_at=NOW,
        source_timestamp=NOW,
        query={"bbox": [24.80, 60.17, 24.86, 60.20]},
        source_crs="EPSG:4326",
        feature_count=42,
        licence=LicenceRecord(
            name="Open Data Commons Open Database License",
            url="https://www.openstreetmap.org/copyright",
            attribution="© OpenStreetMap contributors",
        ),
        artifacts=[
            ArtifactDigest(
                path=f"raw/{adapter_id}.json.gz",
                sha256=ZERO_SHA,
                byte_size=123,
                media_type="application/gzip",
            )
        ],
    )


def snapshot_for(recipe: ScenarioRecipe, sources=None) -> ScenarioSnapshotMetadata:
    return ScenarioSnapshotMetadata(
        snapshot_id="otaniemi-snapshot-v1",
        scenario_id=recipe.scenario_id,
        recipe_sha256=recipe.sha256(),
        created_at=NOW,
        sources=sources or [source_snapshot()],
        field_lineage_artifact=ArtifactDigest(
            path="provenance/field-lineage.jsonl", sha256=ZERO_SHA, byte_size=789
        ),
        derived_artifacts=[
            ArtifactDigest(
                path="derived/network.json", sha256=ONE_SHA, byte_size=456
            )
        ],
    )


def error_text(error: ValidationError) -> str:
    return "\n".join(issue["msg"] for issue in error.errors())


def test_point_radius_recipe_is_versioned_strict_and_deterministic() -> None:
    recipe = point_recipe()
    reordered = point_recipe(
        sources=[
            {
                "role": "base_network",
                "adapter_id": "osm",
            },
            {
                "role": "elevation",
                "adapter_id": "mml-elevation",
            },
        ]
    )

    assert recipe.schema_version == "1.0"
    assert recipe.profile_id == "finland-resilient-access-v1"
    assert recipe.analysis_crs == "EPSG:3067"
    assert recipe.area.coordinate_crs == "EPSG:4326"
    assert recipe.sha256() == reordered.sha256()
    assert len(recipe.sha256()) == 64

    with pytest.raises(ValidationError) as error:
        point_recipe(unrecognised_setting=True)
    assert "Extra inputs are not permitted" in error_text(error.value)

    with pytest.raises(ValidationError) as version_error:
        point_recipe(schema_version="2.0")
    assert "Input should be '1.0'" in error_text(version_error.value)


def test_recipe_rejects_non_finland_location_and_non_tm35fin_analysis() -> None:
    with pytest.raises(ValidationError) as location_error:
        point_recipe(
            area={
                "kind": "point_radius",
                "center": {"longitude": -0.13, "latitude": 51.51},
                "radius_m": 2_000,
            }
        )
    assert "outside the Finland v1 build envelope" in error_text(location_error.value)

    with pytest.raises(ValidationError) as crs_error:
        point_recipe(analysis_crs="EPSG:4326")
    assert "Input should be 'EPSG:3067'" in error_text(crs_error.value)


@pytest.mark.parametrize("radius", [99, 2_501])
def test_point_radius_area_is_bounded(radius: float) -> None:
    with pytest.raises(ValidationError):
        point_recipe(
            area={
                "kind": "point_radius",
                "center": {"longitude": 24.827, "latitude": 60.185},
                "radius_m": radius,
            }
        )


def test_point_radius_area_cannot_cross_the_finland_build_envelope() -> None:
    with pytest.raises(ValidationError) as error:
        point_recipe(
            area={
                "kind": "point_radius",
                "center": {"longitude": 19.001, "latitude": 60.1},
                "radius_m": 1_000,
            }
        )
    assert "crosses outside the Finland v1 build envelope" in error_text(error.value)


def test_polygon_recipe_accepts_small_closed_finland_polygon() -> None:
    recipe = polygon_recipe()
    assert recipe.area.kind == "polygon"
    assert recipe.area.geometry.coordinates[0][0] == (24.80, 60.17)


def test_polygon_recipe_rejects_unclosed_outside_and_oversized_geometry() -> None:
    unclosed = [[24.80, 60.17], [24.86, 60.17], [24.86, 60.20], [24.80, 60.20]]
    with pytest.raises(ValidationError) as closure_error:
        polygon_recipe(
            area={
                "kind": "polygon",
                "geometry": {"type": "Polygon", "coordinates": [unclosed]},
            }
        )
    assert "is not closed" in error_text(closure_error.value)

    outside = [[18.0, 60.0], [18.1, 60.0], [18.1, 60.1], [18.0, 60.0]]
    with pytest.raises(ValidationError) as outside_error:
        polygon_recipe(
            area={
                "kind": "polygon",
                "geometry": {"type": "Polygon", "coordinates": [outside]},
            }
        )
    assert "outside the Finland v1 build envelope" in error_text(outside_error.value)

    oversized = [[24.0, 60.0], [24.3, 60.0], [24.3, 60.2], [24.0, 60.2], [24.0, 60.0]]
    with pytest.raises(ValidationError) as size_error:
        polygon_recipe(
            area={
                "kind": "polygon",
                "geometry": {"type": "Polygon", "coordinates": [oversized]},
            }
        )
    assert "v1 limit" in error_text(size_error.value)


def test_polygon_recipe_rejects_self_intersecting_ring() -> None:
    bow_tie = [
        [24.80, 60.17],
        [24.86, 60.20],
        [24.80, 60.20],
        [24.85, 60.17],
        [24.80, 60.17],
    ]
    with pytest.raises(ValidationError) as error:
        polygon_recipe(
            area={
                "kind": "polygon",
                "geometry": {"type": "Polygon", "coordinates": [bow_tie]},
            }
        )
    assert "self-intersecting" in error_text(error.value)


def test_polygon_recipe_rejects_holes_in_v1_profile() -> None:
    exterior = [
        [24.80, 60.17],
        [24.86, 60.17],
        [24.86, 60.20],
        [24.80, 60.20],
        [24.80, 60.17],
    ]
    hole = [
        [24.81, 60.18],
        [24.82, 60.18],
        [24.82, 60.19],
        [24.81, 60.18],
    ]
    with pytest.raises(ValidationError) as error:
        polygon_recipe(
            area={
                "kind": "polygon",
                "geometry": {"type": "Polygon", "coordinates": [exterior, hole]},
            }
        )
    assert "polygon holes are not supported" in error_text(error.value)


def test_source_declarations_are_required_unique_and_json_serializable() -> None:
    with pytest.raises(ValidationError) as duplicate_error:
        point_recipe(
            sources=[
                {"adapter_id": "osm", "role": "base_network"},
                {"adapter_id": "osm", "role": "municipal_context"},
            ]
        )
    assert "duplicate adapter IDs: osm" in error_text(duplicate_error.value)

    with pytest.raises(ValidationError) as base_error:
        point_recipe(sources=[{"adapter_id": "mml", "role": "elevation"}])
    assert "required base_network" in error_text(base_error.value)

    with pytest.raises(ValidationError) as json_error:
        point_recipe(
            sources=[
                {
                    "adapter_id": "osm",
                    "role": "base_network",
                    "parameters": {"invalid": float("nan")},
                }
            ]
        )
    assert "finite JSON values" in error_text(json_error.value)


def test_snapshot_metadata_requires_offsets_digests_and_unique_sources() -> None:
    recipe = polygon_recipe()
    valid = snapshot_for(recipe)
    valid.validate_against(recipe)
    assert valid.field_lineage_artifact.path == "provenance/field-lineage.jsonl"

    with pytest.raises(ValidationError) as timestamp_error:
        SourceSnapshotMetadata(
            **source_snapshot().model_dump(exclude={"acquired_at"}),
            acquired_at=datetime(2026, 8, 30),
        )
    assert "timezone" in error_text(timestamp_error.value).lower()

    with pytest.raises(ValidationError) as digest_error:
        ArtifactDigest(path="raw/source.json", sha256="not-a-digest", byte_size=1)
    assert "string_pattern_mismatch" in str(digest_error.value)

    with pytest.raises(ValidationError) as duplicate_error:
        snapshot_for(recipe, sources=[source_snapshot(), source_snapshot()])
    assert "duplicate adapter IDs: osm" in error_text(duplicate_error.value)


def test_snapshot_metadata_validates_recipe_identity_and_required_sources() -> None:
    recipe = point_recipe()
    incomplete = snapshot_for(recipe)
    with pytest.raises(ValueError) as missing_error:
        incomplete.validate_against(recipe)
    assert "missing required source adapters: mml-elevation" in str(missing_error.value)

    complete = snapshot_for(recipe, [source_snapshot(), source_snapshot("mml-elevation")])
    complete.validate_against(recipe)

    changed_recipe = point_recipe(name="Changed recipe")
    with pytest.raises(ValueError) as digest_error:
        complete.validate_against(changed_recipe)
    assert "recipe_sha256" in str(digest_error.value)


class FakeAdapter:
    def __init__(self, adapter_id: str) -> None:
        self.adapter_id = adapter_id

    def assess_coverage(self, recipe: ScenarioRecipe) -> CoverageAssessment:
        return CoverageAssessment(
            adapter_id=self.adapter_id,
            status="full",
            message=f"Coverage confirmed for {recipe.scenario_id}",
            checked_at=NOW,
        )

    def acquire(self, context: SourceAcquisitionContext) -> SourceSnapshotMetadata:
        return source_snapshot(context.declaration.adapter_id)


def test_adapter_registry_rejects_duplicate_and_missing_adapter_ids() -> None:
    with pytest.raises(AdapterConfigurationError, match="duplicate source adapter ID 'osm'"):
        AdapterRegistry([FakeAdapter("osm"), FakeAdapter("osm")])

    with pytest.raises(AdapterConfigurationError, match="invalid source adapter ID 'OSM live'"):
        AdapterRegistry([FakeAdapter("OSM live")])

    recipe = point_recipe()
    registry = AdapterRegistry([FakeAdapter("osm")])
    with pytest.raises(
        AdapterConfigurationError,
        match="no registered source adapter.*mml-elevation",
    ):
        registry.resolve(recipe)


def test_adapter_registry_preserves_recipe_order_and_context_is_scoped(tmp_path: Path) -> None:
    recipe = point_recipe()
    registry = AdapterRegistry([FakeAdapter("mml-elevation"), FakeAdapter("osm")])
    adapters = registry.resolve(recipe)
    assert [adapter.adapter_id for adapter in adapters] == ["osm", "mml-elevation"]

    context = SourceAcquisitionContext(
        recipe=recipe,
        declaration=recipe.sources[0],
        workspace=tmp_path.resolve(),
    )
    assert context.workspace.is_absolute()

    unrelated = SourceDeclaration(adapter_id="syke", role="flood_hazard")
    with pytest.raises(ValueError, match="is not part of recipe"):
        SourceAcquisitionContext(recipe=recipe, declaration=unrelated, workspace=tmp_path.resolve())
