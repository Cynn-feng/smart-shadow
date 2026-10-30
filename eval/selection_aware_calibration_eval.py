"""Synthetic runner for selection-aware-calibration-v1."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any, Dict, List, Sequence

from aigc.selection_aware_calibration import (
    OPERATION_ORDINARY_PROPAGATION,
    SelectionAwareBatch,
    SelectionAwareCalibrationConfig,
    SelectionCalibrationGroup,
    evaluate_selection_aware_calibration,
)


def _hex(char: str) -> str:
    return char * 64


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _batch(*, candidate: float = 0.80, operation_scope: str = "content_edit", decoy_value: float | None = None) -> SelectionAwareBatch:
    decoys = (0.10, 0.15, 0.20) + (0.20,) * 21 if decoy_value is None else (decoy_value,) * 24
    refs = tuple(hashlib.sha256(f"saec-runner-decoy-{index}".encode()).hexdigest() for index in range(len(decoys)))
    return SelectionAwareBatch(
        query_digest=_hex("a"),
        query_group_id="query-group",
        candidate_reference_digest=_hex("b"),
        candidate_contrast_raw=candidate,
        decoy_reference_digests=refs,
        decoy_contrasts_raw=decoys,
        candidate_quality_score=0.9,
        candidate_source_match_raw=0.9,
        invariant_route="invariant_candidate",
        manifest_digest=_hex("c"),
        canonical_frame_digest=_hex("d"),
        transform_family="jpeg",
        quality_bucket="high",
        source_match_bucket="matched",
        detector_version="detector-v1",
        score_schema="contrast-v1",
        operator_set_digest=_hex("e"),
        selection_policy_digest=_hex("f"),
        selection_split_digest=_hex("1"),
        calibration_split_digest=_hex("2"),
        evaluation_split_digest=_hex("3"),
        calibration_dataset_digest=_hex("4"),
        profile_level="exact",
        null_profile_digest=_hex("5"),
        operation_scope=operation_scope,
    )


def _groups(*, count: int = 20, max_statistic: float = 0.01) -> Sequence[SelectionCalibrationGroup]:
    rows: List[SelectionCalibrationGroup] = []
    for index in range(count):
        rows.append(
            SelectionCalibrationGroup(
                group_id=f"group-{index}",
                max_statistic_raw=max_statistic,
                decoy_count=24,
                calibration_dataset_digest=_hex("4"),
                calibration_split_digest=_hex("2"),
                selection_policy_digest=_hex("f"),
                profile_level="exact",
                null_profile_digest=_hex("5"),
                manifest_digest=hashlib.sha256(f"saec-runner-manifest-{index}".encode()).hexdigest(),
                detector_version="detector-v1",
                score_schema="contrast-v1",
                operator_set_digest=_hex("e"),
                transform_family="jpeg",
                quality_bucket="high",
                source_match_bucket="matched",
            )
        )
    return tuple(rows)


def run() -> Dict[str, Any]:
    config = SelectionAwareCalibrationConfig()
    cases = [
        ("selection_specific_candidate", _batch(), _groups()),
        ("selection_max_tie", _batch(), _groups(max_statistic=0.80)),
        ("ordinary_propagation", _batch(operation_scope=OPERATION_ORDINARY_PROPAGATION), ()),
        ("decoy_tie", _batch(decoy_value=0.80), _groups()),
        ("calibration_support_missing", _batch(), _groups(count=19)),
        ("candidate_low", _batch(candidate=0.01), _groups()),
    ]
    outputs = []
    for case_id, batch, groups in cases:
        result = evaluate_selection_aware_calibration(batch, groups, config=config)
        outputs.append({"case_id": case_id, "result": result.to_dict()})
    route_counts = {
        route: sum(item["result"]["route"] == route for item in outputs)
        for route in sorted({item["result"]["route"] for item in outputs})
    }
    return {
        "version": "selection-aware-calibration-synthetic-v1",
        "interpretation": "synthetic raw contract only; no route is an AIGC probability or legal finding",
        "count": len(outputs),
        "route_counts": route_counts,
        "dataset_digest": _digest(outputs),
        "config_digest": config.config_digest,
        "cases": outputs,
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True, indent=2))
