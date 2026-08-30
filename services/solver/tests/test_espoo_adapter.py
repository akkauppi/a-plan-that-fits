from __future__ import annotations

import gzip
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from services.scenario_builder import ScenarioRecipe, SourceAcquisitionContext
from services.scenario_builder.adapters import AdapterConfigurationError
from services.scenario_builder.espoo import (
    ESPOO_GIS_NAMESPACE,
    ESPOO_LAYERS,
    ESPOO_OUTPUT_FORMAT,
    ESPOO_SOURCE_CRS,
    ESPOO_WFS_ENDPOINT,
    ESPOO_WFS_VERSION,
    EspooArchiveError,
    EspooWfsAdapter,
    derive_wfs_url,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def recipe(*, parameters: dict | None = None) -> ScenarioRecipe:
    return ScenarioRecipe.model_validate(
        {
            "scenario_id": "otaniemi-resilient-access-v1",
            "name": "Otaniemi resilient access",
            "network_context_buffer_m": 750,
            "area": {
                "kind": "point_radius",
                "center": {"longitude": 24.827, "latitude": 60.185},
                "radius_m": 1_000,
            },
            "sources": [
                {"adapter_id": "osm", "role": "base_network"},
                {
                    "adapter_id": "espoo_wfs",
                    "role": "municipal_context",
                    "parameters": parameters or {},
                },
            ],
        }
    )


def context(tmp_path: Path, current_recipe: ScenarioRecipe) -> SourceAcquisitionContext:
    declaration = next(
        source for source in current_recipe.sources if source.adapter_id == "espoo_wfs"
    )
    return SourceAcquisitionContext(
        recipe=current_recipe,
        declaration=declaration,
        workspace=tmp_path.resolve(),
    )


def response_for_url(
    url: str,
    timeout_s: int = 60,
    *,
    feature_count: int = 2,
    stable_ids: bool = True,
    timestamp: str = "2026-08-30T15:00:00+03:00",
) -> bytes:
    del timeout_s
    parameters = parse_qs(urlsplit(url).query)
    layer = parameters["TYPENAME"][0]
    local_layer = layer.split(":", maxsplit=1)[1]
    values = [float(value) for value in parameters["BBOX"][0].split(",")]
    minimum_x, minimum_y, maximum_x, maximum_y = values
    middle_x = (minimum_x + maximum_x) / 2
    middle_y = (minimum_y + maximum_y) / 2

    members = []
    for number in range(feature_count):
        identity = f' fid="{local_layer}.{number + 1}"' if stable_ids else ""
        members.append(
            f"""
  <gml:featureMember>
    <GIS:{local_layer}{identity}>
      <GIS:Name>feature {number + 1}</GIS:Name>
      <GIS:Geometry>
        <gml:Point srsName="http://www.opengis.net/gml/srs/epsg.xml#3879">
          <gml:coordinates>{middle_x + number:.3f},{middle_y + number:.3f},0</gml:coordinates>
        </gml:Point>
      </GIS:Geometry>
    </GIS:{local_layer}>
  </gml:featureMember>"""
        )
    return (
        f"""<?xml version="1.0" encoding="utf-8"?>
<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs"
 xmlns:gml="http://www.opengis.net/gml"
 xmlns:GIS="{ESPOO_GIS_NAMESPACE}"
 timeStamp="{timestamp}" numberOfFeatures="{feature_count}">
 <gml:boundedBy>
  <gml:Envelope srsName="http://www.opengis.net/gml/srs/epsg.xml#3879">
   <gml:lowerCorner>{middle_x - 10:.3f} {middle_y - 10:.3f}</gml:lowerCorner>
   <gml:upperCorner>{middle_x + 10:.3f} {middle_y + 10:.3f}</gml:upperCorner>
  </gml:Envelope>
 </gml:boundedBy>{"".join(members)}
</wfs:FeatureCollection>"""
    ).encode()


def test_queries_are_fixed_bounded_native_crs_and_omit_bbox_suffix(tmp_path: Path) -> None:
    calls: list[tuple[str, int]] = []

    def transport(url: str, timeout_s: int) -> bytes:
        calls.append((url, timeout_s))
        return response_for_url(url, timeout_s)

    current_recipe = recipe(parameters={"wfs_timeout_s": 45})
    metadata = EspooWfsAdapter(
        refresh=True,
        transport=transport,
        clock=lambda: NOW,
    ).acquire(context(tmp_path, current_recipe))

    assert len(calls) == len(ESPOO_LAYERS)
    assert metadata.feature_count == len(ESPOO_LAYERS) * 2
    assert metadata.source_crs == ESPOO_SOURCE_CRS
    assert metadata.source_timestamp is None
    for (url, timeout_s), expected_layer in zip(calls, ESPOO_LAYERS, strict=True):
        split = urlsplit(url)
        assert f"{split.scheme}://{split.netloc}{split.path}" == ESPOO_WFS_ENDPOINT
        parameters = parse_qs(split.query)
        assert parameters == {
            "OUTPUTFORMAT": [ESPOO_OUTPUT_FORMAT],
            "SERVICE": ["WFS"],
            "VERSION": [ESPOO_WFS_VERSION],
            "REQUEST": ["GetFeature"],
            "TYPENAME": [expected_layer],
            "BBOX": [parameters["BBOX"][0]],
        }
        bbox_parts = parameters["BBOX"][0].split(",")
        assert len(bbox_parts) == 4
        assert "EPSG" not in parameters["BBOX"][0]
        minimum_x, minimum_y, maximum_x, maximum_y = map(float, bbox_parts)
        assert 3_450 < maximum_x - minimum_x < 3_550
        assert 3_450 < maximum_y - minimum_y < 3_550
        assert 24_000_000 < minimum_x < 26_000_000
        assert timeout_s == 45

    assert metadata.query["bbox_crs_suffix_omitted"] is True
    assert metadata.query["coverage_not_inferred_from_feature_count"] is True
    assert "without XML canonicalization" in metadata.query["archive_representation"]
    assert [item["type_name"] for item in metadata.query["layers"]] == list(ESPOO_LAYERS)


def test_endpoint_query_and_layer_injection_are_rejected(tmp_path: Path) -> None:
    bbox = (25_489_000.0, 6_673_000.0, 25_492_000.0, 6_676_000.0)
    with pytest.raises(AdapterConfigurationError, match="six audited"):
        derive_wfs_url("GIS:Katutapahtumat", bbox)

    calls = 0

    def transport(url: str, timeout_s: int) -> bytes:
        nonlocal calls
        calls += 1
        return response_for_url(url, timeout_s)

    injected = recipe(parameters={"layers": ["GIS:Keskilinjat&CQL_FILTER=x"]})
    with pytest.raises(AdapterConfigurationError, match="unsupported Espoo WFS layer"):
        EspooWfsAdapter(refresh=True, transport=transport).acquire(context(tmp_path, injected))
    endpoint = recipe(parameters={"endpoint": "https://example.test/wfs"})
    with pytest.raises(AdapterConfigurationError, match="unsupported espoo_wfs"):
        EspooWfsAdapter(refresh=True, transport=transport).acquire(context(tmp_path, endpoint))
    assert calls == 0


def test_refresh_and_offline_replay_are_identical_and_coverage_stays_unknown(
    tmp_path: Path,
) -> None:
    current_recipe = recipe(parameters={"layers": ["GIS:Keskilinjat"]})
    online = EspooWfsAdapter(
        refresh=True,
        transport=response_for_url,
        clock=lambda: NOW,
    )
    online_metadata = online.acquire(context(tmp_path, current_recipe))
    frozen = next(iter(online.archive_paths.values())).read_bytes()

    def should_not_fetch(url: str, timeout_s: int) -> bytes:
        raise AssertionError(f"offline acquisition fetched {url} with timeout {timeout_s}")

    offline = EspooWfsAdapter(
        refresh=False,
        transport=should_not_fetch,
        clock=lambda: NOW,
    )
    offline_metadata = offline.acquire(context(tmp_path, current_recipe))

    assert offline_metadata == online_metadata
    assert next(iter(offline.archive_paths.values())).read_bytes() == frozen
    coverage = offline.assess_coverage(current_recipe)
    assert coverage.status == "unknown"
    assert coverage.evidence["nonempty_response_is_not_coverage_proof"] is True
    assert coverage.evidence["validated_responses"][0]["feature_count"] == 2


def test_exact_raw_archives_and_gzip_are_deterministic_across_workspaces(
    tmp_path: Path,
) -> None:
    current_recipe = recipe(parameters={"layers": ["GIS:Osoitteet"]})
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    expected_url: list[str] = []

    def transport(url: str, timeout_s: int) -> bytes:
        expected_url.append(url)
        return response_for_url(url, timeout_s)

    first = EspooWfsAdapter(refresh=True, transport=transport, clock=lambda: NOW)
    second = EspooWfsAdapter(refresh=True, transport=transport, clock=lambda: NOW)
    first.acquire(context(first_root, current_recipe))
    second.acquire(context(second_root, current_recipe))

    first_payload = next(iter(first.archive_paths.values())).read_bytes()
    second_payload = next(iter(second.archive_paths.values())).read_bytes()
    assert first_payload == second_payload
    assert gzip.decompress(first_payload) == response_for_url(expected_url[0])
    assert first_payload[4:8] == b"\x00\x00\x00\x00"


def test_identical_later_refresh_preserves_first_acquisition_metadata(tmp_path: Path) -> None:
    current_recipe = recipe(parameters={"layers": ["GIS:Keskilinjat"]})
    first = EspooWfsAdapter(
        refresh=True,
        transport=response_for_url,
        clock=lambda: NOW,
    )
    first_metadata = first.acquire(context(tmp_path, current_recipe))
    pointer = tmp_path / f"{current_recipe.scenario_id}.espoo-wfs.archive.json"
    first_pointer = pointer.read_bytes()

    later = EspooWfsAdapter(
        refresh=True,
        transport=response_for_url,
        clock=lambda: NOW + timedelta(days=7),
    )
    later_metadata = later.acquire(context(tmp_path, current_recipe))

    assert later_metadata == first_metadata
    assert later_metadata.acquired_at == NOW
    assert pointer.read_bytes() == first_pointer


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda text: text.replace("<wfs:FeatureCollection", "<wfs:ExceptionReport", 1).replace(
                "</wfs:FeatureCollection>", "</wfs:ExceptionReport>"
            ),
            "exception report",
        ),
        (
            lambda text: text.replace(
                '<?xml version="1.0" encoding="utf-8"?>',
                '<?xml version="1.0" encoding="utf-8"?><!DOCTYPE x [<!ENTITY e "x">]>',
            ),
            "prohibited DTD",
        ),
        (
            lambda text: text.replace(
                f'xmlns:GIS="{ESPOO_GIS_NAMESPACE}"',
                'xmlns:GIS="https://example.test/wrong"',
            ),
            "expected",
        ),
        (
            lambda text: text.replace("epsg.xml#3879", "epsg.xml#3067", 1),
            "native EPSG:3879",
        ),
        (
            lambda text: text.replace('numberOfFeatures="2"', 'numberOfFeatures="3"'),
            "does not equal",
        ),
    ],
)
def test_malformed_error_or_semantically_wrong_xml_is_rejected(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    current_recipe = recipe(parameters={"layers": ["GIS:Keskilinjat"]})

    def malformed(url: str, timeout_s: int) -> bytes:
        return mutate(response_for_url(url, timeout_s).decode()).encode()

    with pytest.raises(EspooArchiveError, match=message):
        EspooWfsAdapter(
            refresh=True,
            transport=malformed,
            clock=lambda: NOW,
        ).acquire(context(tmp_path, current_recipe))


def test_counts_stable_ids_and_bounds_are_verified(tmp_path: Path) -> None:
    current_recipe = recipe(parameters={"layers": ["GIS:Keskilinjat"]})
    adapter = EspooWfsAdapter(
        refresh=True,
        transport=response_for_url,
        clock=lambda: NOW,
    )
    metadata = adapter.acquire(context(tmp_path, current_recipe))
    layer = metadata.query["layers"][0]
    expected_ids = b"Keskilinjat.1\nKeskilinjat.2\n"
    assert layer["feature_count"] == 2
    assert layer["declared_feature_count"] == 2
    assert layer["stable_id_count"] == 2
    assert layer["stable_ids_sha256"] == hashlib.sha256(expected_ids).hexdigest()
    archive = next(iter(adapter.archive_paths.values())).read_bytes()
    assert layer["raw_sha256"] == hashlib.sha256(gzip.decompress(archive)).hexdigest()
    assert layer["feature_namespace"] == ESPOO_GIS_NAMESPACE
    assert len(layer["collection_bbox"]) == 4

    duplicate_root = tmp_path / "duplicate"
    duplicate_root.mkdir()

    def duplicate(url: str, timeout_s: int) -> bytes:
        return response_for_url(url, timeout_s).replace(
            b'fid="Keskilinjat.2"', b'fid="Keskilinjat.1"'
        )

    with pytest.raises(EspooArchiveError, match="duplicate stable feature ID"):
        EspooWfsAdapter(
            refresh=True,
            transport=duplicate,
            clock=lambda: NOW,
        ).acquire(context(duplicate_root, current_recipe))


def test_archive_tampering_is_detected_before_offline_replay(tmp_path: Path) -> None:
    current_recipe = recipe(parameters={"layers": ["GIS:Vesialueet"]})
    online = EspooWfsAdapter(
        refresh=True,
        transport=response_for_url,
        clock=lambda: NOW,
    )
    online.acquire(context(tmp_path, current_recipe))
    archive_path = next(iter(online.archive_paths.values()))
    archive_path.write_bytes(archive_path.read_bytes() + b"tampered")

    with pytest.raises(EspooArchiveError, match="checksum"):
        EspooWfsAdapter(refresh=False).acquire(context(tmp_path, current_recipe))


def test_response_size_and_feature_limits_are_enforced(tmp_path: Path, monkeypatch) -> None:
    from services.scenario_builder import espoo

    current_recipe = recipe(parameters={"layers": ["GIS:Osoitteet"]})
    monkeypatch.setattr(espoo, "MAX_FEATURES_PER_LAYER", 1)
    with pytest.raises(EspooArchiveError, match="feature layer limit"):
        EspooWfsAdapter(
            refresh=True,
            transport=response_for_url,
            clock=lambda: NOW,
        ).acquire(context(tmp_path, current_recipe))

    monkeypatch.setattr(espoo, "MAX_FEATURES_PER_LAYER", 50_000)
    monkeypatch.setattr(espoo, "MAX_RESPONSE_BYTES", 20)
    with pytest.raises(EspooArchiveError, match="response exceeds"):
        EspooWfsAdapter(
            refresh=True,
            transport=response_for_url,
            clock=lambda: NOW,
        ).acquire(context(tmp_path, current_recipe))


def test_changed_exact_response_creates_a_new_snapshot_timestamp(tmp_path: Path) -> None:
    current_recipe = recipe(parameters={"layers": ["GIS:Keskilinjat"]})
    first = EspooWfsAdapter(
        refresh=True,
        transport=response_for_url,
        clock=lambda: NOW,
    )
    first.acquire(context(tmp_path, current_recipe))
    first_archive = next(iter(first.archive_paths.values()))

    def changed(url: str, timeout_s: int) -> bytes:
        return response_for_url(
            url,
            timeout_s,
            timestamp="2026-09-06T15:00:00+03:00",
        )

    later = EspooWfsAdapter(
        refresh=True,
        transport=changed,
        clock=lambda: NOW + timedelta(days=7),
    )
    metadata = later.acquire(context(tmp_path, current_recipe))

    assert metadata.acquired_at == NOW + timedelta(days=7)
    assert next(iter(later.archive_paths.values())) != first_archive
