from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from services.scenario_builder.adapters import (
    AdapterConfigurationError,
    SourceAcquisitionContext,
    source_adapter_workspace,
)
from services.scenario_builder.base_network import (
    BASE_NETWORK_BUILDER_VERSION,
    BaseNetworkBuildError,
    _base_permissions,
    build_base_network_snapshot,
    validate_base_network_snapshot,
    validate_latest_base_network,
)
from services.scenario_builder.models import ScenarioRecipe
from services.scenario_builder.osm import (
    OVERPASS_ADAPTER_VERSION,
    OVERPASS_ENDPOINT,
    OsmArchiveError,
    OsmOverpassAdapter,
    canonicalize_area,
    canonicalize_network_context,
    derive_overpass_query,
)
from services.scenario_builder.source_bundle import (
    SourceBundleAdapterRegistry,
    acquire_source_bundle,
)

NOW = datetime(2026, 8, 30, 10, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (
            {"highway": "corridor", "access": "permissive"},
            {"private_car": False, "walking": True, "cycling": False},
        ),
        (
            {"highway": "steps", "access": "yes"},
            {"private_car": False, "walking": True, "cycling": False},
        ),
        (
            {"highway": "footway", "access": "destination"},
            {"private_car": False, "walking": True, "cycling": False},
        ),
        (
            {"highway": "footway", "access": "no", "motor_vehicle": "destination"},
            {"private_car": True, "walking": False, "cycling": False},
        ),
        (
            {"highway": "footway", "bicycle": "designated"},
            {"private_car": False, "walking": True, "cycling": True},
        ),
        (
            {"highway": "motorway", "access": "yes", "foot": "yes"},
            {"private_car": True, "walking": True, "cycling": False},
        ),
    ],
)
def test_generic_access_cannot_promote_an_inappropriate_highway_mode(
    tags: dict[str, str], expected: dict[str, bool]
) -> None:
    assert _base_permissions(tags) == expected


def recipe_payload(**overrides) -> dict:
    payload = {
        "schema_version": "1.0",
        "scenario_id": "synthetic-otaniemi-base",
        "name": "Synthetic Otaniemi base-network fixture",
        "scenario_type": "resilient_access",
        "analysis_crs": "EPSG:3067",
        "network_context_buffer_m": 100,
        "area": {
            "kind": "polygon",
            "coordinate_crs": "EPSG:4326",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [24.8200, 60.1800],
                        [24.8220, 60.1800],
                        [24.8220, 60.1820],
                        [24.8200, 60.1820],
                        [24.8200, 60.1800],
                    ]
                ],
            },
        },
        "sources": [
            {
                "adapter_id": "osm",
                "role": "base_network",
                "required": True,
                "parameters": {"overpass_timeout_s": 45},
            }
        ],
    }
    payload.update(overrides)
    return payload


def recipe(**overrides) -> ScenarioRecipe:
    return ScenarioRecipe.model_validate(recipe_payload(**overrides))


def synthetic_overpass(
    *,
    missing_node: bool = False,
    empty: bool = False,
    remark: str | None = None,
    timestamp: bool = True,
) -> bytes:
    elements = [
        {"type": "node", "id": 1, "lon": 24.8190, "lat": 60.1810},
        {"type": "node", "id": 2, "lon": 24.8210, "lat": 60.1810},
        {"type": "node", "id": 3, "lon": 24.8230, "lat": 60.1810},
        {"type": "node", "id": 4, "lon": 24.8210, "lat": 60.1825},
        {"type": "node", "id": 5, "lon": 24.8215, "lat": 60.1815},
        {"type": "node", "id": 6, "lon": 24.8260, "lat": 60.1810},
        {
            "type": "way",
            "id": 10,
            "nodes": [1, 2, 3],
            "tags": {"highway": "residential", "name": "One-way street", "oneway": "yes"},
        },
        {
            "type": "way",
            "id": 20,
            "nodes": [2, 4],
            "tags": {"highway": "footway", "name": "Walking path"},
        },
        {
            "type": "way",
            "id": 30,
            "nodes": [2, 5],
            "tags": {"highway": "cycleway", "name": "Cycle path"},
        },
        {
            "type": "way",
            "id": 40,
            "nodes": [3, 6],
            "tags": {
                "highway": "residential",
                "name": "Context crossing",
                "bridge": "yes",
                "tunnel": "no",
                "layer": "1",
                "covered": "no",
                "ford": "no",
            },
        },
        {
            "type": "way",
            "id": 50,
            "nodes": [5, 4],
            "tags": {
                "highway": "residential",
                "name": "Car-free link",
                "motor_vehicle": "no",
            },
        },
    ]
    if missing_node:
        elements = [element for element in elements if element.get("id") != 6]
    if empty:
        elements = []
    document = {
        "version": 0.6,
        "generator": "synthetic test",
        "osm3s": {"timestamp_osm_base": "2026-08-29T12:00:00Z"} if timestamp else {},
        "elements": elements,
    }
    if remark is not None:
        document["remark"] = remark
    return json.dumps(document).encode()


