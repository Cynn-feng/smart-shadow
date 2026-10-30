"""Synthetic contract runner for D-058 invariant-effect-v1."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from aigc.invariant_effect import (
    InvariantEffectConfig,
    InvariantEffectObservation,
    InvariantNullSample,
    OPERATION_ORDINARY_PROPAGATION,
    evaluate_invariant_effect,
)


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hex(char: str) -> str:
    return char * 64


def _observations(*, contrast: float = 0.60, spread_operator: str | None = None, scope: str = "content_edit") -> List[InvariantEffectObservation]:
    rows: List[InvariantEffectObservation] = []
    for view_index in range(3):
        for operator_index, operator_id in enumerate(("blur", "swap")):
            value = contrast + (0.6 if spread_operator == operator_id else 0.0)
            for region_id in ("r0", "r1"):
                rows.append(
                    InvariantEffectObservation(
                        observation_id=f"o-{view_index}-{operator_id}-{region_id}",
                        asset_id="asset-1",
                        pair_id="pair-1",
                        manifest_digest=_hex("a"),
                        canonical_frame_digest=_hex("b"),
                        view_id=f"view-{view_index}",
                        view_digest=_hex(str(view_index + 1)),
                        operator_id=operator_id,
                        operator_config_digest=_hex("c" if operator_id == "blur" else "d"),
                        operator_execution_digest=_hex(str(operator_index + 5)),
                        region_id=region_id,
                        detector_version="detector-v1",
                        score_schema="score-v1",
                        null_profile_digest=_hex("e"),
                        quality_score=0.9,
                        source_match_raw=0.9,
                        observed_effect_raw=value + 0.1,
                        null_effect_raw=0.1,
                        operation_scope=scope,
                    )
                )
    return rows


def _nulls(count: int = 20, *, statistic: float = 0.05) -> List[InvariantNullSample]:
    return [
        InvariantNullSample(
            sample_id=f"n-{index}",
            group_id=f"g-{index}",
            calibration_dataset_digest=_hex("f"),
            null_profile_digest=_hex("e"),
            detector_version="detector-v1",
            score_schema="score-v1",
            transform_family="jpeg",
            quality_bucket="q2",
            statistic_raw=statistic,
        )
        for index in range(count)
    ]


def run() -> Dict[str, Any]:
    cases = [
        {
            "case_id": "stable_candidate",
            "observations": _observations(),
            "nulls": _nulls(),
            "expected": "invariant_candidate",
        },
        {
            "case_id": "ordinary_propagation",
            "observations": _observations(scope=OPERATION_ORDINARY_PROPAGATION),
            "nulls": _nulls(),
            "expected": "null_consistent",
        },
        {
            "case_id": "null_consistent",
            "observations": _observations(contrast=0.01),
            "nulls": _nulls(statistic=0.10),
            "expected": "null_consistent",
        },
        {
            "case_id": "operator_spread",
            "observations": _observations(spread_operator="swap"),
            "nulls": _nulls(),
            "expected": "view_operator_inconsistent",
        },
        {
            "case_id": "null_support_missing",
            "observations": _observations(),
            "nulls": _nulls(19),
            "expected": "insufficient",
        },
    ]
    outputs: List[Dict[str, Any]] = []
    for case in cases:
        result = evaluate_invariant_effect(case["observations"], case["nulls"], config=InvariantEffectConfig())
        outputs.append(
            {
                "case_id": case["case_id"],
                "expected_route": case["expected"],
                "result": result.to_dict(),
                "expectation_met": result.route == case["expected"],
            }
        )
    route_counts = {
        route: sum(item["result"]["route"] == route for item in outputs)
        for route in sorted({item["result"]["route"] for item in outputs})
    }
    return {
        "version": "invariant-effect-synthetic-v1",
        "interpretation": "synthetic raw contract only; no route is an AIGC probability or legal finding",
        "count": len(outputs),
        "dataset_digest": _digest(outputs),
        "route_counts": route_counts,
        "all_expectations_met": all(item["expectation_met"] for item in outputs),
        "cases": outputs,
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True, indent=2))
