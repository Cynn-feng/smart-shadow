"""Synthetic regression for dependency-aware joint null calibration.

This runner only checks group-matched ordinary-propagation calibration,
Cauchy evidence combination, conflict routing and fail-closed behavior.  It
does not measure AIGC accuracy, probability calibration, or deployment value.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List

from aigc.joint_null_calibration import (
    JointNullConfig,
    JointNullExample,
    evaluate_joint_null,
    fit_joint_null_profile,
)


DATASET_DIGEST = "a" * 64


def build_null_examples() -> List[JointNullExample]:
    return [
        JointNullExample(
            group_id=f"ordinary-{index}",
            p_values={
                "pixel_residual": 0.52 + 0.01 * (index % 3),
                "spectral": 0.58 + 0.01 * (index % 4),
            },
        )
        for index in range(20)
    ]


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_synthetic_evaluation() -> Dict[str, Any]:
    examples = build_null_examples()
    profile = fit_joint_null_profile(
        examples,
        dataset_digest=DATASET_DIGEST,
        minimum_count=20,
    )
    config = JointNullConfig(minimum_null_count=20)
    queries = [
        ("concordant_moderate", {"pixel_residual": 0.04, "spectral": 0.04}),
        ("ordinary_propagation", {"pixel_residual": 0.90, "spectral": 0.90}),
        ("stream_conflict", {"pixel_residual": 0.001, "spectral": 0.95}),
        ("profile_unavailable", {"pixel_residual": 0.04, "spectral": 0.04}),
    ]
    outputs = []
    for case_id, p_values in queries:
        result = evaluate_joint_null(
            p_values,
            None if case_id == "profile_unavailable" else profile,
            config=config,
        )
        outputs.append({"case_id": case_id, "result": result.to_dict()})
    status_counts: Dict[str, int] = {}
    for item in outputs:
        route = item["result"]["route"]
        status_counts[route] = status_counts.get(route, 0) + 1
    return {
        "version": "joint-stream-null-synthetic-v1",
        "count": len(outputs),
        "dataset_digest": _digest({
            "null_examples": [item.to_dict() for item in examples],
            "queries": queries,
            "config": config.digest,
        }),
        "profile_digest": profile.profile_digest,
        "status_counts": status_counts,
        "cases": outputs,
        "interpretation": (
            "synthetic regression only; joint null calibration is raw evidence, "
            "not an AIGC probability, human/AI conclusion, or legal finding"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
