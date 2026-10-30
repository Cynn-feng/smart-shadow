"""Synthetic contract runner for matched placebo counterfactual forensics.

The runner checks ties-inclusive finite-sample p-values, matched identity and
quality buckets, conservative control statistics, deterministic digests and
fail-closed routes.  It does not measure AIGC accuracy or produce a
probability, authorship result, formal error-rate guarantee or legal finding.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Mapping

from aigc.mpcf import (
    MPCFConfig,
    MPCFControlDelta,
    MPCFTarget,
    ROUTE_CANDIDATE_EDIT,
    ROUTE_CONTROL_CONSISTENT,
    ROUTE_INSUFFICIENT,
    evaluate_mpcf,
)
from aigc.regional_fdr import RegionalQueryDelta


PROTOCOL_VERSION = "mpcf-matched-placebo-synthetic-v1"
MANIFEST_DIGEST = "a" * 64
FRAME_DIGEST = "c" * 64
SPEC_DIGEST = "d" * 64


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def make_target(delta: float, *, quality: float = 0.90) -> MPCFTarget:
    return MPCFTarget(
        asset_id="asset-synthetic-1",
        pair_id="pair-synthetic-1",
        manifest_digest=MANIFEST_DIGEST,
        coordinate_frame_digest=FRAME_DIGEST,
        transform_spec_digest=SPEC_DIGEST,
        query_delta=RegionalQueryDelta(
            region_id="r0",
            region_type="object",
            delta_raw=delta,
            quality_score=quality,
            source_match_score=0.90,
            transform_family="jpeg_q75",
            detector_version="synthetic-source-residual-v1",
            score_schema="synthetic-source-residual-score-v1",
        ),
    )


def make_controls(values: Iterable[float], *, quality: float = 0.90, pair_id: str = "pair-synthetic-1") -> List[MPCFControlDelta]:
    return [
        MPCFControlDelta(
            control_id=f"placebo-{index}",
            asset_id="asset-synthetic-1",
            pair_id=pair_id,
            manifest_digest=MANIFEST_DIGEST,
            region_id="r0",
            region_type="object",
            transform_family="jpeg_q75",
            detector_version="synthetic-source-residual-v1",
            score_schema="synthetic-source-residual-score-v1",
            coordinate_frame_digest=FRAME_DIGEST,
            transform_spec_digest=SPEC_DIGEST,
            quality_score=quality,
            source_match_score=0.90,
            delta_raw=float(value),
        )
        for index, value in enumerate(values)
    ]


def _case(case_id: str, config: MPCFConfig) -> Dict[str, Any]:
    if case_id == "candidate_edit":
        target = make_target(0.80)
        controls = make_controls([0.10] * 24)
    elif case_id == "control_consistent":
        target = make_target(0.09)
        controls = make_controls([0.08 + 0.01 * (index % 4) for index in range(24)])
    elif case_id == "identity_mismatch":
        target = make_target(0.80)
        controls = make_controls([0.10] * 24, pair_id="wrong-pair")
    elif case_id == "quality_bucket_mismatch":
        target = make_target(0.80, quality=0.90)
        controls = make_controls([0.10] * 24, quality=0.79)
    elif case_id == "sample_insufficient":
        target = make_target(0.80)
        controls = make_controls([0.10] * 4)
    else:
        raise ValueError(f"unknown case: {case_id}")
    result = evaluate_mpcf(target, controls, config=config)
    return {
        "case_id": case_id,
        "result": result.to_dict(),
        "interpretation": "matched placebo raw evidence only",
    }


def run_synthetic_evaluation() -> Dict[str, Any]:
    config = MPCFConfig(minimum_control_count=20, alpha=0.05)
    cases = [
        _case(case_id, config)
        for case_id in (
            "candidate_edit",
            "control_consistent",
            "identity_mismatch",
            "quality_bucket_mismatch",
            "sample_insufficient",
        )
    ]
    expected = {
        "candidate_edit": ROUTE_CANDIDATE_EDIT,
        "control_consistent": ROUTE_CONTROL_CONSISTENT,
        "identity_mismatch": ROUTE_INSUFFICIENT,
        "quality_bucket_mismatch": ROUTE_INSUFFICIENT,
        "sample_insufficient": ROUTE_INSUFFICIENT,
    }
    actual = {case["case_id"]: case["result"]["route"] for case in cases}
    if actual != expected:
        raise AssertionError({"expected": expected, "actual": actual})
    route_counts: Dict[str, int] = {}
    for route in actual.values():
        route_counts[route] = route_counts.get(route, 0) + 1
    canonical = {
        "version": PROTOCOL_VERSION,
        "config": config.to_dict(),
        "cases": cases,
    }
    return {
        "version": PROTOCOL_VERSION,
        "count": len(cases),
        "config_digest": config.digest,
        "dataset_digest": _digest(canonical),
        "route_counts": route_counts,
        "cases": cases,
        "interpretation": (
            "synthetic matched-placebo raw evidence only; candidate_edit and "
            "control_consistent do not imply an AIGC four-state result, a "
            "probability, authorship, legal finding or formal error guarantee"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
