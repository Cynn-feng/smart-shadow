"""Synthetic regression for paired propagation stability evidence.

This runner uses scalar detector observations rather than image data.  It
checks the protocol's three intended behaviours: stable source-conditioned
scores survive ordinary propagation, unstable scores abstain, and a high
counterfactual score blocks a seemingly high positive.  It is not an AIGC
benchmark and its labels are fixture expectations only.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List

from aigc.propagation_stability import (
    PropagationObservation,
    StabilityConfig,
    fuse_propagation_stability,
)


DEFAULT_DETECTOR = "source-residual-v1"
DEFAULT_SCHEMA = "source-residual-score-v1"
FAMILIES = ("identity", "jpeg_q75", "resize_075")


def _obs(
    asset_id: str,
    kind: str,
    scores: Iterable[float],
    *,
    quality: float = 0.90,
    source_match: float = 0.92,
    families: Iterable[str] = FAMILIES,
) -> List[PropagationObservation]:
    return [
        PropagationObservation(
            asset_id=asset_id,
            version_id=f"{asset_id}-{kind}-{index}",
            score_raw=score,
            quality_score=quality,
            source_match_score=source_match,
            transform_family=family,
            detector_version=DEFAULT_DETECTOR,
            score_schema=DEFAULT_SCHEMA,
            kind=kind,
            propagation_chain=(family,),
        )
        for index, (score, family) in enumerate(zip(scores, families))
    ]


def build_synthetic_cases() -> List[Dict[str, Any]]:
    """Return deterministic fixture cases for protocol regression only."""

    return [
        {
            "case_id": "edited-stable",
            "label": 1,
            "observed": _obs("asset-edited-stable", "observed", (0.82, 0.78, 0.80)),
            "counterfactual": _obs("asset-edited-stable", "counterfactual", (0.08, 0.10, 0.09)),
        },
        {
            "case_id": "human-stable",
            "label": 0,
            "observed": _obs("asset-human-stable", "observed", (0.09, 0.12, 0.10)),
            "counterfactual": _obs("asset-human-stable", "counterfactual", (0.08, 0.11, 0.09)),
        },
        {
            "case_id": "edited-unstable",
            "label": 1,
            "observed": _obs("asset-edited-unstable", "observed", (0.86, 0.30, 0.80)),
            "counterfactual": _obs("asset-edited-unstable", "counterfactual", (0.07, 0.10, 0.09)),
        },
        {
            "case_id": "hard-negative-fails",
            "label": 0,
            "observed": _obs("asset-hard-negative", "observed", (0.65, 0.63, 0.67)),
            "counterfactual": _obs("asset-hard-negative", "counterfactual", (0.58, 0.61, 0.60)),
        },
        {
            "case_id": "counterfactual-coverage-gap",
            "label": 1,
            "observed": _obs("asset-coverage-gap", "observed", (0.76, 0.78, 0.77)),
            "counterfactual": _obs(
                "asset-coverage-gap",
                "counterfactual",
                (0.08, 0.10),
                families=("identity", "jpeg_q75"),
            ),
        },
    ]


def _digest(cases: Iterable[Dict[str, Any]]) -> str:
    payload = []
    for case in cases:
        payload.append(
            {
                "case_id": case["case_id"],
                "label": case["label"],
                "observed": [item.to_dict() for item in case["observed"]],
                "counterfactual": [item.to_dict() for item in case["counterfactual"]],
            }
        )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def run_synthetic_evaluation(*, config: StabilityConfig | None = None) -> Dict[str, Any]:
    cases = build_synthetic_cases()
    cfg = config or StabilityConfig()
    outputs = []
    for case in cases:
        result = fuse_propagation_stability(
            case["observed"] + case["counterfactual"],
            config=cfg,
        )
        outputs.append(
            {
                "case_id": case["case_id"],
                "label": case["label"],
                "result": result.to_dict(),
            }
        )

    positives = [item for item in outputs if item["label"] == 1]
    negatives = [item for item in outputs if item["label"] == 0]
    stable_positive_acceptance = sum(
        not item["result"]["abstained"] for item in positives
    ) / len(positives)
    negative_abstention = sum(
        item["result"]["abstained"] for item in negatives
    ) / len(negatives)
    reason_counts: Dict[str, int] = {}
    for item in outputs:
        reason = item["result"]["reason"]
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    return {
        "version": "propagation-stability-synthetic-v1",
        "count": len(outputs),
        "dataset_digest": _digest(cases),
        "config_digest": cfg.digest,
        "summary": {
            "stable_positive_acceptance_rate": stable_positive_acceptance,
            "negative_abstention_rate": negative_abstention,
            "reason_counts": reason_counts,
        },
        "cases": outputs,
        "interpretation": (
            "synthetic regression only; scalar fixtures do not establish "
            "real-image propagation robustness, AIGC accuracy, calibration, "
            "or legal conclusions"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
