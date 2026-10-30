import hashlib
import unittest

from aigc.selection_aware_acquisition import (
    ACTION_ALTERNATE_OPERATOR,
    ACTION_ALTERNATE_VIEW,
    ACTION_APPEND_DECOY,
    ACTION_BUILD_NULL,
    ACTION_REALIGN_QUALITY,
    ROUTE_INSUFFICIENT,
    ROUTE_REVIEW,
    ROUTE_SELECTION_SPECIFIC,
    STATUS_ACQUIRE,
    STATUS_CANDIDATE,
    STATUS_INSUFFICIENT,
    GENERATOR_ROUTE_KNOWN_FAMILY_SUPPORTED,
    RETRIEVAL_REPLAY_ROUTE_CONSISTENT,
    compute_generator_evidence_digest,
    compute_retrieval_event_digest,
    SelectionAwareAcquisitionConfig,
    SelectionAwareEvidenceState,
    SelectionAwareObservation,
    plan_selection_aware_acquisition,
    run_selection_aware_acquisition,
)


def _hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SelectionAwareAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.config = SelectionAwareAcquisitionConfig(max_actions=3, max_cost_units=5)

    def _state(self, **overrides):
        values = {
            "case_id": "case-1",
            "asset_id": "asset-1",
            "manifest_digest": _hex("manifest"),
            "detector_version": "detector-v1",
            "score_schema": "score-v1",
            "quality_score": 0.9,
            "source_match_score": 0.9,
            "selection_route": "selection_specific_candidate",
            "selection_p_value_raw": 0.01,
            "specificity_gap_raw": 0.4,
            "invariant_route": "invariant_candidate",
            "null_support": 20,
            "null_profile_digest": _hex("null"),
            "selection_evidence_digest": _hex("selection"),
            "invariant_evidence_digest": _hex("invariant"),
        }
        values.update(overrides)
        gate_policy = self.config.gate_policy_digest
        values.setdefault("operation_scope", "content_edit")
        values.setdefault("generator_route", GENERATOR_ROUTE_KNOWN_FAMILY_SUPPORTED)
        values.setdefault("generator_profile_digest", _hex("generator-profile"))
        values.setdefault("generator_input_digest", _hex(values["case_id"] + "-generator-input"))
        values.setdefault("gate_policy_digest", gate_policy)
        values.setdefault(
            "generator_evidence_digest",
            compute_generator_evidence_digest(
                values["generator_route"],
                values["generator_profile_digest"],
                values["generator_input_digest"],
                gate_policy,
            ),
        )
        values.setdefault("retrieval_replay_route", RETRIEVAL_REPLAY_ROUTE_CONSISTENT)
        values.setdefault(
            "retrieval_event_digest",
            compute_retrieval_event_digest(
                values["retrieval_replay_route"],
                case_id=values["case_id"],
                asset_id=values["asset_id"],
                manifest_digest=values["manifest_digest"],
                gate_policy_digest=gate_policy,
            ),
        )
        return SelectionAwareEvidenceState(**values)

    def _observation(self, action, state, step, updates=None, ok=True, output="output"):
        return SelectionAwareObservation(
            action_id=action,
            step=step,
            input_digest=state.input_digest,
            output_digest=_hex(output) if ok else None,
            raw_updates=updates or {},
            ok=ok,
            failure_reason=None if ok else "executor_unavailable",
        )

    def test_all_registered_gates_stop_as_candidate(self):
        plan = plan_selection_aware_acquisition(self._state(), config=self.config)
        self.assertEqual(plan.status, STATUS_CANDIDATE)
        self.assertEqual(plan.route, ROUTE_SELECTION_SPECIFIC)
        self.assertIsNone(plan.next_action)

    def test_selection_ambiguity_requests_decoy(self):
        plan = plan_selection_aware_acquisition(
            self._state(selection_route="selection_ambiguous"), config=self.config
        )
        self.assertEqual(plan.status, STATUS_ACQUIRE)
        self.assertEqual(plan.next_action.action_id, ACTION_APPEND_DECOY)

    def test_null_support_requests_matched_null(self):
        plan = plan_selection_aware_acquisition(
            self._state(
                selection_route="insufficient",
                selection_p_value_raw=None,
                specificity_gap_raw=None,
                null_support=0,
                null_profile_digest=None,
            ),
            config=self.config,
        )
        self.assertEqual(plan.next_action.action_id, ACTION_BUILD_NULL)

    def test_invariant_instability_requests_view_then_operator(self):
        state = self._state(invariant_route="view_operator_inconsistent")
        first = plan_selection_aware_acquisition(state, config=self.config)
        self.assertEqual(first.next_action.action_id, ACTION_ALTERNATE_VIEW)
        state = self._state(invariant_route="view_operator_inconsistent", completed_actions=(ACTION_ALTERNATE_VIEW,))
        second = plan_selection_aware_acquisition(state, config=self.config)
        self.assertEqual(second.next_action.action_id, ACTION_ALTERNATE_OPERATOR)

    def test_quality_gate_requests_realign(self):
        plan = plan_selection_aware_acquisition(self._state(quality_score=0.2), config=self.config)
        self.assertEqual(plan.next_action.action_id, ACTION_REALIGN_QUALITY)

    def test_replay_from_decoy_to_candidate_is_deterministic(self):
        initial = self._state(selection_route="selection_ambiguous")
        observation = self._observation(
            ACTION_APPEND_DECOY,
            initial,
            1,
            {
                "selection_route": "selection_specific_candidate",
                "selection_p_value_raw": 0.01,
                "specificity_gap_raw": 0.4,
                "selection_evidence_digest": _hex("selection-after-decoy"),
            },
        )
        first = run_selection_aware_acquisition(initial, [observation], config=self.config)
        second = run_selection_aware_acquisition(initial, [observation], config=self.config)
        self.assertEqual(first.status, STATUS_CANDIDATE)
        self.assertEqual(first.route, ROUTE_SELECTION_SPECIFIC)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_replay_requires_current_input_digest_and_order(self):
        initial = self._state(selection_route="selection_ambiguous")
        observation = SelectionAwareObservation(
            action_id=ACTION_BUILD_NULL,
            step=1,
            input_digest=initial.input_digest,
            output_digest=_hex("output"),
            raw_updates={},
        )
        result = run_selection_aware_acquisition(initial, [observation], config=self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertTrue(result.abstained)

    def test_failed_probe_routes_review(self):
        initial = self._state(selection_route="selection_ambiguous")
        observation = self._observation(ACTION_APPEND_DECOY, initial, 1, ok=False)
        result = run_selection_aware_acquisition(initial, [observation], config=self.config)
        self.assertEqual(result.route, ROUTE_REVIEW)
        self.assertTrue(result.abstained)

    def test_replay_rejects_probability_fields(self):
        initial = self._state(selection_route="selection_ambiguous")
        with self.assertRaises(ValueError):
            self._observation(
                ACTION_APPEND_DECOY,
                initial,
                1,
                {"aigc_probability": 0.9},
            )

    def test_budget_exhaustion_is_explicit(self):
        config = SelectionAwareAcquisitionConfig(max_actions=1, max_cost_units=1)
        state = self._state(selection_route="selection_ambiguous")
        observation = self._observation(
            ACTION_APPEND_DECOY,
            state,
            1,
            {"selection_route": "selection_ambiguous"},
        )
        result = run_selection_aware_acquisition(state, [observation], config=config)
        self.assertIn(result.route, {ROUTE_REVIEW, "selection_ambiguous"})
        self.assertTrue(result.abstained)

    def test_missing_evidence_digest_cannot_be_candidate(self):
        state = self._state(selection_evidence_digest=None)
        plan = plan_selection_aware_acquisition(state, config=self.config)
        self.assertEqual(plan.status, STATUS_INSUFFICIENT)


if __name__ == "__main__":
    unittest.main()
