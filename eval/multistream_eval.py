"""Synthetic hard-negative regression for the pixel/spectral stream router.

The runner invokes the existing source-residual and phase/spectral raw
features, then checks that independent streams remain visible at the routing
boundary.  The reported routes are fixture behavior only; they are not AIGC
probabilities, accuracy, provenance claims, or legal findings.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

import numpy as np

from aigc.forensic_features import ResidualConfig, compare_aligned_regions
from aigc.multistream import (
    EvidenceStreamObservation,
    MultiStreamRouteConfig,
    ROUTE_CANDIDATE,
    ROUTE_CONFLICT_REVIEW,
    ROUTE_INSUFFICIENT,
    ROUTE_NULL_CONSISTENT,
    route_multistream_evidence,
)
from aigc.spectral_evidence import compute_spectral_evidence


PROTOCOL_VERSION = "multistream-router-synthetic-v1"


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _grids():
    yy, xx = np.mgrid[0:64, 0:64]
    reference = (0.18 + 0.003 * xx + 0.004 * yy).astype(np.float32)
    counterfactual = np.clip(reference + 0.08, 0.0, 1.0)
    edited = counterfactual.copy()
    edited[20:40, 22:42] = np.clip(edited[20:40, 22:42] + 0.25, 0.0, 1.0)
    return reference, edited, counterfactual


def _pixel_observation(reference, query, counterfactual, *, stream_id="pixel_residual"):
    config = ResidualConfig()
    query_evidence = compare_aligned_regions(reference.tolist(), query.tolist(), config=config)
    null_evidence = compare_aligned_regions(reference.tolist(), counterfactual.tolist(), config=config)
    score = max(0.0, query_evidence.edit_score - null_evidence.edit_score)
    inputs = tuple(
        dict.fromkeys(
            (_digest(reference.tolist()), _digest(query.tolist()), _digest(counterfactual.tolist()))
        )
    )
    payload = {
        "stream_id": stream_id,
        "query": query_evidence.to_region_dict("full"),
        "counterfactual": null_evidence.to_region_dict("full"),
        "inputs": inputs,
    }
    return EvidenceStreamObservation(
        stream_id=stream_id,
        accepted=True,
        paired=True,
        score_raw=score,
        quality_score=min(query_evidence.quality_score, null_evidence.quality_score),
        reason=None,
        detector_version=config.detector_version,
        score_schema=config.score_schema,
        config_digest=_digest({"residual_config": config.__dict__}),
        input_digests=inputs,
        evidence_digest=_digest(payload),
        details=payload,
    )


def _spectral_observation(reference, query, counterfactual):
    result = compute_spectral_evidence(reference, query, counterfactual)
    score = max((item.score_raw for item in result.scores), default=None)
    quality = min((item.quality_score for item in result.scores), default=None)
    return EvidenceStreamObservation(
        stream_id="spectral",
        accepted=result.accepted,
        paired=result.paired,
        score_raw=score,
        quality_score=quality,
        reason=None if result.accepted else result.reason,
        detector_version=result.detector_version,
        score_schema=result.score_schema,
        config_digest=result.config_digest,
        input_digests=tuple(
            dict.fromkeys(
                digest
                for digest in (
                    result.reference_sha256,
                    result.query_sha256,
                    result.counterfactual_sha256,
                )
                if digest
            )
        ),
        evidence_digest=result.evidence_digest,
        details={"regions": [item.to_dict() for item in result.scores]},
    )


def _summary(result):
    return {
        "route": result.route,
        "abstained": result.abstained,
        "reason": result.reason,
        "accepted_streams": list(result.accepted_streams),
        "positive_streams": list(result.positive_streams),
        "negative_streams": list(result.negative_streams),
        "unavailable_streams": list(result.unavailable_streams),
        "conflict_streams": list(result.conflict_streams),
        "evidence_digest": result.evidence_digest,
        "stream_scores": {
            stream["stream_id"]: stream["score_raw"] for stream in result.streams
        },
    }


def run_synthetic_evaluation() -> Dict[str, Any]:
    reference, edited, counterfactual = _grids()
    local_streams = (
        _pixel_observation(reference, edited, counterfactual),
        _spectral_observation(reference, edited, counterfactual),
    )
    null_streams = (
        _pixel_observation(reference, counterfactual, counterfactual),
        _spectral_observation(reference, counterfactual, counterfactual),
    )
    conflict_streams = (
        _pixel_observation(reference, counterfactual, counterfactual),
        _spectral_observation(reference, edited, counterfactual),
    )
    unavailable = EvidenceStreamObservation(
        stream_id="spectral",
        accepted=False,
        paired=False,
        score_raw=None,
        quality_score=None,
        reason="calibration_unavailable",
        detector_version="source-spectral-phase-v1",
        score_schema="source-spectral-score-v1",
        config_digest=_digest({"spectral": "fixture"}),
        input_digests=(),
        evidence_digest=_digest({"reason": "calibration_unavailable"}),
        details={"fixture": "missing_stream"},
    )
    insufficient = route_multistream_evidence((_pixel_observation(reference, edited, counterfactual), unavailable))
    # This fixture uses an explicit raw gate chosen for its generated grids;
    # it is not a production threshold and is not learned calibration.
    fixture_config = MultiStreamRouteConfig(raw_positive_threshold=0.45)
    results = {
        "local_edit": _summary(route_multistream_evidence(local_streams, config=fixture_config)),
        "ordinary_propagation_hard_negative": _summary(
            route_multistream_evidence(null_streams, config=fixture_config)
        ),
        "cross_stream_conflict": _summary(
            route_multistream_evidence(conflict_streams, config=fixture_config)
        ),
        "missing_spectral_stream": _summary(
            route_multistream_evidence(
                (_pixel_observation(reference, edited, counterfactual), unavailable),
                config=fixture_config,
            )
        ),
    }
    expected = {
        "local_edit": ROUTE_CANDIDATE,
        "ordinary_propagation_hard_negative": ROUTE_NULL_CONSISTENT,
        "cross_stream_conflict": ROUTE_CONFLICT_REVIEW,
        "missing_spectral_stream": ROUTE_INSUFFICIENT,
    }
    if {name: item["route"] for name, item in results.items()} != expected:
        raise AssertionError({"expected": expected, "actual": results})
    canonical = json.dumps(results, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "version": PROTOCOL_VERSION,
        "cases": results,
        "dataset_digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "interpretation": (
            "synthetic pixel-residual plus spectral raw-evidence routing only; "
            "routes and scores are not AIGC probabilities, provenance or legal findings"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