def load_network(snapshot_dir: Path) -> dict:
    return json.loads((snapshot_dir / "base-network.json").read_text(encoding="utf-8"))


def rewrite_tracked_json(snapshot_dir: Path, relative_path: str, document: dict) -> None:
    payload = (
        json.dumps(
            document, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
        )
        + "\n"
    ).encode("utf-8")
    (snapshot_dir / relative_path).write_bytes(payload)
    metadata_path = snapshot_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    artifact = next(
        artifact for artifact in metadata["derived_artifacts"] if artifact["path"] == relative_path
    )
    artifact["sha256"] = hashlib.sha256(payload).hexdigest()
    artifact["byte_size"] = len(payload)
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")


def rewrite_lineage(snapshot_dir: Path, payload: bytes) -> None:
    metadata_path = snapshot_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    artifact = metadata["field_lineage_artifact"]
    (snapshot_dir / artifact["path"]).write_bytes(payload)
    artifact["sha256"] = hashlib.sha256(payload).hexdigest()
    artifact["byte_size"] = len(payload)
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")


def test_recipe_drives_canonical_core_buffered_context_and_bounded_query() -> None:
    current = recipe()
    core = canonicalize_area(current)
    context = canonicalize_network_context(current, core)
    query = derive_overpass_query(context, 45)

    assert current.network_context_buffer_m == 100
    assert context.analysis.contains(core.analysis)
    assert context.analysis.area > core.analysis.area
    assert "[timeout:45]" in query
    assert 'way["highway"](poly:' in query
    assert OVERPASS_ENDPOINT not in query
    assert "http" not in query
    assert len(query) < 40_000


def test_point_radius_recipe_is_canonicalized_with_default_750m_context() -> None:
    current = ScenarioRecipe.model_validate(
        {
            "scenario_id": "otaniemi-point-base",
            "name": "Otaniemi point recipe",
            "area": {
                "kind": "point_radius",
                "center": {"longitude": 24.827, "latitude": 60.185},
                "radius_m": 500,
            },
            "sources": [{"adapter_id": "osm", "role": "base_network"}],
        }
    )
    core = canonicalize_area(current)
    context = canonicalize_network_context(current, core)

    assert current.network_context_buffer_m == 750
    assert 770_000 < core.analysis.area < 800_000
    assert context.analysis.area > 4_800_000
    assert core.wgs84.within(context.wgs84)


