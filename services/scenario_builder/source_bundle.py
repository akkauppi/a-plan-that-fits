"""Acquire and verify a deterministic bundle of declared scenario sources.

This module is deliberately narrower than a scenario builder.  It records source
evidence, licence/provenance metadata, and the exact bounded area used for source
queries.  It does not derive a routable graph, infer road passability, or make a
flood-safety claim.

The default path is an offline replay of adapters' frozen archives.  Network I/O
is possible only when callers explicitly construct the registered adapters with
``refresh=True`` (the public helper does this only for an explicit refresh).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .adapters import (
    AdapterRegistry,
    SourceAcquisitionContext,
    source_adapter_workspace,
)
from .espoo import EspooWfsAdapter
from .mml import MmlElevationAdapter
from .models import (
    CoverageAssessment,
    ScenarioRecipe,
    SourceDeclaration,
    SourceSnapshotMetadata,
)
from .osm import OsmOverpassAdapter, canonicalize_area, canonicalize_network_context
from .syke import SykeCoastalFloodAdapter

SOURCE_BUNDLE_SCHEMA_VERSION = "1.0"
SOURCE_BUNDLE_BUILDER_VERSION = "1.0.0"
SOURCE_BUNDLE_FILENAME_PREFIX = "source-bundle."

PROFILE_SOURCE_CAPABILITIES = (
    "base_network",
    "elevation",
    "flood_hazard",
    "municipal_context",
    "roadworks",
)

Clock = Callable[[], datetime]
CoverageCallback = Callable[[dict[str, Any]], None]


class SourceBundleError(ValueError):
    """A bounded source bundle could not be assessed, acquired, or published."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "source_bundle_error",
        adapter_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.adapter_id = adapter_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            **({"adapter_id": self.adapter_id} if self.adapter_id is not None else {}),
        }


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BundleFileReference(_StrictModel):
    kind: Literal["pointer", "archive"]
    path: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def path_is_relative(cls, value: str) -> str:
        parts = value.replace("\\", "/").split("/")
        if value.startswith(("/", "\\")) or ".." in parts:
            raise ValueError("bundle file reference must be workspace-relative")
        return value


class PersistedCoverage(_StrictModel):
    """Spatial assessment without the transient time at which it was rechecked."""

    status: Literal["full", "partial", "none", "unknown"]
    message: str = Field(min_length=1, max_length=1_000)
    evidence: dict[str, Any] = Field(default_factory=dict)


class BundleSource(_StrictModel):
    declaration: SourceDeclaration
    readiness: Literal["ready"] = "ready"
    spatial_coverage: PersistedCoverage
    snapshot_metadata: SourceSnapshotMetadata
    source_files: list[BundleFileReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def identifiers_match(self) -> BundleSource:
        if self.declaration.adapter_id != self.snapshot_metadata.adapter_id:
            raise ValueError("source declaration and snapshot adapter IDs differ")
        paths = [reference.path for reference in self.source_files]
        if len(paths) != len(set(paths)):
            raise ValueError("source bundle contains duplicate file references")
        return self


class SourceBundleManifest(_StrictModel):
    schema_version: Literal["1.0"] = SOURCE_BUNDLE_SCHEMA_VERSION
    bundle_builder_version: Literal["1.0.0"] = SOURCE_BUNDLE_BUILDER_VERSION
    scope: Literal["source_evidence_bundle_only"] = "source_evidence_bundle_only"
    scenario_id: str
    scenario_type: Literal["resilient_access"] = "resilient_access"
    recipe_schema_version: Literal["1.0"] = "1.0"
    recipe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_id: Literal["finland-resilient-access-v1"]
    analysis_crs: Literal["EPSG:3067"]
    selected_adapter_ids: list[str] = Field(min_length=1)
    study_area: dict[str, Any]
    capabilities: dict[str, Any]
    sources: list[BundleSource] = Field(min_length=1)
    semantics: dict[str, Any]

    @model_validator(mode="after")
    def source_order_matches_selection(self) -> SourceBundleManifest:
        source_ids = [source.declaration.adapter_id for source in self.sources]
        if source_ids != self.selected_adapter_ids:
            raise ValueError("bundle sources must follow selected recipe order")
        return self


@dataclass(frozen=True)
class SourceBundleAdapterRegistry:
    """Small injectable registry with individual lookup for partial acquisitions."""

    _by_id: Mapping[str, Any]

    def __init__(self, adapters: Iterable[Any]) -> None:
        materialized = tuple(adapters)
        # Reuse the shared contract's duplicate/identifier validation.
        AdapterRegistry(materialized)
        object.__setattr__(
            self,
            "_by_id",
            {adapter.adapter_id: adapter for adapter in materialized},
        )

    @property
    def adapter_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_id))

    def get(self, adapter_id: str) -> Any | None:
        return self._by_id.get(adapter_id)


