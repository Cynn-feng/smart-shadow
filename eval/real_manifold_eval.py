"""Synthetic regression for the ONMA natural-manifold raw fallback.

This runner only checks authorised real-only profile fitting, open-world route
boundaries, profile mismatch handling and immutable versioned adaptation.  It
does not load a model, measure AIGC accuracy, or turn manifold distance into a
human/AI conclusion.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List

from aigc.real_manifold_profile import (
    FEATURE_SCHEMA,
    ROUTE_IN_DISTRIBUTION,
    ROUTE_INSUFFICIENT,
    ROUTE_OUT_OF_MANIFOLD,
    ROUTE_PROFILE_MISMATCH,
    ManifoldObservation,
    ManifoldQuery,
    NaturalManifoldConfig,
    adapt_real_manifold_profile,
    evaluate_real_manifold,
    fit_real_manifold_profile,
)


PROTOCOL_VERSION = "onma-natural-profile-synthetic-v1"


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_observations(count: int = 20) -> List[ManifoldObservation]:
    return [
        ManifoldObservation(
            sample_id=f"sample-{index}",
            group_id=f"group-{index}",
            feature=(0.20 + 0.01 * index, 0.40 + 0.005 * index),
            feature_schema=FEATURE_SCHEMA,
            detector_version="synthetic-adapter-v1",
            quality_score=0.9,
        )
        for index in range(count)
    ]


def _case(query: ManifoldQuery, profile) -> Dict[str, Any]:
    return evaluate_real_manifold(query, profile).to_dict()


def run_synthetic_evaluation() -> Dict[str, Any]:
    config = NaturalManifoldConfig(minimum_support=20, alpha=0.05)
    calibration = build_observations()
    profile = fit_real_manifold_profile(calibration, config=config, prototype_version="synthetic-v1")
    insufficient_profile = fit_real_manifold_profile(
        calibration[:4],
        config=NaturalManifoldConfig(minimum_support=20, alpha=0.05),
        prototype_version="synthetic-v1",
    )
    queries = {
        "in_distribution": ManifoldQuery(
            "query-in", (0.30, 0.45), FEATURE_SCHEMA, "synthetic-adapter-v1"
        ),
        "out_of_manifold": ManifoldQuery(
            "query-out", (10.0, 10.0), FEATURE_SCHEMA, "synthetic-adapter-v1"
        ),
        "quality_insufficient": ManifoldQuery(
            "query-low-quality", (0.30, 0.45), FEATURE_SCHEMA, "synthetic-adapter-v1", 0.2
        ),
        "support_insufficient": ManifoldQuery(
            "query-low-support", (0.30, 0.45), FEATURE_SCHEMA, "synthetic-adapter-v1"
        ),
        "feature_schema_mismatch": ManifoldQuery(
            "query-schema-mismatch", (0.30, 0.45), "other-feature-v1", "synthetic-adapter-v1"
        ),
        "detector_mismatch": ManifoldQuery(
            "query-detector-mismatch", (0.30, 0.45), FEATURE_SCHEMA, "synthetic-adapter-v2"
        ),
        "dimension_mismatch": ManifoldQuery(
            "query-dimension-mismatch", (0.30, 0.45, 0.60), FEATURE_SCHEMA, "synthetic-adapter-v1"
        ),
    }
    cases = {
        "in_distribution": _case(queries["in_distribution"], profile),
        "out_of_manifold": _case(queries["out_of_manifold"], profile),
        "quality_insufficient": _case(queries["quality_insufficient"], profile),
        "support_insufficient": _case(queries["support_insufficient"], insufficient_profile),
        "feature_schema_mismatch": _case(queries["feature_schema_mismatch"], profile),
        "detector_mismatch": _case(queries["detector_mismatch"], profile),
        "dimension_mismatch": _case(queries["dimension_mismatch"], profile),
    }
    expected_routes = {
        "in_distribution": ROUTE_IN_DISTRIBUTION,
        "out_of_manifold": ROUTE_OUT_OF_MANIFOLD,
        "quality_insufficient": ROUTE_INSUFFICIENT,
        "support_insufficient": ROUTE_INSUFFICIENT,
        "feature_schema_mismatch": ROUTE_PROFILE_MISMATCH,
        "detector_mismatch": ROUTE_PROFILE_MISMATCH,
        "dimension_mismatch": ROUTE_PROFILE_MISMATCH,
    }
    actual_routes = {name: result["route"] for name, result in cases.items()}
    if actual_routes != expected_routes:
        raise AssertionError({"expected": expected_routes, "actual": actual_routes})

    replay = calibration + [
        ManifoldObservation(
            "sample-new-0",
            "group-new-0",
            (0.31, 0.46),
            feature_schema=FEATURE_SCHEMA,
            detector_version="synthetic-adapter-v1",
            quality_score=0.9,
        ),
        ManifoldObservation(
            "sample-new-1",
            "group-new-1",
            (0.32, 0.47),
            feature_schema=FEATURE_SCHEMA,
            detector_version="synthetic-adapter-v1",
            quality_score=0.9,
        ),
    ]
    adapted = adapt_real_manifold_profile(
        profile,
        replay,
        parent_profile_digest=profile.profile_digest,
        prototype_version="synthetic-v2",
    )
    if adapted.parent_profile_digest != profile.profile_digest or adapted.version_index != 2:
        raise AssertionError("adaptation did not create an auditable child profile")

    canonical = {
        "version": PROTOCOL_VERSION,
        "config": config.to_dict(),
        "profile": profile.to_dict(),
        "adapted_profile": adapted.to_dict(),
        "cases": cases,
    }
    route_counts: Dict[str, int] = {}
    for route in actual_routes.values():
        route_counts[route] = route_counts.get(route, 0) + 1
    return {
        "version": PROTOCOL_VERSION,
        "count": len(cases),
        "profile_digest": profile.profile_digest,
        "adapted_profile_digest": adapted.profile_digest,
        "dataset_digest": _digest(canonical),
        "route_counts": route_counts,
        "cases": cases,
        "interpretation": (
            "synthetic natural-manifold raw evidence only; in_distribution and "
            "out_of_manifold do not prove human or AI origin, and do not provide "
            "an AIGC probability or legal finding"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
