from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from services.scenario_builder.models import (
    ArtifactDigest,
    CoverageAssessment,
    LicenceRecord,
    ScenarioRecipe,
    SourceSnapshotMetadata,
)
from services.scenario_builder.osm import OsmOverpassAdapter
from services.scenario_builder.source_bundle import (
    SOURCE_BUNDLE_FILENAME_PREFIX,
    SourceBundleAdapterRegistry,
    SourceBundleError,
    acquire_source_bundle,
    assess_source_coverage,
    default_source_adapter_registry,
    source_bundle_filename,
)

FIXED_TIME = datetime(2026, 8, 30, 9, 15, tzinfo=UTC)


def _recipe(*, with_all_sources: bool = True, parameter_override: Any = None) -> ScenarioRecipe:
    sources: list[dict[str, Any]] = [
        {
            "adapter_id": "osm",
            "role": "base_network",
            "required": True,
            "parameters": parameter_override or {},
        }
    ]
    if with_all_sources:
        sources.extend(
            [
                {
                    "adapter_id": "syke",
                    "role": "flood_hazard",
                    "required": True,
                    "parameters": {},
                },
                {
                    "adapter_id": "espoo_wfs",
                    "role": "municipal_context",
                    "required": False,
                    "parameters": {},
                },
            ]
        )
    return ScenarioRecipe.model_validate(
        {
            "scenario_id": "test-otaniemi-bundle",
            "name": "Test Otaniemi source bundle",
            "network_context_buffer_m": 250,
            "area": {
                "kind": "point_radius",
                "center": {"longitude": 24.8278, "latitude": 60.1834},
                "radius_m": 650,
            },
            "sources": sources,
        }
    )


