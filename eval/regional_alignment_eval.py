"""Synthetic image-grid to PC-SCFT regression.

This runner exercises the new adapter-level slice with NumPy arrays that have
the same shape as ``ImageAdapterResult.gray``.  It intentionally stops at raw
regional evidence and PC-SCFT gating: no model probability, AIGC state, or
real-image generalization claim is produced.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import numpy as np

from aigc.regional_alignment import build_paired_regional_observations
from aigc.regional_counterfactual import RegionalCounterfactualConfig, fuse_regional_counterfactual


def _base_grid() -> np.ndarray:
    rng = np.random.default_rng(20260920)
    noise = rng.normal(0.0, 0.025, size=(32, 32)).astype(np.float32)
    yy, xx = np.mgrid[0:32, 0:32]
    smooth = 0.2 + 0.25 * (xx / 31.0) + 0.18 * (yy / 31.0)
    smooth += 0.12 * np.sin(xx / 3.5) * np.cos(yy / 5.0)
    return np.clip(smooth.astype(np.float32) + noise, 0.02, 0.98)


def _propagate(grid: np.ndarray, family: str) -> np.ndarray:
    if family == "identity":
        return grid.copy()
    if family == "shift_x2":
        shifted = np.roll(grid, 2, axis=1)
        shifted[:, :2] = grid[:, :2].mean(axis=1, keepdims=True)
        return shifted
    if family == "brightness_plus":
        return np.clip(grid + 0.035, 0.0, 1.0).astype(np.float32)
    raise ValueError(f"unknown synthetic propagation family: {family}")


def _edited(grid: np.ndarray, *, enabled: bool) -> np.ndarray:
    result = grid.copy()
    if enabled:
        # A patch contained in the top-left quadrant provides a localized
        # source-conditioned difference while leaving three regions unchanged.
        result[3:12, 3:12] = np.clip(result[3:12, 3:12] + 0.34, 0.0, 1.0)
    return result


def _case(case_id: str, label: int, *, edited: bool, mismatch: bool = False) -> Dict[str, Any]:
    reference = _base_grid()
    families = ("identity", "shift_x2", "brightness_plus")
    observations = []
    batch_audit = []
    for index, family in enumerate(families):
        counterfactual = _propagate(reference, family)
        observed = _edited(counterfactual, enabled=edited)
        if mismatch:
            # The observed view and counterfactual are deliberately in
            # different source coordinate frames; the builder must reject the
            # pair before emitting RegionalObservation rows.
            observed = _propagate(observed, "shift_x2")
        batch = build_paired_regional_observations(
            reference,
            observed,
            counterfactual,
            asset_id=case_id,
            pair_id=f"{case_id}-pair-{index}",
            transform_family=family,
        )
        batch_audit.append(
            {
                "pair_id": batch.pair_id,
                "family": family,
                "accepted": batch.accepted,
                "reason": batch.reason,
                "region_count": batch.region_count,
                "observed_alignment": batch.observed_alignment.to_dict(),
                "counterfactual_alignment": batch.counterfactual_alignment.to_dict(),
            }
        )
        if batch.accepted:
            observations.extend(batch.observations)
    fused = fuse_regional_counterfactual(
        observations,
        config=RegionalCounterfactualConfig(minimum_pairs=2, minimum_region_views=2),
    )
    return {
        "case_id": case_id,
        "label_fixture_only": label,
        "batch_audit": batch_audit,
        "observation_count": len(observations),
        "result": fused.to_dict(),
    }


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def run_synthetic_evaluation() -> Dict[str, Any]:
    cases = [
        _case("aligned-edit", 1, edited=True),
        _case("aligned-human", 0, edited=False),
        _case("paired-geometry-mismatch", 0, edited=True, mismatch=True),
    ]
    return {
        "version": "regional-alignment-synthetic-v1",
        "count": len(cases),
        "dataset_digest": _digest(cases),
        "accepted_case_rate": sum(item["result"]["has_score"] for item in cases) / len(cases),
        "case_summary": {
            item["case_id"]: {
                "has_score": item["result"]["has_score"],
                "abstained": item["result"]["abstained"],
                "reason": item["result"]["reason"],
                "observation_count": item["observation_count"],
            }
            for item in cases
        },
        "cases": cases,
        "interpretation": (
            "synthetic adapter-to-PC-SCFT regression only; raw alignment and "
            "regional deltas are not calibrated probabilities and do not establish "
            "real-image AIGC accuracy, propagation robustness, or legal conclusions"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
