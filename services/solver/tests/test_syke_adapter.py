from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from services.scenario_builder import ScenarioRecipe, SourceAcquisitionContext
from services.scenario_builder.adapters import AdapterConfigurationError
from services.scenario_builder.syke import (
    ANALYSIS_CRS,
    MAX_FEATURES_PER_LAYER,
    SEA_FLOOD_1_IN_100,
    SEA_FLOOD_1_IN_1000,
    SYKE_OUTPUT_FORMAT,
    SYKE_WFS_ENDPOINT,
    SYKE_WFS_VERSION,
    SykeArchiveError,
    SykeCoastalFloodAdapter,
    derive_wfs_url,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def recipe(*, parameters: dict | None = None) -> ScenarioRecipe:
    return ScenarioRecipe.model_validate(
        {
            "scenario_id": "otaniemi-flood-v1",
            "name": "Otaniemi coastal flood",
            "network_context_buffer_m": 750,
            "area": {
                "kind": "point_radius",
                "center": {"longitude": 24.827, "latitude": 60.185},
                "radius_m": 1_000,
            },
            "sources": [
                {"adapter_id": "osm", "role": "base_network"},
                {
                    "adapter_id": "syke",
                    "role": "flood_hazard",
                    "parameters": parameters or {},
                },
            ],
        }
    )


def context(tmp_path: Path, current_recipe: ScenarioRecipe) -> SourceAcquisitionContext:
    declaration = next(
        source for source in current_recipe.sources if source.adapter_id == "syke"
    )
    return SourceAcquisitionContext(
        recipe=current_recipe,
        declaration=declaration,
        workspace=tmp_path.resolve(),
    )


def response_for_url(
    url: str,
    *,
    reverse: bool = True,
    edition: str = "2025-11-18T00:00:00Z",
) -> bytes:
    parameters = parse_qs(urlsplit(url).query)
    layer = parameters["typeNames"][0]
    recurrence = 100 if layer == SEA_FLOOD_1_IN_100 else 1_000
    local_layer = layer.split(":", maxsplit=1)[1]
    minimum_x, minimum_y, maximum_x, maximum_y, crs = parameters["bbox"][0].split(",")
    assert crs == ANALYSIS_CRS
    x = (float(minimum_x) + float(maximum_x)) / 2
    y = (float(minimum_y) + float(maximum_y)) / 2

    def feature(number: int, offset: float) -> dict:
        return {
            "type": "Feature",
            "id": f"{local_layer}.{number}",
            "geometry_name": "geom",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [x + offset, y + offset],
                        [x + offset + 10, y + offset],
                        [x + offset + 10, y + offset + 10],
                        [x + offset, y + offset + 10],
                        [x + offset, y + offset],
                    ]
                ],
            },
            "properties": {
                "objectid": number,
                "toistuvuus": recurrence,
                "muutospvm": edition,
            },
        }

    features = [feature(2, 20), feature(1, 0)] if reverse else [feature(1, 0), feature(2, 20)]
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": features,
            "numberMatched": len(features),
            "numberReturned": len(features),
            "timeStamp": "2026-08-30T09:33:37.839Z",
            "crs": {
                "type": "name",
                "properties": {"name": "urn:ogc:def:crs:EPSG::3067"},
            },
        }
    ).encode()


def test_queries_are_fixed_bounded_and_include_network_context(tmp_path: Path) -> None:
    calls: list[tuple[str, int]] = []

    def transport(url: str, timeout_s: int) -> bytes:
        calls.append((url, timeout_s))
        return response_for_url(url)

    current_recipe = recipe(parameters={"wfs_timeout_s": 45})
    adapter = SykeCoastalFloodAdapter(refresh=True, transport=transport, clock=lambda: NOW)
    metadata = adapter.acquire(context(tmp_path, current_recipe))

    assert len(calls) == 2
    assert metadata.feature_count == 4
    assert metadata.source_timestamp == datetime(2025, 11, 18, tzinfo=UTC)
    assert metadata.query["network_context_buffer_m"] == 750
    for (url, timeout_s), expected_layer in zip(
        calls,
        (SEA_FLOOD_1_IN_100, SEA_FLOOD_1_IN_1000),
        strict=True,
    ):
        split = urlsplit(url)
        assert f"{split.scheme}://{split.netloc}{split.path}" == SYKE_WFS_ENDPOINT
        parameters = parse_qs(split.query)
        assert parameters == {
            "service": ["WFS"],
            "version": [SYKE_WFS_VERSION],
            "request": ["GetFeature"],
            "typeNames": [expected_layer],
            "outputFormat": [SYKE_OUTPUT_FORMAT],
            "srsName": [ANALYSIS_CRS],
            "bbox": [parameters["bbox"][0]],
            "count": [str(MAX_FEATURES_PER_LAYER)],
        }
        bbox_parts = parameters["bbox"][0].split(",")
        assert bbox_parts[-1] == ANALYSIS_CRS
        minimum_x, minimum_y, maximum_x, maximum_y = map(float, bbox_parts[:4])
        # A 1 km core plus 750 m context on both sides is approximately 3.5 km.
        assert 3_490 < maximum_x - minimum_x < 3_510
        assert 3_490 < maximum_y - minimum_y < 3_510
        assert timeout_s == 45

    assert metadata.query["bounded_network_context_bbox"] == [
        float(value) for value in parse_qs(urlsplit(calls[0][0]).query)["bbox"][0].split(",")[:4]
    ]
    assert [item["return_period_years"] for item in metadata.query["layers"]] == [100, 1_000]
    assert "passability_not_inferred" in metadata.query


