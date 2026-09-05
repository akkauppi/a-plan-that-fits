from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from scripts import build_service_coverage_scenario as pipeline

ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = ROOT / "data" / "derived" / "service-coverage-otaniemi-tapiola-v1"


def _artifact() -> dict:
    return json.loads((OUTPUT_DIR / "scenario.json").read_text(encoding="utf-8"))


def test_snapshot_fingerprint_binds_all_nested_snapshot_ids() -> None:
    artifact = _artifact()

    assert pipeline.computed_snapshot_id(artifact) == artifact["snapshot_id"]
    tampered = copy.deepcopy(artifact)
    tampered["solver"]["snapshot_id"] = "coverage-forged"

    with pytest.raises(pipeline.BuildError, match="snapshot identifiers disagree"):
        pipeline.validate_artifact(tampered)


@pytest.mark.parametrize(
    "tamper",
    [
        lambda browser: browser.update(description="Tampered browser description"),
        lambda browser: browser["attribution_sources"].pop(),
    ],
)
def test_snapshot_fingerprint_binds_browser_and_attribution_payload(tamper) -> None:
    artifact = _artifact()
    tampered = copy.deepcopy(artifact)
    tamper(tampered["browser"])

    with pytest.raises(pipeline.BuildError, match="normalized artifact content"):
        pipeline.validate_artifact(tampered)


def test_published_snapshot_rejects_same_size_file_hash_tampering(tmp_path: Path) -> None:
    for name in (*pipeline.PUBLISHED_ARTIFACT_NAMES, "metadata.json"):
        shutil.copy2(OUTPUT_DIR / name, tmp_path / name)

    browser_path = tmp_path / "browser.json"
    original = browser_path.read_bytes()
    assert original.endswith(b"\n")
    browser_path.write_bytes(original[:-1] + b" ")

    with pytest.raises(pipeline.BuildError, match="checksum mismatch for browser.json"):
        pipeline.validate_published_snapshot(tmp_path)


def test_published_snapshot_rejects_tampered_metadata_digest(tmp_path: Path) -> None:
    for name in (*pipeline.PUBLISHED_ARTIFACT_NAMES, "metadata.json"):
        shutil.copy2(OUTPUT_DIR / name, tmp_path / name)

    metadata_path = tmp_path / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["artifacts"][0]["sha256"] = "0" * 64
    pipeline.write_json(metadata_path, metadata)

    with pytest.raises(pipeline.BuildError, match="checksum mismatch"):
        pipeline.validate_published_snapshot(tmp_path)
