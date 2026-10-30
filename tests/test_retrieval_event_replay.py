import hashlib
import unittest
from dataclasses import replace

from aigc.retrieval_aware_tree_null import RSCPTNConfig, fit_rscptn_null_profile
from aigc.retrieval_event_replay import (
    ArchiveEntry,
    EditEvidence,
    ResearchAuthorization,
    ReplayRequest,
    RetrievalArchiveSnapshot,
    ROUTE_CANDIDATE,
    ROUTE_INSUFFICIENT,
    ROUTE_NOT_EVALUATED,
    ROUTE_NULL_CONSISTENT,
    ROUTE_OPEN_SET_UNKNOWN,
    ROUTE_REVIEW,
    replay_retrieval_event,
)


def _h(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


AUTH = ResearchAuthorization(
    authorization_id="auth-1",
    scope="offline-research",
    deletion_owner="owner-1",
    privacy_scope="private-asset-manifest-v1",
    request_principal_digest=_h("principal"),
    access_policy_digest=_h("access-policy"),
    access_audit_digest=_h("access-audit"),
    retention_policy_digest=_h("retention"),
    deletion_tombstone_digest=_h("tombstone"),
)
CONFIG = RSCPTNConfig(alpha=0.20, minimum_selected_delta=0.15)
GLOBAL_ARCHIVE_DIGEST = _h("global-index-v1")


def _entry(event_id, rank=1, *, operation="ordinary_propagation", delta=0.01,
           membership="exact", asset=None, tree=None, version=None, parent=None,
           branch="main", depth=0, retrieval_score=None, edit=False,
           generator_family="known"):
    return ArchiveEntry(
        candidate_id=f"{event_id}-c{rank}",
        candidate_rank=rank,
        retrieval_score=float(retrieval_score if retrieval_score is not None else 1.0 / rank),
        asset_id=asset or f"asset-{event_id}",
        tree_id=tree or f"tree-{event_id}",
        version_id=version or f"{event_id}-v{rank}",
        parent_version_id=parent,
        branch_id=branch,
        depth=depth,
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


def _snapshot(event_id, *, operation="ordinary_propagation", delta=0.01,
              entries=None, generator_family="known", edit=False):
    entries = tuple(entries or (_entry(event_id, operation=operation, delta=delta,
                                      generator_family=generator_family, edit=edit),))
    return RetrievalArchiveSnapshot.freeze(
        entries,
        snapshot_id=f"snapshot-{event_id}",
        query_asset_id=f"query-{event_id}",
        query_digest=_h(f"query-{event_id}"),
        retrieval_policy_digest=_h("retrieval-policy"),
        membership_policy_digest=_h("membership-policy"),
        manifest_digest=_h("manifest"),
        canonical_frame_digest=_h("frame"),
        detector_version="detector-v1",
        score_schema="paired-delta-v1",
        archive_index_digest=GLOBAL_ARCHIVE_DIGEST,
    )


def _request(snapshot, *, split="evaluation", null_profile=None,
             operation=None, edit_evidence=None, selection_trace=None,
             **kwargs):
    operation = operation or snapshot.entries[0].operation_scope if snapshot.entries else operation
    authorization = kwargs.pop("authorization", AUTH)
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
        authorization=authorization,
        null_profile=null_profile,
        rscptn_config=CONFIG,
        retrieval_archive_digest=snapshot.archive_index_digest,
        edit_evidence=edit_evidence,
        selection_trace=selection_trace,
        **kwargs,
    )


def _profile():
    events = []
    for index in range(8):
        result = replay_retrieval_event(_request(_snapshot(f"null-{index}"), split="calibration"))
        assert result.event is not None
        events.append(result.event)
    return fit_rscptn_null_profile(events, CONFIG)


class RetrievalEventReplayContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = _profile()

    def test_clean_content_event_uses_frozen_rank_and_replays_candidate(self):
        snapshot = _snapshot("clean", operation="content_edit", delta=0.80, edit=True)
        result = replay_retrieval_event(_request(
            snapshot,
            operation="content_edit",
            edit_evidence=EditEvidence(_h("mask-clean"), "inpaint", ("step-1",)),
            null_profile=self.profile,
        ))
        self.assertEqual(result.route, ROUTE_CANDIDATE)
        self.assertTrue(result.evaluated)
        self.assertEqual(result.selection_actions[0]["action"], "replay_ranked_candidates")
        self.assertNotIn("aigc_probability", result.to_dict())

    def test_same_snapshot_is_deterministic(self):
        snapshot = _snapshot("deterministic", operation="content_edit", delta=0.8, edit=True)
        request = _request(snapshot, operation="content_edit", edit_evidence=EditEvidence(
            _h("mask-deterministic"), "inpaint", ("step-1",)), null_profile=self.profile)
        one = replay_retrieval_event(request)
        two = replay_retrieval_event(request)
        self.assertEqual(one.to_dict(), two.to_dict())
        self.assertEqual(one.binding_digest, two.binding_digest)

    def test_rank_tamper_changes_binding_or_fails_closed(self):
        snapshot = _snapshot("rank-tamper", operation="content_edit", delta=0.8, edit=True)
        tampered = replace(snapshot.entries[0], candidate_rank=2)
        tampered_snapshot = replace(snapshot, entries=(tampered,))
        result = replay_retrieval_event(_request(
            tampered_snapshot, operation="content_edit",
            edit_evidence=EditEvidence(_h("mask-rank-tamper"), "inpaint", ("step-1",)),
            null_profile=self.profile,
        ))
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertIn("archive_snapshot_invalid", result.reason)

    def test_membership_tamper_is_not_soft_weighted(self):
        snapshot = _snapshot("membership", operation="content_edit", delta=0.8, edit=True)
        changed = replace(snapshot.entries[0], membership_tier="uncertain")
        changed_snapshot = RetrievalArchiveSnapshot.freeze(
            (changed,), snapshot_id=snapshot.snapshot_id, query_asset_id=snapshot.query_asset_id,
            query_digest=snapshot.query_digest, retrieval_policy_digest=snapshot.retrieval_policy_digest,
            membership_policy_digest=snapshot.membership_policy_digest, manifest_digest=snapshot.manifest_digest,
            canonical_frame_digest=snapshot.canonical_frame_digest, detector_version=snapshot.detector_version,
            score_schema=snapshot.score_schema,
        )
        result = replay_retrieval_event(_request(
            changed_snapshot, operation="content_edit",
            edit_evidence=EditEvidence(_h("mask-membership"), "inpaint", ("step-1",)),
            null_profile=self.profile,
        ))
        self.assertIn(result.route, {ROUTE_REVIEW, ROUTE_INSUFFICIENT})
        self.assertTrue(result.abstained)

    def test_selection_trace_is_generated_and_tamper_rejected(self):
        snapshot = _snapshot("action", operation="content_edit", delta=0.8, edit=True)
        clean = replay_retrieval_event(_request(
            snapshot, operation="content_edit", edit_evidence=EditEvidence(
                _h("mask-action"), "inpaint", ("step-1",)), null_profile=self.profile,
        ))
        tampered_action = replace(clean.trace.actions[0], output_candidate_ids=("forged",))
        forged_trace = replace(clean.trace, actions=(tampered_action,) + clean.trace.actions[1:])
        result = replay_retrieval_event(_request(
            snapshot, operation="content_edit", edit_evidence=EditEvidence(
                _h("mask-action"), "inpaint", ("step-1",)), null_profile=self.profile,
            selection_trace=forged_trace,
        ))
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "selection_trace_tampered")

    def test_parent_cycle_branch_and_depth_are_rejected(self):
        cycle = RetrievalArchiveSnapshot.freeze((
            _entry("cycle", 1, asset="a", tree="t", version="v1", parent="v2", depth=1),
            _entry("cycle", 2, asset="a", tree="t", version="v2", parent="v1", depth=1),
        ), snapshot_id="snapshot-cycle", query_asset_id="query-cycle", query_digest=_h("query-cycle"),
            retrieval_policy_digest=_h("retrieval-policy"), membership_policy_digest=_h("membership-policy"),
            manifest_digest=_h("manifest"), canonical_frame_digest=_h("frame"), detector_version="detector-v1", score_schema="paired-delta-v1")
        cycle_result = replay_retrieval_event(_request(cycle, operation="ordinary_propagation"))
        self.assertEqual(cycle_result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(cycle_result.reason, "propagation_tree_invalid")
        self.assertTrue(any("cycle" in error or "root_count" in error for error in cycle_result.tree_errors))

        branch = RetrievalArchiveSnapshot.freeze((
            _entry("branch", 1, asset="a", tree="t", version="v1", branch="main", depth=0),
            _entry("branch", 2, asset="a", tree="t", version="v2", parent="v1", branch="fork", depth=1),
        ), snapshot_id="snapshot-branch", query_asset_id="query-branch", query_digest=_h("query-branch"),
            retrieval_policy_digest=_h("retrieval-policy"), membership_policy_digest=_h("membership-policy"),
            manifest_digest=_h("manifest"), canonical_frame_digest=_h("frame"), detector_version="detector-v1", score_schema="paired-delta-v1")
        branch_result = replay_retrieval_event(_request(branch))
        self.assertEqual(branch_result.reason, "propagation_tree_invalid")
        self.assertTrue(any("branch_mismatch" in error for error in branch_result.tree_errors))

        depth = RetrievalArchiveSnapshot.freeze((
            _entry("depth", 1, asset="a", tree="t", version="v1", depth=0),
            _entry("depth", 2, asset="a", tree="t", version="v2", parent="v1", depth=3),
        ), snapshot_id="snapshot-depth", query_asset_id="query-depth", query_digest=_h("query-depth"),
            retrieval_policy_digest=_h("retrieval-policy"), membership_policy_digest=_h("membership-policy"),
            manifest_digest=_h("manifest"), canonical_frame_digest=_h("frame"), detector_version="detector-v1", score_schema="paired-delta-v1")
        depth_result = replay_retrieval_event(_request(depth))
        self.assertEqual(depth_result.reason, "propagation_tree_invalid")
        self.assertTrue(any("depth_mismatch" in error for error in depth_result.tree_errors))

    def test_missing_edit_mask_and_ordinary_edit_label_fail_closed(self):
        content = _snapshot("missing-mask", operation="content_edit", delta=0.8, edit=False)
        missing = replay_retrieval_event(_request(
            content, operation="content_edit", edit_evidence=EditEvidence(None, "inpaint", ("step-1",)), null_profile=self.profile,
        ))
        self.assertEqual(missing.route, ROUTE_INSUFFICIENT)
        self.assertEqual(missing.reason, "edit_mask_type_or_steps_missing")

        ordinary = _snapshot("ordinary-label", operation="ordinary_propagation", edit=False)
        labeled = replace(ordinary.entries[0], edit_type="inpaint", edit_mask_digest=_h("label"), edit_steps=("step-1",))
        labeled_snapshot = RetrievalArchiveSnapshot.freeze(
            (labeled,), snapshot_id=ordinary.snapshot_id, query_asset_id=ordinary.query_asset_id,
            query_digest=ordinary.query_digest, retrieval_policy_digest=ordinary.retrieval_policy_digest,
            membership_policy_digest=ordinary.membership_policy_digest, manifest_digest=ordinary.manifest_digest,
            canonical_frame_digest=ordinary.canonical_frame_digest, detector_version=ordinary.detector_version,
            score_schema=ordinary.score_schema,
        )
        ordinary_result = replay_retrieval_event(_request(labeled_snapshot, operation="ordinary_propagation"))
        self.assertEqual(ordinary_result.route, ROUTE_INSUFFICIENT)
        self.assertIn(ordinary_result.reason, {"ordinary_propagation_candidate_edit_label", "archive_snapshot_invalid"})

        bound_mismatch = replay_retrieval_event(_request(
            _snapshot("edit-binding", operation="content_edit", delta=0.8, edit=True),
            operation="content_edit",
            edit_evidence=EditEvidence(_h("different-mask"), "inpaint", ("step-1",)),
            null_profile=self.profile,
        ))
        self.assertEqual(bound_mismatch.route, ROUTE_INSUFFICIENT)
        self.assertEqual(bound_mismatch.reason, "edit_evidence_binding_mismatch")

    def test_missing_null_and_external_split_are_not_evaluated(self):
        snapshot = _snapshot("missing-null", operation="content_edit", delta=0.8, edit=True)
        missing = replay_retrieval_event(_request(
            snapshot, operation="content_edit", edit_evidence=EditEvidence(_h("mask-missing-null"), "inpaint", ("step-1",)),
        ))
        self.assertEqual(missing.route, ROUTE_NOT_EVALUATED)
        external = replay_retrieval_event(_request(
            snapshot, split="external", operation="content_edit", external_split=True,
            edit_evidence=EditEvidence(_h("mask-external"), "inpaint", ("step-1",)), null_profile=self.profile,
        ))
        self.assertEqual(external.route, ROUTE_NOT_EVALUATED)

    def test_ordinary_propagation_is_null_consistent(self):
        snapshot = _snapshot("ordinary", operation="ordinary_propagation", delta=0.8)
        result = replay_retrieval_event(_request(snapshot, null_profile=self.profile))
        self.assertEqual(result.route, ROUTE_NULL_CONSISTENT)

    def test_poisoning_false_positive_and_open_set_preserve_review_routes(self):
        poisoned = _snapshot("poisoned", operation="content_edit", delta=0.8, edit=True)
        poisoning = replay_retrieval_event(_request(
            poisoned, operation="content_edit", poisoning_stress_route="poisoning",
            edit_evidence=EditEvidence(_h("mask-poisoned"), "inpaint", ("step-1",)), null_profile=self.profile,
        ))
        self.assertEqual(poisoning.route, ROUTE_REVIEW)

        false_positive = _snapshot("false-positive", operation="content_edit", delta=0.8, edit=True)
        fp = replay_retrieval_event(_request(
            false_positive, operation="content_edit", reference_route="reference_ambiguous",
            edit_evidence=EditEvidence(_h("mask-false-positive"), "inpaint", ("step-1",)), null_profile=self.profile,
        ))
        self.assertEqual(fp.route, ROUTE_REVIEW)

        unknown = _snapshot("unknown", operation="content_edit", delta=0.8, edit=True, generator_family="unknown")
        unknown_result = replay_retrieval_event(_request(
            unknown, operation="content_edit", generator_family="unknown", open_set=True,
            edit_evidence=EditEvidence(_h("mask-unknown"), "inpaint", ("step-1",)), null_profile=self.profile,
        ))
        self.assertEqual(unknown_result.route, ROUTE_OPEN_SET_UNKNOWN)

        relabeled = replay_retrieval_event(_request(
            unknown, operation="content_edit", edit_evidence=EditEvidence(
                _h("mask-unknown"), "inpaint", ("step-1",)), null_profile=self.profile,
        ))
        self.assertEqual(relabeled.route, ROUTE_OPEN_SET_UNKNOWN)
        self.assertEqual(relabeled.reason, "generator_family_binding_mismatch")

    def test_privacy_and_authorization_gates(self):
        snapshot = _snapshot("privacy", operation="ordinary_propagation")
        baseline = replay_retrieval_event(_request(snapshot, null_profile=self.profile))
        changed_scope = replace(AUTH, privacy_scope="private-asset-manifest-v2")
        changed_scope_result = replay_retrieval_event(
            _request(snapshot, null_profile=self.profile, authorization=changed_scope)
        )
        self.assertEqual(baseline.route, ROUTE_NULL_CONSISTENT)
        self.assertEqual(changed_scope_result.route, ROUTE_NULL_CONSISTENT)
        self.assertNotEqual(baseline.binding_digest, changed_scope_result.binding_digest)
        missing_privacy = replay_retrieval_event(_request(
            snapshot, null_profile=self.profile, authorization=ResearchAuthorization("a", "research", "owner"),
        ))
        self.assertEqual(missing_privacy.route, ROUTE_INSUFFICIENT)
        self.assertTrue(missing_privacy.reason.startswith("privacy_"))
        expired = replace(AUTH, expires_at="2000-01-01")
        expired_result = replay_retrieval_event(_request(snapshot, null_profile=self.profile, authorization=expired, evaluation_time="2026-09-21"))
        self.assertEqual(expired_result.reason, "authorization_expired")
        deleted = replace(AUTH, deletion_tombstone_present=True)
        deleted_result = replay_retrieval_event(_request(snapshot, null_profile=self.profile, authorization=deleted))
        self.assertEqual(deleted_result.reason, "privacy_deletion_tombstone")

        valid_content = _snapshot("privacy-binding", operation="content_edit", delta=0.8, edit=True)
        base = replay_retrieval_event(_request(
            valid_content, operation="content_edit",
            edit_evidence=EditEvidence(_h("mask-privacy-binding"), "inpaint", ("step-1",)),
            null_profile=self.profile,
        ))
        changed_auth = replace(AUTH, privacy_scope="different-private-scope")
        changed = replay_retrieval_event(_request(
            valid_content, operation="content_edit", authorization=changed_auth,
            edit_evidence=EditEvidence(_h("mask-privacy-binding"), "inpaint", ("step-1",)),
            null_profile=self.profile,
        ))
        self.assertEqual(base.route, ROUTE_CANDIDATE)
        self.assertEqual(changed.route, ROUTE_CANDIDATE)
        self.assertNotEqual(base.binding_digest, changed.binding_digest)

    def test_archive_candidate_authorization_and_cross_scope_cannot_be_overridden(self):
        ordinary = _snapshot("candidate-auth", operation="ordinary_propagation")
        unauthorized_row = replace(ordinary.entries[0], authorized_for_research=False)
        unauthorized_snapshot = RetrievalArchiveSnapshot.freeze(
            (unauthorized_row,), snapshot_id=ordinary.snapshot_id, query_asset_id=ordinary.query_asset_id,
            query_digest=ordinary.query_digest, retrieval_policy_digest=ordinary.retrieval_policy_digest,
            membership_policy_digest=ordinary.membership_policy_digest, manifest_digest=ordinary.manifest_digest,
            canonical_frame_digest=ordinary.canonical_frame_digest, detector_version=ordinary.detector_version,
            score_schema=ordinary.score_schema,
        )
        unauthorized = replay_retrieval_event(_request(unauthorized_snapshot, null_profile=self.profile))
        self.assertEqual(unauthorized.route, ROUTE_INSUFFICIENT)
        self.assertTrue(any("candidate_unauthorized" in error for error in unauthorized.replay_errors))

        mixed = _snapshot("mixed-scope", operation="ordinary_propagation", entries=(
            _entry("mixed-scope", operation="ordinary_propagation", rank=1),
            _entry("mixed-scope", operation="content_edit", rank=2, edit=True),
        ))
        mixed_result = replay_retrieval_event(_request(mixed, operation="ordinary_propagation", null_profile=self.profile))
        self.assertEqual(mixed_result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(mixed_result.reason, "operation_scope_mismatch")


if __name__ == "__main__":
    unittest.main()
