"""Synthetic contract runner for generator-family/open-set routing.

The runner uses scalar feature fixtures only.  It checks deterministic
profile fitting, known-family support, unknown-family rejection, real-only
consistency and evidence conflict routing.  It is not a detector benchmark or
an AIGC accuracy result.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from aigc.open_set_routing import (
    FEATURE_SCHEMA,
    ROUTE_CONFLICT_REVIEW,
    ROUTE_INSUFFICIENT,
    ROUTE_KNOWN_FAMILY,
    ROUTE_OPEN_SET_UNKNOWN,
    ROUTE_REAL_CONSISTENT,
    GeneratorFamilyExample,
    OpenSetQuery,
    OpenSetRoutingConfig,
    evaluate_open_set_route,
    fit_generator_family_profile,
)


PROTOCOL_VERSION = "generator-family-open-set-synthetic-v1"
REAL_PROFILE_DIGEST = "a" * 64


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _examples() -> List[GeneratorFamilyExample]:
    rows: List[GeneratorFamilyExample] = []
    for index in range(6):
        rows.append(
            GeneratorFamilyExample(
                sample_id=f"family-a-{index}",
                group_id=f"group-a-{index}",
                family_id="family-a",
                feature=(0.01 * index, 0.015 * index),
                feature_schema=FEATURE_SCHEMA,
                detector_version="synthetic-adapter-v1",
            )
        )
        rows.append(
            GeneratorFamilyExample(
                sample_id=f"family-b-{index}",
                group_id=f"group-b-{index}",
                family_id="family-b",
                feature=(1.0 + 0.01 * index, 1.0 + 0.015 * index),
                feature_schema=FEATURE_SCHEMA,
                detector_version="synthetic-adapter-v1",
            )
        )
    return rows


def _query(sample_id: str, feature, p_value: float = 0.01) -> OpenSetQuery:
    return OpenSetQuery(
        sample_id=sample_id,
        feature=feature,
        feature_schema=FEATURE_SCHEMA,
        detector_version="synthetic-adapter-v1",
        input_digest=hashlib.sha256(sample_id.encode("utf-8")).hexdigest(),
        real_p_value_raw=p_value,
        real_profile_digest=REAL_PROFILE_DIGEST,
    )


def run_synthetic_evaluation() -> Dict[str, Any]:
    config = OpenSetRoutingConfig(
        minimum_family_support=4,
        maximum_family_distance=0.15,
        minimum_family_margin=0.03,
    )
    profile = fit_generator_family_profile(
        _examples(),
        config,
        real_profile_digest=REAL_PROFILE_DIGEST,
        real_calibration_dataset_digest="b" * 64,
        real_calibration_support_count=64,
    )
    cases = {
        "known_family": _query("known-family", (0.03, 0.03), 0.01),
        "real_only_consistent": _query("real-only", (0.50, 0.50), 0.80),
        "open_set_unknown": _query("unknown-family", (0.50, 0.50), 0.01),
        "evidence_conflict": _query("family-real-conflict", (0.03, 0.03), 0.80),
        "family_far_midpoint": _query("family-far-midpoint", (0.525, 0.525), 0.01),
    }
    expected = {
        "known_family": ROUTE_KNOWN_FAMILY,
        "real_only_consistent": ROUTE_REAL_CONSISTENT,
        "open_set_unknown": ROUTE_OPEN_SET_UNKNOWN,
        "evidence_conflict": ROUTE_CONFLICT_REVIEW,
        "family_far_midpoint": ROUTE_OPEN_SET_UNKNOWN,
    }
    results = {
        name: evaluate_open_set_route(query, profile, config).to_dict()
        for name, query in cases.items()
    }
    actual = {name: result["route"] for name, result in results.items()}
    if actual != expected:
        raise AssertionError({"expected": expected, "actual": actual})
    repeat = fit_generator_family_profile(
        list(reversed(_examples())),
        config,
        real_profile_digest=REAL_PROFILE_DIGEST,
        real_calibration_dataset_digest="b" * 64,
        real_calibration_support_count=64,
    )
    if profile.profile_digest != repeat.profile_digest:
        raise AssertionError("profile fitting is not deterministic")
    canonical = {
        "version": PROTOCOL_VERSION,
        "config": config.to_dict(),
        "profile": profile.to_dict(),
        "results": results,
    }
    counts: Dict[str, int] = {}
    for route in actual.values():
        counts[route] = counts.get(route, 0) + 1
    return {
        "version": PROTOCOL_VERSION,
        "profile_digest": profile.profile_digest,
        "dataset_digest": _digest(canonical),
        "count": len(results),
        "route_counts": counts,
        "results": results,
        "interpretation": (
            "synthetic open-set routing contract only; known_family_supported, "
            "real_consistent and open_set_unknown are raw evidence routes, not "
            "AIGC probabilities, provenance proof or legal findings"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
