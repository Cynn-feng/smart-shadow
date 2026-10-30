"""Synthetic contract runner for source-conditioned matched interventions.

The runner only uses scalar scores.  It verifies full observation binding,
paired observed/null contrasts, region-swap controls and fail-closed routes;
it is not an AIGC benchmark and does not read images or call a detector.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from aigc.evidence_grounded_explanation import (
    ExplanationAuditConfig,
    ExplanationAuditObservation,
    OPERATION_SCOPE_CONTENT,
    OPERATION_SCOPE_PROPAGATION,
    evaluate_explanation_audit,
)


VERSION = "explanation-audit-synthetic-v2"
HEX = "a" * 64


def _observation(case_id: str, **kwargs: Any) -> ExplanationAuditObservation:
    values: Dict[str, Any] = {
        "asset_id": f"asset-{case_id}",
        "pair_id": f"pair-{case_id}",
        "transform_family": "identity",
        "transform_spec_digest": "0" * 64,
        "reference_digest": "1" * 64,
        "observed_digest": "2" * 64,
        "null_digest": "3" * 64,
        "manifest_digest": HEX,
        "canonical_frame_digest": "b" * 64,
        "detector_version": "source-residual-v1",
        "score_schema": "source-residual-score-v1",
        "operation_scope": OPERATION_SCOPE_CONTENT,
        "evidence_region_ids": ("region-1",),
        "taxonomy_version": "artifact-taxonomy-v1",
        "artifact_category": "boundary",
        "proposal_mask_digest": "c" * 64,
        "intervention_operator_digest": "d" * 64,
        "null_intervention_operator_digest": "d" * 64,
        "evidence_digest": "e" * 64,
        "crop_policy_digest": "f" * 64,
        "control_pair_id": f"pair-{case_id}-null",
        "null_profile_digest": "1" * 64,
        "intervention_execution_digest": "4" * 64,
        "quality_score": 0.90,
        "source_match_raw": 0.90,
        "null_quality_score": 0.90,
        "null_source_match_raw": 0.90,
        "score_before_raw": 0.80,
        "score_after_maskout_raw": 0.40,
        "score_after_region_swap_raw": 0.30,
        "null_score_before_raw": 0.50,
        "null_score_after_maskout_raw": 0.45,
        "null_score_after_region_swap_raw": 0.48,
        "observed_mask_out_executed": True,
        "null_mask_out_executed": True,
        "observed_region_swap_executed": True,
        "null_region_swap_executed": True,
        "human_review_ref": None,
    }
    values.update(kwargs)
    return ExplanationAuditObservation(**values)


def build_cases() -> List[Dict[str, Any]]:
    return [
        {
            "case_id": "matched_grounded",
            "observation": _observation("matched-grounded"),
            "config": ExplanationAuditConfig(),
            "expected": "grounded_consistent",
        },
        {
            "case_id": "null_explains_effect",
            "observation": _observation(
                "null-explains-effect",
                null_score_after_maskout_raw=0.15,
            ),
            "config": ExplanationAuditConfig(minimum_matched_contrast_raw=0.35),
            "expected": "maskout_inconsistent",
        },
        {
            "case_id": "maskout_inconsistent",
            "observation": _observation(
                "maskout-inconsistent", score_after_maskout_raw=0.76
            ),
            "config": ExplanationAuditConfig(),
            "expected": "maskout_inconsistent",
        },
        {
            "case_id": "swap_contrast_inconclusive",
            "observation": _observation(
                "swap-contrast-inconclusive",
                score_after_region_swap_raw=0.60,
                null_score_after_region_swap_raw=0.32,
            ),
            "config": ExplanationAuditConfig(),
            "expected": "inconclusive",
        },
        {
            "case_id": "swap_missing",
            "observation": _observation(
                "swap-missing",
                score_after_region_swap_raw=None,
                null_score_after_region_swap_raw=None,
                observed_region_swap_executed=False,
                null_region_swap_executed=False,
            ),
            "config": ExplanationAuditConfig(),
            "expected": "inconclusive",
        },
        {
            "case_id": "ordinary_propagation",
            "observation": _observation(
                "ordinary-propagation",
                operation_scope=OPERATION_SCOPE_PROPAGATION,
            ),
            "config": ExplanationAuditConfig(),
            "expected": "insufficient",
        },
        {
            "case_id": "source_mismatch",
            "observation": _observation(
                "source-mismatch", source_match_raw=0.20
            ),
            "config": ExplanationAuditConfig(),
            "expected": "insufficient",
        },
        {
            "case_id": "null_unstable",
            "observation": _observation(
                "null-unstable", null_score_after_maskout_raw=-0.10
            ),
            "config": ExplanationAuditConfig(),
            "expected": "insufficient",
        },
        {
            "case_id": "null_swap_unstable",
            "observation": _observation(
                "null-swap-unstable", null_score_after_region_swap_raw=-0.10
            ),
            "config": ExplanationAuditConfig(),
            "expected": "insufficient",
        },
        {
            "case_id": "operator_mismatch",
            "observation": _observation(
                "operator-mismatch", null_intervention_operator_digest="9" * 64
            ),
            "config": ExplanationAuditConfig(),
            "expected": "insufficient",
        },
        {
            "case_id": "null_maskout_missing",
            "observation": _observation(
                "null-maskout-missing", null_mask_out_executed=False
            ),
            "config": ExplanationAuditConfig(),
            "expected": "insufficient",
        },
        {
            "case_id": "unknown_artifact",
            "observation": _observation(
                "unknown-artifact", artifact_category="unknown"
            ),
            "config": ExplanationAuditConfig(),
            "expected": "inconclusive",
        },
    ]


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_synthetic_evaluation() -> Dict[str, Any]:
    cases = build_cases()
    outputs: List[Dict[str, Any]] = []
    for case in cases:
        result = evaluate_explanation_audit(case["observation"], config=case["config"])
        if result.route != case["expected"]:
            raise AssertionError(
                {
                    "case_id": case["case_id"],
                    "expected": case["expected"],
                    "actual": result.route,
                    "reason": result.reason,
                }
            )
        outputs.append(
            {
                "case_id": case["case_id"],
                "route": result.route,
                "abstained": result.abstained,
                "reason": result.reason,
                "faithfulness_delta_raw": result.faithfulness_delta_raw,
                "null_effect_raw": result.null_effect_raw,
                "contrast_faithfulness_raw": result.contrast_faithfulness_raw,
                "region_swap_delta_raw": result.region_swap_delta_raw,
                "null_region_swap_delta_raw": result.null_region_swap_delta_raw,
                "swap_contrast_raw": result.swap_contrast_raw,
                "binding_digest": result.binding_digest,
                "config_digest": result.config_digest,
                "explanation_digest": result.explanation_digest,
            }
        )
    route_counts: Dict[str, int] = {}
    for row in outputs:
        route_counts[row["route"]] = route_counts.get(row["route"], 0) + 1
    canonical = {
        "version": VERSION,
        "cases": outputs,
        "route_counts": route_counts,
    }
    return {
        "version": VERSION,
        "scope": "synthetic scalar source-conditioned matched-intervention contract only",
        "count": len(outputs),
        "route_counts": route_counts,
        "cases": outputs,
        "dataset_digest": _digest(canonical),
        "interpretation": (
            "synthetic raw contract only; matched intervention and region-swap "
            "contrasts are not AIGC probabilities, provenance proofs, legal "
            "findings, or measured detector effects"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