class FakeAdapter:
    def __init__(
        self,
        adapter_id: str,
        log: list[str],
        *,
        fail: bool = False,
        checked_at: datetime = FIXED_TIME,
    ) -> None:
        self.adapter_id = adapter_id
        self.log = log
        self.fail = fail
        self.checked_at = checked_at
        self._archive_path: Path | None = None
        self._archive_manifest: dict[str, Any] | None = None

    @property
    def archive_path(self) -> Path:
        if self._archive_path is None:
            raise RuntimeError("not acquired")
        return self._archive_path

    @property
    def archive_manifest(self) -> dict[str, Any]:
        if self._archive_manifest is None:
            raise RuntimeError("not acquired")
        return dict(self._archive_manifest)

    def assess_coverage(self, recipe: ScenarioRecipe) -> CoverageAssessment:
        self.log.append(f"coverage:{self.adapter_id}")
        return CoverageAssessment(
            adapter_id=self.adapter_id,
            status="unknown",
            message=f"{self.adapter_id} is bounded, but completeness is not inferred.",
            checked_at=self.checked_at,
            evidence={
                "bounded": True,
                # Bundle persistence must ignore this lifecycle-dependent field.
                **(
                    {"validated_responses": [{"feature_count": 1}]}
                    if self._archive_manifest is not None
                    else {}
                ),
            },
        )

    def archive_pointer_path(self, context: Any) -> Path:
        return context.workspace / f"{context.recipe.scenario_id}.{self.adapter_id}.archive.json"

    def acquire(self, context: Any) -> SourceSnapshotMetadata:
        self.log.append(f"acquire:{self.adapter_id}")
        if self.fail:
            # Raw archives are allowed to survive a later failed acquisition.
            context.workspace.mkdir(parents=True, exist_ok=True)
            (context.workspace / "partial.raw").write_bytes(b"partial")
            raise ValueError("injected source failure")

        payload = f"frozen source for {self.adapter_id}\n".encode()
        archive = context.workspace / f"{context.recipe.scenario_id}.{self.adapter_id}.raw"
        context.workspace.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(payload)
        archive_sha256 = hashlib.sha256(payload).hexdigest()
        pointer_document = {
            "schema_version": "1.0",
            "adapter_id": self.adapter_id,
            "archive_file": archive.name,
            "archive_sha256": archive_sha256,
            "acquired_at": FIXED_TIME.isoformat(),
        }
        pointer = context.workspace / f"{context.recipe.scenario_id}.{self.adapter_id}.archive.json"
        pointer.write_text(
            json.dumps(pointer_document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self._archive_path = archive
        self._archive_manifest = pointer_document
        return SourceSnapshotMetadata(
            adapter_id=self.adapter_id,
            source_name=f"Fake {self.adapter_id}",
            endpoint=f"https://fixed.example/{self.adapter_id}",
            acquired_at=FIXED_TIME,
            source_timestamp=FIXED_TIME,
            query={"adapter_version": "test-1", "bounded": True},
            source_crs="EPSG:4326",
            normalized_crs="EPSG:3067",
            feature_count=1,
            licence=LicenceRecord(
                name="Test licence",
                url="https://fixed.example/licence",
                attribution="Test source",
            ),
            artifacts=[
                ArtifactDigest(
                    path=f"raw/{self.adapter_id}.raw",
                    sha256=archive_sha256,
                    byte_size=len(payload),
                    media_type="application/octet-stream",
                )
            ],
        )


def _fake_registry(log: list[str], *, fail_id: str | None = None) -> SourceBundleAdapterRegistry:
    return SourceBundleAdapterRegistry(
        FakeAdapter(adapter_id, log, fail=adapter_id == fail_id)
        for adapter_id in ("osm", "syke", "espoo_wfs")
    )


def test_bundle_assesses_first_acquires_in_recipe_order_and_is_explicit_about_scope(
    tmp_path: Path,
) -> None:
    log: list[str] = []
    emitted: list[dict[str, Any]] = []
    result = acquire_source_bundle(
        _recipe(),
        source_dir=tmp_path,
        # Caller order must not alter recipe precedence.
        selected_adapter_ids=("espoo_wfs", "osm", "syke"),
        registry=_fake_registry(log),
        on_coverage=emitted.append,
    )

    assert log == [
        "coverage:osm",
        "coverage:syke",
        "coverage:espoo_wfs",
        "acquire:osm",
        "acquire:syke",
        "acquire:espoo_wfs",
    ]
    assert emitted[0]["all_selected_adapters_configured"] is True
    assert emitted[0]["all_selected_archive_pointers_present"] is False
    first_coverage = emitted[0]["sources"][0]
    assert first_coverage["adapter_configuration"]["status"] == "configured"
    assert first_coverage["local_archive"]["status"] == "missing"
    assert first_coverage["spatial_coverage"]["status"] == "unknown"

    assert result.manifest is not None
    assert result.manifest.selected_adapter_ids == ["osm", "syke", "espoo_wfs"]
    assert result.manifest.capabilities["present"] == [
        "base_network",
        "flood_hazard",
        "municipal_context",
    ]
    assert result.manifest.semantics["derived_scenario_created"] is False
    assert result.manifest.semantics["road_passability_inferred"] is False
    assert result.manifest.semantics["flood_safety_claimed"] is False
    assert result.manifest.study_area["core_geometry"]["type"] == "Polygon"
    assert result.manifest.study_area["network_context_buffer_m"] == 250
    assert all(source.snapshot_metadata.feature_count == 1 for source in result.manifest.sources)
    assert all(
        {reference.kind for reference in source.source_files} == {"archive", "pointer"}
        for source in result.manifest.sources
    )


def test_offline_and_refresh_modes_with_same_sources_publish_identical_manifest_bytes(
    tmp_path: Path,
) -> None:
    recipe = _recipe()
    first = acquire_source_bundle(
        recipe,
        source_dir=tmp_path,
        refresh=True,
        registry=_fake_registry([]),
    )
    assert first.manifest_path is not None
    first_bytes = first.manifest_path.read_bytes()

    second = acquire_source_bundle(
        recipe,
        source_dir=tmp_path,
        refresh=False,
        registry=_fake_registry([]),
    )
    assert second.manifest_path is not None
    assert second.manifest_path.read_bytes() == first_bytes


def test_real_osm_adapter_refresh_offline_and_repeated_refresh_reproduce_bundle_bytes(
    tmp_path: Path,
) -> None:
    recipe = _recipe(with_all_sources=False)
    response = json.dumps(
        {
            "version": 0.6,
            "generator": "source-bundle-test",
            "osm3s": {"timestamp_osm_base": "2026-08-29T12:00:00Z"},
            "elements": [],
        }
    ).encode()

    first = acquire_source_bundle(
        recipe,
        source_dir=tmp_path,
        refresh=True,
        registry=SourceBundleAdapterRegistry(
            [
                OsmOverpassAdapter(
                    refresh=True,
                    transport=lambda _query, _timeout: response,
                    clock=lambda: FIXED_TIME,
                )
            ]
        ),
    )
    assert first.manifest_path is not None
    first_bytes = first.manifest_path.read_bytes()

    offline = acquire_source_bundle(
        recipe,
        source_dir=tmp_path,
        registry=SourceBundleAdapterRegistry(
            [OsmOverpassAdapter(refresh=False, clock=lambda: datetime(2027, 1, 1, tzinfo=UTC))]
        ),
    )
    assert offline.manifest_path is not None
    assert offline.manifest_path.read_bytes() == first_bytes

    repeated_refresh = acquire_source_bundle(
        recipe,
        source_dir=tmp_path,
        refresh=True,
        registry=SourceBundleAdapterRegistry(
            [
                OsmOverpassAdapter(
                    refresh=True,
                    transport=lambda _query, _timeout: response,
                    clock=lambda: datetime(2027, 6, 1, tzinfo=UTC),
                )
            ]
        ),
    )
    assert repeated_refresh.manifest_path is not None
    assert repeated_refresh.manifest_path.read_bytes() == first_bytes


def test_reusing_loaded_adapters_does_not_change_bundle_identity(tmp_path: Path) -> None:
    recipe = _recipe()
    registry = _fake_registry([])
    first = acquire_source_bundle(recipe, source_dir=tmp_path, registry=registry)
    assert first.manifest_path is not None
    first_bytes = first.manifest_path.read_bytes()

    second = acquire_source_bundle(recipe, source_dir=tmp_path, registry=registry)
    assert second.manifest_path is not None
    assert second.manifest_path.read_bytes() == first_bytes


def test_subset_and_full_bundle_manifests_coexist(tmp_path: Path) -> None:
    recipe = _recipe()
    full = acquire_source_bundle(
        recipe,
        source_dir=tmp_path,
        registry=_fake_registry([]),
    )
    subset = acquire_source_bundle(
        recipe,
        source_dir=tmp_path,
        selected_adapter_ids=("syke", "espoo_wfs"),
        registry=_fake_registry([]),
    )

    assert full.manifest_path is not None
    assert subset.manifest_path is not None
    assert full.manifest_path != subset.manifest_path
    assert full.manifest_path.name == source_bundle_filename(
        recipe, ("osm", "syke", "espoo_wfs")
    )
    assert subset.manifest_path.name == source_bundle_filename(
        recipe, ("syke", "espoo_wfs")
    )
    assert full.manifest_path.is_file()
    assert subset.manifest_path.is_file()
    assert json.loads(full.manifest_path.read_text(encoding="utf-8"))[
        "selected_adapter_ids"
    ] == ["osm", "syke", "espoo_wfs"]
    assert json.loads(subset.manifest_path.read_text(encoding="utf-8"))[
        "selected_adapter_ids"
    ] == ["syke", "espoo_wfs"]


def test_coverage_only_performs_no_acquisition_and_publishes_nothing(tmp_path: Path) -> None:
    log: list[str] = []
    result = acquire_source_bundle(
        _recipe(),
        source_dir=tmp_path / "sources",
        coverage_only=True,
        registry=_fake_registry(log),
    )

    assert log == ["coverage:osm", "coverage:syke", "coverage:espoo_wfs"]
    assert result.manifest is None
    assert result.manifest_path is None
    assert not (tmp_path / "sources").exists()


def test_missing_selected_required_adapter_fails_before_manifest_publication(
    tmp_path: Path,
) -> None:
    recipe = _recipe()
    registry = SourceBundleAdapterRegistry([FakeAdapter("osm", [])])
    with pytest.raises(SourceBundleError, match="no registered adapter") as caught:
        acquire_source_bundle(
            recipe,
            source_dir=tmp_path,
            selected_adapter_ids=("syke",),
            registry=registry,
        )

    assert caught.value.code == "adapter_not_registered"
    assert not list(
        (tmp_path / recipe.scenario_id).glob(f"{SOURCE_BUNDLE_FILENAME_PREFIX}*.json")
    )


def test_later_adapter_failure_keeps_raw_files_but_does_not_publish_manifest(
    tmp_path: Path,
) -> None:
    recipe = _recipe()
    with pytest.raises(SourceBundleError, match="injected source failure") as caught:
        acquire_source_bundle(
            recipe,
            source_dir=tmp_path,
            registry=_fake_registry([], fail_id="syke"),
        )

    workspace = tmp_path / recipe.scenario_id
    assert caught.value.adapter_id == "syke"
    assert list((workspace / "osm").glob("*.raw"))
    assert (workspace / "syke" / "partial.raw").is_file()
    assert not list(workspace.glob(f"{SOURCE_BUNDLE_FILENAME_PREFIX}*.json"))


@pytest.mark.parametrize(
    ("selected", "parameters", "code"),
    [
        (("not_declared",), {}, "undeclared_adapter"),
        (("osm",), {"endpoint": "https://attacker.example/query"}, "caller_supplied_url"),
    ],
)
def test_undeclared_ids_and_caller_supplied_urls_are_rejected_before_adapter_calls(
    tmp_path: Path,
    selected: tuple[str, ...],
    parameters: dict[str, Any],
    code: str,
) -> None:
    log: list[str] = []
    recipe = _recipe(with_all_sources=False, parameter_override=parameters)
    with pytest.raises(SourceBundleError) as caught:
        acquire_source_bundle(
            recipe,
            source_dir=tmp_path,
            selected_adapter_ids=selected,
            registry=_fake_registry(log),
        )

    assert caught.value.code == code
    assert log == []


def test_default_registry_coverage_uses_injected_clock_without_network() -> None:
    recipe = _recipe()
    registry = default_source_adapter_registry(clock=lambda: FIXED_TIME)
    report, declarations, assessments = assess_source_coverage(recipe, registry=registry)

    assert registry.adapter_ids == ("espoo_wfs", "mml_elevation", "osm", "syke")
    assert [declaration.adapter_id for declaration in declarations] == [
        "osm",
        "syke",
        "espoo_wfs",
    ]
    assert report["spatial_coverage_is_not_source_readiness"] is True
    assert report["all_selected_archive_pointers_present"] is None
    assert all(assessment.checked_at == FIXED_TIME for assessment in assessments.values())


def test_cli_coverage_only_emits_machine_readable_events_and_writes_nothing(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[3]
    recipe = project_root / "data" / "recipes" / "espoo-otaniemi-coastal-base-v1.json"
    source_dir = tmp_path / "cli-sources"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/acquire_scenario_sources.py",
            "--recipe",
            str(recipe),
            "--source-dir",
            str(source_dir),
            "--coverage-only",
        ],
        cwd=project_root,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    events = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [event["event"] for event in events] == [
        "source_preflight_assessed",
        "source_preflight_complete",
    ]
    assert events[0]["all_selected_adapters_configured"] is True
    assert events[0]["all_selected_archive_pointers_present"] is False
    assert events[0]["sources"][0]["adapter_configuration"]["status"] == "configured"
    assert events[0]["sources"][0]["local_archive"]["status"] == "missing"
    assert events[0]["sources"][0]["local_archive"]["pointer_present"] is False
    assert "spatial_coverage" in events[0]["sources"][0]
    assert events[1]["manifest_published"] is False
    assert not source_dir.exists()


def test_cli_recipe_failure_is_machine_readable(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[3]
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/acquire_scenario_sources.py",
            "--recipe",
            str(tmp_path / "missing.json"),
        ],
        cwd=project_root,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 2
    error = json.loads(completed.stderr)
    assert error["ok"] is False
    assert error["error"]["code"] == "recipe_read_failed"
