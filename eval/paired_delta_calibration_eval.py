"""Synthetic regression for the paired PC-SCFT delta calibration contract.

The fixtures contain ordinary propagation groups only.  The runner checks
exact quality/family strata, explicit fallback, finite-sample p-values and the
unevaluated state when no compatible null support exists.  It does not read
images, train a detector, or establish AIGC accuracy.
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


DETECTOR = "source-residual-v1"
SCHEMA = "source-residual-score-v1"


def _group(
    group_id: str,
    *,
    family: str = "identity",
    quality: float = 0.90,
    deltas: Iterable[float] = (0.01, 0.02),
) -> PairedDeltaGroup:
    values = tuple(deltas)
    return PairedDeltaGroup(
        group_id=group_id,
        transform_family=family,
        quality_score=quality,
        region_deltas=values,
        detector_version=DETECTOR,
        score_schema=SCHEMA,
        region_ids=tuple(f"region-{index}" for index in range(len(values))),
    )


def build_synthetic_groups() -> List[PairedDeltaGroup]:
    """Return deterministic ordinary-propagation null fixtures."""

    groups: List[PairedDeltaGroup] = []
    for index in range(8):
        groups.append(
            _group(
                f"identity-high-{index}",
                family="identity",
                quality=0.90,
                deltas=(0.01 + 0.004 * index, -0.01),
            )
        )
    for index in range(4):
        groups.append(
            _group(
                f"jpeg-mid-{index}",
                family="jpeg_q75",
                quality=0.55,
                deltas=(0.02 + 0.005 * index, 0.01),
            )
        )
    return groups


def _digest(groups: Iterable[PairedDeltaGroup]) -> str:
    payload = [item.to_dict() for item in sorted(groups, key=lambda item: item.group_id)]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def run_synthetic_evaluation() -> Dict[str, Any]:
    groups = build_synthetic_groups()
    config = PairedDeltaCalibrationConfig(minimum_stratum_count=3, alpha=0.20)
    profile = fit_paired_delta_profile(groups, config=config)
    fixture_digest = _digest(groups)
    queries = [
        _group("query-exact", family="identity", quality=0.90, deltas=(0.90, -0.1)),
        _group("query-family-fallback", family="jpeg_q75", quality=0.20, deltas=(0.90,)),
        _group("query-global-fallback", family="unknown_engine", quality=0.20, deltas=(0.90,)),
    ]
    outputs = [{"query_id": query.group_id, "result": profile.evaluate(query).to_dict()} for query in queries]
    unavailable_profile = fit_paired_delta_profile(
        [_group("small-0", deltas=(0.01,)), _group("small-1", deltas=(0.02,))],
        config=PairedDeltaCalibrationConfig(
            minimum_stratum_count=3,
            alpha=0.20,
            allow_family_fallback=False,
            allow_global_fallback=False,
        ),
    )
    unavailable = unavailable_profile.evaluate(
        _group("query-unavailable", family="new_engine", quality=0.20, deltas=(0.90,))
    )
    outputs.append({"query_id": "query-unavailable", "result": unavailable.to_dict()})
    return {
        "version": "paired-delta-conformal-synthetic-v1",
        "group_count": len(groups),
        "dataset_digest": profile.dataset_digest,
        "fixture_digest": fixture_digest,
        "profile_digest": profile.profile_digest,
        "summary": {
            "evaluated_count": sum(item["result"]["evaluated"] for item in outputs),
            "unknown_count": sum(item["result"]["unknown"] for item in outputs),
            "fallbacks": {
                fallback: sum(item["result"]["fallback"] == fallback for item in outputs)
                for fallback in ("none", "family", "global", "unavailable")
            },
        },
        "queries": outputs,
        "interpretation": (
            "synthetic regression only; paired-delta p-values are null-consistency "
            "observations and do not establish AIGC accuracy, calibration coverage, "
            "or legal conclusions"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