def test_refresh_then_offline_rebuild_is_reproducible_and_mode_explicit(
    tmp_path: Path,
) -> None:
    current = recipe()
    source_dir = tmp_path / "source"
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"
    calls: list[tuple[str, int]] = []

    def transport(query: str, timeout_s: int) -> bytes:
        calls.append((query, timeout_s))
        return synthetic_overpass()

    first = build_base_network_snapshot(
        current,
        source_dir=source_dir,
        output_dir=first_output,
        refresh=True,
        transport=transport,
        clock=lambda: NOW,
    )
    assert len(calls) == 1
    assert calls[0][1] == 45
    assert OVERPASS_ENDPOINT not in calls[0][0]

    source_workspace = source_adapter_workspace(source_dir, current, current.sources[0])
    original_pointer = next(source_workspace.glob("*.archive.json")).read_bytes()
    original_files = {
        path.relative_to(first.snapshot_dir): path.read_bytes()
        for path in first.snapshot_dir.rglob("*")
        if path.is_file()
    }
    repeated = build_base_network_snapshot(
        current,
        source_dir=source_dir,
        output_dir=first_output,
        refresh=True,
        transport=transport,
        clock=lambda: NOW + timedelta(days=1),
    )
    assert len(calls) == 2
    assert repeated.snapshot_id == first.snapshot_id
    assert next(source_workspace.glob("*.archive.json")).read_bytes() == original_pointer
    assert {
        path.relative_to(first.snapshot_dir): path.read_bytes()
        for path in first.snapshot_dir.rglob("*")
        if path.is_file()
    } == original_files
    assert [path.name for path in (first_output / "snapshots").iterdir()] == [first.snapshot_id]

    second = build_base_network_snapshot(
        current,
        source_dir=source_dir,
        output_dir=second_output,
        refresh=False,
        transport=lambda *_: pytest.fail("offline rebuild must not use the transport"),
    )
    assert second.snapshot_id == first.snapshot_id
    assert validate_latest_base_network(first_output, current) == first.snapshot_dir
    assert validate_latest_base_network(second_output, current) == second.snapshot_dir

    first_files = {
        path.relative_to(first.snapshot_dir): path.read_bytes()
        for path in first.snapshot_dir.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second.snapshot_dir): path.read_bytes()
        for path in second.snapshot_dir.rglob("*")
        if path.is_file()
    }
    assert second_files == first_files

    network = load_network(first.snapshot_dir)
    assert network["scope"] == "base_network_only"
    assert network["builder_version"] == BASE_NETWORK_BUILDER_VERSION
    assert network["network_context_buffer_m"] == 100
    assert network["capabilities"]["available"] == ["base_network"]
    assert "flood_hazard" in network["capabilities"]["not_built"]
    assert network["counts"]["nodes"] > 0
    assert network["counts"]["directed_edges"] > 0
    assert 0 < network["counts"]["physical_segments"] < network["counts"]["directed_edges"]
    assert {node["id"] for node in network["nodes"]} == {
        node_id for edge in network["edges"] for node_id in (edge["from"], edge["to"])
    }
    assert any(node["id"].startswith("osm-boundary-") for node in network["nodes"])

    browser = json.loads((first.snapshot_dir / "base-network.geojson").read_text(encoding="utf-8"))
    segment_features = [
        feature
        for feature in browser["features"]
        if feature["properties"]["layer"] == "base_network"
    ]
    assert len(segment_features) == network["counts"]["physical_segments"]
    assert len(
        {feature["properties"]["physical_segment_id"] for feature in segment_features}
    ) == len(segment_features)
    browser_edge_ids = [
        edge_id
        for feature in segment_features
        for edge_id in (
            feature["properties"]["forward_edge_id"],
            feature["properties"]["reverse_edge_id"],
        )
        if edge_id is not None
    ]
    assert len(browser_edge_ids) == len(set(browser_edge_ids))
    assert set(browser_edge_ids) == {edge["id"] for edge in network["edges"]}

    forward = next(
        edge
        for edge in network["edges"]
        if edge["source"]["way_id"] == 10 and edge["direction"] == "forward"
    )
    reverse = next(
        edge
        for edge in network["edges"]
        if edge["source"]["way_id"] == 10 and edge["direction"] == "reverse"
    )
    assert forward["permissions"] == {
        "private_car": True,
        "walking": True,
        "cycling": True,
    }
    assert reverse["permissions"] == {
        "private_car": False,
        "walking": True,
        "cycling": False,
    }
    one_way_feature = next(
        feature
        for feature in segment_features
        if feature["properties"]["physical_segment_id"] == forward["id"].removesuffix("-f")
    )
    assert {
        "forward_edge_id": forward["id"],
        "reverse_edge_id": reverse["id"],
        "private_car_forward": True,
        "private_car_reverse": False,
        "walking_forward": True,
        "walking_reverse": True,
        "cycling_forward": True,
        "cycling_reverse": False,
    }.items() <= one_way_feature["properties"].items()
    footway_edges = [edge for edge in network["edges"] if edge["source"]["way_id"] == 20]
    assert len(footway_edges) == 2
    assert all(
        edge["permissions"] == {"private_car": False, "walking": True, "cycling": False}
        for edge in footway_edges
    )
    cycle_edges = [edge for edge in network["edges"] if edge["source"]["way_id"] == 30]
    assert len(cycle_edges) == 2
    assert all(edge["permissions"]["cycling"] for edge in cycle_edges)
    car_free = [edge for edge in network["edges"] if edge["source"]["way_id"] == 50]
    assert car_free and all(not edge["permissions"]["private_car"] for edge in car_free)
    vertical_separation_edges = [
        edge for edge in network["edges"] if edge["source"]["way_id"] == 40
    ]
    assert vertical_separation_edges
    assert all(
        {key: edge["tags"][key] for key in ("bridge", "tunnel", "layer", "covered", "ford")}
        == {
            "bridge": "yes",
            "tunnel": "no",
            "layer": "1",
            "covered": "no",
            "ford": "no",
        }
        for edge in vertical_separation_edges
    )

    metadata = json.loads((first.snapshot_dir / "metadata.json").read_text())
    query_metadata = metadata["sources"][0]["query"]
    assert query_metadata["adapter_version"] == OVERPASS_ADAPTER_VERSION
    assert query_metadata["network_context_buffer_m"] == 100
    assert query_metadata["core_area"] != query_metadata["bounded_network_context"]
    lineage_artifact = metadata["field_lineage_artifact"]
    assert lineage_artifact["path"] == "provenance/field-lineage.jsonl.gz"
    assert lineage_artifact["media_type"] == "application/gzip"
    lineage_payload = (first.snapshot_dir / lineage_artifact["path"]).read_bytes()
    assert lineage_payload[4:8] == b"\x00\x00\x00\x00"
    uncompressed_lineage = gzip.decompress(lineage_payload)
    assert len(lineage_payload) < len(uncompressed_lineage)
    assert len(uncompressed_lineage.splitlines()) == 5 * network["counts"]["directed_edges"]


