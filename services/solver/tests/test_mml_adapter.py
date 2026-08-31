from __future__ import annotations

import base64
import gzip
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest

from services.scenario_builder.adapters import (
    AdapterConfigurationError,
    SourceAcquisitionContext,
)
from services.scenario_builder.mml import (
    MML_ADAPTER_VERSION,
    MML_API_KEY_ENV,
    MML_COVERAGE_ID,
    MML_OUTPUT_FORMAT,
    MML_SOURCE_CRS,
    MML_VERTICAL_CRS,
    MML_WCS_ENDPOINT,
    MML_WCS_VERSION,
    NATIVE_RESOLUTION_M,
    MmlArchiveError,
    MmlElevationAdapter,
    _default_transport,
    _RejectRedirects,
)
from services.scenario_builder.models import ANALYSIS_CRS, ScenarioRecipe

NOW = datetime(2026, 8, 30, 18, 30, tzinfo=UTC)
FAKE_API_KEY = "fake-mml-key-for-tests-only"


def recipe(*, parameters: dict | None = None) -> ScenarioRecipe:
    return ScenarioRecipe.model_validate(
        {
            "scenario_id": "otaniemi-elevation-test-v1",
            "name": "Otaniemi elevation adapter test",
            "network_context_buffer_m": 0,
            "area": {
                "kind": "point_radius",
                "center": {"longitude": 24.8278, "latitude": 60.1834},
                "radius_m": 100,
            },
            "sources": [
                {
                    "adapter_id": "osm",
                    "role": "base_network",
                    "required": True,
                    "parameters": {},
                },
                {
                    "adapter_id": "mml_elevation",
                    "role": "elevation",
                    "required": True,
                    "parameters": parameters or {},
                },
            ],
        }
    )


def context(tmp_path: Path, current_recipe: ScenarioRecipe) -> SourceAcquisitionContext:
    return SourceAcquisitionContext(
        recipe=current_recipe,
        declaration=current_recipe.sources[1],
        workspace=tmp_path.resolve(),
    )


def _subset_bounds(url: str) -> tuple[float, float, float, float]:
    subsets = parse_qs(urlsplit(url).query)["subset"]
    axes: dict[str, tuple[float, float]] = {}
    for subset in subsets:
        matched = re.fullmatch(r"([EN])\((-?[0-9.]+),(-?[0-9.]+)\)", subset)
        assert matched is not None
        axes[matched.group(1)] = (float(matched.group(2)), float(matched.group(3)))
    return axes["E"][0], axes["N"][0], axes["E"][1], axes["N"][1]


def response_for_url(
    url: str,
    *,
    extra_whitespace: bool = False,
    dimension_delta: int = 0,
    non_finite: bool = False,
    include_nodata_header: bool = True,
) -> bytes:
    minimum_x, minimum_y, maximum_x, maximum_y = _subset_bounds(url)
    ncols = round((maximum_x - minimum_x) / NATIVE_RESOLUTION_M) + dimension_delta
    nrows = round((maximum_y - minimum_y) / NATIVE_RESOLUTION_M)
    rows: list[str] = []
    for row_index in range(nrows):
        values = [str(10 + row_index % 3)] * ncols
        if row_index == 0:
            values[0] = "nan" if non_finite else "-9999"
        separator = "   " if extra_whitespace else " "
        rows.append(separator.join(values))
    separator = "   " if extra_whitespace else " "
    lines = [
        f"ncols{separator}{ncols}",
        f"nrows{separator}{nrows}",
        f"xllcorner{separator}{minimum_x:.3f}",
        f"yllcorner{separator}{minimum_y:.3f}",
        f"cellsize{separator}{NATIVE_RESOLUTION_M:g}",
    ]
    if include_nodata_header:
        lines.append(f"NODATA_value{separator}-9999")
    lines.extend(rows)
    newline = "\r\n" if extra_whitespace else "\n"
    return (newline.join(lines) + newline).encode("ascii")