def test_endpoint_and_layer_or_query_injection_are_not_configurable(tmp_path: Path) -> None:
    bbox = (378_000.0, 6_672_000.0, 381_000.0, 6_675_000.0)
    with pytest.raises(AdapterConfigurationError, match="only the two audited"):
        derive_wfs_url("inspire_nz:other", bbox)

    calls = 0

    def transport(url: str, timeout_s: int) -> bytes:
        nonlocal calls
        calls += 1
        return response_for_url(url)

    invalid_layer = recipe(parameters={"layers": [f"{SEA_FLOOD_1_IN_100}&CQL_FILTER=x"]})
    with pytest.raises(AdapterConfigurationError, match="unsupported SYKE layer"):
        SykeCoastalFloodAdapter(refresh=True, transport=transport).acquire(
            context(tmp_path, invalid_layer)
        )
    caller_endpoint = recipe(parameters={"endpoint": "https://example.test/wfs"})
    with pytest.raises(AdapterConfigurationError, match="unsupported syke source parameter"):
        SykeCoastalFloodAdapter(refresh=True, transport=transport).acquire(
            context(tmp_path, caller_endpoint)
        )
    assert calls == 0


def test_refresh_and_offline_replay_return_identical_metadata(tmp_path: Path) -> None:
    current_recipe = recipe()
    online = SykeCoastalFloodAdapter(
        refresh=True,
        transport=lambda url, timeout: response_for_url(url),
        clock=lambda: NOW,
    )
    online_metadata = online.acquire(context(tmp_path, current_recipe))
    frozen_bytes = {
        layer: path.read_bytes() for layer, path in online.archive_paths.items()
    }

    def should_not_fetch(url: str, timeout_s: int) -> bytes:
        raise AssertionError(f"offline acquisition fetched {url} with timeout {timeout_s}")

    offline = SykeCoastalFloodAdapter(
        refresh=False,
        transport=should_not_fetch,
        clock=lambda: NOW,
    )
    offline_metadata = offline.acquire(context(tmp_path, current_recipe))

    assert offline_metadata == online_metadata
    assert {
        layer: path.read_bytes() for layer, path in offline.archive_paths.items()
    } == frozen_bytes
    assert offline.assess_coverage(current_recipe).status == "unknown"
    assert len(offline.assess_coverage(current_recipe).evidence["validated_responses"]) == 2


def test_canonical_sort_and_gzip_are_deterministic_across_workspaces(tmp_path: Path) -> None:
    current_recipe = recipe(parameters={"layers": [SEA_FLOOD_1_IN_100]})
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()

    first = SykeCoastalFloodAdapter(
        refresh=True,
        transport=lambda url, timeout: response_for_url(url, reverse=True),
        clock=lambda: NOW,
    )
    second = SykeCoastalFloodAdapter(
        refresh=True,
        transport=lambda url, timeout: response_for_url(url, reverse=False),
        clock=lambda: NOW,
    )
    first.acquire(context(first_root, current_recipe))
    second.acquire(context(second_root, current_recipe))

    first_payload = next(iter(first.archive_paths.values())).read_bytes()
    second_payload = next(iter(second.archive_paths.values())).read_bytes()
    assert first_payload == second_payload
    document = json.loads(gzip.decompress(first_payload))
    assert [feature["id"].rsplit(".", maxsplit=1)[1] for feature in document["features"]] == [
        "1",
        "2",
    ]
    # Deterministic gzip writes an all-zero MTIME header.
    assert first_payload[4:8] == b"\x00\x00\x00\x00"


