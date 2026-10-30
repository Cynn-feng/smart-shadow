"""Synthetic RSCPTN runner; no image, model, or customer data is loaded."""

from __future__ import annotations

import hashlib
import json
from typing import Dict, Iterable, Tuple

from aigc.retrieval_aware_tree_null import (
    MEMBERSHIP_EXACT,
    MEMBERSHIP_OUTSIDE,
    MEMBERSHIP_UNCERTAIN,
    OPERATION_CONTENT_EDIT,
    OPERATION_ORDINARY_PROPAGATION,
    RSCPTNConfig,
    RetrievalCandidate,
    RetrievalEvent,
    evaluate_retrieval_aware_tree_null,
    fit_rscptn_null_profile,
)


HEX = "a" * 64


def _digest(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _candidate(event_id: str, rank: int, *, membership: str = MEMBERSHIP_EXACT,
               delta: float = 0.01, operation: str = OPERATION_ORDINARY_PROPAGATION,
               generator_family: str = "known") -> RetrievalCandidate:
    return RetrievalCandidate(
        candidate_id=f"{event_id}-c{rank}",
        candidate_rank=rank,
        membership_tier=membership,
        asset_id=f"asset-{event_id}",
        tree_id=f"tree-{event_id}",
        version_id=f"{event_id}-v{rank}",
        parent_version_id=None,
        branch_id="main",
        depth=rank - 1,
        paired_delta_raw=delta,
        quality_score=0.95,
        source_match_score=0.95,
        canonical_frame_digest=HEX,
        detector_version="detector-v1",
        score_schema="paired-delta-v1",
        input_digest=HEX,
        evidence_digest=HEX,
        transform_family="jpeg",
        quality_bucket="high",
        transport_bucket="same",
        time_bucket="t0",
        operation_scope=operation,
        selection_group_id=f"group-{event_id}",
        generator_family=generator_family,
    )


def _event(event_id: str, *, split: str = "calibration",
           operation: str = OPERATION_ORDINARY_PROPAGATION,
           delta: float = 0.01, generator_family: str = "known",
           open_set: bool = False, membership: str = MEMBERSHIP_EXACT,
           candidates: Tuple[RetrievalCandidate, ...] | None = None,
           reference_route: str = "reference_specific_candidate",
           poisoning_stress_route: str = "clean") -> RetrievalEvent:
    candidates = candidates or (_candidate(event_id, 1, membership=membership,
                                            delta=delta, operation=operation,
                                            generator_family=generator_family),)
    split_digest = "b" * 64 if split == "calibration" else "c" * 64
    return RetrievalEvent(
        event_id=event_id,
        query_digest=HEX,
        retrieval_policy_digest=HEX,
        candidates=candidates,
        manifest_digest="d" * 64,
        split_digest=split_digest,
        calibration_split_digest="b" * 64,
        evaluation_split_digest="c" * 64,
        selection_policy_digest=HEX,
        selection_key_digest=HEX,
        canonical_frame_digest=HEX,
        detector_version="detector-v1",
        score_schema="paired-delta-v1",
        action_budget=2,
        input_digest=HEX,
        evidence_digest=HEX,
        retrieval_archive_digest=HEX,
        membership_policy_digest=HEX,
        decoy_injection_digest=HEX,
        split=split,
        query_asset_id=f"query-{event_id}",
        operation_scope=operation,
        candidate_count=len(candidates),
        reference_route=reference_route,
        open_set=open_set,
        poisoning_stress_route=poisoning_stress_route,
        generator_family=generator_family,
    )


def _profile(config: RSCPTNConfig, *, family: str = "known", contaminated: bool = False):
    events = []
    for index in range(8):
        if contaminated:
            events.append(_event(
                f"contam-null-{index}", generator_family=family,
                candidates=(
                    _candidate(f"contam-null-{index}", 1, delta=0.01),
                    _candidate(f"contam-null-{index}", 2, membership=MEMBERSHIP_UNCERTAIN, delta=0.01),
                ),
            ))
        else:
            events.append(_event(f"null-{family}-{index}", generator_family=family))
    return fit_rscptn_null_profile(events, config)


def _tie_profile(config: RSCPTNConfig):
    events = []
    for index in range(8):
        event_id = f"tie-null-{index}"
        events.append(_event(
            event_id,
            candidates=(
                _candidate(event_id, 1, delta=0.01),
                _candidate(event_id, 2, delta=0.01),
            ),
        ))
    return fit_rscptn_null_profile(events, config)


def main() -> None:
    config = RSCPTNConfig(alpha=0.20, minimum_selected_delta=0.15)
    clean_profile = _profile(config)
    unknown_profile = _profile(config, family="unknown")
    contaminated_profile = _profile(config, contaminated=True)
    tie_profile = _tie_profile(config)
    cases = (
        ("dual_null_candidate", _event("candidate", split="evaluation",
                                        operation=OPERATION_CONTENT_EDIT, delta=0.80), clean_profile),
        ("ordinary_propagation", _event("ordinary", split="evaluation", delta=0.80), clean_profile),
        ("wrong_reference", _event("wrong-reference", split="evaluation",
                                    operation=OPERATION_CONTENT_EDIT, delta=0.80,
                                    reference_route="reference_ambiguous"), clean_profile),
        ("selection_tie", _event(
            "tie", split="evaluation", operation=OPERATION_CONTENT_EDIT,
            candidates=(
                _candidate("tie", 1, delta=0.80, operation=OPERATION_CONTENT_EDIT),
                _candidate("tie", 2, delta=0.80, operation=OPERATION_CONTENT_EDIT),
            ),
        ), tie_profile),
        ("poisoning", _event("poisoning", split="evaluation", operation=OPERATION_CONTENT_EDIT,
                              delta=0.80, poisoning_stress_route="poisoning"), clean_profile),
        ("low_delta", _event("low", split="evaluation", operation=OPERATION_CONTENT_EDIT,
                              delta=0.02), clean_profile),
        ("open_set_unknown", _event("unknown", split="evaluation", operation=OPERATION_CONTENT_EDIT,
                                    delta=0.80, generator_family="unknown", open_set=True), unknown_profile),
        ("membership_contamination", _event(
            "contaminated", split="evaluation", operation=OPERATION_CONTENT_EDIT,
            candidates=(
                _candidate("contaminated", 1, delta=0.80, operation=OPERATION_CONTENT_EDIT),
                _candidate("contaminated", 2, membership=MEMBERSHIP_UNCERTAIN, delta=0.75,
                           operation=OPERATION_CONTENT_EDIT),
            ),
        ), contaminated_profile),
        ("outside_candidate", _event(
            "outside", split="evaluation", operation=OPERATION_CONTENT_EDIT,
            candidates=(_candidate("outside", 1, membership=MEMBERSHIP_OUTSIDE, delta=0.80,
                                   operation=OPERATION_CONTENT_EDIT),),
        ), clean_profile),
    )
    rows = []
    for case_id, event, profile in cases:
        result = evaluate_retrieval_aware_tree_null(event, profile, config)
        rows.append({"case_id": case_id, "result": result.to_dict()})
    route_counts: Dict[str, int] = {}
    for row in rows:
        route = row["result"]["route"]
        route_counts[route] = route_counts.get(route, 0) + 1
    dataset_digest = _digest({
        "config": config.to_dict(),
        "profiles": [clean_profile.to_dict(), unknown_profile.to_dict(), contaminated_profile.to_dict(),
                     tie_profile.to_dict()],
        "cases": rows,
    })
    print(json.dumps({
        "version": "retrieval-aware-tree-null-synthetic-v1",
        "count": len(rows),
        "route_counts": dict(sorted(route_counts.items())),
        "config_digest": config.config_digest,
        "profile_digests": [clean_profile.profile_digest, unknown_profile.profile_digest,
                             contaminated_profile.profile_digest, tie_profile.profile_digest],
        "dataset_digest": dataset_digest,
        "cases": rows,
        "interpretation": "synthetic raw contract only; routes are not AIGC probabilities or legal findings",
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
