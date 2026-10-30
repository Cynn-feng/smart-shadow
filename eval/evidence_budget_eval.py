"""Synthetic regression for the bounded A9 evidence-acquisition planner."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List

from aigc.evidence_budget import (
    EvidenceAcquisitionConfig,
    EvidenceAcquisitionState,
    plan_evidence_acquisition,
)


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _state(case: Dict[str, Any]) -> EvidenceAcquisitionState:
    values = {
        "asset_id": case["case_id"],
        "detector_version": "source-residual-v1",
        "score_schema": "source-residual-score-v1",
        "quality_score": case.get("quality_score", 0.9),
        "source_match_score": case.get("source_match_score", 0.9),
        "regional_coverage_raw": case.get("regional_coverage_raw"),
        "null_evaluated": case.get("null_evaluated", False),
        "null_rejected": case.get("null_rejected", False),
        "shape_ambiguous": case.get("shape_ambiguous", False),
        "provenance_verified": case.get("provenance_verified", False),
        "uncertainty_raw": case.get("uncertainty_raw"),
        "completed_actions": tuple(case.get("completed_actions", ())),
    }
    return EvidenceAcquisitionState(**values)


def run_synthetic_evaluation() -> Dict[str, Any]:
    fixtures: List[Dict[str, Any]] = [
        {
            "case_id": "missing-null-and-provenance",
            "null_evaluated": False,
            "provenance_verified": False,
            "shape_ambiguous": True,
        },
        {
            "case_id": "quality-insufficient",
            "quality_score": 0.2,
            "null_evaluated": False,
        },
        {
            "case_id": "budget-review",
            "provenance_verified": True,
            "null_evaluated": False,
        },
        {
            "case_id": "no-policy-gap",
            "provenance_verified": True,
            "null_evaluated": True,
            "regional_coverage_raw": 0.95,
            "uncertainty_raw": 0.1,
        },
    ]
    config = EvidenceAcquisitionConfig(max_actions=2, max_cost_units=3)
    outputs = []
    for fixture in fixtures:
        result = plan_evidence_acquisition(_state(fixture), config=config)
        outputs.append(
            {
                "case_id": fixture["case_id"],
                "result": result.to_dict(),
            }
        )
    status_counts: Dict[str, int] = {}
    for item in outputs:
        status = item["result"]["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "version": "evidence-acquisition-synthetic-v1",
        "count": len(outputs),
        "dataset_digest": _digest(fixtures),
        "config_digest": config.digest,
        "status_counts": status_counts,
        "cases": outputs,
        "interpretation": (
            "synthetic regression only; the planner schedules raw observations and "
            "does not determine AIGC, authorship or legal status"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