@dataclass(frozen=True)
class SourceBundleResult:
    coverage_report: dict[str, Any]
    manifest: SourceBundleManifest | None
    manifest_path: Path | None


def default_source_adapter_registry(
    *,
    refresh: bool = False,
    clock: Clock | None = None,
) -> SourceBundleAdapterRegistry:
    """Register the audited network, elevation, hazard, and municipal adapters."""

    adapter_clock = clock or (lambda: datetime.now(UTC))
    return SourceBundleAdapterRegistry(
        (
            OsmOverpassAdapter(refresh=refresh, clock=adapter_clock),
            MmlElevationAdapter(refresh=refresh, clock=adapter_clock),
            SykeCoastalFloodAdapter(refresh=refresh, clock=adapter_clock),
            EspooWfsAdapter(refresh=refresh, clock=adapter_clock),
        )
    )


def _selected_declarations(
    recipe: ScenarioRecipe, selected_adapter_ids: Iterable[str] | None
) -> tuple[SourceDeclaration, ...]:
    declared = {declaration.adapter_id: declaration for declaration in recipe.sources}
    if selected_adapter_ids is None:
        return tuple(recipe.sources)

    requested = tuple(selected_adapter_ids)
    if not requested:
        raise SourceBundleError(
            "at least one adapter must be selected",
            code="empty_adapter_selection",
        )
    duplicates = sorted(
        adapter_id for adapter_id in set(requested) if requested.count(adapter_id) > 1
    )
    if duplicates:
        raise SourceBundleError(
            "adapter selection contains duplicates: " + ", ".join(duplicates),
            code="duplicate_adapter_selection",
        )
    undeclared = sorted(set(requested) - set(declared))
    if undeclared:
        raise SourceBundleError(
            "adapter selection is not declared by the recipe: " + ", ".join(undeclared),
            code="undeclared_adapter",
        )
    requested_set = set(requested)
    # Recipe order is the reproducible source precedence order. CLI order cannot
    # silently change provenance or acquisition ordering.
    return tuple(
        declaration for declaration in recipe.sources if declaration.adapter_id in requested_set
    )


