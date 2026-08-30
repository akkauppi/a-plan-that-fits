#!/usr/bin/env python3
"""Build an offline, exposure-only coastal-flood overlay.

No network adapter is invoked by this command. Both the base network and the
content-addressed SYKE source pointer must already exist and pass verification.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.scenario_builder.flood_exposure import (  # noqa: E402
    FloodExposureBuildError,
    build_flood_exposure_snapshot,
    validate_latest_flood_exposure,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Intersect one verified frozen base network with the audited SYKE 1/100 and "
            "1/1000 coastal-hazard archives. The result is exposure evidence only; it does "
            "not infer closures, passability, or safe routes."
        )
    )
    parser.add_argument(
        "--base-network",
        type=Path,
        required=True,
        help="Path to base-network.json inside a validated immutable snapshot",
    )
    parser.add_argument(
        "--syke-pointer",
        type=Path,
        required=True,
        help="Path to the verified *.syke-coastal-flood.archive.json pointer",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Destination root for immutable flood-exposure snapshots",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Revalidate the latest output and both frozen input identities without rebuilding",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.validate_only:
            snapshot = validate_latest_flood_exposure(
                output_dir=args.output_dir,
                base_network_path=args.base_network,
                syke_pointer_path=args.syke_pointer,
            )
            print(f"Validated flood-exposure snapshot: {snapshot}")
            print("Scope: exposure_only; road passability and closures are not inferred")
            return 0
        result = build_flood_exposure_snapshot(
            base_network_path=args.base_network,
            syke_pointer_path=args.syke_pointer,
            output_dir=args.output_dir,
        )
        counts = result.exposed_segment_counts
        print(
            f"Built flood-exposure snapshot {result.snapshot_id}: "
            f"{result.physical_segment_count} physical segments; "
            f"{counts[100]} exposed at 1/100 and {counts[1_000]} at 1/1000"
        )
        print(f"Snapshot: {result.snapshot_dir}")
        print("Scope: exposure_only; road passability and closures are not inferred")
        return 0
    except (FloodExposureBuildError, OSError, ValueError) as error:
        print(f"Flood-exposure build failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
