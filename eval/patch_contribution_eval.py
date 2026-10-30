"""Synthetic regression for patch contribution/distraction auditing.

The runner uses scalar regional deltas only.  It verifies deterministic
leave-one-out/top-k mask-out routing and fail-closed behavior; it is not a
measurement of AIGC accuracy or real propagation robustness.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List

from aigc.patch_contribution import PatchContributionConfig, audit_patch_contributions
from aigc.patch_coverage import PatchDelta


def _patches(values: Iterable[float]) -> List[PatchDelta]:
    return [
        PatchDelta(
            region_id=f"r{index}",
            delta_raw=float(value),
            quality_score=0.90,
            source_match_score=0.90,
            detector_version="synthetic-detector-v1",
            score_schema="synthetic-delta-v1",
        )
        for index, value in enumerate(values)
    ]


def build_synthetic_cases() -> List[Dict[str, Any]]:
    return [
        {
            "case_id": "distributed_stable",
            "patches": _patches((0.45, 0.42, 0.48, 0.44)),
            "config": PatchContributionConfig(),
        },
        {
            "case_id": "global_distraction",
            "patches": _patches((0.95, 0.30, 0.30, 0.30)),
            "config": PatchContributionConfig(maximum_global_dominance=0.50),
        },
        {
            "case_id": "localized_expected",
            "patches": _patches((0.82, 0.02, 0.01, 0.01)),
            "config": PatchContributionConfig(),
        },
        {
            "case_id": "ambiguous_shape",
            "patches": _patches((0.80, 0.80, 0.02, 0.02)),
            "config": PatchContributionConfig(),
        },
        {
            "case_id": "no_positive",
            "patches": _patches((0.01, -0.02, 0.03, 0.02)),
            "config": PatchContributionConfig(),
        },
    ]


def _digest(cases: Iterable[Dict[str, Any]]) -> str:
    payload = [
        {
            "case_id": case["case_id"],
            "config": case["config"].to_dict(),
            "patches": [item.to_dict() for item in case["patches"]],
        }
        for case in cases
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def run_synthetic_evaluation() -> Dict[str, Any]:
    cases = build_synthetic_cases()
    outputs = []
    for case in cases:
        result = audit_patch_contributions(case["patches"], config=case["config"])
        outputs.append({"case_id": case["case_id"], "result": result.to_dict()})
    status_counts: Dict[str, int] = {}
    for item in outputs:
        status = item["result"]["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "version": "patch-contribution-synthetic-v1",
        "count": len(outputs),
        "dataset_digest": _digest(cases),
        "status_counts": status_counts,
        "cases": outputs,
        "interpretation": (
            "synthetic regression only; mask-out contribution is raw review "
            "evidence, not an AIGC probability, human/AI conclusion, or legal finding"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