def _reject_parameter_urls(declarations: Iterable[SourceDeclaration]) -> None:
    def walk(value: Any) -> Iterable[str]:
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key, nested in value.items():
                yield str(key)
                yield from walk(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from walk(nested)

    for declaration in declarations:
        for value in walk(declaration.parameters):
            lowered = value.strip().lower()
            if "://" in lowered or lowered.startswith("//"):
                raise SourceBundleError(
                    "source parameter URLs are not allowed; endpoints are fixed by audited "
                    f"adapter {declaration.adapter_id!r}",
                    code="caller_supplied_url",
                    adapter_id=declaration.adapter_id,
                )


def _coverage_entry(
    declaration: SourceDeclaration,
    assessment: CoverageAssessment,
    *,
    refresh: bool,
    archive_pointer: Path | None,
) -> dict[str, Any]:
    if archive_pointer is None:
        archive_presence = {
            "status": "not_assessed",
            "pointer_present": None,
            "message": (
                "This adapter does not expose a side-effect-free local pointer preflight. "
                "No offline-readiness claim is made."
            ),
        }
    elif archive_pointer.is_file():
        archive_presence = {
            "status": "pointer_present_unvalidated",
            "pointer_present": True,
            "message": (
                "A local archive pointer is present. Acquisition validates the pointer and "
                "its referenced content before any source is reported ready."
            ),
        }
    else:
        archive_presence = {
            "status": "missing",
            "pointer_present": False,
            "message": (
                "No local archive pointer is present. Offline acquisition is not ready; "
                "an explicit refresh is required."
            ),
        }
    return {
        "adapter_id": declaration.adapter_id,
        "role": declaration.role,
        "required": declaration.required,
        "adapter_configuration": {
            "status": "configured",
            "message": "The declared adapter is registered and its bounded preflight passed.",
            "acquisition_mode": "explicit_refresh" if refresh else "offline_replay",
        },
        "local_archive": archive_presence,
        "spatial_coverage": assessment.model_dump(mode="json"),
    }


def assess_source_coverage(
    recipe: ScenarioRecipe,
    *,
    source_dir: Path | None = None,
    selected_adapter_ids: Iterable[str] | None = None,
    registry: SourceBundleAdapterRegistry | None = None,
    refresh: bool = False,
) -> tuple[dict[str, Any], tuple[SourceDeclaration, ...], dict[str, CoverageAssessment]]:
    """Preflight configuration, bounds, and optional local pointer presence.

    This deliberately does not equate a registered adapter with offline source
    readiness. Pointer presence is only a cheap read-only observation; full
    pointer and archive validation remains part of acquisition.
    """

    declarations = _selected_declarations(recipe, selected_adapter_ids)
    _reject_parameter_urls(declarations)
    registry = registry or default_source_adapter_registry(refresh=refresh)

    entries: list[dict[str, Any]] = []
    assessments: dict[str, CoverageAssessment] = {}
    pointer_presence: list[bool | None] = []
    for declaration in declarations:
        adapter = registry.get(declaration.adapter_id)
        if adapter is None:
            requirement = "required " if declaration.required else ""
            raise SourceBundleError(
                f"no registered adapter for selected {requirement}source "
                f"{declaration.adapter_id!r}",
                code="adapter_not_registered",
                adapter_id=declaration.adapter_id,
            )
        try:
            assessment = adapter.assess_coverage(recipe)
        except Exception as error:
            raise SourceBundleError(
                f"coverage assessment failed for {declaration.adapter_id!r}: {error}",
                code="coverage_assessment_failed",
                adapter_id=declaration.adapter_id,
            ) from error
        if assessment.adapter_id != declaration.adapter_id:
            raise SourceBundleError(
                f"coverage assessment from {declaration.adapter_id!r} returned adapter ID "
                f"{assessment.adapter_id!r}",
                code="adapter_identity_mismatch",
                adapter_id=declaration.adapter_id,
            )
        assessments[declaration.adapter_id] = assessment
        archive_pointer: Path | None = None
        if source_dir is not None:
            workspace = source_adapter_workspace(source_dir, recipe, declaration)
            pointer_resolver = getattr(adapter, "archive_pointer_path", None)
            if callable(pointer_resolver):
                try:
                    archive_pointer = pointer_resolver(
                        SourceAcquisitionContext(
                            recipe=recipe,
                            declaration=declaration,
                            workspace=workspace,
                        )
                    )
                except Exception as error:
                    raise SourceBundleError(
                        f"archive preflight failed for {declaration.adapter_id!r}: {error}",
                        code="archive_preflight_failed",
                        adapter_id=declaration.adapter_id,
                    ) from error
        pointer_presence.append(
            archive_pointer.is_file() if archive_pointer is not None else None
        )
        entries.append(
            _coverage_entry(
                declaration,
                assessment,
                refresh=refresh,
                archive_pointer=archive_pointer,
            )
        )

    all_present: bool | None
    if any(presence is None for presence in pointer_presence):
        all_present = None
    else:
        all_present = all(bool(presence) for presence in pointer_presence)

    report = {
        "schema_version": SOURCE_BUNDLE_SCHEMA_VERSION,
        "event": "source_preflight_assessed",
        "assessment_scope": "configuration_bounds_and_local_pointer_presence",
        "scenario_id": recipe.scenario_id,
        "recipe_sha256": recipe.sha256(),
        "selected_adapter_ids": [declaration.adapter_id for declaration in declarations],
        "all_selected_adapters_configured": True,
        "all_selected_archive_pointers_present": all_present,
        "archive_pointer_presence_is_not_archive_validation": True,
        "spatial_coverage_is_not_source_readiness": True,
        "sources": entries,
    }
    return report, declarations, assessments


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def source_bundle_filename(
    recipe: ScenarioRecipe, selected_adapter_ids: Iterable[str]
) -> str:
    """Return a stable manifest name keyed by recipe and recipe-ordered selection.

    A full bundle and a hazard/context-only bundle must coexist: acquiring the
    latter must never replace the former. An explicit refresh may atomically update
    the selected manifest while immutable raw archives retain their content identities.
    Full SHA-256 values also avoid relying on caller-provided adapter IDs as
    filesystem tokens.
    """

    selection_payload = json.dumps(
        list(selected_adapter_ids),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return (
        f"{SOURCE_BUNDLE_FILENAME_PREFIX}{recipe.sha256()}."
        f"{_sha256(selection_payload)}.json"
    )


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_write_if_changed(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == payload:
        return
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _safe_reference_path(path: Path, workspace: Path) -> str:
    resolved = path.resolve()
    root = workspace.resolve()
    if resolved != root and root not in resolved.parents:
        raise SourceBundleError(
            f"adapter exposed a source file outside the scenario workspace: {resolved}",
            code="unsafe_source_reference",
        )
    if not resolved.is_file():
        raise SourceBundleError(
            f"adapter exposed a missing source file: {resolved}",
            code="missing_source_reference",
        )
    return resolved.relative_to(root).as_posix()


def _read_optional_property(adapter: Any, name: str) -> Any | None:
    try:
        return getattr(adapter, name)
    except (AttributeError, RuntimeError):
        return None


def _exposed_source_files(
    adapter: Any,
    *,
    adapter_workspace: Path,
    bundle_workspace: Path,
) -> list[BundleFileReference]:
    """Record pointer/archive files exposed by the current audited adapters."""

    paths: dict[Path, Literal["pointer", "archive"]] = {}
    archive_path = _read_optional_property(adapter, "archive_path")
    if isinstance(archive_path, Path):
        paths[archive_path] = "archive"
    archive_paths = _read_optional_property(adapter, "archive_paths")
    if isinstance(archive_paths, Mapping):
        for path in archive_paths.values():
            if isinstance(path, Path):
                paths[path] = "archive"

    archive_manifest = _read_optional_property(adapter, "archive_manifest")
    if isinstance(archive_manifest, dict):
        matching_pointers: list[Path] = []
        for candidate in sorted(adapter_workspace.glob("*.archive.json")):
            try:
                if json.loads(candidate.read_text(encoding="utf-8")) == archive_manifest:
                    matching_pointers.append(candidate)
            except (OSError, json.JSONDecodeError):
                continue
        if len(matching_pointers) > 1:
            raise SourceBundleError(
                f"adapter {adapter.adapter_id!r} exposed multiple identical archive pointers",
                code="ambiguous_archive_pointer",
                adapter_id=adapter.adapter_id,
            )
        if matching_pointers:
            paths[matching_pointers[0]] = "pointer"

    references: list[BundleFileReference] = []
    for path, kind in sorted(paths.items(), key=lambda item: str(item[0])):
        relative = _safe_reference_path(path, bundle_workspace)
        payload = path.read_bytes()
        references.append(
            BundleFileReference(
                kind=kind,
                path=relative,
                sha256=_sha256(payload),
                byte_size=len(payload),
            )
        )
    return references


def _rounded_bounds(bounds: tuple[float, float, float, float], decimals: int) -> list[float]:
    return [round(float(value), decimals) for value in bounds]


def _capabilities(
    recipe: ScenarioRecipe, acquired: tuple[SourceDeclaration, ...]
) -> dict[str, Any]:
    present = {declaration.role for declaration in acquired}
    declared = {declaration.role for declaration in recipe.sources}
    return {
        "present": [
            capability for capability in PROFILE_SOURCE_CAPABILITIES if capability in present
        ],
        "declared_but_not_acquired": [
            capability
            for capability in PROFILE_SOURCE_CAPABILITIES
            if capability in declared and capability not in present
        ],
        "not_declared": [
            capability for capability in PROFILE_SOURCE_CAPABILITIES if capability not in declared
        ],
        "capability_means_source_archived_only": True,
    }


def acquire_source_bundle(
    recipe: ScenarioRecipe,
    *,
    source_dir: Path,
    selected_adapter_ids: Iterable[str] | None = None,
    refresh: bool = False,
    coverage_only: bool = False,
    registry: SourceBundleAdapterRegistry | None = None,
    clock: Clock | None = None,
    on_coverage: CoverageCallback | None = None,
) -> SourceBundleResult:
    """Assess then acquire selected sources, publishing the manifest last.

    Raw content-addressed archives are intentionally allowed to remain if a later
    adapter fails.  The bundle manifest is written only after every selected source
    has returned validated metadata.
    """

    registry = registry or default_source_adapter_registry(refresh=refresh, clock=clock)
    report, declarations, assessments = assess_source_coverage(
        recipe,
        source_dir=source_dir,
        selected_adapter_ids=selected_adapter_ids,
        registry=registry,
        refresh=refresh,
    )
    if on_coverage is not None:
        on_coverage(report)
    if coverage_only:
        return SourceBundleResult(report, None, None)

    source_root = source_dir.resolve()
    bundle_workspace = source_root / recipe.scenario_id
    acquired_sources: list[BundleSource] = []
    for declaration in declarations:
        adapter = registry.get(declaration.adapter_id)
        if adapter is None:  # defensive: assessment has already checked this
            raise SourceBundleError(
                f"adapter {declaration.adapter_id!r} disappeared after coverage assessment",
                code="adapter_not_registered",
                adapter_id=declaration.adapter_id,
            )
        adapter_workspace = source_adapter_workspace(source_root, recipe, declaration)
        adapter_workspace.mkdir(parents=True, exist_ok=True)
        try:
            snapshot = adapter.acquire(
                SourceAcquisitionContext(
                    recipe=recipe,
                    declaration=declaration,
                    workspace=adapter_workspace,
                )
            )
        except Exception as error:
            raise SourceBundleError(
                f"source acquisition failed for {declaration.adapter_id!r}: {error}",
                code="source_acquisition_failed",
                adapter_id=declaration.adapter_id,
            ) from error
        if snapshot.adapter_id != declaration.adapter_id:
            raise SourceBundleError(
                f"source metadata from {declaration.adapter_id!r} returned adapter ID "
                f"{snapshot.adapter_id!r}",
                code="adapter_identity_mismatch",
                adapter_id=declaration.adapter_id,
            )
        assessment = assessments[declaration.adapter_id]
        references = _exposed_source_files(
            adapter,
            adapter_workspace=adapter_workspace,
            bundle_workspace=bundle_workspace,
        )
        acquired_sources.append(
            BundleSource(
                declaration=declaration,
                spatial_coverage=PersistedCoverage(
                    status=assessment.status,
                    message=assessment.message,
                    evidence={
                        key: value
                        for key, value in assessment.evidence.items()
                        # These observations are useful in the live coverage event,
                        # but can appear only after an adapter has loaded its archive.
                        # They must not make bundle identity depend on object lifetime.
                        if key != "validated_responses"
                    },
                ),
                snapshot_metadata=snapshot,
                source_files=references,
            )
        )

    core = canonicalize_area(recipe)
    context = canonicalize_network_context(recipe, core)
    manifest = SourceBundleManifest(
        scenario_id=recipe.scenario_id,
        recipe_schema_version=recipe.schema_version,
        recipe_sha256=recipe.sha256(),
        profile_id=recipe.profile_id,
        analysis_crs=recipe.analysis_crs,
        selected_adapter_ids=[declaration.adapter_id for declaration in declarations],
        study_area={
            "coordinate_crs": "EPSG:4326",
            "core_geometry": core.geojson,
            "core_bbox_wgs84": _rounded_bounds(core.wgs84.bounds, 7),
            "core_bbox_analysis": _rounded_bounds(core.analysis.bounds, 3),
            "network_context_geometry": context.geojson,
            "network_context_bbox_wgs84": _rounded_bounds(context.wgs84.bounds, 7),
            "network_context_bbox_analysis": _rounded_bounds(context.analysis.bounds, 3),
            "network_context_buffer_m": recipe.network_context_buffer_m,
        },
        capabilities=_capabilities(recipe, declarations),
        sources=acquired_sources,
        semantics={
            "derived_scenario_created": False,
            "graph_built": False,
            "source_coverage_proves_absence_of_hazard": False,
            "road_passability_inferred": False,
            "flood_safety_claimed": False,
            "message": (
                "This is a verified bundle of source observations, not a derived scenario, "
                "routing result, passability assessment, or safety finding."
            ),
        },
    )
    manifest_path = bundle_workspace / source_bundle_filename(
        recipe, (declaration.adapter_id for declaration in declarations)
    )
    payload = _json_bytes(manifest.model_dump(mode="json"))
    try:
        _atomic_write_if_changed(manifest_path, payload)
    except OSError as error:
        raise SourceBundleError(
            f"cannot publish source bundle manifest {manifest_path}: {error}",
            code="manifest_publication_failed",
        ) from error
    return SourceBundleResult(report, manifest, manifest_path)


__all__ = [
    "SOURCE_BUNDLE_BUILDER_VERSION",
    "SOURCE_BUNDLE_FILENAME_PREFIX",
    "SOURCE_BUNDLE_SCHEMA_VERSION",
    "BundleFileReference",
    "BundleSource",
    "PersistedCoverage",
    "SourceBundleAdapterRegistry",
    "SourceBundleError",
    "SourceBundleManifest",
    "SourceBundleResult",
    "acquire_source_bundle",
    "assess_source_coverage",
    "default_source_adapter_registry",
    "source_bundle_filename",
]