def test_identical_refresh_preserves_first_acquisition_provenance(tmp_path: Path) -> None:
    current_recipe = recipe(parameters={"layers": [SEA_FLOOD_1_IN_100]})
    first = SykeCoastalFloodAdapter(
        refresh=True,
        transport=lambda url, timeout: response_for_url(url),
        clock=lambda: NOW,
    )
    first_metadata = first.acquire(context(tmp_path, current_recipe))
    pointer = tmp_path / "otaniemi-flood-v1.syke-coastal-flood.archive.json"
    first_pointer_bytes = pointer.read_bytes()

    second = SykeCoastalFloodAdapter(
        refresh=True,
        transport=lambda url, timeout: response_for_url(url),
        clock=lambda: NOW + timedelta(days=7),
    )
    second_metadata = second.acquire(context(tmp_path, current_recipe))

    assert pointer.read_bytes() == first_pointer_bytes
    assert second_metadata == first_metadata
    assert second_metadata.acquired_at == NOW


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda document: document.update(type="Feature"), "FeatureCollection"),
        (
            lambda document: document["crs"]["properties"].update(name="EPSG:4326"),
            "expected an advertised EPSG:3067",
        ),
        (
            lambda document: document["features"][0]["properties"].update(toistuvuus=50),
            "expected 100",
        ),
        (
            lambda document: document["features"][0]["geometry"]["coordinates"][0][0].__setitem__(
                0, float("nan")
            ),
            "non-finite",
        ),
    ],
)
def test_malformed_or_semantically_wrong_response_is_rejected(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    current_recipe = recipe(parameters={"layers": [SEA_FLOOD_1_IN_100]})

    def malformed(url: str, timeout_s: int) -> bytes:
        document = json.loads(response_for_url(url))
        mutation(document)
        return json.dumps(document).encode()

    with pytest.raises(SykeArchiveError, match=message):
        SykeCoastalFloodAdapter(
            refresh=True,
            transport=malformed,
            clock=lambda: NOW,
        ).acquire(context(tmp_path, current_recipe))


def test_archive_tampering_is_detected_before_offline_replay(tmp_path: Path) -> None:
    current_recipe = recipe(parameters={"layers": [SEA_FLOOD_1_IN_100]})
    online = SykeCoastalFloodAdapter(
        refresh=True,
        transport=lambda url, timeout: response_for_url(url),
        clock=lambda: NOW,
    )
    online.acquire(context(tmp_path, current_recipe))
    archive_path = next(iter(online.archive_paths.values()))
    archive_path.write_bytes(archive_path.read_bytes() + b"tampered")

    with pytest.raises(SykeArchiveError, match="checksum"):
        SykeCoastalFloodAdapter(refresh=False).acquire(context(tmp_path, current_recipe))


def test_date_only_source_edition_is_preserved_without_false_timestamp(tmp_path: Path) -> None:
    current_recipe = recipe(parameters={"layers": [SEA_FLOOD_1_IN_100]})
    adapter = SykeCoastalFloodAdapter(
        refresh=True,
        transport=lambda url, timeout: response_for_url(url, edition="2025-11-18"),
        clock=lambda: NOW,
    )
    metadata = adapter.acquire(context(tmp_path, current_recipe))

    assert metadata.query["layers"][0]["edition_values"] == ["2025-11-18"]
    assert metadata.source_timestamp is None


def test_duplicate_feature_ids_and_truncated_response_are_rejected(tmp_path: Path) -> None:
    current_recipe = recipe(parameters={"layers": [SEA_FLOOD_1_IN_100]})

    def duplicate(url: str, timeout_s: int) -> bytes:
        document = json.loads(response_for_url(url))
        document["features"][1]["id"] = document["features"][0]["id"]
        return json.dumps(document).encode()

    with pytest.raises(SykeArchiveError, match="duplicate feature ID"):
        SykeCoastalFloodAdapter(
            refresh=True,
            transport=duplicate,
            clock=lambda: NOW,
        ).acquire(context(tmp_path, current_recipe))

    def truncated(url: str, timeout_s: int) -> bytes:
        document = json.loads(response_for_url(url))
        document["numberMatched"] = 3
        return json.dumps(document).encode()

    with pytest.raises(SykeArchiveError, match="truncated"):
        SykeCoastalFloodAdapter(
            refresh=True,
            transport=truncated,
            clock=lambda: NOW,
        ).acquire(context(tmp_path, current_recipe))


def test_null_source_boundary_attributes_are_preserved(tmp_path: Path) -> None:
    current_recipe = recipe(parameters={"layers": [SEA_FLOOD_1_IN_100]})

    def source_boundary_feature(url: str, timeout_s: int) -> bytes:
        document = json.loads(response_for_url(url))
        document["features"][0]["properties"]["toistuvuus"] = None
        document["features"][0]["properties"]["muutospvm"] = None
        return json.dumps(document).encode()

    adapter = SykeCoastalFloodAdapter(
        refresh=True,
        transport=source_boundary_feature,
        clock=lambda: NOW,
    )
    metadata = adapter.acquire(context(tmp_path, current_recipe))

    assert metadata.feature_count == 2
    assert metadata.source_timestamp == datetime(2025, 11, 18, tzinfo=UTC)