def test_refresh_uses_fixed_bounded_request_and_never_persists_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MML_API_KEY_ENV, FAKE_API_KEY)
    calls: list[tuple[str, int, str]] = []

    def transport(url: str, timeout_s: int, api_key: str) -> bytes:
        calls.append((url, timeout_s, api_key))
        return response_for_url(url)

    current_recipe = recipe(parameters={"wcs_timeout_s": 45})
    adapter = MmlElevationAdapter(refresh=True, transport=transport, clock=lambda: NOW)
    metadata = adapter.acquire(context(tmp_path, current_recipe))

    assert len(calls) == 1
    url, timeout_s, api_key = calls[0]
    assert timeout_s == 45
    assert api_key == FAKE_API_KEY
    split = urlsplit(url)
    assert f"{split.scheme}://{split.netloc}{split.path}" == MML_WCS_ENDPOINT
    parameters = parse_qs(split.query)
    assert parameters == {
        "service": ["WCS"],
        "version": [MML_WCS_VERSION],
        "request": ["GetCoverage"],
        "CoverageID": [MML_COVERAGE_ID],
        "format": [MML_OUTPUT_FORMAT],
        "subset": parameters["subset"],
    }
    assert [value[0] for value in parameters["subset"]] == ["E", "N"]
    assert FAKE_API_KEY not in url
    assert "api-key" not in split.query.lower()

    minimum_x, minimum_y, maximum_x, maximum_y = _subset_bounds(url)
    width = maximum_x - minimum_x
    height = maximum_y - minimum_y
    assert width % NATIVE_RESOLUTION_M == 0
    assert height % NATIVE_RESOLUTION_M == 0
    assert metadata.query["bounded_network_context_bbox"] == [
        minimum_x,
        minimum_y,
        maximum_x,
        maximum_y,
    ]
    total_cells = (
        metadata.query["grid_dimensions"]["ncols"]
        * metadata.query["grid_dimensions"]["nrows"]
    )
    assert metadata.feature_count == total_cells - 1
    assert metadata.source_crs == ANALYSIS_CRS
    assert metadata.query["vertical_crs"] == MML_VERTICAL_CRS
    assert metadata.source_timestamp is None
    assert metadata.query["flood_hazard_not_derived"] is True
    assert metadata.query["passability_not_inferred"] is True
    assert metadata.licence.name.endswith("(CC BY 4.0)")
    assert "National Land Survey of Finland" in metadata.licence.attribution

    serialized_metadata = json.dumps(metadata.model_dump(mode="json"), sort_keys=True)
    serialized_manifest = json.dumps(adapter.archive_manifest, sort_keys=True)
    assert FAKE_API_KEY not in serialized_metadata
    assert FAKE_API_KEY not in serialized_manifest
    assert all(FAKE_API_KEY.encode() not in path.read_bytes() for path in tmp_path.iterdir())


def test_refresh_requires_runtime_environment_key_before_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(MML_API_KEY_ENV, raising=False)
    calls = 0

    def transport(url: str, timeout_s: int, api_key: str) -> bytes:
        nonlocal calls
        calls += 1
        return response_for_url(url)

    with pytest.raises(MmlArchiveError, match="MML_API_KEY is required"):
        MmlElevationAdapter(refresh=True, transport=transport).acquire(
            context(tmp_path, recipe())
        )
    assert calls == 0


@pytest.mark.parametrize(
    "parameters",
    [
        {"endpoint": "https://attacker.example/wcs"},
        {"coverage_id": "other"},
        {"api_key": "recipe-secret"},
        {"wcs_timeout_s": 121},
    ],
)
def test_endpoint_coverage_and_credentials_are_not_recipe_configurable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parameters: dict,
) -> None:
    monkeypatch.setenv(MML_API_KEY_ENV, FAKE_API_KEY)
    calls = 0

    def transport(url: str, timeout_s: int, api_key: str) -> bytes:
        nonlocal calls
        calls += 1
        return response_for_url(url)

    with pytest.raises(AdapterConfigurationError):
        MmlElevationAdapter(refresh=True, transport=transport).acquire(
            context(tmp_path, recipe(parameters=parameters))
        )
    assert calls == 0


