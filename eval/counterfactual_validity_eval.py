"""Synthetic contract runner for CIVG-v1.

The runner uses scalar fixture values and digest bindings only.  It emits raw
route/reason/support/digest records and explicitly marks real data as not
evaluated.  It does not load images, fit a detector, estimate a probability,
or make a provenance, authorship, or legal finding.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Tuple

from aigc.counterfactual_validity import (
    CONTENT_EDIT,
    DECOY,
    ORDINARY_PROPAGATION,
    WRONG_REFERENCE,
    CIVGObservation,
    ROUTE_INSUFFICIENT,
    ROUTE_INVALID,
    ROUTE_SPILLOVER,
    ROUTE_VALID,
    evaluate_civg,
)


VERSION = "counterfactual-validity-synthetic-v1"


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _observation(**overrides: Any) -> CIVGObservation:
    values: Dict[str, Any] = {
        "asset_id": "asset-synthetic",
        "pair_id": "pair-synthetic",
        "intervention_scope": CONTENT_EDIT,
        "reference_digest": "b" * 64,
        "observed_digest": "c" * 64,
        "counterfactual_digest": "d" * 64,
        "canonical_frame": "frame-v1",
        "detector_version": "detector-v1",
        "score_schema": "civg-score-v1",
        "authorized": True,
        "executed": True,
        "pair_binding_digest": "e" * 64,
        "ordinary_null_digest": "f" * 64,
        "target_mask_digest": "1" * 64,
        "operator_digest": "2" * 64,
        "execution_digest": "3" * 64,
        "quality_score": 0.95,
        "source_match_score": 0.90,
        "target_effect_raw": 0.80,
        "non_target_preservation_raw": 0.95,
        "mask_leakage_raw": 0.05,
        "semantic_consistency_raw": 0.90,
        "causal_consistency_raw": 0.88,
        "minimum_intervention_raw": 0.92,
    }
    values.update(overrides)
    return CIVGObservation(**values)


def build_cases() -> List[Tuple[str, CIVGObservation, str]]:
    """Return deterministic scalar cases and their expected raw routes."""

    return [
        ("valid_intervention", _observation(), ROUTE_VALID),
        (
            "spillover_non_target_and_mask_leakage",
            _observation(non_target_preservation_raw=0.50, mask_leakage_raw=0.80),
            ROUTE_SPILLOVER,
        ),
        (
            "target_effect_failure",
            _observation(target_effect_raw=0.0),
            ROUTE_INVALID,
        ),
        (
            "semantic_consistency_failure",
            _observation(semantic_consistency_raw=0.0),
            ROUTE_INVALID,
        ),
        (
            "causal_consistency_failure",
            _observation(causal_consistency_raw=0.0),
            ROUTE_INVALID,
        ),
        (
            "minimum_intervention_failure",
            _observation(minimum_intervention_raw=0.0),
            ROUTE_INVALID,
        ),
        (
            "missing_causal_signal",
            _observation(causal_consistency_raw=None),
            ROUTE_INSUFFICIENT,
        ),
        (
            "ordinary_propagation_scope",
            _observation(intervention_scope=ORDINARY_PROPAGATION),
            ROUTE_INVALID,
        ),
        ("decoy_scope", _observation(intervention_scope=DECOY), ROUTE_INVALID),
        (
            "wrong_reference_scope",
            _observation(intervention_scope=WRONG_REFERENCE),
            ROUTE_INVALID,
        ),
        ("unauthorized_input", _observation(authorized=False), ROUTE_INSUFFICIENT),
        ("execution_missing", _observation(executed=False), ROUTE_INSUFFICIENT),
        (
            "binding_missing",
            _observation(pair_binding_digest=None, target_mask_digest=None),
            ROUTE_INSUFFICIENT,
        ),
        (
            "observed_counterfactual_identical",
            _observation(counterfactual_digest="c" * 64),
            ROUTE_INVALID,
        ),
    ]


def run_synthetic_evaluation() -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for case_id, observation, expected_route in build_cases():
        result = evaluate_civg(observation)
        if result.route != expected_route:
            raise AssertionError(
                {
                    "case_id": case_id,
                    "expected": expected_route,
                    "actual": result.route,
                    "reason": result.reason,
                }
            )
        rows.append(
            {
                "case_id": case_id,
                "route": result.route,
                "reason": result.reason,
                "support": {
                    "abstained": result.abstained,
                    "downstream_eligible": result.downstream_eligible,
                    "failure_count": len(result.failure_reasons),
                },
                "digest": {
                    "config": result.config_digest,
                    "evidence": result.evidence_digest,
                },
            }
        )

    canonical = {"version": VERSION, "cases": rows}
    return {
        "real_data_status": "not_evaluated",
        "cases": rows,
        "digest": _digest(canonical),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
