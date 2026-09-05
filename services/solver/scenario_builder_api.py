from __future__ import annotations

import hashlib
import json
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.scenario_builder.adapters import (
    SourceAcquisitionContext,
    source_adapter_workspace,
)
from services.scenario_builder.base_network import (
    BaseNetworkBuildError,
    build_base_network_snapshot,
    validate_latest_base_network,
)
from services.scenario_builder.flood_exposure import (
    FloodExposureBuildError,
    validate_latest_flood_exposure,
)
from services.scenario_builder.mml import MmlArchiveError, MmlElevationAdapter
from services.scenario_builder.models import LonLat, PointRadiusArea, ScenarioRecipe
from services.scenario_builder.osm import (
    OsmArchiveError,
    OsmOverpassAdapter,
    canonicalize_area,
    canonicalize_network_context,
)
from services.scenario_builder.source_bundle import SourceBundleManifest

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECIPE_DIR = ROOT / "data" / "recipes"
DEFAULT_SOURCE_DIR = ROOT / "data" / "source" / "scenario-builder"
DEFAULT_DERIVED_DIR = ROOT / "data" / "derived"
OTANIEMI_PRESET_ID = "otaniemi-coastal-v1"
OTANIEMI_BASE_RECIPE = "espoo-otaniemi-coastal-base-v1.json"
OTANIEMI_SOURCE_RECIPE = "espoo-otaniemi-coastal-v1.json"
OTANIEMI_ELEVATION_RECIPE = "espoo-otaniemi-coastal-elevation-v1.json"


class BuilderRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PointRadiusSelection(BuilderRequestModel):
    kind: Literal["point_radius"] = "point_radius"
    longitude: float = Field(ge=19.0, le=32.0)
    latitude: float = Field(ge=59.0, le=70.5)
    radius_m: float = Field(default=1_000, ge=100, le=2_500)


class BuilderSelection(BuilderRequestModel):
    preset_id: Literal["otaniemi-coastal-v1"] | None = None
    area: PointRadiusSelection | None = None

    @model_validator(mode="after")
    def exactly_one_selection(self) -> BuilderSelection:
        if self.preset_id is None and self.area is None:
            self.preset_id = OTANIEMI_PRESET_ID
        if self.preset_id is not None and self.area is not None:
            raise ValueError("select either a frozen preset or a point-radius area, not both")
        return self


class BuilderBuildRequest(BuilderSelection):
    refresh: bool = False
    confirm_live_source_refresh: Literal["REFRESH_OSM"] | None = None

    @model_validator(mode="after")
    def refresh_is_explicit(self) -> BuilderBuildRequest:
        if self.refresh and self.confirm_live_source_refresh != "REFRESH_OSM":
            raise ValueError(
                "a live OSM refresh requires confirm_live_source_refresh='REFRESH_OSM'"
            )
        if not self.refresh and self.confirm_live_source_refresh is not None:
            raise ValueError("refresh confirmation was supplied while refresh is false")
        return self


BuildEventEmitter = Callable[[str, str, dict[str, Any] | None], None]
BuildRunner = Callable[
    [ScenarioRecipe, bool, threading.Event, BuildEventEmitter], dict[str, Any]
]
SnapshotValidator = Callable[[Path, ScenarioRecipe], Path]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _round_bounds(bounds: tuple[float, float, float, float], digits: int) -> list[float]:
    return [round(float(value), digits) for value in bounds]