def test_source_bundle_archive_is_consumed_by_base_builder_from_same_source_root(
    tmp_path: Path,
) -> None:
    current = recipe()
    source_root = tmp_path / "sources"
    adapter = OsmOverpassAdapter(
        refresh=True,
        transport=lambda *_: synthetic_overpass(),
        clock=lambda: NOW,
    )
    bundle = acquire_source_bundle(
        current,
        source_dir=source_root,
        refresh=True,
        registry=SourceBundleAdapterRegistry([adapter]),
    )

    workspace = source_adapter_workspace(source_root, current, current.sources[0])
    assert bundle.manifest_path is not None
    assert bundle.manifest_path.parent == source_root / current.scenario_id
    assert adapter.archive_path.parent == workspace
    assert not list(source_root.glob("*.archive.json"))

    result = build_base_network_snapshot(
        current,
        source_dir=source_root,
        output_dir=tmp_path / "derived",
        transport=lambda *_: pytest.fail("offline build must consume the bundled archive"),
    )

    assert result.node_count > 0
    assert result.edge_count > 0
    assert validate_latest_base_network(tmp_path / "derived", current) == result.snapshot_dir


def test_validator_proves_browser_edge_mapping_and_geometry_orientation(
    tmp_path: Path,
) -> None:
    current = recipe()
    result = build_base_network_snapshot(
        current,
        source_dir=tmp_path / "source",
        output_dir=tmp_path / "output",
        refresh=True,
        transport=lambda *_: synthetic_overpass(),
        clock=lambda: NOW,
    )
    browser_path = result.snapshot_dir / "base-network.geojson"
    original_browser = browser_path.read_text(encoding="utf-8")

    browser = json.loads(original_browser)
    paired_feature = next(
        feature
        for feature in browser["features"]
        if feature["properties"].get("forward_edge_id") is not None
        and feature["properties"].get("reverse_edge_id") is not None
    )
    paired_feature["properties"]["reverse_edge_id"] = paired_feature["properties"][
        "forward_edge_id"
    ]
    rewrite_tracked_json(result.snapshot_dir, "base-network.geojson", browser)
    with pytest.raises(BaseNetworkBuildError, match="reverse_edge_id differs"):
        validate_base_network_snapshot(result.snapshot_dir, current)

    browser = json.loads(original_browser)
    segment_feature = next(
        feature
        for feature in browser["features"]
        if feature["properties"].get("layer") == "base_network"
    )
    segment_feature["geometry"]["coordinates"].reverse()
    rewrite_tracked_json(result.snapshot_dir, "base-network.geojson", browser)
    with pytest.raises(BaseNetworkBuildError, match="geometry orientation differs"):
        validate_base_network_snapshot(result.snapshot_dir, current)


