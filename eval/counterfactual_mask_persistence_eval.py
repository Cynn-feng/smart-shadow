"""Synthetic runner for the four-way counterfactual mask-persistence audit.

The runner uses scalar region IDs and fixed control masks only.  It does not
load images, train a detector, or claim an AIGC metric.  Its purpose is to
make the factual-positive, same-label-null, decoy, and wrong-reference gates
replayable before an authorised image manifest is available.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Sequence

from aigc.counterfactual_mask_persistence import (
    KIND_DECOY,
    KIND_FACTUAL,
    KIND_ORDINARY_PROPAGATION,
    KIND_WRONG_REFERENCE,
    ROUTE_INSUFFICIENT,
    ROUTE_MASK_INCONSISTENT,
    ROUTE_NULL_CONSISTENT,
    ROUTE_PERSISTENT_CANDIDATE,
    MaskPersistenceObservation,
    evaluate_counterfactual_mask_persistence,
)


VERSION = "counterfactual-mask-persistence-synthetic-v1"
HEX = "a" * 64
WRONG_REFERENCE = "b" * 64


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row(kind: str, view: int, regions: Sequence[str] = (), *, reference: str = HEX, overlap: float = 0.90, quality: float = 0.90) -> MaskPersistenceObservation:
    return MaskPersistenceObservation(
        asset_id="asset-synthetic",
        pair_id="pair-synthetic",
        view_id=f"view-{view}",
        view_order=view,
        kind=kind,
        canonical_frame_digest="c" * 64,
        manifest_digest="d" * 64,
        detector_version="source-residual-v1",
        score_schema="source-residual-score-v1",
        proposal_mask_digest="e" * 64,
        operator_digest="f" * 64,
        view_spec_digest=("1" * 63) + str(view),
        reference_digest=reference,
        observed_digest="2" * 64,
        evidence_region_ids=tuple(regions),
        quality_score=quality,
        source_match_score=0.90,
        mask_overlap_raw=overlap if kind == KIND_FACTUAL else None,
    )


def _four_way(*, factual=("r1", "r2"), ordinary=(), decoy=(), wrong=(), wrong_reference=WRONG_REFERENCE, factual_overlap=0.90):
    rows: List[MaskPersistenceObservation] = []
    for view in (1, 2, 3):
        rows.extend(
            (
                _row(KIND_FACTUAL, view, factual, overlap=factual_overlap),
                _row(KIND_ORDINARY_PROPAGATION, view, ordinary),
                _row(KIND_DECOY, view, decoy),
                _row(KIND_WRONG_REFERENCE, view, wrong, reference=wrong_reference),
            )
        )
    return rows


def build_cases() -> List[Dict[str, Any]]:
    unstable: List[MaskPersistenceObservation] = []
    for view, region in ((1, "r1"), (2, "r2"), (3, "r3")):
        unstable.extend(
            (
                _row(KIND_FACTUAL, view, (region,)),
                _row(KIND_ORDINARY_PROPAGATION, view),
                _row(KIND_DECOY, view),
                _row(KIND_WRONG_REFERENCE, view, reference=WRONG_REFERENCE),
            )
        )
    return [
        {
            "case_id": "factual_persistent_controls_quiet",
            "kind": "factual_positive",
            "observations": _four_way(),
            "expected": ROUTE_PERSISTENT_CANDIDATE,
        },
        {
            "case_id": "ordinary_null_hallucination",
            "kind": "same_label_null",
            "observations": _four_way(ordinary=("r1",)),
            "expected": ROUTE_NULL_CONSISTENT,
        },
        {
            "case_id": "decoy_unrelated_mask",
            "kind": "decoy_absent_from_target",
            "observations": _four_way(decoy=("unrelated",)),
            "expected": ROUTE_PERSISTENT_CANDIDATE,
        },
        {
            "case_id": "factual_mask_unstable",
            "kind": "factual_mask_inconsistent",
            "observations": unstable,
            "expected": ROUTE_MASK_INCONSISTENT,
        },
        {
            "case_id": "missing_decoy_control",
            "kind": "control_support_missing",
            "observations": [row for row in _four_way() if row.kind != KIND_DECOY],
            "expected": ROUTE_INSUFFICIENT,
        },
        {
            "case_id": "wrong_reference_not_distinct",
            "kind": "control_binding_invalid",
            "observations": _four_way(wrong_reference=HEX),
            "expected": ROUTE_INSUFFICIENT,
        },
    ]


def run_synthetic_evaluation() -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for case in build_cases():
        result = evaluate_counterfactual_mask_persistence(case["observations"])
        if result.route != case["expected"]:
            raise AssertionError(
                {
                    "case_id": case["case_id"],
                    "expected": case["expected"],
                    "actual": result.route,
                    "reason": result.reason,
                }
            )
        rows.append(
            {
                "case_id": case["case_id"],
                "kind": case["kind"],
                "route": result.route,
                "abstained": result.abstained,
                "reason": result.reason,
                "factual_mask_persistence_raw": result.factual_mask_persistence_raw,
                "factual_set_jaccard_raw": result.factual_set_jaccard_raw,
                "null_mask_hallucination_rate_raw": result.null_mask_hallucination_rate_raw,
                "control_persistence_raw": dict(result.control_persistence_raw),
                "consensus_region_ids": list(result.consensus_region_ids),
                "binding_digest": result.binding_digest,
                "config_digest": result.config_digest,
                "evidence_digest": result.evidence_digest,
            }
        )
    route_counts: Dict[str, int] = {}
    for row in rows:
        route_counts[row["route"]] = route_counts.get(row["route"], 0) + 1
    canonical = {"version": VERSION, "cases": rows, "route_counts": route_counts}
    return {
        "version": VERSION,
        "scope": "synthetic scalar four-way counterfactual mask persistence contract only",
        "count": len(rows),
        "route_counts": route_counts,
        "cases": rows,
        "dataset_digest": _digest(canonical),
        "interpretation": (
            "raw mask persistence and null hallucination audit only; routes do not imply "
            "an AIGC probability, provenance, authorship, legal finding, or formal FDR guarantee"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
