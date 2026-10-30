import hashlib
import unittest
from dataclasses import replace

from eval.temporal_lifecycle_gate_eval import run_synthetic_evaluation
from aigc.temporal_lifecycle_gate import (
    EVENT_CREATE,
    EVENT_DELETE,
    EVENT_RESTORE,
    OPERATION_CONTENT_EDIT,
    OPERATION_ORDINARY_PROPAGATION,
    ROUTE_DELETION_REPLAY_MISMATCH,
    ROUTE_FUTURE_EVENT_LEAK,
    ROUTE_INSUFFICIENT,
    ROUTE_LIFECYCLE_CONSISTENT,
    ROUTE_NOT_EVALUATED,
    ROUTE_PROFILE_STALE,
    ROUTE_STALE_SNAPSHOT_REVIEW,
    ROUTE_TOMBSTONED_INSUFFICIENT,
    TemporalLifecycleConfig,
    TemporalLifecycleEvent,
    TemporalLifecycleRequest,
    evaluate_temporal_lifecycle,
)


class TemporalLifecycleGateTests(unittest.TestCase):
    def setUp(self):
        self.manifest = self.h("manifest")
        self.authorization = self.h("authorization")
        self.retention = self.h("retention")
        self.access = self.h("access")
        self.profile = self.h("profile")
        self.upstream = self.h("upstream")
        self.config = TemporalLifecycleConfig(maximum_profile_age_days=30)

    @staticmethod
    def h(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def events(self, specs, *, snapshot_id="snapshot-1", asset_id="asset-1"):
        rows = []
        previous = None
        for number, spec in enumerate(specs, 1):
            event = TemporalLifecycleEvent(
                event_id=spec.get("event_id", f"event-{number}"),
                asset_id=asset_id,
                version_id=spec["version_id"],
                sequence=number,
                event_time=spec.get("event_time", f"2026-09-20T0{number}:00:00Z"),
                event_type=spec["event_type"],
                content_digest=self.h(spec.get("content", f"content-{number}")),
                manifest_digest=self.manifest,
                authorization_digest=self.authorization,
                retention_policy_digest=self.retention,
                access_policy_digest=self.access,
                snapshot_id=snapshot_id,
                parent_version_id=spec.get("parent_version_id"),
                previous_event_digest=previous,
                deletion_tombstone_digest=(
                    self.h(spec.get("event_id", f"event-{number}") + "-tombstone")
                    if spec["event_type"] == EVENT_DELETE
                    else None
                ),
                restores_event_id=spec.get("restores_event_id"),
            )
            rows.append(event)
            previous = event.computed_digest
        return tuple(rows)

    def request(
        self,
        rows=None,
        *,
        query_as_of="2026-09-20T12:00:00Z",
        snapshot_created_at="2026-09-20T10:00:00Z",
        snapshot_sequence=None,
        ledger_head_sequence=None,
        ledger_head_event_time=None,
        selected_version_id="v1",
        split="evaluation",
        operation_scope=OPERATION_CONTENT_EDIT,
        upstream_route="candidate_edit",
        profile_fitted_through="2026-09-19T12:00:00Z",
        profile_max_age_days=None,
        expected_snapshot_digest=None,
        authorization_digest=None,
    ):
        rows = tuple(rows if rows is not None else self.events([{"version_id": "v1", "event_type": EVENT_CREATE}]))
        snapshot_sequence = len(rows) if snapshot_sequence is None else snapshot_sequence
        ledger_head_sequence = snapshot_sequence if ledger_head_sequence is None else ledger_head_sequence
        return TemporalLifecycleRequest(
            event_id="query-event",
            asset_id="asset-1",
            query_as_of=query_as_of,
            snapshot_id="snapshot-1",
            snapshot_created_at=snapshot_created_at,
            snapshot_sequence=snapshot_sequence,
            ledger_head_sequence=ledger_head_sequence,
            ledger_head_event_time=ledger_head_event_time,
            index_epoch="epoch-1",
            events=rows,
            selected_version_id=selected_version_id,
            manifest_digest=self.manifest,
            authorization_digest=authorization_digest or self.authorization,
            retention_policy_digest=self.retention,
            access_policy_digest=self.access,
            profile_digest=self.profile,
            profile_fitted_through=profile_fitted_through,
            profile_max_age_days=profile_max_age_days,
            split=split,
            operation_scope=operation_scope,
            upstream_route=upstream_route,
            upstream_evidence_digest=self.upstream,
            expected_snapshot_digest=expected_snapshot_digest,
        )

    def test_valid_candidate_is_lifecycle_consistent_and_downstream_eligible(self):
        result = evaluate_temporal_lifecycle(self.request(), self.config)
        self.assertEqual(result.route, ROUTE_LIFECYCLE_CONSISTENT)
        self.assertTrue(result.downstream_eligible)
        self.assertFalse(result.abstained)

    def test_reversed_input_order_has_same_digest(self):
        rows = self.events([
            {"version_id": "v1", "event_type": EVENT_CREATE},
            {"version_id": "v1", "event_type": "update", "event_time": "2026-09-20T02:00:00Z"},
        ])
        first = evaluate_temporal_lifecycle(self.request(rows), self.config)
        second = evaluate_temporal_lifecycle(self.request(tuple(reversed(rows))), self.config)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_event_after_query_is_future_leak(self):
        rows = self.events([{"version_id": "v1", "event_type": EVENT_CREATE, "event_time": "2026-09-20T13:00:00Z"}])
        result = evaluate_temporal_lifecycle(self.request(rows, snapshot_created_at="2026-09-20T09:00:00Z"), self.config)
        self.assertEqual(result.route, ROUTE_FUTURE_EVENT_LEAK)

    def test_effective_interval_after_query_is_future_leak(self):
        rows = self.events([{"version_id": "v1", "event_type": EVENT_CREATE}])
        tampered = (replace(rows[0], effective_from="2026-09-20T13:00:00Z"),)
        result = evaluate_temporal_lifecycle(self.request(tampered), self.config)
        self.assertEqual(result.route, ROUTE_FUTURE_EVENT_LEAK)

    def test_snapshot_created_after_query_is_future_leak(self):
        result = evaluate_temporal_lifecycle(self.request(snapshot_created_at="2026-09-20T13:00:00Z"), self.config)
        self.assertEqual(result.reason, "snapshot_created_after_query_as_of")
        self.assertEqual(result.route, ROUTE_FUTURE_EVENT_LEAK)

    def test_snapshot_behind_visible_head_is_stale_review(self):
        result = evaluate_temporal_lifecycle(
            self.request(snapshot_sequence=1, ledger_head_sequence=2, ledger_head_event_time="2026-09-20T11:00:00Z"),
            self.config,
        )
        self.assertEqual(result.route, ROUTE_STALE_SNAPSHOT_REVIEW)

    def test_future_ledger_head_is_future_leak(self):
        result = evaluate_temporal_lifecycle(
            self.request(snapshot_sequence=1, ledger_head_sequence=2, ledger_head_event_time="2026-09-20T13:00:00Z"),
            self.config,
        )
        self.assertEqual(result.route, ROUTE_FUTURE_EVENT_LEAK)

    def test_profile_older_than_max_age_is_stale(self):
        result = evaluate_temporal_lifecycle(
            self.request(profile_fitted_through="2026-07-01T00:00:00Z", profile_max_age_days=7),
            self.config,
        )
        self.assertEqual(result.route, ROUTE_PROFILE_STALE)

    def test_deleted_selected_version_is_tombstoned(self):
        rows = self.events([
            {"version_id": "v1", "event_type": EVENT_CREATE},
            {"version_id": "v1", "event_type": EVENT_DELETE, "event_time": "2026-09-20T02:00:00Z"},
        ])
        result = evaluate_temporal_lifecycle(self.request(rows), self.config)
        self.assertEqual(result.route, ROUTE_TOMBSTONED_INSUFFICIENT)
        self.assertTrue(result.deletion_seen)
        self.assertFalse(result.downstream_eligible)

    def test_valid_restore_requires_new_version_and_can_be_selected(self):
        rows = self.events([
            {"version_id": "v1", "event_type": EVENT_CREATE},
            {"version_id": "v1", "event_type": EVENT_DELETE, "event_time": "2026-09-20T02:00:00Z"},
            {"version_id": "v2", "event_type": EVENT_RESTORE, "parent_version_id": "v1", "restores_event_id": "event-2", "event_time": "2026-09-20T03:00:00Z"},
        ])
        result = evaluate_temporal_lifecycle(self.request(rows, selected_version_id="v2"), self.config)
        self.assertEqual(result.route, ROUTE_LIFECYCLE_CONSISTENT)
        self.assertTrue(result.downstream_eligible)
        self.assertEqual(result.active_version_ids, ("v2",))

    def test_restore_binding_mismatch_is_deletion_replay_mismatch(self):
        rows = self.events([
            {"version_id": "v1", "event_type": EVENT_CREATE},
            {"version_id": "v1", "event_type": EVENT_DELETE, "event_time": "2026-09-20T02:00:00Z"},
            {"version_id": "v1", "event_type": EVENT_RESTORE, "parent_version_id": "wrong", "restores_event_id": "event-2", "event_time": "2026-09-20T03:00:00Z"},
        ])
        result = evaluate_temporal_lifecycle(self.request(rows, selected_version_id="v1"), self.config)
        self.assertEqual(result.route, ROUTE_DELETION_REPLAY_MISMATCH)

    def test_binding_digest_mismatch_is_insufficient(self):
        result = evaluate_temporal_lifecycle(self.request(authorization_digest=self.h("wrong")), self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "lifecycle_binding_mismatch")

    def test_cross_tenant_event_is_insufficient(self):
        rows = self.events([{"version_id": "v1", "event_type": EVENT_CREATE}])
        tampered = (replace(rows[0], tenant_id="tenant-other"),)
        result = evaluate_temporal_lifecycle(self.request(tampered), self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "lifecycle_binding_mismatch")

    def test_event_chain_mismatch_is_insufficient(self):
        rows = self.events([{"version_id": "v1", "event_type": EVENT_CREATE}])
        tampered = replace(rows[0], previous_event_digest=self.h("unexpected"))
        result = evaluate_temporal_lifecycle(self.request((tampered,)), self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "event_chain_invalid")

    def test_sequence_gap_is_insufficient(self):
        rows = self.events([{"version_id": "v1", "event_type": EVENT_CREATE}, {"version_id": "v1", "event_type": "update"}])
        tampered = (rows[0], replace(rows[1], sequence=3, previous_event_digest=rows[0].computed_digest))
        result = evaluate_temporal_lifecycle(self.request(tampered, snapshot_sequence=3), self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)

    def test_external_split_is_not_evaluated(self):
        result = evaluate_temporal_lifecycle(self.request(split="external"), self.config)
        self.assertEqual(result.route, ROUTE_NOT_EVALUATED)
        self.assertFalse(result.evaluated)

    def test_open_set_upstream_cannot_be_repaired(self):
        result = evaluate_temporal_lifecycle(self.request(upstream_route="open_set_unknown"), self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertFalse(result.downstream_eligible)

    def test_ordinary_propagation_never_becomes_downstream_candidate(self):
        result = evaluate_temporal_lifecycle(
            self.request(operation_scope=OPERATION_ORDINARY_PROPAGATION, upstream_route="candidate_edit"),
            self.config,
        )
        self.assertEqual(result.route, ROUTE_LIFECYCLE_CONSISTENT)
        self.assertFalse(result.downstream_eligible)

    def test_expected_snapshot_digest_tamper_is_insufficient(self):
        result = evaluate_temporal_lifecycle(self.request(expected_snapshot_digest=self.h("wrong")), self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "snapshot_digest_mismatch")

    def test_result_field_hygiene_and_runner(self):
        result = evaluate_temporal_lifecycle(self.request(), self.config)
        text = str(result.to_dict()).lower()
        for forbidden in ("probability", "confidence", "human_supported", "ai_generated_supported", "copyright", "legal"):
            self.assertNotIn(forbidden, text)
        first = run_synthetic_evaluation()
        second = run_synthetic_evaluation()
        self.assertEqual(first["dataset_digest"], second["dataset_digest"])
        self.assertGreaterEqual(first["count"], 12)


if __name__ == "__main__":
    unittest.main()
