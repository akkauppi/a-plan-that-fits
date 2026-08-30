#!/usr/bin/env python3
"""Build a bounded resilient-access base network from a versioned recipe.

This is intentionally a base-network-only path beside ``build_scenario.py``. It
does not create flood hazards, roadworks, origins, destinations, or solver actions.
The default command is offline and requires a previously archived OSM response;
``--refresh`` is the only mode that contacts the adapter-controlled Overpass URL.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.scenario_builder.base_network import (  # noqa: E402
    BaseNetworkBuildError,
    build_base_network_snapshot,
    validate_latest_base_network,
)
from services.scenario_builder.models import ScenarioRecipe  # noqa: E402
from services.scenario_builder.osm import OsmArchiveError  # noqa: E402


def load_recipe(path: Path) -> ScenarioRecipe:
    try:
        return ScenarioRecipe.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise BaseNetworkBuildError(f"cannot read recipe {path}: {error}") from error
    except ValidationError as error:
        raise BaseNetworkBuildError(f"invalid scenario recipe {path}:\n{error}") from error


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a validated, immutable base-network snapshot from an OSM recipe. "
            "The recipe must declare adapter_id 'osm' with role 'base_network'; its only "
            "supported parameter is overpass_timeout_s (10--120)."
        )
    )
    parser.add_argument("--recipe", type=Path, required=True, help="Versioned recipe JSON")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=ROOT / "data" / "source" / "scenario-builder",
        help=(
            "Source-store root; the OSM workspace is always resolved as "
            "<source-dir>/<scenario-id>/osm"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "Snapshot output root; defaults to data/derived/<scenario-id>-base-network"
        ),
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Explicitly contact the fixed Overpass endpoint and publish a new source archive",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help=(
            "Validate the latest derived snapshot without reading or refreshing the source archive"
        ),
    )
    args = parser.parse_args(argv)
    if args.refresh and args.validate_only:
        parser.error("--refresh and --validate-only cannot be used together")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        recipe = load_recipe(args.recipe.resolve())
        output_dir = (
            args.output_dir.resolve()
            if args.output_dir is not None
            else ROOT / "data" / "derived" / f"{recipe.scenario_id}-base-network"
        )
        if args.validate_only:
            snapshot_dir = validate_latest_base_network(output_dir, recipe)
            print(f"Validated base-network snapshot: {snapshot_dir}")
            return 0

        result = build_base_network_snapshot(
            recipe,
            source_dir=args.source_dir.resolve(),
            output_dir=output_dir,
            refresh=args.refresh,
        )
        mode = "refreshed and built" if args.refresh else "rebuilt offline"
        print(
            f"OSM base network {mode}: {result.snapshot_id} "
            f"({result.node_count} nodes, {result.edge_count} directed edges)"
        )
        print(f"Snapshot: {result.snapshot_dir}")
        print("Scope: base_network_only (no flood or roadworks capability)")
        return 0
    except (BaseNetworkBuildError, OsmArchiveError, ValueError) as error:
        print(f"Base-network build failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
