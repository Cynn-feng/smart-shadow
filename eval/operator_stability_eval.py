"""Synthetic contract runner for the D-051 multi-operator stability audit."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from aigc.operator_stability import (
    OperatorStabilityConfig,
    OperatorStabilityObservation,
    evaluate_operator_stability,
)


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row(
    operator_id: str,
    *,
    contrast: float = 0.35,
    swap_contrast: float = 0.30,
    route: str = "grounded_consistent",
    binding: str = "b" * 64,
    mask_out: bool = True,
    region_swap: bool = True,
    valid: bool = True,
    failure_reason=None,
) -> OperatorStabilityObservation:
    config_char = {"blur": "a", "swap": "b", "inpaint": "c"}.get(operator_id, "d")
    execution_char = {"blur": "1", "swap": "2", "inpaint": "3"}.get(operator_id, "4")
    return OperatorStabilityObservation(
        operator_id=operator_id,
        operator_config_digest=config_char * 64,
        operator_execution_digest=execution_char * 64,
        binding_digest=binding,
        asset_id="asset-1",
        pair_id="pair-1",
        manifest_digest="c" * 64,
        canonical_frame_digest="d" * 64,
        proposal_mask_digest="f" * 64,
        detector_version="detector-v1",
        score_schema="score-v1",
        null_profile_digest="1" * 64,
        quality_score=0.9,
        source_match_raw=0.9,
        null_quality_score=0.9,
        null_source_match_raw=0.9,
        operator_route=route,
        operator_validity=valid,
        mask_out_executed=mask_out,
        region_swap_executed=region_swap,
        observed_effect_raw=0.5 if mask_out else None,
        null_effect_raw=0.05 if mask_out else None,
        contrast_raw=contrast if mask_out else None,
        observed_swap_effect_raw=0.45 if region_swap else None,
        null_swap_effect_raw=0.05 if region_swap else None,
        swap_contrast_raw=swap_contrast if region_swap else None,
        failure_reason=failure_reason,
    )


def run() -> Dict[str, Any]:
    cases = [
        {
            "case_id": "stable",
            "observations": [_row("blur", contrast=0.35), _row("swap", contrast=0.40, swap_contrast=0.25)],
            "config": OperatorStabilityConfig(),
            "expected": "operator_stable_grounded",
        },
        {
            "case_id": "route_inconsistent",
            "observations": [_row("blur"), _row("swap", route="maskout_inconsistent")],
            "config": OperatorStabilityConfig(),
            "expected": "operator_inconsistent",
        },
        {
            "case_id": "spread_exceeded",
            "observations": [_row("blur", contrast=0.10), _row("swap", contrast=0.60)],
            "config": OperatorStabilityConfig(),
            "expected": "operator_inconsistent",
        },
        {
            "case_id": "intervention_missing",
            "observations": [_row("blur"), _row("swap", region_swap=False)],
            "config": OperatorStabilityConfig(),
            "expected": "operator_inconclusive",
        },
        {
            "case_id": "binding_mismatch",
            "observations": [_row("blur"), _row("swap", binding="9" * 64)],
            "config": OperatorStabilityConfig(),
            "expected": "insufficient",
        },
        {
            "case_id": "support_insufficient",
            "observations": [_row("blur")],
            "config": OperatorStabilityConfig(),
            "expected": "insufficient",
        },
    ]
    outputs: List[Dict[str, Any]] = []
    for case in cases:
        result = evaluate_operator_stability(case["observations"], config=case["config"])
        outputs.append(
            {
                "case_id": case["case_id"],
                "expected_route": case["expected"],
                "result": result.to_dict(),
                "expectation_met": result.route == case["expected"],
            }
        )
    return {
        "version": "operator-stability-synthetic-v1",
        "interpretation": "synthetic raw contract only; no operator route is an AIGC probability or legal finding",
        "count": len(outputs),
        "dataset_digest": _digest(outputs),
        "route_counts": {
            route: sum(1 for item in outputs if item["result"]["route"] == route)
            for route in sorted({item["result"]["route"] for item in outputs})
        },
        "all_expectations_met": all(item["expectation_met"] for item in outputs),
        "cases": outputs,
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True, indent=2))
