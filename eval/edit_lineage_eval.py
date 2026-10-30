"""Synthetic contract runner for operation-aware edit-lineage evidence.

The runner uses scalar regional raw deltas and explicit operation metadata.  It
checks ordered parent links, canonical region lineage, operation/mask gates,
quality/source gates and fail-closed binding context.  It does not load an
image or model and must not be interpreted as AIGC accuracy, probability, or
provenance verification.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Sequence

from aigc.edit_lineage import (
    EditLineageTrace,
    EditRegionEvidence,
    EditTraceStep,
    ROUTE_CONSISTENT,
    ROUTE_INCONSISTENT,
    ROUTE_INSUFFICIENT,
    evaluate_edit_lineage,
)


MASK = "a" * 64


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _trace(case_id: str, steps: Sequence[EditTraceStep], *, binding: bool = True) -> EditLineageTrace:
    return EditLineageTrace(
        asset_id=f"asset-{case_id}",
        source_version_id=f"source-{case_id}",
        observed_version_id=f"observed-{case_id}",
        detector_version="source-residual-v1",
        score_schema="regional-delta-v1",
        steps=tuple(steps),
        pair_id=f"pair-{case_id}",
        transform_family="identity" if case_id != "propagation" else "jpeg_q75",
        canonical_frame_digest="b" * 64,
        manifest_digest="c" * 64 if binding else None,
        binding_digest="d" * 64,
    )


def _evidence(step_id: str, region_id: str, delta: float, *, quality: float = 0.9, source: float = 0.95, overlap: float | None = 0.8) -> EditRegionEvidence:
    return EditRegionEvidence(
        step_id=step_id,
        region_id=region_id,
        delta_raw=delta,
        quality_score=quality,
        source_match_score=source,
        mask_overlap_raw=overlap,
    )


def build_cases() -> List[Dict[str, Any]]:
    return [
        {
            "case_id": "ordered",
            "kind": "ordered_content_edit",
            "trace": _trace(
                "ordered",
                (
                    EditTraceStep("s1", 1, "add", output_region_ids=("r1",), mask_digest=MASK),
                    EditTraceStep("s2", 2, "replace", parent_step_ids=("s1",), input_region_ids=("r1",), output_region_ids=("r2",), mask_digest=MASK),
                ),
            ),
            "evidence": [_evidence("s1", "r1", 0.62), _evidence("s2", "r2", 0.54)],
        },
        {
            "case_id": "propagation",
            "kind": "ordinary_propagation_trace",
            "trace": _trace(
                "propagation",
                (
                    EditTraceStep("s1", 1, "identity", output_region_ids=("r1",)),
                    EditTraceStep("s2", 2, "jpeg_reencode", parent_step_ids=("s1",), input_region_ids=("r1",), output_region_ids=("r1",)),
                ),
            ),
            "evidence": [_evidence("s1", "r1", 0.01), _evidence("s2", "r1", 0.02)],
        },
        {
            "case_id": "lineage-gap",
            "kind": "region_lineage_gap",
            "trace": _trace(
                "lineage-gap",
                (
                    EditTraceStep("s1", 1, "add", output_region_ids=("r1",), mask_digest=MASK),
                    EditTraceStep("s2", 2, "replace", parent_step_ids=("s1",), input_region_ids=("r9",), output_region_ids=("r2",), mask_digest=MASK),
                ),
            ),
            "evidence": [_evidence("s1", "r1", 0.55), _evidence("s2", "r2", 0.51)],
        },
        {
            "case_id": "binding-gap",
            "kind": "missing_manifest_binding",
            "trace": _trace(
                "binding-gap",
                (EditTraceStep("s1", 1, "add", output_region_ids=("r1",), mask_digest=MASK),),
                binding=False,
            ),
            "evidence": [_evidence("s1", "r1", 0.58)],
        },
        {
            "case_id": "quality-gap",
            "kind": "quality_insufficient",
            "trace": _trace(
                "quality-gap",
                (EditTraceStep("s1", 1, "inpaint", input_region_ids=("r1",), output_region_ids=("r1",), mask_digest=MASK),),
            ),
            "evidence": [_evidence("s1", "r1", 0.7, quality=0.1)],
        },
    ]


def run() -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for case in build_cases():
        result = evaluate_edit_lineage(case["trace"], case["evidence"])
        rows.append({
            "case_id": case["case_id"],
            "kind": case["kind"],
            "route": result.route,
            "abstained": result.abstained,
            "reason": result.reason,
            "operation_scope": result.operation_scope,
            "step_count": result.step_count,
            "accepted_step_count": result.accepted_step_count,
            "evidence_coverage_raw": result.evidence_coverage_raw,
            "ordered_consistency_raw": result.ordered_consistency_raw,
            "lineage_consistency_raw": result.lineage_consistency_raw,
            "operation_consistency_raw": result.operation_consistency_raw,
            "weighted_delta_raw": result.weighted_delta_raw,
            "trace_digest": result.trace_digest,
            "evidence_digest": result.evidence_digest,
            "config_digest": result.config_digest,
        })
    summary = {
        "consistent": sum(row["route"] == ROUTE_CONSISTENT for row in rows),
        "inconsistent": sum(row["route"] == ROUTE_INCONSISTENT for row in rows),
        "insufficient": sum(row["route"] == ROUTE_INSUFFICIENT for row in rows),
    }
    payload = {
        "version": "edit-lineage-synthetic-v1",
        "scope": "synthetic scalar edit-trace contract only",
        "cases": rows,
        "summary": summary,
    }
    payload["dataset_digest"] = _digest(payload)
    return payload


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