def _custom_scenario_id(area: PointRadiusSelection) -> str:
    canonical = json.dumps(area.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return f"finland-point-{hashlib.sha256(canonical.encode()).hexdigest()[:12]}"


class ScenarioBuilderService:
    """Offline-first preflight and background base-network build coordinator.

    The service is deliberately separate from the loaded Kallio solver scenario. A
    completed job publishes a resilient-access base-network artifact; it never swaps
    the active modal-filter solver graph or makes a flood/passability claim.
    """

    def __init__(
        self,
        *,
        recipe_dir: Path = DEFAULT_RECIPE_DIR,
        source_dir: Path = DEFAULT_SOURCE_DIR,
        derived_dir: Path = DEFAULT_DERIVED_DIR,
        runner: BuildRunner | None = None,
        snapshot_validator: SnapshotValidator = validate_latest_base_network,
    ) -> None:
        self.recipe_dir = recipe_dir.resolve()
        self.source_dir = source_dir.resolve()
        self.derived_dir = derived_dir.resolve()
        self.runner = runner or self._default_runner
        self.snapshot_validator = snapshot_validator
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._cancellations: dict[str, threading.Event] = {}
        self._snapshot_validation_cache: dict[
            tuple[Any, ...], tuple[str, str, dict[str, Any] | None]
        ] = {}
        self._flood_validation_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._elevation_validation_cache: dict[tuple[Any, ...], dict[str, Any]] = {}

    def _load_recipe(self, filename: str) -> ScenarioRecipe:
        path = (self.recipe_dir / filename).resolve()
        if path.parent != self.recipe_dir:
            raise ValueError("recipe path escapes the configured recipe directory")
        try:
            return ScenarioRecipe.model_validate_json(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise ValueError(f"frozen recipe is unavailable: {path.name}") from error

    def recipe_for(self, selection: BuilderSelection) -> ScenarioRecipe:
        if selection.preset_id == OTANIEMI_PRESET_ID:
            return self._load_recipe(OTANIEMI_BASE_RECIPE)
        if selection.area is None:  # protected by model validation
            raise ValueError("no study area was selected")
        area = selection.area
        return ScenarioRecipe.model_validate(
            {
                "schema_version": "1.0",
                "profile_id": "finland-resilient-access-v1",
                "scenario_id": _custom_scenario_id(area),
                "name": "User-selected Finland resilient-access base network",
                "scenario_type": "resilient_access",
                "analysis_crs": "EPSG:3067",
                "network_context_buffer_m": 750,
                "area": PointRadiusArea(
                    center=LonLat(longitude=area.longitude, latitude=area.latitude),
                    radius_m=area.radius_m,
                ),
                "sources": [
                    {
                        "adapter_id": "osm",
                        "role": "base_network",
                        "required": True,
                        "parameters": {"overpass_timeout_s": 120},
                    }
                ],
            }
        )

    def catalog(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "profile_id": "finland-resilient-access-v1",
            "default_preset_id": OTANIEMI_PRESET_ID,
            "presets": [
                {
                    "id": OTANIEMI_PRESET_ID,
                    "name": "Otaniemi coast, Espoo",
                    "description": (
                        "Frozen low-lying coastal study area with archived OSM, NLS terrain, "
                        "SYKE flood-hazard, and City of Espoo context sources."
                    ),
                    "frozen": True,
                    "default_successor": True,
                }
            ],
            "location_limits": {
                "coordinate_crs": "EPSG:4326",
                "finland_preflight_envelope": [19.0, 59.0, 32.0, 70.5],
                "radius_m": {"minimum": 100, "maximum": 2_500, "default": 1_000},
                "network_context_buffer_m": 750,
            },
            "active_solver": {
                "scenario": "Kallio--Vallila",
                "unchanged": True,
                "message": (
                    "Building a successor base network does not replace or mutate the active "
                    "modal-filter experiment scenario."
                ),
            },
        }

    def _osm_declaration(self, recipe: ScenarioRecipe):
        return next(
            source
            for source in recipe.sources
            if source.adapter_id == "osm" and source.role == "base_network"
        )

    def _source_workspace(self, recipe: ScenarioRecipe) -> Path:
        return source_adapter_workspace(
            self.source_dir,
            recipe,
            self._osm_declaration(recipe),
        )

    def _source_pointer(self, recipe: ScenarioRecipe) -> Path:
        workspace = self._source_workspace(recipe)
        return workspace / f"{recipe.scenario_id}.osm-overpass.archive.json"

    def _derived_pointer(self, recipe: ScenarioRecipe) -> Path:
        return self.derived_dir / f"{recipe.scenario_id}-base-network" / "latest.json"

    def _snapshot_cache_key(self, latest_pointer: Path) -> tuple[Any, ...] | None:
        latest = _read_json(latest_pointer)
        snapshot_path = latest.get("snapshot_path") if latest else None
        if not isinstance(snapshot_path, str):
            return None
        snapshot = (latest_pointer.parent / snapshot_path).resolve()
        if latest_pointer.parent.resolve() not in snapshot.parents or not snapshot.is_dir():
            return None
        try:
            files = tuple(
                (
                    path.relative_to(snapshot).as_posix(),
                    path.stat().st_size,
                    path.stat().st_mtime_ns,
                )
                for path in sorted(snapshot.rglob("*"))
                if path.is_file()
            )
            pointer_stat = latest_pointer.stat()
        except OSError:
            return None
        return (
            latest_pointer.resolve().as_posix(),
            pointer_stat.st_size,
            pointer_stat.st_mtime_ns,
            files,
        )

    def _otaniemi_context_sources(self) -> list[dict[str, Any]]:
        full_recipe = self._load_recipe(OTANIEMI_SOURCE_RECIPE)
        workspace = self.source_dir / full_recipe.scenario_id
        manifests = sorted(workspace.glob("source-bundle.*.json"))
        compatible: list[SourceBundleManifest] = []
        bundle_errors: list[str] = []
        for path in manifests:
            document = _read_json(path)
            if not document or document.get("recipe_sha256") != full_recipe.sha256():
                continue
            try:
                manifest = SourceBundleManifest.model_validate(document)
                for source in manifest.sources:
                    for reference in source.source_files:
                        artifact = (workspace / reference.path).resolve()
                        if workspace.resolve() not in artifact.parents or not artifact.is_file():
                            raise ValueError(f"unsafe or missing source artifact {reference.path}")
                        payload = artifact.read_bytes()
                        if len(payload) != reference.byte_size:
                            raise ValueError(f"source artifact size mismatch: {reference.path}")
                        if hashlib.sha256(payload).hexdigest() != reference.sha256:
                            raise ValueError(f"source artifact checksum mismatch: {reference.path}")
                compatible.append(manifest)
            except (OSError, ValueError) as error:
                bundle_errors.append(f"{path.name}: {error}")
        bundled: dict[str, dict[str, Any]] = {}
        for manifest in compatible:
            for source in manifest.sources:
                bundled[source.declaration.adapter_id] = source.model_dump(mode="json")

        labels = {
            "syke": "SYKE coastal flood zones",
            "espoo_wfs": "City of Espoo municipal context",
        }
        sources: list[dict[str, Any]] = []
        for adapter_id, role in (("syke", "flood_hazard"), ("espoo_wfs", "municipal_context")):
            raw = bundled.get(adapter_id)
            snapshot = raw.get("snapshot_metadata", {}) if raw else {}
            coverage = raw.get("spatial_coverage", {}) if raw else {}
            sources.append(
                {
                    "adapter_id": adapter_id,
                    "name": labels[adapter_id],
                    "role": role,
                    "readiness": (
                        "archived" if raw else "invalid_archive" if bundle_errors else "missing"
                    ),
                    "available_offline": bool(raw),
                    "feature_count": snapshot.get("feature_count"),
                    "acquired_at": snapshot.get("acquired_at"),
                    "source_timestamp": snapshot.get("source_timestamp"),
                    "spatial_coverage": coverage.get("status", "unknown"),
                    "message": (
                        "Frozen source evidence is available; it does not itself establish "
                        "road passability or safety."
                        if raw
                        else (
                            "Frozen source evidence failed integrity validation: "
                            + bundle_errors[0]
                            if bundle_errors
                            else "No compatible frozen source bundle is available."
                        )
                    ),
                }
            )
        return sources

    @staticmethod
    def _elevation_cache_key(
        recipe: ScenarioRecipe,
        pointer: Path,
        workspace: Path,
    ) -> tuple[Any, ...] | None:
        pointer_document = _read_json(pointer)
        archive_name = pointer_document.get("archive_file") if pointer_document else None
        if not isinstance(archive_name, str) or Path(archive_name).name != archive_name:
            return None
        archive = workspace / archive_name
        try:
            pointer_stat = pointer.stat()
            archive_stat = archive.stat()
            with pointer.open("rb") as stream:
                pointer_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
            with archive.open("rb") as stream:
                archive_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        except OSError:
            return None
        return (
            recipe.sha256(),
            pointer.resolve().as_posix(),
            pointer_stat.st_size,
            pointer_stat.st_mtime_ns,
            pointer_sha256,
            archive.resolve().as_posix(),
            archive_stat.st_size,
            archive_stat.st_mtime_ns,
            archive_sha256,
        )

    def _otaniemi_elevation_source(self) -> dict[str, Any]:
        """Validate the frozen MML raster without consulting runtime credentials."""

        unavailable = {
            "adapter_id": "mml_elevation",
            "name": "National Land Survey elevation",
            "role": "elevation",
            "readiness": "credentials_required",
            "available_offline": False,
            "feature_count": None,
            "acquired_at": None,
            "source_timestamp": None,
            "spatial_coverage": "unknown",
            "message": (
                "No compatible frozen Elevation Model 2 m raster is available. "
                "Configure MML_API_KEY only for an explicit source refresh; preflight "
                "never reads the credential."
            ),
        }
        try:
            recipe = self._load_recipe(OTANIEMI_ELEVATION_RECIPE)
            declaration = next(
                source
                for source in recipe.sources
                if source.adapter_id == "mml_elevation" and source.role == "elevation"
            )
            workspace = source_adapter_workspace(self.source_dir, recipe, declaration)
            context = SourceAcquisitionContext(
                recipe=recipe,
                declaration=declaration,
                workspace=workspace,
            )
            adapter = MmlElevationAdapter(refresh=False)
            pointer = adapter.archive_pointer_path(context)
        except (OSError, StopIteration, ValueError) as error:
            return {
                **unavailable,
                "readiness": "invalid_archive",
                "message": f"Elevation source configuration is invalid: {error}",
            }
        if not pointer.is_file():
            return unavailable

        cache_key = self._elevation_cache_key(recipe, pointer, workspace)
        with self._lock:
            cached = self._elevation_validation_cache.get(cache_key) if cache_key else None
        if cached is not None:
            return cached.copy()

        try:
            metadata = adapter.acquire(context)
            manifest = adapter.archive_manifest
            assessment = adapter.assess_coverage(recipe)
            ncols = int(manifest["ncols"])
            nrows = int(manifest["nrows"])
            valid_cells = int(manifest["valid_cell_count"])
            nodata_cells = int(manifest["nodata_cell_count"])
            minimum = float(manifest["minimum_elevation_m"])
            maximum = float(manifest["maximum_elevation_m"])
        except (KeyError, MmlArchiveError, OSError, TypeError, ValueError) as error:
            return {
                **unavailable,
                "readiness": "invalid_archive",
                "message": f"Frozen elevation raster failed integrity validation: {error}",
            }

        summary = {
            "adapter_id": "mml_elevation",
            "name": "National Land Survey elevation",
            "role": "elevation",
            "readiness": "archived",
            "available_offline": True,
            # Raster cells are not vector features; expose their counts in the message.
            "feature_count": None,
            "acquired_at": metadata.acquired_at.isoformat(),
            "source_timestamp": metadata.source_timestamp,
            "spatial_coverage": assessment.status,
            "message": (
                f"Frozen 2 m elevation raster validated offline: {ncols:,} x {nrows:,} "
                f"cells ({valid_cells:,} values; {nodata_cells:,} NoData), with a "
                f"{minimum:g} to {maximum:g} m N2000 value range. Elevation is "
                "quality-control evidence only; it does not establish flooding, road "
                "passability, or route safety."
            ),
        }
        if cache_key is not None:
            with self._lock:
                self._elevation_validation_cache.clear()
                self._elevation_validation_cache[cache_key] = summary.copy()
        return summary

    def _otaniemi_flood_exposure(
        self,
        *,
        base_status: str,
        base_latest_pointer: Path,
        base_latest: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Return a verified exposure summary without implying road availability."""

        common = {
            "scope": "exposure_only",
            "passability_inferred": False,
        }
        if base_status != "verified_snapshot" or not base_latest:
            return {
                **common,
                "status": "base_unavailable",
                "message": "A verified base network is required before exposure can be checked.",
            }
        snapshot_path = base_latest.get("snapshot_path")
        if not isinstance(snapshot_path, str):
            return {
                **common,
                "status": "base_unavailable",
                "message": "The verified base pointer does not identify its snapshot.",
            }
        base_network_path = base_latest_pointer.parent / snapshot_path / "base-network.json"
        full_recipe = self._load_recipe(OTANIEMI_SOURCE_RECIPE)
        syke_declaration = next(
            source for source in full_recipe.sources if source.adapter_id == "syke"
        )
        syke_workspace = source_adapter_workspace(
            self.source_dir,
            full_recipe,
            syke_declaration,
        )
        syke_pointer = (
            syke_workspace
            / f"{full_recipe.scenario_id}.syke-coastal-flood.archive.json"
        )
        output_dir = self.derived_dir / f"{full_recipe.scenario_id}-flood-exposure"
        latest_pointer = output_dir / "latest.json"
        if not latest_pointer.is_file() or not syke_pointer.is_file():
            return {
                **common,
                "status": "not_built",
                "message": "No compatible frozen flood-exposure snapshot is published.",
            }
        cache_key = (
            self._snapshot_cache_key(base_latest_pointer),
            self._snapshot_cache_key(latest_pointer),
            *self._directory_stat_signature(syke_workspace),
        )
        cached = self._flood_validation_cache.get(cache_key)
        if cached:
            return cached
        try:
            snapshot_dir = validate_latest_flood_exposure(
                output_dir=output_dir,
                base_network_path=base_network_path,
                syke_pointer_path=syke_pointer,
            )
            document = _read_json(snapshot_dir / "flood-exposure.json")
            if not document:
                raise FloodExposureBuildError("flood exposure document is not valid JSON")
            counts = document.get("counts")
            if not isinstance(counts, dict):
                raise FloodExposureBuildError("flood exposure document lacks counts")
            exposed = counts["exposed_physical_segments_by_return_period"]
            lengths = counts["exposed_length_m_by_return_period"]
            review = counts["exposed_segments_needing_vertical_review_by_return_period"]
            summary = {
                **common,
                "status": "verified_exposure",
                "snapshot_id": document["snapshot_id"],
                "base_snapshot_id": document["base_network"]["snapshot_id"],
                "return_periods": {
                    period: {
                        "exposed_segments": exposed[period],
                        "exposed_length_m": lengths[period],
                        "vertical_review_segments": review[period],
                    }
                    for period in ("100", "1000")
                },
                "message": (
                    "Verified horizontal segment/polygon exposure only; road closure, "
                    "passability, and route safety are not inferred."
                ),
            }
        except (FloodExposureBuildError, KeyError, OSError, TypeError, ValueError) as error:
            summary = {
                **common,
                "status": "invalid_exposure",
                "message": f"Published flood exposure failed validation: {error}",
            }
        self._flood_validation_cache[cache_key] = summary
        return summary

    @staticmethod
    def _directory_stat_signature(directory: Path) -> tuple[Any, ...]:
        try:
            return tuple(
                (
                    path.relative_to(directory).as_posix(),
                    path.stat().st_size,
                    path.stat().st_mtime_ns,
                )
                for path in sorted(directory.rglob("*"))
                if path.is_file()
            )
        except OSError:
            return ()

    def preflight(self, selection: BuilderSelection) -> dict[str, Any]:
        recipe = self.recipe_for(selection)
        core = canonicalize_area(recipe)
        context = canonicalize_network_context(recipe, core)
        assessment = OsmOverpassAdapter(refresh=False).assess_coverage(recipe)
        source_pointer = self._source_pointer(recipe)
        source_manifest: dict[str, Any] = {}
        archive_ready = False
        source_readiness = "refresh_required"
        source_message = assessment.message
        if source_pointer.is_file():
            try:
                declaration = self._osm_declaration(recipe)
                adapter = OsmOverpassAdapter(refresh=False)
                adapter.acquire(
                    SourceAcquisitionContext(
                        recipe=recipe,
                        declaration=declaration,
                        workspace=self._source_workspace(recipe),
                    )
                )
                source_manifest = adapter.archive_manifest
                archive_ready = True
                source_readiness = "archived"
            except (OsmArchiveError, OSError, StopIteration, ValueError) as error:
                source_readiness = "invalid_archive"
                source_message = f"Frozen OSM archive failed integrity validation: {error}"

        latest_pointer = self._derived_pointer(recipe)
        latest = _read_json(latest_pointer)
        derived_status = "not_built"
        derived_message = "No compatible derived base-network snapshot is published."
        if latest_pointer.is_file():
            cache_key = self._snapshot_cache_key(latest_pointer)
            cached = self._snapshot_validation_cache.get(cache_key) if cache_key else None
            if cached:
                derived_status, derived_message, latest = cached
            else:
                try:
                    snapshot_dir = self.snapshot_validator(latest_pointer.parent, recipe)
                    latest = _read_json(latest_pointer)
                    if not latest:
                        raise BaseNetworkBuildError("latest snapshot pointer is not valid JSON")
                    derived_status = "verified_snapshot"
                    derived_message = f"Validated immutable snapshot at {snapshot_dir.name}."
                except (BaseNetworkBuildError, OSError, ValueError) as error:
                    derived_status = "invalid_snapshot"
                    derived_message = f"Published snapshot failed validation: {error}"
                if cache_key:
                    self._snapshot_validation_cache[cache_key] = (
                        derived_status,
                        derived_message,
                        latest,
                    )
        sources = [
            {
                "adapter_id": "osm",
                "name": "OpenStreetMap road network",
                "role": "base_network",
                "readiness": source_readiness,
                "available_offline": archive_ready,
                "feature_count": source_manifest.get("feature_count") if archive_ready else None,
                "acquired_at": source_manifest.get("acquired_at") if archive_ready else None,
                "source_timestamp": (
                    source_manifest.get("source_timestamp") if archive_ready else None
                ),
                "spatial_coverage": assessment.status,
                "message": source_message,
            }
        ]
        if selection.preset_id == OTANIEMI_PRESET_ID:
            sources.extend(self._otaniemi_context_sources())
            sources.extend(
                [
                    self._otaniemi_elevation_source(),
                    {
                        "adapter_id": "roadworks_geojson",
                        "name": "Roadworks interchange",
                        "role": "roadworks",
                        "readiness": "user_source_required",
                        "available_offline": False,
                        "spatial_coverage": "unknown",
                        "message": (
                            "No reliable anonymous live feed was found; a frozen, explicitly "
                            "attributed roadworks GeoJSON is required."
                        ),
                    },
                ]
            )
        analysis_artifacts = {
            "flood_exposure": (
                self._otaniemi_flood_exposure(
                    base_status=derived_status,
                    base_latest_pointer=latest_pointer,
                    base_latest=latest,
                )
                if selection.preset_id == OTANIEMI_PRESET_ID
                else {
                    "status": "not_requested",
                    "scope": "exposure_only",
                    "passability_inferred": False,
                    "message": "No flood source bundle has been acquired for this custom area.",
                }
            )
        }
        return {
            "schema_version": "1.0",
            "selection": selection.model_dump(mode="json", exclude_none=True),
            "recipe": {
                "scenario_id": recipe.scenario_id,
                "name": recipe.name,
                "sha256": recipe.sha256(),
                "analysis_crs": recipe.analysis_crs,
                "network_context_buffer_m": recipe.network_context_buffer_m,
            },
            "area": {
                "coordinate_crs": "EPSG:4326",
                "core_geometry": core.geojson,
                "core_bbox": _round_bounds(core.wgs84.bounds, 7),
                "core_area_km2": round(float(core.analysis.area) / 1_000_000, 3),
                "network_context_bbox": _round_bounds(context.wgs84.bounds, 7),
            },
            "sources": sources,
            "analysis_artifacts": analysis_artifacts,
            "offline_build_ready": archive_ready,
            "build": {
                "status": derived_status,
                "snapshot_id": (
                    latest.get("snapshot_id") if derived_status == "verified_snapshot" else None
                ),
                "message": derived_message,
            },
            "semantics": {
                "coverage_is_not_completeness": True,
                "base_network_only": True,
                "active_solver_unchanged": True,
                "flood_passability_inferred": False,
                "message": (
                    "Preflight validates bounds and local source readiness. It does not fetch "
                    "data, prove source completeness, infer closures, or change the active solver."
                ),
            },
        }

    def _default_runner(
        self,
        recipe: ScenarioRecipe,
        refresh: bool,
        cancelled: threading.Event,
        emit: BuildEventEmitter,
    ) -> dict[str, Any]:
        if cancelled.is_set():
            return {"cancelled": True}
        emit(
            "source_replay_started" if not refresh else "source_refresh_started",
            (
                "Replaying the frozen OSM archive."
                if not refresh
                else "Fetching one bounded OSM snapshot from the fixed Overpass endpoint."
            ),
            {"refresh": refresh},
        )
        result = build_base_network_snapshot(
            recipe,
            source_dir=self.source_dir,
            output_dir=self.derived_dir / f"{recipe.scenario_id}-base-network",
            refresh=refresh,
        )
        if cancelled.is_set():
            return {"cancelled": True, "published_snapshot_id": result.snapshot_id}
        emit(
            "snapshot_verified",
            "The base-network snapshot passed its independent artifact validation.",
            {"snapshot_id": result.snapshot_id},
        )
        return {
            "snapshot_id": result.snapshot_id,
            "node_count": result.node_count,
            "directed_edge_count": result.edge_count,
            "snapshot_path": str(result.snapshot_dir.relative_to(ROOT)),
            "scope": "base_network_only",
        }

    def _emit(
        self,
        job_id: str,
        event_type: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            events = job["events"]
            events.append(
                {
                    "sequence": len(events) + 1,
                    "type": event_type,
                    "message": message,
                    "timestamp": _utc_now(),
                    "details": details or {},
                }
            )
            job["updated_at"] = events[-1]["timestamp"]

    def start(self, request: BuilderBuildRequest) -> dict[str, Any]:
        recipe = self.recipe_for(request)
        with self._lock:
            if any(
                job["status"] in {"queued", "preflighting", "building", "cancellation_requested"}
                for job in self._jobs.values()
            ):
                raise RuntimeError("another scenario build is already active")
            job_id = str(uuid.uuid4())
            created_at = _utc_now()
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "created_at": created_at,
                "updated_at": created_at,
                "scenario_id": recipe.scenario_id,
                "refresh": request.refresh,
                "result": None,
                "error": None,
                "events": [],
            }
            cancelled = threading.Event()
            self._cancellations[job_id] = cancelled
        self._emit(job_id, "queued", "Base-network build queued.", {"refresh": request.refresh})

        thread = threading.Thread(
            target=self._run,
            args=(job_id, recipe, request.refresh, cancelled),
            name=f"scenario-build-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return self.get(job_id)

    def _run(
        self,
        job_id: str,
        recipe: ScenarioRecipe,
        refresh: bool,
        cancelled: threading.Event,
    ) -> None:
        try:
            with self._lock:
                self._jobs[job_id]["status"] = "preflighting"
            self._emit(job_id, "preflight_started", "Validating area and source readiness.")
            canonicalize_network_context(recipe)
            if cancelled.is_set():
                self._finish_cancelled(job_id)
                return
            with self._lock:
                self._jobs[job_id]["status"] = "building"
            self._emit(
                job_id,
                "build_started",
                "Building a deterministic analytical and browser network snapshot.",
            )
            result = self.runner(
                recipe,
                refresh,
                cancelled,
                lambda event_type, message, details=None: self._emit(
                    job_id, event_type, message, details
                ),
            )
            if cancelled.is_set() or result.get("cancelled"):
                self._finish_cancelled(job_id, result)
                return
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "verified"
                job["result"] = result
            self._emit(
                job_id,
                "complete",
                "Verified base-network artifact is ready. The active Kallio solver was unchanged.",
                {"snapshot_id": result.get("snapshot_id")},
            )
        except OsmArchiveError as error:
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "missing_archive"
                job["error"] = {
                    "code": "offline_archive_missing",
                    "message": str(error),
                }
            self._emit(
                job_id,
                "offline_archive_missing",
                "No matching frozen OSM archive exists. Review preflight, then explicitly "
                "allow a live refresh.",
            )
        except Exception as error:  # defensive background boundary
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "failed"
                job["error"] = {
                    "code": "build_failed",
                    "message": f"{type(error).__name__}: {error}",
                }
            self._emit(job_id, "failed", "The base-network build failed; no solver claim was made.")
        finally:
            with self._lock:
                self._cancellations.pop(job_id, None)

    def _finish_cancelled(
        self, job_id: str, result: dict[str, Any] | None = None
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["status"] = "cancelled"
            job["result"] = result
        message = "Build cancelled before a result was activated."
        if result and result.get("published_snapshot_id"):
            message = (
                "Cancellation arrived after immutable artifact publication; the active solver "
                "was still unchanged."
            )
        self._emit(job_id, "cancelled", message)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            # JSON round-trip gives callers an immutable snapshot of nested event data.
            return json.loads(json.dumps(job))

    def events(self, job_id: str, after: int = 0) -> dict[str, Any]:
        job = self.get(job_id)
        return {
            "job_id": job_id,
            "status": job["status"],
            "events": [event for event in job["events"] if event["sequence"] > after],
        }

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            event = self._cancellations.get(job_id)
            if event is None:
                return {"job_id": job_id, "accepted": False, "status": job["status"]}
            event.set()
            job["status"] = "cancellation_requested"
        self._emit(
            job_id,
            "cancellation_requested",
            "Cancellation requested. The current deterministic step will reach a safe checkpoint.",
        )
        return {"job_id": job_id, "accepted": True, "status": "cancellation_requested"}


__all__ = [
    "BuilderBuildRequest",
    "BuilderSelection",
    "PointRadiusSelection",
    "ScenarioBuilderService",
]
