from __future__ import annotations

import copy
import json
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .service_coverage import (
    FrozenServiceCoverageScenario,
    ServiceCoverageRequest,
    solve_service_coverage,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SERVICE_COVERAGE_PATH = (
    ROOT
    / "data/derived/service-coverage-otaniemi-tapiola-v1/scenario.json"
)


class ServiceCoverageRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServiceCoverageSolveRequest(ServiceCoverageRequestModel):
    scenario_id: str = Field(min_length=1, max_length=120)
    site_budget: int = Field(default=4, ge=0, le=32)
    max_distance_m: float = Field(default=1_200, ge=100, le=5_000)
    capacity_multiplier: float = Field(default=1, ge=0.1, le=4)
    forced_site_ids: list[str] = Field(default_factory=list, max_length=40)
    banned_site_ids: list[str] = Field(default_factory=list, max_length=40)
    timeout_seconds: float = Field(default=30, ge=0.01, le=120)

    @model_validator(mode="after")
    def site_constraints_are_consistent(self) -> ServiceCoverageSolveRequest:
        for field_name in ("forced_site_ids", "banned_site_ids"):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must not contain duplicates")
        overlap = sorted(set(self.forced_site_ids) & set(self.banned_site_ids))
        if overlap:
            raise ValueError(
                "A candidate site cannot be both forced and prohibited: "
                + ", ".join(overlap)
            )
        return self

    def solver_request(self) -> ServiceCoverageRequest:
        return ServiceCoverageRequest(
            site_budget=self.site_budget,
            max_distance_m=self.max_distance_m,
            capacity_multiplier=self.capacity_multiplier,
            forced_site_ids=tuple(sorted(self.forced_site_ids)),
            banned_site_ids=tuple(sorted(self.banned_site_ids)),
            timeout_seconds=self.timeout_seconds,
        )


class ServiceCoverageCancelRequest(ServiceCoverageRequestModel):
    solve_id: str = Field(min_length=1, max_length=80)


class ServiceCoverageService:
    """Lazy, in-memory runtime over one checked frozen scenario artifact."""

    def __init__(
        self,
        artifact_path: str | Path = DEFAULT_SERVICE_COVERAGE_PATH,
        *,
        artifact: Mapping[str, Any] | None = None,
    ) -> None:
        self.artifact_path = Path(artifact_path)
        self._provided_artifact = copy.deepcopy(dict(artifact)) if artifact else None
        self._lock = threading.RLock()
        self._document: dict[str, Any] | None = None
        self._scenario: FrozenServiceCoverageScenario | None = None

    @property
    def scenario(self) -> FrozenServiceCoverageScenario:
        self._load()
        assert self._scenario is not None
        return self._scenario

    def scenario_payload(self) -> dict[str, Any]:
        self._load()
        assert self._document is not None
        browser = self._document.get("browser")
        if isinstance(browser, Mapping):
            payload = copy.deepcopy(dict(browser))
        else:
            payload = _fallback_browser_payload(self._document, self.scenario)
        payload.setdefault("id", self.scenario.scenario_id)
        payload.setdefault("scenario_id", self.scenario.scenario_id)
        payload.setdefault("snapshot_id", self.scenario.snapshot_id)
        return payload

    def solve(
        self,
        request: ServiceCoverageSolveRequest,
        *,
        cancel_event: threading.Event | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if request.scenario_id != self.scenario.scenario_id:
            return {
                "status": "data_error",
                "message": (
                    f"Requested scenario {request.scenario_id!r} does not match the frozen "
                    f"scenario {self.scenario.scenario_id!r}."
                ),
                "claim_scope": "No allocation or infeasibility claim was made.",
                "selected_site_ids": [],
                "assignments": [],
                "site_loads": [],
                "diagnostics": {"finding": "scenario_mismatch"},
                "snapshot_id": self.scenario.snapshot_id,
            }
        return solve_service_coverage(
            self.scenario,
            request.solver_request(),
            cancel_event=cancel_event,
            on_event=on_event,
        )

    def _load(self) -> None:
        with self._lock:
            if self._scenario is not None:
                return
            if self._provided_artifact is not None:
                document = copy.deepcopy(self._provided_artifact)
            else:
                document = json.loads(self.artifact_path.read_text(encoding="utf-8"))
            scenario_document = document.get("solver")
            if not isinstance(scenario_document, Mapping):
                scenario_document = document
            self._scenario = FrozenServiceCoverageScenario.from_artifact(
                scenario_document
            )
            self._document = document


def _fallback_browser_payload(
    document: Mapping[str, Any], scenario: FrozenServiceCoverageScenario
) -> dict[str, Any]:
    """Make diagnostic fixtures inspectable; production artifacts carry `browser`."""

    metadata = document.get("metadata")
    metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
    demand_source = {
        str(item.get("id")): item
        for item in document.get("demand", [])
        if isinstance(item, Mapping) and item.get("id") is not None
    }
    site_source = {
        str(item.get("id")): item
        for item in document.get("sites", [])
        if isinstance(item, Mapping) and item.get("id") is not None
    }

    population_cells: list[dict[str, Any]] = []
    for cell in scenario.demand:
        source = demand_source.get(cell.id, {})
        population_cells.append(
            {
                "id": cell.id,
                "label": cell.label,
                "district": cell.district_id or "Study area",
                "population": cell.population,
                "centroid": [cell.longitude, cell.latitude],
                **(
                    {"feature": copy.deepcopy(source["feature"])}
                    if isinstance(source, Mapping) and "feature" in source
                    else {}
                ),
            }
        )
    candidate_sites = [
        {
            "id": site.id,
            "label": site.label,
            "category": str(
                site_source.get(site.id, {}).get(
                    "category", "Reviewed public facility"
                )
            ),
            "point": [site.longitude, site.latitude],
            "eligible": site.eligible,
            "capacity_default": site.capacity,
            "capacity_status": "declared",
            "capacity_note": (
                "Analyst-declared sensitivity input; not observed facility throughput."
            ),
        }
        for site in scenario.sites
    ]
    longitudes = [item.longitude for item in (*scenario.demand, *scenario.sites)]
    latitudes = [item.latitude for item in (*scenario.demand, *scenario.sites)]
    bbox = [min(longitudes), min(latitudes), max(longitudes), max(latitudes)]
    return {
        "id": scenario.scenario_id,
        "name": str(metadata.get("name", "Equitable service coverage")),
        "description": str(
            metadata.get(
                "description",
                "Frozen walking-network service allocation over reviewed public facilities.",
            )
        ),
        "snapshot_id": scenario.snapshot_id,
        "snapshot_timestamp": str(metadata.get("snapshot_timestamp", "unknown")),
        "bbox": bbox,
        "center": [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2],
        "network": {"type": "FeatureCollection", "features": []},
        "population_cells": population_cells,
        "candidate_sites": candidate_sites,
        "defaults": copy.deepcopy(
            metadata.get(
                "defaults",
                {
                    "site_budget": 4,
                    "max_distance_m": 1_200,
                    "capacity_multiplier": 1,
                    "timeout_seconds": 30,
                },
            )
        ),
        "methodology": str(
            metadata.get(
                "methodology",
                "NetworkX compiled walking distances before Z3 solved the complete assignment.",
            )
        ),
        "attribution": str(
            metadata.get(
                "attribution",
                "© OpenStreetMap contributors · source metadata in the frozen artifact",
            )
        ),
    }
