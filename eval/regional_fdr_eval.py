"""Synthetic regression for group-matched regional selection.

This runner tests only the evidence contract: region-wise finite-sample
ordinary-propagation p-values, BH q-value selection, deterministic digests and
fail-closed support gates.  It is not an AIGC accuracy or FDR guarantee.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List

from aigc.regional_fdr import (
    RegionalFDRConfig,
    RegionNullDelta,
    RegionalQueryDelta,
    evaluate_regional_fdr,
    fit_regional_fdr_profile,
)


REGIONS = (
    ("r0", "object"),
    ("r1", "stuff"),
    ("r2", "background"),
    ("r3", "object"),
)


def build_null_stream(count: int = 24) -> List[RegionNullDelta]:
    values = []
    for index in range(count):
        for offset, (region_id, region_type) in enumerate(REGIONS):
            values.append(
                RegionNullDelta(
                    group_id=f"null-{index}",
                    transform_family="jpeg_q75",
                    quality_score=0.90,
                    region_id=region_id,
                    region_type=region_type,
                    delta_raw=0.02 + ((index + offset) % 3) * 0.01,
                    detector_version="synthetic-detector-v1",
                    score_schema="synthetic-delta-v1",
                )
            )
    return values


def build_query(case_id: str) -> List[RegionalQueryDelta]:
    cases = {
        "local_edit_candidate": (0.80, 0.03, 0.02, 0.04),
        "ordinary_propagation": (0.03, 0.04, 0.02, 0.03),
        "negative_delta": (-0.20, -0.10, -0.30, -0.05),
    }
    values = cases[case_id]
    return [
        RegionalQueryDelta(
            region_id=region_id,
            region_type=region_type,
            delta_raw=delta,
            quality_score=0.90,
            source_match_score=0.90,
            transform_family="jpeg_q75",
            detector_version="synthetic-detector-v1",
            score_schema="synthetic-delta-v1",
        )
        for (region_id, region_type), delta in zip(REGIONS, values)
    ]


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def run_synthetic_evaluation() -> Dict[str, Any]:
    config = RegionalFDRConfig(minimum_null_count=10, q_value=0.20)
    null_values = build_null_stream()
    profile = fit_regional_fdr_profile(null_values, config=config)
    case_ids = ("local_edit_candidate", "ordinary_propagation", "negative_delta")
    outputs = []
    for case_id in case_ids:
        result = evaluate_regional_fdr(profile, build_query(case_id), config=config)
        outputs.append({"case_id": case_id, "result": result.to_dict()})
    return {
        "version": "regional-fdr-synthetic-v1",
        "count": len(outputs),
        "profile_digest": profile.profile_digest,
        "dataset_digest": _digest([item.to_dict() for item in null_values]),
        "outputs": outputs,
        "interpretation": (
            "synthetic regional-selection regression only; BH/q-values and routes "
            "are raw evidence, not an AIGC probability or formal FDR guarantee"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
