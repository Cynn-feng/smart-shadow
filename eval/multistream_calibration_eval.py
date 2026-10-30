"""Synthetic regression for independent multistream null calibration.

The runner uses the existing pixel-residual and spectral fixtures to build a
small ordinary-propagation null profile, then evaluates concordant edit,
concordant null, cross-stream conflict and missing-stream cases.  It reports
only calibrated raw-evidence routes and digests; it is not an AIGC accuracy or
probability estimate.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from aigc.multistream import EvidenceStreamObservation
from aigc.multistream_calibration import (
    MultiStreamCalibrationConfig,
    StreamNullExample,
    evaluate_calibrated_multistream,
    fit_stream_null_profiles,
)
from eval.multistream_eval import (
    _grids,
    _pixel_observation,
    _spectral_observation,
)


PROTOCOL_VERSION = "multistream-conformal-synthetic-v1"


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _profile_examples(pixel_null: EvidenceStreamObservation, spectral_null: EvidenceStreamObservation):
    examples = []
    for stream in (pixel_null, spectral_null):
        for index in range(60):
            score = min(1.0, float(stream.score_raw) + 0.001 * (index % 4))
            examples.append(
                StreamNullExample(
                    stream_id=stream.stream_id,
                    score_raw=score,
                    group_id=f"{stream.stream_id}-ordinary-null-{index}",
                    detector_version=stream.detector_version,
                    score_schema=stream.score_schema,
                    quality_score=float(stream.quality_score),
                    transform_family="ordinary_propagation",
                )
            )
    return fit_stream_null_profiles(examples)


def _summary(result):
    return {
        "route": result.route,
        "abstained": result.abstained,
        "reason": result.reason,
        "alpha": result.alpha,
        "per_stream_alpha": result.per_stream_alpha,
        "stream_results": [item.to_dict() for item in result.stream_results],
        "config_digest": result.config_digest,
        "profile_digests": list(result.profile_digests),
        "evidence_digest": result.evidence_digest,
    }


def run_synthetic_evaluation() -> Dict[str, Any]:
    reference, edited, counterfactual = _grids()
    pixel_edit = _pixel_observation(reference, edited, counterfactual)
    spectral_edit = _spectral_observation(reference, edited, counterfactual)
    pixel_null = _pixel_observation(reference, counterfactual, counterfactual)
    spectral_null = _spectral_observation(reference, counterfactual, counterfactual)
    profiles = _profile_examples(pixel_null, spectral_null)
    config = MultiStreamCalibrationConfig(alpha=0.05, minimum_null_count=20)

    missing_spectral = EvidenceStreamObservation(
        stream_id="spectral",
        accepted=False,
        paired=False,
        score_raw=None,
        quality_score=None,
        reason="calibration_unavailable",
        detector_version=spectral_edit.detector_version,
        score_schema=spectral_edit.score_schema,
        config_digest=spectral_edit.config_digest,
        input_digests=(),
        evidence_digest=_digest({"missing": "spectral"}),
    )
    cases = {
        "local_edit": _summary(
            evaluate_calibrated_multistream((pixel_edit, spectral_edit), profiles, config=config)
        ),
        "ordinary_propagation_hard_negative": _summary(
            evaluate_calibrated_multistream((pixel_null, spectral_null), profiles, config=config)
        ),
        "cross_stream_conflict": _summary(
            evaluate_calibrated_multistream((pixel_null, spectral_edit), profiles, config=config)
        ),
        "missing_spectral_stream": _summary(
            evaluate_calibrated_multistream((pixel_edit, missing_spectral), profiles, config=config)
        ),
    }
    expected_routes = {
        "local_edit": "candidate_edit",
        "ordinary_propagation_hard_negative": "null_consistent",
        "cross_stream_conflict": "conflict_review",
        "missing_spectral_stream": "insufficient",
    }
    actual_routes = {name: item["route"] for name, item in cases.items()}
    if actual_routes != expected_routes:
        raise AssertionError({"expected": expected_routes, "actual": actual_routes})
    canonical = {
        "version": PROTOCOL_VERSION,
        "config": config.to_dict(),
        "profiles": [profile.to_dict() for profile in profiles],
        "cases": cases,
    }
    return {
        "version": PROTOCOL_VERSION,
        "cases": cases,
        "profile_digests": [profile.profile_digest for profile in profiles],
        "dataset_digest": _digest(canonical),
        "interpretation": (
            "synthetic independent-stream conformal routing only; p-values and routes "
            "are not AIGC probabilities, provenance or legal findings"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
