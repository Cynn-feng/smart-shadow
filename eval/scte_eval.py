"""Synthetic regression for the SCTE triadic evidence adapter.

The fixtures exercise the complete offline contract:

``observed -> ordinary-propagation counterfactual -> e_edit -> regional FDR``.

This runner intentionally produces raw evidence and fail-closed reasons only.
It is not an AIGC accuracy benchmark, a probability estimate, or a formal FDR
guarantee.  Real authorized images, independently frozen ordinary-propagation
nulls and deployment integration remain required.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from aigc.regional_counterfactual import RegionalObservation
from aigc.regional_fdr import (
    RegionalFDRConfig,
    RegionNullDelta,
    evaluate_regional_fdr,
    fit_regional_fdr_profile,
)
from aigc.scte import SCTEAlignmentFrame, SCTEBinding, build_scte_query_deltas


DETECTOR = "synthetic-source-residual-v1"
SCORE_SCHEMA = "synthetic-source-residual-score-v1"
FAMILY = "jpeg_q75"
REGIONS: Tuple[Tuple[str, str], ...] = (("r0", "object"), ("r1", "background"))
DIGESTS = {
    "manifest": "a" * 64,
    "reference": "b" * 64,
    "transform": "c" * 64,
    "config": "d" * 64,
}


def _frame(role: str, *, offset: int = 0) -> SCTEAlignmentFrame:
    return SCTEAlignmentFrame(
        role=role,
        aligned_shape=(16, 16),
        reference_offset=(0, 0),
        query_offset=(offset, 0),
        dx=offset,
        dy=0,
        alignment_version="regional-alignment-v2",
        resize_version="bilinear-grid-resize-v1",
        config_digest=DIGESTS["config"],
    )


def _binding(case_id: str, *, geometry_mismatch: bool = False, region_ids: Sequence[str] = ("r0", "r1")) -> SCTEBinding:
    observed = _frame("observed")
    counterfactual = _frame("counterfactual", offset=1 if geometry_mismatch else 0)
    return SCTEBinding(
        asset_id=f"asset-{case_id}",
        pair_id=f"pair-{case_id}",
        manifest_digest=DIGESTS["manifest"],
        reference_digest=DIGESTS["reference"],
        observed_digest=hashlib.sha256(f"observed:{case_id}".encode()).hexdigest(),
        counterfactual_digest=hashlib.sha256(f"counterfactual:{case_id}".encode()).hexdigest(),
        transform_family=FAMILY,
        transform_spec_digest=DIGESTS["transform"],
        propagation_chain=(FAMILY,),
        observed_alignment=observed,
        counterfactual_alignment=counterfactual,
        region_ids=tuple(region_ids),
        detector_version=DETECTOR,
        score_schema=SCORE_SCHEMA,
        region_types={region_id: ("object" if region_id == "r0" else "background") for region_id in region_ids},
    )


def _observations(
    case_id: str,
    values: Mapping[str, Tuple[float, float]],
    *,
    include_counterfactual: bool = True,
    extra_region: bool = False,
) -> List[RegionalObservation]:
    binding = _binding(case_id)
    rows: List[RegionalObservation] = []
    for region_id, (observed_score, null_score) in values.items():
        rows.append(
            RegionalObservation(
                asset_id=binding.asset_id,
                pair_id=binding.pair_id,
                region_id=region_id,
                version_id=f"{case_id}-observed-{region_id}",
                transform_family=FAMILY,
                score_raw=observed_score,
                quality_score=0.90,
                source_match_score=0.90,
                kind="observed",
                detector_version=DETECTOR,
                score_schema=SCORE_SCHEMA,
                propagation_chain=(FAMILY,),
            )
        )
        if include_counterfactual or region_id != "r1":
            rows.append(
                RegionalObservation(
                    asset_id=binding.asset_id,
                    pair_id=binding.pair_id,
                    region_id=region_id,
                    version_id=f"{case_id}-counterfactual-{region_id}",
                    transform_family=FAMILY,
                    score_raw=null_score,
                    quality_score=0.90,
                    source_match_score=0.90,
                    kind="counterfactual",
                    detector_version=DETECTOR,
                    score_schema=SCORE_SCHEMA,
                    propagation_chain=(FAMILY,),
                )
            )
    if extra_region:
        rows.append(
            RegionalObservation(
                asset_id=binding.asset_id,
                pair_id=binding.pair_id,
                region_id="r-extra",
                version_id=f"{case_id}-observed-r-extra",
                transform_family=FAMILY,
                score_raw=0.30,
                quality_score=0.90,
                source_match_score=0.90,
                kind="observed",
                detector_version=DETECTOR,
                score_schema=SCORE_SCHEMA,
                propagation_chain=(FAMILY,),
            )
        )
    return rows


def build_null_stream(count: int = 24) -> List[RegionNullDelta]:
    """Build a deterministic ordinary-propagation null fixture."""

    values: List[RegionNullDelta] = []
    for index in range(count):
        for offset, (region_id, region_type) in enumerate(REGIONS):
            values.append(
                RegionNullDelta(
                    group_id=f"null-{index}",
                    transform_family=FAMILY,
                    quality_score=0.90,
                    region_id=region_id,
                    region_type=region_type,
                    delta_raw=0.02 + 0.005 * ((index + offset) % 2),
                    detector_version=DETECTOR,
                    score_schema=SCORE_SCHEMA,
                )
            )
    return values


def _evaluate_case(
    case_id: str,
    *,
    null_profile: Any,
    fdr_config: RegionalFDRConfig,
) -> Dict[str, Any]:
    values = {
        "local_edit": {"r0": (0.82, 0.10), "r1": (0.12, 0.10)},
        "ordinary_propagation": {"r0": (0.12, 0.10), "r1": (0.13, 0.11)},
        "missing_counterfactual": {"r0": (0.82, 0.10), "r1": (0.12, 0.10)},
        "region_set_mismatch": {"r0": (0.82, 0.10), "r1": (0.12, 0.10)},
    }[case_id]
    if case_id == "missing_counterfactual":
        observations = _observations(case_id, values, include_counterfactual=False)
        binding = _binding(case_id)
    elif case_id == "region_set_mismatch":
        observations = _observations(case_id, values, extra_region=True)
        binding = _binding(case_id)
    else:
        observations = _observations(case_id, values)
        binding = _binding(case_id)

    scte = build_scte_query_deltas(observations, binding)
    fdr = None
    if scte.accepted:
        fdr = evaluate_regional_fdr(null_profile, scte.query_deltas, config=fdr_config)
    return {
        "case_id": case_id,
        "scte": scte.to_dict(),
        "regional_fdr": None if fdr is None else fdr.to_dict(),
        "interpretation": "raw evidence contract only",
    }


def _geometry_mismatch_case() -> Dict[str, Any]:
    try:
        _binding("geometry_mismatch", geometry_mismatch=True)
    except ValueError as exc:
        return {
            "case_id": "geometry_mismatch",
            "scte": {"route": "insufficient", "reason": "alignment_geometry_mismatch"},
            "regional_fdr": None,
            "error": str(exc),
            "interpretation": "raw evidence contract only",
        }
    raise AssertionError("geometry mismatch fixture unexpectedly accepted")


def run_synthetic_evaluation() -> Dict[str, Any]:
    config = RegionalFDRConfig(minimum_null_count=10, q_value=0.20)
    nulls = build_null_stream()
    profile = fit_regional_fdr_profile(nulls, config=config)
    case_ids = (
        "local_edit",
        "ordinary_propagation",
        "missing_counterfactual",
        "region_set_mismatch",
    )
    cases = [_evaluate_case(case_id, null_profile=profile, fdr_config=config) for case_id in case_ids]
    cases.append(_geometry_mismatch_case())
    return {
        "version": "scte-triadic-synthetic-v1",
        "count": len(cases),
        "profile_digest": profile.profile_digest,
        "dataset_digest": _digest([item.to_dict() for item in nulls]),
        "cases": cases,
        "interpretation": (
            "synthetic SCTE observed/counterfactual/FDR contract only; this does "
            "not establish AIGC accuracy, probability, formal FDR control, or legal conclusions"
        ),
    }


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
