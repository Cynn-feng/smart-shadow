"""Synthetic contract runner for ordered lineage multi-view control audits.

This runner composes the existing edit-lineage trace with scalar
observed/counterfactual deltas and already-evaluated matched-placebo routes.
It deliberately does not load images, fit a detector, or re-fit placebo
statistics.  Results are raw audit evidence only.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Sequence

from aigc.edit_lineage import EditLineageTrace, EditTraceStep
from aigc.lineage_view_control import (
    CONTROL_CANDIDATE,
    CONTROL_CONSISTENT,
    CONTROL_INSUFFICIENT,
    LineageViewControlObservation,
    ROUTE_CONSISTENT,
    ROUTE_INCONSISTENT,
    ROUTE_INSUFFICIENT,
    evaluate_lineage_view_control,
)


PROTOCOL_VERSION = "lineage-view-control-synthetic-v1"
MASK_DIGEST = "a" * 64


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _trace(case_id: str, steps: Sequence[EditTraceStep], *, bound: bool = True) -> EditLineageTrace:
    return EditLineageTrace(
        asset_id=f"asset-{case_id}",
        source_version_id=f"source-{case_id}",
        observed_version_id=f"observed-{case_id}",
        detector_version="source-residual-v1",
        score_schema="regional-delta-v1",
        steps=tuple(steps),
        pair_id=f"pair-{case_id}",
        transform_family="identity",
        canonical_frame_digest="b" * 64,
        manifest_digest="c" * 64 if bound else None,
        binding_digest="d" * 64,
    )


def _observations(
    trace: EditLineageTrace,
    support_by_step: Dict[str, Iterable[int]],
    *,
    mismatch: bool = False,
    insufficient_control: bool = False,
) -> List[LineageViewControlObservation]:
    rows: List[LineageViewControlObservation] = []
    for view_order in (1, 2, 3):
        for step in trace.steps:
            supported = view_order in set(support_by_step.get(step.step_id, ()))
            route = CONTROL_INSUFFICIENT if insufficient_control else (
                CONTROL_CANDIDATE if supported else CONTROL_CONSISTENT
            )
            rows.append(
                LineageViewControlObservation(
                    trace_digest=trace.trace_digest,
                    asset_id=trace.asset_id if not mismatch else "other-asset",
                    pair_id=trace.pair_id or "pair-missing",
                    transform_family=trace.transform_family or "identity",
                    canonical_frame_digest=trace.canonical_frame_digest or "0" * 64,
                    manifest_digest=trace.manifest_digest or "0" * 64,
                    binding_digest=trace.binding_digest or "0" * 64,
                    detector_version=trace.detector_version,
                    score_schema=trace.score_schema,
                    view_id=f"view-{view_order}",
                    view_order=view_order,
                    view_spec_digest="e" * 64,
                    step_id=step.step_id,
                    region_id=step.output_region_ids[0],
                    operation_type=step.operation_type,
                    delta_raw=0.65 if supported else 0.12,
                    quality_score=0.9,
                    source_match_score=0.95,
                    control_route=route,
                    control_contrast_raw=0.5 if supported else -0.01,
                    control_p_value_raw=0.02 if supported else 0.8,
                    control_digest="f" * 64,
                    mask_overlap_raw=0.85,
                )
            )
    return rows


def build_cases() -> List[Dict[str, Any]]:
    ordered = _trace(
        "ordered",
        (
            EditTraceStep("s1", 1, "add", output_region_ids=("r1",), mask_digest=MASK_DIGEST),
            EditTraceStep(
                "s2", 2, "replace", parent_step_ids=("s1",), input_region_ids=("r1",),
                output_region_ids=("r2",), mask_digest=MASK_DIGEST,
            ),
        ),
    )
    ordinary = _trace(
        "ordinary",
        (EditTraceStep("s1", 1, "identity", output_region_ids=("r1",)),),
    )
    return [
        {
            "case_id": "ordered_consistent",
            "kind": "ordered_controlled_lineage",
            "trace": ordered,
            "observations": _observations(ordered, {"s1": (1, 2, 3), "s2": (2, 3)}),
            "expected": ROUTE_CONSISTENT,
        },
        {
            "case_id": "onset_reversed",
            "kind": "step_onset_order_inconsistent",
            "trace": ordered,
            "observations": _observations(ordered, {"s1": (2, 3), "s2": (1, 2)}),
            "expected": ROUTE_INCONSISTENT,
        },
        {
            "case_id": "ordinary_propagation",
            "kind": "ordinary_propagation_scope",
            "trace": ordinary,
            "observations": _observations(ordinary, {"s1": (1, 2, 3)}),
            "expected": ROUTE_INSUFFICIENT,
        },
        {
            "case_id": "binding_mismatch",
            "kind": "binding_fail_closed",
            "trace": ordered,
            "observations": _observations(ordered, {"s1": (1, 2, 3), "s2": (2, 3)}, mismatch=True),
            "expected": ROUTE_INSUFFICIENT,
        },
        {
            "case_id": "control_insufficient",
            "kind": "control_support_fail_closed",
            "trace": ordered,
            "observations": _observations(
                ordered, {"s1": (1, 2, 3), "s2": (2, 3)}, insufficient_control=True
            ),
            "expected": ROUTE_INSUFFICIENT,
        },
    ]


def run_synthetic_evaluation() -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for case in build_cases():
        result = evaluate_lineage_view_control(case["trace"], case["observations"])
        if result.route != case["expected"]:
            raise AssertionError(
                {"case_id": case["case_id"], "expected": case["expected"], "actual": result.route}
            )
        rows.append(
            {
                "case_id": case["case_id"],
                "kind": case["kind"],
                "route": result.route,
                "abstained": result.abstained,
                "reason": result.reason,
                "operation_scope": result.operation_scope,
                "step_count": result.step_count,
                "view_count": result.view_count,
                "supported_step_count": result.supported_step_count,
                "persistence_raw": result.persistence_raw,
                "ordered_consistency_raw": result.ordered_consistency_raw,
                "trace_digest": result.trace_digest,
                "config_digest": result.config_digest,
                "evidence_digest": result.evidence_digest,
                "control_digest": result.control_digest,
            }
        )
    route_counts: Dict[str, int] = {}
    for row in rows:
        route_counts[row["route"]] = route_counts.get(row["route"], 0) + 1
    canonical = {"version": PROTOCOL_VERSION, "cases": rows, "route_counts": route_counts}
    return {
        "version": PROTOCOL_VERSION,
        "scope": "synthetic scalar ordered-lineage/view/control contract only",
        "count": len(rows),
        "route_counts": route_counts,
        "cases": rows,
        "dataset_digest": _digest(canonical),
        "interpretation": (
            "raw control-backed lineage audit only; routes do not imply an AIGC "
            "probability, provenance, authorship, legal finding or formal FDR guarantee"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
