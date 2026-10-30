"""Synthetic contract runner for the blind reference-specificity gate."""

from __future__ import annotations

import hashlib
import json

from aigc.reference_specificity import (
    ROUTE_INSUFFICIENT,
    ROUTE_REFERENCE_AMBIGUOUS,
    ROUTE_REFERENCE_NULL_CONSISTENT,
    ROUTE_REFERENCE_SPECIFIC,
    ReferenceSpecificityBatch,
    ReferenceSpecificityConfig,
    ReferenceSpecificityObservation,
    evaluate_reference_specificity,
)


HEXES = ["a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64, "f" * 64, "1" * 64, "2" * 64, "3" * 64]


def _reference_digest(index):
    return hashlib.sha256(f"reference-specificity-decoy-{index}".encode("utf-8")).hexdigest()


def _obs(observation_id, reference_digest, role, contrast, *, quality_bucket="high", source_match_bucket="matched"):
    return ReferenceSpecificityObservation(
        observation_id=observation_id,
        reference_digest=reference_digest,
        role=role,
        contrast_raw=contrast,
        quality_score=0.90,
        source_match_score=0.85,
        quality_bucket=quality_bucket,
        source_match_bucket=source_match_bucket,
    )


def _batch(candidate, decoys, *, selection_split_digest=HEXES[7], quality_bucket="high", source_match_bucket="matched"):
    return ReferenceSpecificityBatch(
        query_digest=HEXES[0],
        evaluation_split_digest=HEXES[1],
        selection_split_digest=selection_split_digest,
        manifest_digest=HEXES[2],
        canonical_frame_digest=HEXES[3],
        transform_spec_digest=HEXES[4],
        operator_digest=HEXES[5],
        detector_version="detector-v1",
        score_schema="contrast-v1",
        quality_bucket=quality_bucket,
        source_match_bucket=source_match_bucket,
        selection_policy_digest=HEXES[6],
        candidate=_obs("candidate", HEXES[1], "candidate", candidate, quality_bucket=quality_bucket, source_match_bucket=source_match_bucket),
        decoys=tuple(
            _obs(f"decoy-{index}", _reference_digest(index), "decoy", value, quality_bucket=quality_bucket, source_match_bucket=source_match_bucket)
            for index, value in enumerate(decoys)
        ),
    )


def main() -> None:
    config = ReferenceSpecificityConfig(minimum_decoy_count=3, decoy_quantile=0.75)
    cases = [
        (
            "specific_candidate",
            _batch(0.80, (0.10, 0.15, 0.20) + (0.20,) * 21),
            ROUTE_REFERENCE_SPECIFIC,
        ),
        ("ambiguous_decoys", _batch(0.80, (0.72, 0.76, 0.78)), ROUTE_REFERENCE_AMBIGUOUS),
        ("null_consistent", _batch(0.01, (0.02, 0.03, 0.04)), ROUTE_REFERENCE_NULL_CONSISTENT),
        ("support_missing", _batch(0.80, (0.10, 0.15)), ROUTE_INSUFFICIENT),
        ("bucket_mismatch", _batch(0.80, (0.10, 0.15, 0.20), quality_bucket="high"), ROUTE_REFERENCE_SPECIFIC),
    ]
    # Make the last case fail closed by changing one decoy's quality bucket.
    mismatched = _batch(0.80, (0.10, 0.15, 0.20))
    mismatched = ReferenceSpecificityBatch(
        **{**mismatched.__dict__, "decoys": (mismatched.decoys[0], _obs("decoy-1", HEXES[3], "decoy", 0.15, quality_bucket="medium"), mismatched.decoys[2])}
    )
    cases[-1] = ("bucket_mismatch", mismatched, ROUTE_INSUFFICIENT)
    outputs = []
    for case_id, batch, expected in cases:
        result = evaluate_reference_specificity(batch, config=config)
        if result.route != expected:
            raise AssertionError(f"{case_id}: expected {expected}, got {result.route}")
        outputs.append({"case_id": case_id, "expected_route": expected, "result": result.to_dict()})
    digest = hashlib.sha256(json.dumps(outputs, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    counts = {}
    for item in outputs:
        route = item["result"]["route"]
        counts[route] = counts.get(route, 0) + 1
    print(json.dumps({
        "version": "reference-specificity-synthetic-v1",
        "scope": "synthetic raw reference-specificity contract only",
        "interpretation": "routes are raw evidence and do not imply AIGC probability, provenance, authorship, legal finding, or production performance",
        "count": len(outputs),
        "route_counts": counts,
        "dataset_digest": digest,
        "cases": outputs,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
