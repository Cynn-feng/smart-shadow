"""Synthetic regression for the integrated PC-SCFT decision protocol.

The runner composes regional counterfactual, paired conformal calibration and
patch coverage fixtures.  Its outputs are evidence-routing states only; they
are not AIGC labels, probabilities or real-image accuracy measurements.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List

from aigc.paired_delta_calibration import (
    PairedDeltaCalibrationConfig,
    PairedDeltaGroup,
    fit_paired_delta_profile,
)
from aigc.patch_coverage import PatchCoverageConfig, PatchDelta, summarize_patch_coverage
from aigc.pc_scft import PCSCFTConfig, decide_pc_scft
from aigc.regional_counterfactual import (
    RegionalCounterfactualConfig,
    RegionalObservation,
    fuse_regional_counterfactual,
)


DETECTOR = "source-residual-v1"
SCHEMA = "source-residual-score-v1"


def _null_group(group_id: str, index: int) -> PairedDeltaGroup:
    return PairedDeltaGroup(
        group_id=group_id,
        transform_family="identity",
        quality_score=0.9,
        region_deltas=(0.01 + index * 0.002, 0.0),
        detector_version=DETECTOR,
        score_schema=SCHEMA,
    )


def _profile():
    return fit_paired_delta_profile(
        [_null_group(f"null-{index}", index) for index in range(6)],
        config=PairedDeltaCalibrationConfig(
            minimum_stratum_count=3,
            alpha=0.2,
            allow_family_fallback=False,
            allow_global_fallback=False,
        ),
    )


def _regional(case_id: str, edited: bool) -> Any:
    observations: List[RegionalObservation] = []
    for index, family in enumerate(("identity", "jpeg_q75", "resize_075")):
        observed = 0.80 if edited else 0.12
        for region_id, score in (("r0", observed), ("r1", 0.12)):
            observations.extend(
                [
                    RegionalObservation(
                        asset_id=case_id,
                        pair_id=f"pair-{index}",
                        region_id=region_id,
                        version_id=f"{case_id}-observed-{index}-{region_id}",
                        transform_family=family,
                        score_raw=score,
                        quality_score=0.9,
                        source_match_score=0.9,
                        kind="observed",
                        detector_version=DETECTOR,
                        score_schema=SCHEMA,
                    ),
                    RegionalObservation(
                        asset_id=case_id,
                        pair_id=f"pair-{index}",
                        region_id=region_id,
                        version_id=f"{case_id}-counterfactual-{index}-{region_id}",
                        transform_family=family,
                        score_raw=0.10,
                        quality_score=0.9,
                        source_match_score=0.9,
                        kind="counterfactual",
                        detector_version=DETECTOR,
                        score_schema=SCHEMA,
                    ),
                ]
            )
    return fuse_regional_counterfactual(
        observations,
        config=RegionalCounterfactualConfig(minimum_pairs=2, minimum_region_views=2),
    )


def _coverage(case_id: str, *, ambiguous: bool = False):
    values = (0.80, 0.80, 0.02, 0.02) if ambiguous else (0.45, 0.42, 0.48, 0.44)
    types = ("object", "stuff", "background", "object")
    return summarize_patch_coverage(
        [
            PatchDelta(
                region_id=f"r{index}",
                delta_raw=value,
                quality_score=0.9,
                source_match_score=0.9,
                detector_version=DETECTOR,
                score_schema=SCHEMA,
                region_type=types[index],
            )
            for index, value in enumerate(values)
        ],
        config=PatchCoverageConfig(require_region_type_diversity=True),
    )


def _digest(cases: Iterable[Dict[str, Any]]) -> str:
    payload = json.dumps(list(cases), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_synthetic_evaluation() -> Dict[str, Any]:
    profile = _profile()
    cases = [
        ("edited-global", True, False, (0.80, 0.70)),
        ("ordinary-null", False, False, (0.02, 0.01)),
        ("edited-ambiguous", True, True, (0.80, 0.70)),
    ]
    outputs = []
    for case_id, edited, ambiguous, query_deltas in cases:
        calibration = profile.evaluate(
            PairedDeltaGroup(
                group_id=f"query-{case_id}",
                transform_family="identity",
                quality_score=0.9,
                region_deltas=query_deltas,
                detector_version=DETECTOR,
                score_schema=SCHEMA,
            )
        )
        result = decide_pc_scft(
            _regional(case_id, edited),
            calibration,
            _coverage(case_id, ambiguous=ambiguous),
            config=PCSCFTConfig(),
        )
        outputs.append(
            {
                "case_id": case_id,
                "fixture_label": "edited" if edited else "ordinary_propagation",
                "result": result.to_dict(),
            }
        )
    status_counts: Dict[str, int] = {}
    for item in outputs:
        status = item["result"]["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "version": "pc-scft-decision-synthetic-v1",
        "count": len(outputs),
        "dataset_digest": _digest(
            [
                {"case_id": case_id, "edited": edited, "ambiguous": ambiguous, "query_deltas": query_deltas}
                for case_id, edited, ambiguous, query_deltas in cases
            ]
        ),
        "profile_digest": profile.profile_digest,
        "status_counts": status_counts,
        "cases": outputs,
        "interpretation": (
            "synthetic regression only; PC-SCFT states are raw evidence-routing "
            "outputs, not AIGC accuracy, probability, authorship or legal findings"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
