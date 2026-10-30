"""Synthetic regression runner for quality-aware near-duplicate fusion.

The runner creates several propagated versions of each synthetic asset.  A
low-quality version intentionally carries a high raw detector score so the
report can show how simple averaging differs from quality-aware fusion.  It
uses only the standard library and produces a digest of the complete audit
payload.  This is a fusion-protocol regression test, not a real-image AIGC
result or a calibrated production threshold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Sequence, Tuple

from aigc.near_duplicate import NearDuplicateObservation, fuse_near_duplicate_scores


PROTOCOL_VERSION = "near-duplicate-fusion-synthetic-v1"
DEFAULT_SEED = 20260920
DEFAULT_ASSET_COUNT = 4
DEFAULT_QUALITY_THRESHOLD = 0.35
DEFAULT_QUALITY_POWER = 2.0


def _clip(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _round(value: float) -> float:
    return round(float(value), 12)


def build_synthetic_versions(
    *, seed: int = DEFAULT_SEED, asset_count: int = DEFAULT_ASSET_COUNT
) -> Tuple[Tuple[NearDuplicateObservation, ...], ...]:
    """Generate deterministic same-asset propagation observations."""

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if isinstance(asset_count, bool) or not isinstance(asset_count, int) or asset_count < 1:
        raise ValueError("asset_count must be a positive integer")
    rng = random.Random(seed)
    assets: List[Tuple[NearDuplicateObservation, ...]] = []
    for index in range(asset_count):
        asset_id = f"synthetic-asset-{index:03d}"
        base = rng.uniform(0.45, 0.82)
        observations = (
            NearDuplicateObservation(
                asset_id,
                f"{asset_id}-original",
                _clip(base + rng.uniform(-0.025, 0.025)),
                0.98,
                "synthetic-detector-v1",
                "synthetic-score-v1",
                ("original",),
            ),
            NearDuplicateObservation(
                asset_id,
                f"{asset_id}-jpeg",
                _clip(base * 0.94 + rng.uniform(-0.035, 0.015)),
                0.78,
                "synthetic-detector-v1",
                "synthetic-score-v1",
                ("jpeg:q75",),
            ),
            NearDuplicateObservation(
                asset_id,
                f"{asset_id}-screenshot",
                _clip(base * 0.84 + rng.uniform(-0.045, 0.02)),
                0.55,
                "synthetic-detector-v1",
                "synthetic-score-v1",
                ("resize:0.8", "screenshot"),
            ),
            NearDuplicateObservation(
                asset_id,
                f"{asset_id}-reencoded",
                _clip(base * 0.79 + rng.uniform(-0.05, 0.02)),
                0.35,
                "synthetic-detector-v1",
                "synthetic-score-v1",
                ("jpeg:q40", "resize:0.6"),
            ),
            # A low-quality outlier receives a deliberately high score.  It is
            # retained for audit but excluded by the default quality gate.
            NearDuplicateObservation(
                asset_id,
                f"{asset_id}-low-quality",
                _clip(base + 0.22 + rng.uniform(-0.015, 0.015)),
                0.12,
                "synthetic-detector-v1",
                "synthetic-score-v1",
                ("screenshot", "jpeg:q20", "crop"),
            ),
        )
        assets.append(observations)
    return tuple(assets)


def _asset_report(
    observations: Sequence[NearDuplicateObservation],
    *,
    quality_threshold: float,
    quality_power: float,
) -> Dict[str, Any]:
    weighted = fuse_near_duplicate_scores(
        observations,
        minimum_quality=quality_threshold,
        quality_power=quality_power,
    )
    scores = [item.detector_score for item in observations]
    return {
        "asset_id": observations[0].asset_id,
        "version_count": len(observations),
        "single_original_score_raw": _round(observations[0].detector_score),
        "simple_mean_score_raw": _round(mean(scores)),
        "quality_weighted": weighted.to_dict(),
    }


def run_synthetic_evaluation(
    *,
    seed: int = DEFAULT_SEED,
    asset_count: int = DEFAULT_ASSET_COUNT,
    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
    quality_power: float = DEFAULT_QUALITY_POWER,
) -> Dict[str, Any]:
    if isinstance(quality_threshold, bool) or not isinstance(quality_threshold, (int, float)):
        raise ValueError("quality_threshold must be a finite number between 0 and 1")
    quality_threshold = float(quality_threshold)
    if not math.isfinite(quality_threshold) or not 0.0 <= quality_threshold <= 1.0:
        raise ValueError("quality_threshold must be a finite number between 0 and 1")
    if isinstance(quality_power, bool) or not isinstance(quality_power, (int, float)):
        raise ValueError("quality_power must be a positive finite number")
    quality_power = float(quality_power)
    if not math.isfinite(quality_power) or quality_power <= 0.0:
        raise ValueError("quality_power must be a positive finite number")
    assets = build_synthetic_versions(seed=seed, asset_count=asset_count)
    reports = [
        _asset_report(
            observations,
            quality_threshold=quality_threshold,
            quality_power=quality_power,
        )
        for observations in assets
    ]
    simple_scores = [item["simple_mean_score_raw"] for item in reports]
    weighted_scores = [item["quality_weighted"]["weighted_score_raw"] for item in reports]
    single_scores = [item["single_original_score_raw"] for item in reports]
    digest_payload = {
        "protocol": PROTOCOL_VERSION,
        "seed": seed,
        "asset_count": asset_count,
        "quality_threshold": quality_threshold,
        "quality_power": quality_power,
        "assets": reports,
    }
    canonical = json.dumps(digest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "protocol": PROTOCOL_VERSION,
        "dataset_identity": {
            "seed": seed,
            "asset_count": asset_count,
            "quality_threshold": quality_threshold,
            "quality_power": quality_power,
        },
        "dataset_digest": digest,
        "summary": {
            "single_original_mean_raw": mean(single_scores),
            "simple_mean_of_versions_raw": mean(simple_scores),
            "quality_weighted_mean_raw": mean(weighted_scores),
            "quality_weighted_minus_simple_raw": mean(weighted_scores) - mean(simple_scores),
        },
        "assets": reports,
        "interpretation": (
            "synthetic regression only; all detector scores and fusion outputs are raw observations, "
            "not calibrated AIGC probabilities or legal conclusions"
        ),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate quality-aware near-duplicate score fusion")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--asset-count", type=int, default=DEFAULT_ASSET_COUNT)
    parser.add_argument("--quality-threshold", type=float, default=DEFAULT_QUALITY_THRESHOLD)
    parser.add_argument("--quality-power", type=float, default=DEFAULT_QUALITY_POWER)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    payload = run_synthetic_evaluation(
        seed=args.seed,
        asset_count=args.asset_count,
        quality_threshold=args.quality_threshold,
        quality_power=args.quality_power,
    )
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
