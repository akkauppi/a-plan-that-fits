#!/usr/bin/env python3
"""Acquire or replay a bounded bundle of resilient-access source evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.scenario_builder.adapters import AdapterConfigurationError  # noqa: E402
from services.scenario_builder.models import ScenarioRecipe  # noqa: E402
from services.scenario_builder.source_bundle import (  # noqa: E402
    SourceBundleError,
    acquire_source_bundle,
)


def _emit(value: dict[str, Any], *, stream: Any = sys.stdout) -> None:
    print(
        json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        file=stream,
        flush=True,
    )


def load_recipe(path: Path) -> ScenarioRecipe:
    try:
        return ScenarioRecipe.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise SourceBundleError(
            f"cannot read recipe {path}: {error}", code="recipe_read_failed"
        ) from error
    except ValidationError as error:
        raise SourceBundleError(
            f"invalid scenario recipe {path}: {error}", code="recipe_validation_failed"
        ) from error


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Assess and acquire a deterministic source-evidence bundle. Offline verified "
            "replay is the default; --refresh is the only network-acquisition mode."
        )
    )
    parser.add_argument("--recipe", type=Path, required=True, help="Versioned recipe JSON")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=ROOT / "data" / "source" / "scenario-builder",
        help="Root containing one persistent source workspace per scenario",
    )
    parser.add_argument(
        "--adapter",
        action="append",
        dest="adapters",
        help=(
            "Acquire one declared adapter ID; repeat for a subset. The default is all recipe "
            "declarations. Recipe order always controls acquisition order."
        ),
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Explicitly contact adapter-controlled remote endpoints before verification",
    )
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help=(
            "Run read-only configuration, bounds, local-pointer, and spatial-coverage "
            "preflight; acquire and publish nothing"
        ),
    )
    args = parser.parse_args(argv)
    if args.refresh and args.coverage_only:
        parser.error("--refresh and --coverage-only cannot be used together")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        recipe = load_recipe(args.recipe.resolve())
        result = acquire_source_bundle(
            recipe,
            source_dir=args.source_dir.resolve(),
            selected_adapter_ids=args.adapters,
            refresh=args.refresh,
            coverage_only=args.coverage_only,
            on_coverage=_emit,
        )
        if args.coverage_only:
            _emit(
                {
                    "event": "source_preflight_complete",
                    "ok": True,
                    "scenario_id": recipe.scenario_id,
                    "manifest_published": False,
                }
            )
            return 0
        assert result.manifest is not None and result.manifest_path is not None
        _emit(
            {
                "event": "source_bundle_published",
                "ok": True,
                "scenario_id": recipe.scenario_id,
                "acquisition_mode": "explicit_refresh" if args.refresh else "offline_replay",
                "selected_adapter_ids": result.manifest.selected_adapter_ids,
                "manifest": str(result.manifest_path),
                "scope": result.manifest.scope,
                "derived_scenario_created": False,
            }
        )
        return 0
    except SourceBundleError as error:
        _emit(
            {"event": "source_bundle_error", "ok": False, "error": error.as_dict()},
            stream=sys.stderr,
        )
        return 2
    except (AdapterConfigurationError, ValueError) as error:
        # AdapterConfigurationError is kept separate in the public contract, while
        # this CLI still gives it the same machine-readable failure envelope.
        _emit(
            {
                "event": "source_bundle_error",
                "ok": False,
                "error": {"code": "source_configuration_error", "message": str(error)},
            },
            stream=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
