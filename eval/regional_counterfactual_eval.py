"""Synthetic regression for regional paired counterfactual evidence.

The fixture contains scalar region scores only.  It validates regional
pairing, quality-weighted deltas, coverage and stability gates; it is not a
real-image benchmark or an AIGC classifier evaluation.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from aigc.regional_counterfactual import (
    RegionalCounterfactualConfig,
    RegionalObservation,
    fuse_regional_counterfactual,
)


DEFAULT_DETECTOR = "source-residual-v1"
DEFAULT_SCHEMA = "source-residual-score-v1"


def _make_pair(
    asset_id: str,
    pair_index: int,
    region_id: str,
    observed_score: float,
    counterfactual_score: float,
    *,
    family: str,
    quality: float = 0.90,
    source_match: float = 0.90,
) -> List[RegionalObservation]:
    pair_id = f"pair-{pair_index}"
    return [
        RegionalObservation(
            asset_id=asset_id,
            pair_id=pair_id,
            region_id=region_id,
            version_id=f"{asset_id}-observed-{pair_index}",
            transform_family=family,
            score_raw=observed_score,
            quality_score=quality,
            source_match_score=source_match,
            kind="observed",
            detector_version=DEFAULT_DETECTOR,
            score_schema=DEFAULT_SCHEMA,
            propagation_chain=(family,),
        ),
        RegionalObservation(
            asset_id=asset_id,
            pair_id=pair_id,
            region_id=region_id,
            version_id=f"{asset_id}-counterfactual-{pair_index}",
            transform_family=family,
            score_raw=counterfactual_score,
            quality_score=quality,
            source_match_score=source_match,
            kind="counterfactual",
            detector_version=DEFAULT_DETECTOR,
            score_schema=DEFAULT_SCHEMA,
            propagation_chain=(family,),
        ),
    ]


def _families() -> Tuple[str, ...]:
    return ("identity", "jpeg_q75", "resize_075")


def build_synthetic_cases() -> List[Dict[str, Any]]:
    """Build deterministic protocol fixtures; labels are fixture expectations."""

    families = _families()
    stable_edit: List[RegionalObservation] = []
    stable_human: List[RegionalObservation] = []
    unstable: List[RegionalObservation] = []
    for index, family in enumerate(families):
        stable_edit.extend(_make_pair("regional-edited", index, "edited", 0.78, 0.18, family=family))
        stable_edit.extend(_make_pair("regional-edited", index, "unchanged", 0.12, 0.11, family=family))
        stable_human.extend(_make_pair("regional-human", index, "scene", 0.12, 0.10, family=family))
        unstable.extend(
            _make_pair(
                "regional-unstable",
                index,
                "edited",
                (0.85, 0.30, 0.84)[index],
                0.10,
                family=family,
            )
        )

    coverage_gap = []
    for index, family in enumerate(families[:2]):
        coverage_gap.extend(_make_pair("regional-gap", index, "scene", 0.70, 0.10, family=family))
    coverage_gap.append(
        RegionalObservation(
            asset_id="regional-gap",
            pair_id="pair-2",
            region_id="scene",
            version_id="regional-gap-observed-2",
            transform_family=families[2],
            score_raw=0.72,
            quality_score=0.90,
            source_match_score=0.90,
            kind="observed",
            detector_version=DEFAULT_DETECTOR,
            score_schema=DEFAULT_SCHEMA,
            propagation_chain=(families[2],),
        )
    )

    quality_gap = []
    quality_gap.extend(_make_pair("regional-quality", 0, "scene", 0.75, 0.10, family="identity"))
    quality_gap.extend(
        _make_pair(
            "regional-quality",
            1,
            "scene",
            0.72,
            0.10,
            family="jpeg_q75",
            quality=0.20,
        )
    )
    return [
        {"case_id": "stable-edit", "label": 1, "observations": stable_edit},
        {"case_id": "stable-human", "label": 0, "observations": stable_human},
        {"case_id": "delta-unstable", "label": 1, "observations": unstable},
        {"case_id": "coverage-gap", "label": 0, "observations": coverage_gap},
        {"case_id": "quality-gap", "label": 0, "observations": quality_gap},
    ]


def _digest(cases: Iterable[Dict[str, Any]]) -> str:
    payload = [
        {
            "case_id": case["case_id"],
            "label": case["label"],
            "observations": [item.to_dict() for item in case["observations"]],
        }
        for case in cases
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def run_synthetic_evaluation(
    *, config: RegionalCounterfactualConfig | None = None
) -> Dict[str, Any]:
    cases = build_synthetic_cases()
    cfg = config or RegionalCounterfactualConfig()
    outputs = []
    for case in cases:
        result = fuse_regional_counterfactual(case["observations"], config=cfg)
        outputs.append(
            {
                "case_id": case["case_id"],
                "label": case["label"],
                "result": result.to_dict(),
            }
        )

    positives = [item for item in outputs if item["label"] == 1]
    negatives = [item for item in outputs if item["label"] == 0]
    reason_counts: Dict[str, int] = {}
    for item in outputs:
        reason = item["result"]["reason"]
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "version": "regional-counterfactual-synthetic-v1",
        "count": len(outputs),
        "dataset_digest": _digest(cases),
        "config_digest": cfg.digest,
        "summary": {
            "stable_positive_acceptance_rate": sum(
                not item["result"]["abstained"] for item in positives
            ) / len(positives),
            "negative_abstention_rate": sum(
                item["result"]["abstained"] for item in negatives
            ) / len(negatives),
            "reason_counts": reason_counts,
        },
        "cases": outputs,
        "interpretation": (
            "synthetic regression only; regional scalar fixtures do not establish "
            "real-image propagation robustness, AIGC accuracy, calibration, "
            "or legal conclusions"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