def test_refresh_and_uncredentialed_offline_replay_return_identical_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MML_API_KEY_ENV, FAKE_API_KEY)
    current_recipe = recipe()
    online = MmlElevationAdapter(
        refresh=True,
        transport=lambda url, timeout, api_key: response_for_url(url),
        clock=lambda: NOW,
    )
    online_metadata = online.acquire(context(tmp_path, current_recipe))
    frozen_bytes = online.archive_path.read_bytes()

    monkeypatch.delenv(MML_API_KEY_ENV)

    def should_not_fetch(url: str, timeout_s: int, api_key: str) -> bytes:
        raise AssertionError(f"offline replay unexpectedly fetched {url}")

    offline = MmlElevationAdapter(
        refresh=False,
        transport=should_not_fetch,
        clock=lambda: NOW + timedelta(days=1),
    )
    offline_metadata = offline.acquire(context(tmp_path, current_recipe))

    assert offline_metadata == online_metadata
    assert offline.archive_path.read_bytes() == frozen_bytes
    assert offline.assess_coverage(current_recipe).status == "unknown"
    assert offline.assess_coverage(current_recipe).evidence["validated_responses"] == [
        {
            "coverage_id": MML_COVERAGE_ID,
            "valid_cell_count": online_metadata.feature_count,
            "nodata_cell_count": 1,
        }
    ]


def test_ascii_canonicalization_and_gzip_are_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MML_API_KEY_ENV, FAKE_API_KEY)
    current_recipe = recipe()
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()

    first = MmlElevationAdapter(
        refresh=True,
        transport=lambda url, timeout, api_key: response_for_url(
            url, extra_whitespace=True
        ),
        clock=lambda: NOW,
    )
    second = MmlElevationAdapter(
        refresh=True,
        transport=lambda url, timeout, api_key: response_for_url(url),
        clock=lambda: NOW,
    )
    first.acquire(context(first_root, current_recipe))
    second.acquire(context(second_root, current_recipe))

    first_payload = first.archive_path.read_bytes()
    assert first_payload == second.archive_path.read_bytes()
    assert first_payload[:10] == b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"
    raw = gzip.decompress(first_payload)
    assert b"\r" not in raw
    assert b"   " not in raw


def test_complete_grid_without_optional_nodata_header_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MML_API_KEY_ENV, FAKE_API_KEY)
    current_recipe = recipe()
    adapter = MmlElevationAdapter(
        refresh=True,
        transport=lambda url, timeout, api_key: response_for_url(
            url, include_nodata_header=False
        ).replace(b"-9999", b"10"),
        clock=lambda: NOW,
    )

    metadata = adapter.acquire(context(tmp_path, current_recipe))

    assert metadata.feature_count == (
        metadata.query["grid_dimensions"]["ncols"]
        * metadata.query["grid_dimensions"]["nrows"]
    )
    assert adapter.archive_manifest["nodata_value"] is None
    assert adapter.archive_manifest["nodata_cell_count"] == 0


def test_identical_refresh_preserves_first_acquisition_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MML_API_KEY_ENV, FAKE_API_KEY)
    current_recipe = recipe()
    first = MmlElevationAdapter(
        refresh=True,
        transport=lambda url, timeout, api_key: response_for_url(url),
        clock=lambda: NOW,
    )
    first_metadata = first.acquire(context(tmp_path, current_recipe))
    pointer = tmp_path / "otaniemi-elevation-test-v1.mml-elevation-2m.archive.json"
    pointer_bytes = pointer.read_bytes()

    second = MmlElevationAdapter(
        refresh=True,
        transport=lambda url, timeout, api_key: response_for_url(url),
        clock=lambda: NOW + timedelta(days=7),
    )
    second_metadata = second.acquire(context(tmp_path, current_recipe))

    assert pointer.read_bytes() == pointer_bytes
    assert second_metadata == first_metadata
    assert second_metadata.acquired_at == NOW


