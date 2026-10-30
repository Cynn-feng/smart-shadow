"""Synthetic regression runner for the PE-CEA propagation envelope contract.

The runner uses scalar paired deltas and an independent ordinary-propagation
null profile.  It exercises persistence over severity, null isolation, an
isolated spike, and missing support.  These fixtures are raw contract
evidence only: they do not measure real-image accuracy or output an AIGC
probability.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List

from aigc.propagation_envelope import (
    CONTENT_EDIT,
    ORDINARY_PROPAGATION,
    EnvelopeConfig,
    EnvelopeObservation,
    evaluate_propagation_envelope,
    fit_propagation_envelope_profile,
)


MANIFEST_DIGEST = "a" * 64
CALIBRATION_SPLIT_DIGEST = "b" * 64
EVALUATION_SPLIT_DIGEST = "c" * 64


def _observation(
    group_id: str,
    severity_level: int,
    paired_delta: float,
    *,
    asset_id: str | None = None,
    split: str = "calibration",
    split_digest: str | None = None,
    operation_scope: str = ORDINARY_PROPAGATION,
    edit_mask_digest: str | None = None,
    quality_score: float = 0.90,
    source_match_score: float = 0.90,
) -> EnvelopeObservation:
    if asset_id is None:
        asset_id = f"asset-{group_id}"
    if split_digest is None:
        split_digest = (
            CALIBRATION_SPLIT_DIGEST
            if split == "calibration"
            else EVALUATION_SPLIT_DIGEST
        )
    return EnvelopeObservation(
        group_id=group_id,
        asset_id=asset_id,
        severity_level=severity_level,
        transform_family="jpeg",
        operation_scope=operation_scope,
        observed_delta_raw=paired_delta,
        counterfactual_delta_raw=0.0,
        quality_score=quality_score,
        source_match_score=source_match_score,
        manifest_digest=MANIFEST_DIGEST,
        canonical_frame="canonical-v1",
        split=split,
        split_digest=split_digest,
        detector_version="detector-v1",
        score_schema="paired-delta-v1",
        edit_mask_digest=edit_mask_digest,
    )


def build_synthetic_profile(config: EnvelopeConfig | None = None):
    """Build an independent ordinary-propagation null profile."""

    cfg = config or EnvelopeConfig(minimum_groups_per_level=3)
    rows = []
    null_deltas = (0.01, 0.02, 0.03, 0.025)
    for group, delta in enumerate(null_deltas):
        for severity in cfg.severity_levels:
            rows.append(_observation(f"null-{group}", severity, delta))
    return cfg, fit_propagation_envelope_profile(rows, cfg)


def _query(
    case_id: str,
    values: Iterable[float],
    *,
    config: EnvelopeConfig,
    operation_scope: str = CONTENT_EDIT,
    edit_mask_digest: str | None = "f" * 64,
    quality_score: float = 0.90,
    asset_id: str | None = None,
) -> Dict[str, Any]:
    rows = [
        _observation(
            case_id,
            severity,
            value,
            asset_id=asset_id or f"asset-{case_id}",
            split="evaluation",
            split_digest=EVALUATION_SPLIT_DIGEST,
            operation_scope=operation_scope,
            edit_mask_digest=(edit_mask_digest if operation_scope == CONTENT_EDIT else None),
            quality_score=quality_score,
        )
        for severity, value in zip(config.severity_levels, values)
    ]
    return {"case_id": case_id, "observations": rows}


def build_synthetic_cases(config: EnvelopeConfig) -> List[Dict[str, Any]]:
    return [
        _query("candidate", (0.70, 0.72, 0.71), config=config),
        _query("null-consistent", (0.01, 0.02, 0.03), config=config),
        _query("isolated-spike", (0.80, 0.01, 0.01), config=config),
        _query(
            "ordinary-high",
            (0.90, 0.90, 0.90),
            config=config,
            operation_scope=ORDINARY_PROPAGATION,
        ),
        _query("quality-insufficient", (0.80, 0.80, 0.80), config=config, quality_score=0.20),
        _query(
            "calibration-asset-reuse",
            (0.80, 0.80, 0.80),
            config=config,
            asset_id="asset-null-0",
        ),
    ]


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def run_synthetic_evaluation() -> Dict[str, Any]:
    config, profile = build_synthetic_profile()
    outputs: List[Dict[str, Any]] = []
    for case in build_synthetic_cases(config):
        result = evaluate_propagation_envelope(case["observations"], profile, config)
        outputs.append(
            {
                "case_id": case["case_id"],
                "result": result.to_dict(),
            }
        )
    route_counts: Dict[str, int] = {}
    for row in outputs:
        route = row["result"]["route"]
        route_counts[route] = route_counts.get(route, 0) + 1
    return {
        "version": "propagation-envelope-synthetic-v1",
        "count": len(outputs),
        "config_digest": config.digest,
        "profile_digest": profile.profile_digest,
        "dataset_digest": _digest(outputs),
        "route_counts": dict(sorted(route_counts.items())),
        "cases": outputs,
        "interpretation": (
            "synthetic raw contract only; scalar severity fixtures do not establish "
            "real-image propagation FPR, AIGC accuracy, calibration, or legal conclusions"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
