from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import (
    CoverageAssessment,
    ScenarioRecipe,
    SourceDeclaration,
    SourceSnapshotMetadata,
)


class AdapterConfigurationError(ValueError):
    """Raised before acquisition when source adapter wiring is incomplete or ambiguous."""


@dataclass(frozen=True)
class SourceAcquisitionContext:
    recipe: ScenarioRecipe
    declaration: SourceDeclaration
    workspace: Path

    def __post_init__(self) -> None:
        if self.declaration not in self.recipe.sources:
            raise ValueError(
                f"source declaration {self.declaration.adapter_id!r} is not part of "
                f"recipe {self.recipe.scenario_id!r}"
            )
        if not self.workspace.is_absolute():
            raise ValueError("source acquisition workspace must be an absolute path")


def source_adapter_workspace(
    source_root: Path,
    recipe: ScenarioRecipe,
    declaration: SourceDeclaration,
) -> Path:
    """Return the canonical workspace for one declared scenario source.

    ``source_root`` is always the shared source-store root, never an adapter's
    workspace. Keeping the mapping here prevents acquisition and derivation
    entry points from interpreting ``--source-dir`` differently.
    """

    if declaration not in recipe.sources:
        raise ValueError(
            f"source declaration {declaration.adapter_id!r} is not part of "
            f"recipe {recipe.scenario_id!r}"
        )
    return source_root.resolve() / recipe.scenario_id / declaration.adapter_id


@runtime_checkable
class SourceAdapter(Protocol):
    """Contract implemented independently by OSM, MML, Espoo, and Syke adapters.

    Implementations assess source-specific coverage before acquiring raw data. An
    asynchronous job runner may call these synchronous, deterministic methods in a
    worker; network scheduling is intentionally outside this phase-one contract.
    """

    adapter_id: str

    def assess_coverage(self, recipe: ScenarioRecipe) -> CoverageAssessment: ...

    def acquire(self, context: SourceAcquisitionContext) -> SourceSnapshotMetadata: ...


class AdapterRegistry:
    """Immutable adapter lookup with fail-fast duplicate and missing-ID checks."""

    def __init__(self, adapters: list[SourceAdapter] | tuple[SourceAdapter, ...]) -> None:
        by_id: dict[str, SourceAdapter] = {}
        for adapter in adapters:
            adapter_id = getattr(adapter, "adapter_id", None)
            if not isinstance(adapter_id, str) or not adapter_id.strip():
                raise AdapterConfigurationError(
                    "every source adapter must expose a non-empty string adapter_id"
                )
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", adapter_id):
                raise AdapterConfigurationError(
                    f"invalid source adapter ID {adapter_id!r}; use 1--80 lowercase "
                    "letters, digits, dots, underscores, or hyphens"
                )
            if adapter_id in by_id:
                raise AdapterConfigurationError(
                    f"duplicate source adapter ID {adapter_id!r}; adapter IDs must be unique"
                )
            by_id[adapter_id] = adapter
        self._by_id = by_id

    @property
    def adapter_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_id))

    def resolve(self, recipe: ScenarioRecipe) -> tuple[SourceAdapter, ...]:
        missing = sorted(
            declaration.adapter_id
            for declaration in recipe.sources
            if declaration.adapter_id not in self._by_id
        )
        if missing:
            raise AdapterConfigurationError(
                "no registered source adapter for recipe declaration(s): " + ", ".join(missing)
            )
        return tuple(self._by_id[source.adapter_id] for source in recipe.sources)
