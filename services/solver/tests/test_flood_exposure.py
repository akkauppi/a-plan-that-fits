from __future__ import annotations

import copy
import gzip
import hashlib
import json
import math
from pathlib import Path

import pytest
from pyproj import Transformer
from shapely.geometry import LineString, MultiPolygon, Polygon, box, mapping, shape
from shapely.ops import transform

from services.scenario_builder.flood_exposure import (
    ANALYSIS_CRS,
    DISPLAY_CRS,
    FloodExposureBuildError,
    _rounded_mapping,
    build_flood_exposure_snapshot,
    derive_flood_exposure_documents,
    validate_flood_exposure_document,
    validate_latest_flood_exposure,
)
from services.scenario_builder.syke import (
    SEA_FLOOD_1_IN_100,
    SEA_FLOOD_1_IN_1000,
    SYKE_ADAPTER_VERSION,
    SYKE_WFS_ENDPOINT,
    derive_wfs_url,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


TO_ANALYSIS = Transformer.from_crs(DISPLAY_CRS, ANALYSIS_CRS, always_xy=True)


def _analysis_line(coordinates: list[list[float]]) -> LineString:
    return transform(TO_ANALYSIS.transform, LineString(coordinates))


def base_network() -> dict:
    lines = {
        "street": [[24.8200, 60.1800], [24.8230, 60.1800]],
        "dry": [[24.8200, 60.1810], [24.8230, 60.1810]],
        "bridge": [[24.8200, 60.1820], [24.8230, 60.1820]],
    }
    nodes: list[dict] = []
    edges: list[dict] = []
    for way_id, (name, coordinates) in enumerate(lines.items(), 10):
        start_id = f"n-{way_id}-a"
        end_id = f"n-{way_id}-b"
        nodes.extend([{"id": start_id}, {"id": end_id}])
        physical_id = f"osm-way-{way_id}-segment-0000-part-00"
        tags = {"bridge": "yes", "layer": "1"} if name == "bridge" else {}
        length_m = round(_analysis_line(coordinates).length, 3)
        for direction, edge_from, edge_to, geometry, suffix in (
            ("forward", start_id, end_id, coordinates, "f"),
            ("reverse", end_id, start_id, list(reversed(coordinates)), "r"),
        ):
            edges.append(
                {
                    "id": f"{physical_id}-{suffix}",
                    "physical_segment_id": physical_id,
                    "from": edge_from,
                    "to": edge_to,
                    "geometry": geometry,
                    "length_m": length_m,
                    "permissions": {
                        "private_car": True,
                        "walking": True,
                        "cycling": True,
                    },
                    "highway": "residential",
                    "name": name.title(),
                    "direction": direction,
                    "source": {
                        "adapter_id": "osm",
                        "way_id": way_id,
                        "segment_index": 0,
                        "part_index": 0,
                    },
                    "tags": tags,
                }
            )
    context = {
        "type": "Polygon",
        "coordinates": [
            [
                [24.8190, 60.1790],
                [24.8240, 60.1790],
                [24.8240, 60.1830],
                [24.8190, 60.1830],
                [24.8190, 60.1790],
            ]
        ],
    }
    return {
        "schema_version": "1.0",
        "artifact_type": "resilient_access_base_network",
        "builder_version": "1.1.0",
        "scope": "base_network_only",
        "scenario_id": "synthetic-base",
        "snapshot_id": "base-synthetic",
        "analysis_crs": ANALYSIS_CRS,
        "display_crs": DISPLAY_CRS,
        "network_context_boundary": context,
        "nodes": nodes,
        "edges": edges,
    }


def _hazard_geometry_for(name: str, *, width_m: float = 12) -> dict:
    edge = next(edge for edge in base_network()["edges"] if edge["name"].lower() == name)
    line = _analysis_line(edge["geometry"])
    return mapping(line.buffer(width_m, cap_style="flat"))


def _feature(
    layer: str,
    number: int,
    period: int | None,
    depth_id: int | None,
    geometry: dict,
    *,
    label: str | None = None,
) -> dict:
    local_layer = layer.split(":", maxsplit=1)[1]
    return {
        "type": "Feature",
        "id": f"{local_layer}.{number}",
        "geometry": geometry,
        "properties": {
            "toistuvuus": period,
            "syvsuojluokka_id": depth_id,
            "syvsuojluokka": label,
            "silta_id": None,
            "muutospvm": "2025-11-18",
        },
    }


def _document(features: list[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "features": sorted(features, key=lambda item: item["id"]),
        "numberMatched": len(features),
        "numberReturned": len(features),
        "timeStamp": "2026-08-30T10:00:00Z",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:EPSG::3067"},
        },
    }


def hazard_documents(*, include_exclusions: bool = True) -> dict[str, dict]:
    one_hundred = [
        _feature(
            SEA_FLOOD_1_IN_100,
            1,
            100,
            1,
            _hazard_geometry_for("street"),
            label="0–0.5 m",
        ),
        _feature(
            SEA_FLOOD_1_IN_100,
            2,
            100,
            5,
            _hazard_geometry_for("bridge"),
            label=">3 m",
        ),
    ]
    if include_exclusions:
        one_hundred.extend(
            [
                _feature(
                    SEA_FLOOD_1_IN_100,
                    3,
                    100,
                    0,
                    _hazard_geometry_for("dry"),
                    label="kuiva maa",
                ),
                _feature(
                    SEA_FLOOD_1_IN_100,
                    4,
                    100,
                    99,
                    _hazard_geometry_for("street", width_m=2),
                    label="vesistö",
                ),
                _feature(
                    SEA_FLOOD_1_IN_100,
                    5,
                    100,
                    12,
                    _hazard_geometry_for("street", width_m=3),
                    label="kiinteä suojaus",
                ),
                _feature(
                    SEA_FLOOD_1_IN_100,
                    6,
                    None,
                    None,
                    _hazard_geometry_for("street", width_m=4),
                    label=None,
                ),
            ]
        )
        one_hundred[-1]["properties"]["muutospvm"] = None
    one_thousand = [
        _feature(
            SEA_FLOOD_1_IN_1000,
            1,
            1_000,
            2,
            _hazard_geometry_for("street", width_m=16),
            label="0.5–1 m",
        )
    ]
    return {
        SEA_FLOOD_1_IN_100: _document(one_hundred),
        SEA_FLOOD_1_IN_1000: _document(one_thousand),
    }


def _manifest(network: dict) -> dict:
    context = transform(
        TO_ANALYSIS.transform, Polygon(network["network_context_boundary"]["coordinates"][0])
    )
    minimum_x, minimum_y, maximum_x, maximum_y = context.bounds
    return {
        "adapter_version": SYKE_ADAPTER_VERSION,
        "scenario_id": "synthetic-flood",
        "acquired_at": "2026-08-30T10:00:00+00:00",
        "bbox": [minimum_x - 1, minimum_y - 1, maximum_x + 1, maximum_y + 1],
    }


def _derive(
    network: dict | None = None, documents: dict[str, dict] | None = None
) -> tuple[dict, dict, list[dict]]:
    current_network = network or base_network()
    current_documents = documents or hazard_documents()
    return derive_flood_exposure_documents(
        current_network,
        current_documents,
        scenario_id="synthetic-flood",
        snapshot_id="flood-synthetic",
        base_sha256="a" * 64,
        syke_pointer_sha256="b" * 64,
        syke_archive_sha256={
            SEA_FLOOD_1_IN_100: "c" * 64,
            SEA_FLOOD_1_IN_1000: "d" * 64,
        },
        syke_manifest=_manifest(current_network),
    )


def test_exposure_deduplicates_directions_and_keeps_passability_unknown() -> None:
    document, geojson, lineage = _derive()

    assert document["scope"] == "exposure_only"
    assert document["semantics"] == {
        "exposure_only": True,
        "passability_not_inferred": True,
        "closure_not_inferred": True,
        "safe_route_not_inferred": True,
    }
    assert document["counts"]["base_directed_edges"] == 6
    assert document["counts"]["physical_segments"] == 3
    assert document["counts"]["deduplicated_directed_edge_records"] == 3
    segments = {segment["name"]: segment for segment in document["segments"]}
    assert len(segments["Street"]["directed_edge_ids"]) == 2
    assert segments["Street"]["scenarios"][0]["exposed"] is True
    assert segments["Street"]["scenarios"][0]["deepest_depth_class_id"] == 1
    assert segments["Dry"]["scenarios"][0]["exposed"] is False
    assert segments["Bridge"]["scenarios"][0]["deepest_depth_class_id"] == 5
    assert segments["Bridge"]["vertical_separation"]["status"] == "review_required"
    assert segments["Bridge"]["vertical_separation"]["indicators"] == {
        "bridge": "yes",
        "layer": "1",
    }
    excluded = document["counts"]["excluded_source_features_by_reason"]
    assert excluded == {
        "dry_land": 1,
        "fixed_protection": 1,
        "null_boundary_artifact": 1,
        "waterbody": 1,
    }
    assert all(
        feature["properties"].get("passability_not_inferred", True)
        for feature in geojson["features"]
    )
    validate_flood_exposure_document(document, geojson, base_network(), lineage)


def test_display_precision_reduction_preserves_multipolygon_validity() -> None:
    # Naively rounding the 4e-8 degree gap to seven decimals makes the two
    # polygons share an edge, which is invalid as a MultiPolygon. The serializer
    # must node/merge topology at the display grid instead.
    geometry = MultiPolygon(
        [
            box(24.0, 60.0, 24.001, 60.001),
            box(24.00100004, 60.0, 24.002, 60.001),
        ]
    )

    serialized = shape(_rounded_mapping(geometry))

    assert serialized.is_valid
    assert not serialized.is_empty


def test_invalid_hazard_geometry_is_repaired_with_lineage() -> None:
    documents = hazard_documents(include_exclusions=False)
    street_line = _analysis_line(base_network()["edges"][0]["geometry"])
    midpoint = street_line.interpolate(0.5, normalized=True)
    x, y = midpoint.x, midpoint.y
    bow_tie = {
        "type": "Polygon",
        "coordinates": [
            [
                [x - 30, y - 20],
                [x + 30, y + 20],
                [x + 30, y - 20],
                [x - 30, y + 20],
                [x - 30, y - 20],
            ]
        ],
    }
    documents[SEA_FLOOD_1_IN_100]["features"][0]["geometry"] = bow_tie
    document, _, lineage = _derive(documents=documents)

    assert document["counts"]["geometry_repairs_with_make_valid"] == 1
    repair = next(
        record
        for record in lineage
        if record["record_type"] == "hazard_feature_preparation"
        and record["return_period_years"] == 100
        and record["source_fields"]["syvsuojluokka_id"] == 1
    )
    assert repair["geometry_repaired_with_make_valid"] is True


def test_spatial_index_avoids_segment_times_feature_scan() -> None:
    documents = hazard_documents(include_exclusions=False)
    context = transform(
        TO_ANALYSIS.transform,
        Polygon(base_network()["network_context_boundary"]["coordinates"][0]),
    )
    minimum_x, minimum_y, maximum_x, maximum_y = context.bounds
    features = documents[SEA_FLOOD_1_IN_100]["features"]
    for index in range(100):
        row, column = divmod(index, 20)
        geometry = mapping(
            box(
                minimum_x + 2 + column * 4,
                maximum_y - 2 - row * 4,
                minimum_x + 4 + column * 4,
                maximum_y - row * 4,
            )
        )
        features.append(
            _feature(
                SEA_FLOOD_1_IN_100,
                100 + index,
                100,
                1,
                geometry,
                label="0–0.5 m",
            )
        )
    features.sort(key=lambda item: item["id"])
    documents[SEA_FLOOD_1_IN_100]["numberMatched"] = len(features)
    documents[SEA_FLOOD_1_IN_100]["numberReturned"] = len(features)

    document, _, _ = _derive(documents=documents)

    checked = document["counts"]["spatial_index_candidate_checks_by_return_period"]["100"]
    naive_checks = len(features) * document["counts"]["physical_segments"]
    assert checked < naive_checks / 10


def _canonical_payload(document: dict) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _write_base_snapshot(root: Path, network: dict) -> Path:
    root.mkdir(parents=True)
    payload = _canonical_payload(network)
    path = root / "base-network.json"
    path.write_bytes(payload)
    metadata = {
        "snapshot_id": network["snapshot_id"],
        "created_at": "2026-08-29T10:00:00+00:00",
        "derived_artifacts": [
            {
                "path": "base-network.json",
                "sha256": _sha256(payload),
                "byte_size": len(payload),
            }
        ],
    }
    (root / "metadata.json").write_bytes(_canonical_payload(metadata))
    return path


def _write_syke_sources(root: Path, network: dict, documents: dict[str, dict]) -> Path:
    root.mkdir(parents=True)
    manifest = _manifest(network)
    manifest.update(
        {
            "schema_version": "1.0",
            "endpoint": SYKE_WFS_ENDPOINT,
            "source_crs": ANALYSIS_CRS,
            "layers": [],
        }
    )
    bbox = tuple(manifest["bbox"])
    for layer in (SEA_FLOOD_1_IN_100, SEA_FLOOD_1_IN_1000):
        document = copy.deepcopy(documents[layer])
        document["features"].sort(key=lambda item: item["id"])
        raw = _canonical_payload(document)
        compressed = gzip.compress(raw, compresslevel=9, mtime=0)
        filename = f"{layer.split(':')[1]}.{_sha256(raw)[:16]}.geojson.gz"
        (root / filename).write_bytes(compressed)
        query_url = derive_wfs_url(layer, bbox)
        period = 100 if layer == SEA_FLOOD_1_IN_100 else 1_000
        manifest["layers"].append(
            {
                "layer": layer,
                "return_period_years": period,
                "query_url": query_url,
                "query_sha256": _sha256(query_url.encode()),
                "archive_file": filename,
                "archive_sha256": _sha256(compressed),
                "raw_sha256": _sha256(raw),
                "byte_size": len(compressed),
                "feature_count": len(document["features"]),
            }
        )
    pointer = root / "synthetic.syke-coastal-flood.archive.json"
    pointer.write_bytes(_canonical_payload(manifest))
    return pointer


def test_snapshot_is_deterministic_offline_and_detects_tampering(tmp_path: Path) -> None:
    network = base_network()
    documents = hazard_documents()
    base_path = _write_base_snapshot(tmp_path / "base", network)
    pointer_path = _write_syke_sources(tmp_path / "source", network, documents)

    first = build_flood_exposure_snapshot(
        base_network_path=base_path,
        syke_pointer_path=pointer_path,
        output_dir=tmp_path / "first",
    )
    second = build_flood_exposure_snapshot(
        base_network_path=base_path,
        syke_pointer_path=pointer_path,
        output_dir=tmp_path / "second",
    )
    assert first.snapshot_id == second.snapshot_id
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
    assert first_files == second_files
    lineage = first.snapshot_dir / "provenance/flood-exposure-lineage.jsonl.gz"
    assert lineage.read_bytes()[4:8] == b"\x00\x00\x00\x00"
    assert len(gzip.decompress(lineage.read_bytes()).splitlines()) == 6 + len(
        documents[SEA_FLOOD_1_IN_100]["features"]
    ) + len(documents[SEA_FLOOD_1_IN_1000]["features"])
    assert (
        validate_latest_flood_exposure(
            output_dir=tmp_path / "first",
            base_network_path=base_path,
            syke_pointer_path=pointer_path,
        )
        == first.snapshot_dir
    )

    archive = next((tmp_path / "source").glob("*.geojson.gz"))
    archive.write_bytes(archive.read_bytes() + b"tampered")
    with pytest.raises(FloodExposureBuildError, match="checksum or size"):
        build_flood_exposure_snapshot(
            base_network_path=base_path,
            syke_pointer_path=pointer_path,
            output_dir=tmp_path / "tampered",
        )


def test_missing_base_and_source_references_are_rejected() -> None:
    network = base_network()
    broken_network = copy.deepcopy(network)
    broken_network["edges"][0]["from"] = "missing-node"
    with pytest.raises(FloodExposureBuildError, match="missing node"):
        _derive(network=broken_network)

    document, geojson, lineage = _derive(network=network)
    document["segments"][0]["scenarios"][0]["source_feature_ids"] = ["missing-source"]
    with pytest.raises(FloodExposureBuildError, match="missing source feature"):
        validate_flood_exposure_document(document, geojson, network, lineage)


def test_old_base_builder_marks_absent_vertical_tags_unknown() -> None:
    network = base_network()
    network["builder_version"] = "1.0.0"
    document, _, _ = _derive(network=network)
    dry = next(segment for segment in document["segments"] if segment["name"] == "Dry")
    assert dry["vertical_separation"]["status"] == "unknown"
    assert dry["vertical_separation"]["review_required"] is None


def test_metric_lengths_are_finite_and_bounded() -> None:
    document, _, _ = _derive()
    for segment in document["segments"]:
        assert math.isfinite(segment["length_m"])
        assert segment["length_m"] > 0
        for scenario in segment["scenarios"]:
            assert 0 <= scenario["intersected_length_m"] <= segment["length_m"] + 0.01
