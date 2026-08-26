from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PortalPair(BaseModel):
    model_config = ConfigDict(extra="ignore")

    a: str
    b: str
    label: str | None = None


class SolveRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    scenario_id: str = "helsinki-kallio-vallila"
    budget: int = Field(default=4, ge=0, le=20)
    required_portal_pairs: list[PortalPair] | None = None
    forced_interventions: list[str] = Field(default_factory=list)
    locked_open_streets: list[str] = Field(default_factory=list)
    emergency_permeable: bool = True
    service_access_enabled: bool = False
    objective_mode: Literal["balanced", "fewest", "access", "minimum_filters"] = "balanced"
    timeout_seconds: float = Field(default=10.0, ge=0.01, le=120.0)
    solve_id: str | None = None

    @field_validator("required_portal_pairs", mode="before")
    @classmethod
    def parse_pair_arrays(cls, value: Any) -> Any:
        if value is None:
            return None
        parsed: list[Any] = []
        for pair in value:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                parsed.append({"a": str(pair[0]), "b": str(pair[1])})
            else:
                parsed.append(pair)
        return parsed

    @field_validator("forced_interventions", "locked_open_streets")
    @classmethod
    def unique_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class NextSolutionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    solve_id: str
    timeout_seconds: float | None = Field(default=None, ge=0.01, le=120.0)


class CancelRequest(BaseModel):
    solve_id: str


class SolverEvent(BaseModel):
    type: str
    solve_id: str
    iteration: int = 0
    state: str
    message: str
    timestamp_ms: int
    payload: dict[str, Any] = Field(default_factory=dict)