def test_validator_decompresses_and_validates_every_lineage_record(tmp_path: Path) -> None:
    current = recipe()
    result = build_base_network_snapshot(
        current,
        source_dir=tmp_path / "source",
        output_dir=tmp_path / "output",
        refresh=True,
        transport=lambda *_: synthetic_overpass(),
        clock=lambda: NOW,
    )
    rewrite_lineage(result.snapshot_dir, gzip.compress(b'{"not":"lineage"}\n', mtime=0))

    with pytest.raises(BaseNetworkBuildError, match="invalid field-lineage record"):
        validate_base_network_snapshot(result.snapshot_dir, current)


def test_offline_mode_requires_matching_archive_and_unknown_url_parameter_is_refused(
    tmp_path: Path,
) -> None:
    current = recipe()
    with pytest.raises(OsmArchiveError, match="run the same command once with --refresh"):
        build_base_network_snapshot(
            current,
            source_dir=tmp_path / "missing",
            output_dir=tmp_path / "output",
        )

    unsafe_recipe = recipe(
        sources=[
            {
                "adapter_id": "osm",
                "role": "base_network",
                "parameters": {"endpoint": "https://example.invalid/overpass"},
            }
        ]
    )
    declaration = unsafe_recipe.sources[0]
    adapter = OsmOverpassAdapter(
        refresh=True,
        transport=lambda *_: pytest.fail("configuration must fail before network acquisition"),
        clock=lambda: NOW,
    )
    with pytest.raises(AdapterConfigurationError, match="endpoint and query shape are controlled"):
        adapter.acquire(
            SourceAcquisitionContext(
                recipe=unsafe_recipe,
                declaration=declaration,
                workspace=(tmp_path / "unsafe").resolve(),
            )
        )


def test_failed_graph_derivation_never_publishes_a_partial_snapshot(tmp_path: Path) -> None:
    current = recipe()
    output_dir = tmp_path / "output"
    with pytest.raises(BaseNetworkBuildError, match="references missing node"):
        build_base_network_snapshot(
            current,
            source_dir=tmp_path / "source",
            output_dir=output_dir,
            refresh=True,
            transport=lambda *_: synthetic_overpass(missing_node=True),
            clock=lambda: NOW,
        )

    assert not (output_dir / "latest.json").exists()
    snapshots_dir = output_dir / "snapshots"
    assert not snapshots_dir.exists() or not list(snapshots_dir.iterdir())


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (synthetic_overpass(remark="runtime error: Query timed out"), "contains a remark"),
        (synthetic_overpass(timestamp=False), "timestamp_osm_base"),
    ],
)
def test_partial_or_unversioned_overpass_response_is_never_archived(
    tmp_path: Path, payload: bytes, message: str
) -> None:
    with pytest.raises(OsmArchiveError, match=message):
        build_base_network_snapshot(
            recipe(),
            source_dir=tmp_path / "source",
            output_dir=tmp_path / "output",
            refresh=True,
            transport=lambda *_: payload,
            clock=lambda: NOW,
        )

    assert not list((tmp_path / "source").rglob("*.*"))
    assert not (tmp_path / "output" / "latest.json").exists()


def test_valid_but_empty_source_cannot_publish_an_empty_network(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    with pytest.raises(BaseNetworkBuildError, match="no usable nodes or directed edges"):
        build_base_network_snapshot(
            recipe(),
            source_dir=tmp_path / "source",
            output_dir=output_dir,
            refresh=True,
            transport=lambda *_: synthetic_overpass(empty=True),
            clock=lambda: NOW,
        )

    assert not (output_dir / "latest.json").exists()
    assert not (output_dir / "snapshots").exists()
