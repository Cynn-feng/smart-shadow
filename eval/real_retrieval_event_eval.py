"""ALG-001 replay runner.

The repository currently has no authorized retrieval archive or real image
manifest.  This runner therefore exercises the replay contract with synthetic
rows and explicitly labels the result as ``not_evaluated`` for real-world
performance.  It is useful for regression of tamper/fail-closed behavior; it
does not print accuracy, FPR, probability, or customer metrics.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, Tuple

from aigc.retrieval_aware_tree_null import RSCPTNConfig, fit_rscptn_null_profile
from aigc.retrieval_event_replay import (
    ArchiveEntry,
    EditEvidence,
    ResearchAuthorization,
    ReplayRequest,
    RetrievalArchiveSnapshot,
    replay_retrieval_event,
)


def _h(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


AUTH = ResearchAuthorization(
    authorization_id="synthetic-auth",
    scope="offline-contract-fixture",
    deletion_owner="fixture-owner",
    privacy_scope="synthetic-only",
    request_principal_digest=_h("principal"),
    access_policy_digest=_h("access-policy"),
    access_audit_digest=_h("access-audit"),
    retention_policy_digest=_h("retention"),
    deletion_tombstone_digest=_h("tombstone"),
)
CONFIG = RSCPTNConfig(alpha=0.20, minimum_selected_delta=0.15)
GLOBAL_ARCHIVE_DIGEST = _h("global-index-fixture-v1")


def _entry(event_id: str, *, operation: str = "ordinary_propagation", delta: float = 0.01,
           membership: str = "exact", rank: int = 1, asset_id: str | None = None,
           generator_family: str = "known", edit: bool = False) -> ArchiveEntry:
    return ArchiveEntry(
        candidate_id=f"{event_id}-c{rank}",
        candidate_rank=rank,
        retrieval_score=1.0 / rank,
        asset_id=asset_id or f"asset-{event_id}",
        tree_id=f"tree-{event_id}",
        version_id=f"{event_id}-v{rank}",
        parent_version_id=None,
        branch_id="main",
        depth=0,
        membership_tier=membership,
        paired_delta_raw=delta,
        quality_score=0.95,
        source_match_score=0.95,
        canonical_frame_digest=_h("frame"),
        detector_version="detector-v1",
        score_schema="paired-delta-v1",
        operation_scope=operation,
        transform_family="jpeg",
        quality_bucket="high",
        transport_bucket="same",
        time_bucket="t0",
        selection_group_id=f"group-{event_id}",
        generator_family=generator_family,
        edit_mask_digest=_h(f"mask-{event_id}") if edit else None,
        edit_type="inpaint" if edit else None,
        edit_steps=("step-1",) if edit else (),
    )


def _snapshot(event_id: str, *, operation: str = "ordinary_propagation", delta: float = 0.01,
              membership: str = "exact", generator_family: str = "known", edit: bool = False,
              entries: Iterable[ArchiveEntry] | None = None) -> RetrievalArchiveSnapshot:
    rows = tuple(entries) if entries is not None else (_entry(
        event_id, operation=operation, delta=delta, membership=membership,
        generator_family=generator_family, edit=edit,
    ),)
    return RetrievalArchiveSnapshot.freeze(
        rows,
        snapshot_id=f"snapshot-{event_id}",
        query_asset_id=f"query-{event_id}",
        query_digest=_h(f"query-{event_id}"),
        retrieval_policy_digest=_h("retrieval-policy"),
        membership_policy_digest=_h("membership-policy"),
        manifest_digest=_h("synthetic-manifest"),
        canonical_frame_digest=_h("frame"),
        detector_version="detector-v1",
        score_schema="paired-delta-v1",
        archive_index_digest=GLOBAL_ARCHIVE_DIGEST,
    )


def _request(snapshot: RetrievalArchiveSnapshot, *, split: str = "evaluation",
             null_profile=None, operation: str | None = None, edit: bool = False,
             **kwargs: Any) -> ReplayRequest:
    operation = operation or (snapshot.entries[0].operation_scope if snapshot.entries else "content_edit")
    edit_evidence = EditEvidence(_h(f"mask-{snapshot.snapshot_id[9:]}"), "inpaint", ("step-1",)) if edit else None
    return ReplayRequest(
        event_id=snapshot.snapshot_id,
        snapshot=snapshot,
        query_digest=snapshot.query_digest,
        query_asset_id=snapshot.query_asset_id,
        manifest_digest=snapshot.manifest_digest,
        split=split,
        calibration_split_digest=_h("calibration-split"),
        evaluation_split_digest=_h("evaluation-split"),
        operation_scope=operation,
        authorization=AUTH,
        null_profile=null_profile,
        rscptn_config=CONFIG,
        retrieval_archive_digest=GLOBAL_ARCHIVE_DIGEST,
        edit_evidence=edit_evidence,
        **kwargs,
    )


def _profile():
    events = []
    for index in range(8):
        snapshot = _snapshot(f"null-{index}")
        result = replay_retrieval_event(_request(snapshot, split="calibration"))
        if result.event is None:
            raise RuntimeError(f"calibration fixture failed: {result.reason}")
        events.append(result.event)
    return fit_rscptn_null_profile(events, CONFIG)


def main() -> None:
    profile = _profile()
    cases = (
        ("clean", _request(_snapshot("clean", operation="content_edit", delta=0.80, edit=True), operation="content_edit", edit=True, null_profile=profile)),
        ("missing", _request(_snapshot("missing", entries=()), operation="content_edit", edit=True, null_profile=profile)),
        ("false_positive", _request(_snapshot("false-positive", operation="content_edit", delta=0.80, edit=True), operation="content_edit", edit=True, reference_route="reference_ambiguous", null_profile=profile)),
        ("planted_near_duplicate", _request(_snapshot("near-duplicate", operation="content_edit", delta=0.80, membership="matched", edit=True), operation="content_edit", edit=True, null_profile=profile)),
        ("wrong_reference", _request(_snapshot("wrong-reference", operation="content_edit", delta=0.80, edit=True), operation="content_edit", edit=True, reference_route="reference_ambiguous", null_profile=profile)),
        ("ordinary_propagation", _request(_snapshot("ordinary", delta=0.80), null_profile=profile)),
        ("unknown_generator", _request(_snapshot("unknown", operation="content_edit", delta=0.80, generator_family="unknown", edit=True), operation="content_edit", edit=True, generator_family="unknown", open_set=True, null_profile=profile)),
        ("next_time_window", _request(_snapshot("next-window", operation="content_edit", delta=0.80, edit=True), split="external", external_split=True, operation="content_edit", edit=True, null_profile=profile)),
        ("poisoning", _request(_snapshot("poisoning", operation="content_edit", delta=0.80, edit=True), operation="content_edit", edit=True, poisoning_stress_route="poisoning", null_profile=profile)),
    )
    rows = []
    for case_id, request in cases:
        result = replay_retrieval_event(request)
        rows.append({"case_id": case_id, "route": result.route, "reason": result.reason, "result": result.to_dict()})
    route_counts: Dict[str, int] = {}
    for row in rows:
        route_counts[row["route"]] = route_counts.get(row["route"], 0) + 1
    dataset_digest = _h({"config": CONFIG.to_dict(), "profile": profile.to_dict(), "cases": rows})
    print(json.dumps({
        "version": "real-retrieval-event-eval-contract-v1",
        "count": len(rows),
        "route_counts": dict(sorted(route_counts.items())),
        "dataset_digest": dataset_digest,
        "profile_digest": profile.profile_digest,
        "cases": rows,
        "real_data_status": "not_evaluated",
        "interpretation": "synthetic replay contract only; no real archive, image, model, FPR, probability, customer, or legal metric",
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