@pytest.mark.parametrize(
    ("response_kwargs", "message"),
    [
        ({"dimension_delta": 1}, "dimensions do not match"),
        ({"non_finite": True}, "non-finite"),
    ],
)
def test_malformed_or_mismatched_grid_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response_kwargs: dict,
    message: str,
) -> None:
    monkeypatch.setenv(MML_API_KEY_ENV, FAKE_API_KEY)
    with pytest.raises(MmlArchiveError, match=message):
        MmlElevationAdapter(
            refresh=True,
            transport=lambda url, timeout, api_key: response_for_url(
                url, **response_kwargs
            ),
            clock=lambda: NOW,
        ).acquire(context(tmp_path, recipe()))


def test_archive_and_pointer_tampering_are_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MML_API_KEY_ENV, FAKE_API_KEY)
    current_recipe = recipe()
    online = MmlElevationAdapter(
        refresh=True,
        transport=lambda url, timeout, api_key: response_for_url(url),
        clock=lambda: NOW,
    )
    online.acquire(context(tmp_path, current_recipe))
    pristine_archive = online.archive_path.read_bytes()
    online.archive_path.write_bytes(pristine_archive + b"tampered")

    monkeypatch.delenv(MML_API_KEY_ENV)
    with pytest.raises(MmlArchiveError, match="checksum"):
        MmlElevationAdapter(refresh=False).acquire(context(tmp_path, current_recipe))

    # Restore a valid archive, then prove unexpected pointer fields are rejected
    # so a credential cannot be smuggled into persisted provenance.
    online.archive_path.write_bytes(pristine_archive)
    pointer = tmp_path / "otaniemi-elevation-test-v1.mml-elevation-2m.archive.json"
    document = json.loads(pointer.read_text(encoding="utf-8"))
    document["api_key"] = "must-not-be-accepted"
    pointer.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(MmlArchiveError, match="unexpected or missing fields"):
        MmlElevationAdapter(refresh=False).acquire(context(tmp_path, current_recipe))


def test_default_transport_sends_basic_username_with_empty_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def read(self, limit: int) -> bytes:
            return b"payload"

    captured = None

    class FakeOpener:
        def open(self, request, timeout: int):
            nonlocal captured
            captured = request
            assert timeout == 30
            return FakeResponse()

    handlers = ()

    def fake_build_opener(*values):
        nonlocal handlers
        handlers = values
        return FakeOpener()

    monkeypatch.setattr("urllib.request.build_opener", fake_build_opener)
    url = f"{MML_WCS_ENDPOINT}?service=WCS"
    assert _default_transport(url, 30, FAKE_API_KEY) == b"payload"
    assert any(isinstance(handler, _RejectRedirects) for handler in handlers)
    assert captured is not None
    expected = base64.b64encode(f"{FAKE_API_KEY}:".encode("ascii")).decode("ascii")
    assert captured.get_header("Authorization") == f"Basic {expected}"
    assert FAKE_API_KEY not in captured.full_url


def test_redirect_handler_refuses_to_forward_credentials() -> None:
    request = Request(
        f"{MML_WCS_ENDPOINT}?service=WCS",
        headers={"Authorization": "Basic test-only"},
    )
    with pytest.raises(MmlArchiveError, match="redirect refused"):
        _RejectRedirects().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://untrusted.example/redirected",
        )


def test_coverage_assessment_does_not_read_or_require_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(MML_API_KEY_ENV, raising=False)
    assessment = MmlElevationAdapter(refresh=True, clock=lambda: NOW).assess_coverage(recipe())

    assert assessment.status == "unknown"
    assert assessment.evidence["credential_required_for_refresh"] is True
    assert assessment.evidence["credential_in_query_url"] is False
    assert assessment.evidence["elevation_is_not_flood_or_passability_evidence"] is True
    assert assessment.checked_at == NOW
    assert MML_ADAPTER_VERSION == "1.0.1"
    assert MML_SOURCE_CRS == ANALYSIS_CRS
