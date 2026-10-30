import hashlib
import unittest

from aigc.evidence_budget import (
    ACTION_BUILD_COUNTERFACTUAL,
    ACTION_REALIGN_REGION,
    ACTION_VERIFY_PROVENANCE,
    EvidenceAcquisitionState,
)
from aigc.policy_calibration import (
    PolicyCalibrationConfig,
    PolicyNullExample,
    evaluate_policy_fpr,
    fit_policy_null_profile,
)
from aigc.sequential_evidence import (
    ROUTE_CANDIDATE,
    ROUTE_NULL_CONSISTENT,
    ROUTE_REVIEW,
    ROUTE_INSUFFICIENT,
    STATUS_COMPLETE,
    AdaptiveEvidenceState,
    ProbeObservation,
    SequentialPolicyConfig,
    apply_probe_observation,
    result_from_state,
    run_sequential_evidence,
    start_sequential_evidence,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SequentialEvidenceTests(unittest.TestCase):
    def _base(self, **overrides):
        values = {
            "asset_id": "asset-1",
            "detector_version": "source-residual-v1",
            "score_schema": "source-residual-score-v1",
            "quality_score": 0.9,
            "source_match_score": 0.9,
            "regional_coverage_raw": 0.95,
            "null_evaluated": False,
            "provenance_verified": False,
        }
        values.update(overrides)
        return EvidenceAcquisitionState(**values)

    def _policy(self, **overrides):
        values = {"max_actions": 2, "max_cost_units": 3}
        values.update(overrides)
        return SequentialPolicyConfig(**values)

    def _observation(self, state, *, route=None, calibration_digest=None, step=None, **overrides):
        action = state.next_action
        self.assertIsNotNone(action)
        values = {
            "action_id": action.action_id,
            "step": state.step + 1 if step is None else step,
            "target": action.target,
            "input_digest": _digest(f"input-{state.step + 1}"),
            "output_digest": _digest(f"output-{state.step + 1}"),
            "route": route,
            "calibration_digest": calibration_digest,
        }
        values.update(overrides)
        return ProbeObservation(**values)

    def test_policy_digest_and_action_order_are_replayable(self):
        policy = self._policy()
        first = start_sequential_evidence(self._base(), policy=policy)
        second = start_sequential_evidence(self._base(), policy=policy)
        self.assertEqual(first.policy_digest, second.policy_digest)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.remaining_actions, ("verify_provenance", "build_counterfactual"))

    def test_precompleted_actions_are_audited_but_never_queued_again(self):
        state = start_sequential_evidence(
            self._base(completed_actions=(ACTION_VERIFY_PROVENANCE,)),
            policy=self._policy(),
        )
        self.assertNotIn(ACTION_VERIFY_PROVENANCE, state.remaining_actions)
        self.assertIn(ACTION_VERIFY_PROVENANCE, state.completed_actions)
        self.assertEqual(state.remaining_actions, (ACTION_BUILD_COUNTERFACTUAL,))

    def test_custom_policy_order_is_recorded_and_used_for_pending_actions(self):
        policy = SequentialPolicyConfig(
            max_actions=3,
            max_cost_units=5,
            action_order=(ACTION_REALIGN_REGION, ACTION_VERIFY_PROVENANCE, ACTION_BUILD_COUNTERFACTUAL),
            action_costs=(
                (ACTION_REALIGN_REGION, 2),
                (ACTION_VERIFY_PROVENANCE, 1),
                (ACTION_BUILD_COUNTERFACTUAL, 2),
            ),
        )
        state = start_sequential_evidence(self._base(shape_ambiguous=True), policy=policy)
        self.assertEqual(state.remaining_actions, (ACTION_REALIGN_REGION, ACTION_VERIFY_PROVENANCE, ACTION_BUILD_COUNTERFACTUAL))

    def test_quality_and_source_mismatch_fail_closed_without_actions(self):
        quality = start_sequential_evidence(self._base(quality_score=0.1), policy=self._policy())
        source = start_sequential_evidence(self._base(source_match_score=0.1), policy=self._policy())
        self.assertEqual(result_from_state(quality).route, ROUTE_INSUFFICIENT)
        self.assertEqual(result_from_state(quality).reason, "quality_gate")
        self.assertEqual(result_from_state(source).reason, "source_match_gate")
        self.assertEqual(quality.status, STATUS_COMPLETE)
        self.assertEqual(quality.remaining_actions, ())

    def test_no_policy_gap_is_explicitly_insufficient(self):
        state = start_sequential_evidence(
            self._base(
                provenance_verified=True,
                null_evaluated=True,
                regional_coverage_raw=0.95,
                uncertainty_raw=0.1,
            ),
            policy=self._policy(),
        )
        self.assertEqual(state.route, ROUTE_INSUFFICIENT)
        self.assertEqual(state.reason, "no_policy_gap")
        self.assertIsNone(state.next_action)

    def test_successful_probe_without_output_digest_fails_closed(self):
        state = start_sequential_evidence(self._base(), policy=self._policy())
        observation = self._observation(state, route=None, output_digest=None)
        updated = apply_probe_observation(state, observation)
        self.assertEqual(updated.route, ROUTE_INSUFFICIENT)
        self.assertEqual(updated.reason, "output_digest_missing")
        self.assertTrue(updated.status == STATUS_COMPLETE)

    def test_candidate_requires_calibration_digest(self):
        state = start_sequential_evidence(self._base(), policy=self._policy(max_actions=1, max_cost_units=1))
        updated = apply_probe_observation(state, self._observation(state, route=ROUTE_CANDIDATE))
        self.assertEqual(updated.route, ROUTE_INSUFFICIENT)
        self.assertEqual(updated.reason, "calibration_unavailable")

    def test_null_route_continues_until_policy_budget_is_exhausted(self):
        calibration = _digest("calibration")
        state = start_sequential_evidence(self._base(), policy=self._policy())
        state = apply_probe_observation(state, self._observation(state, route=ROUTE_NULL_CONSISTENT, calibration_digest=calibration))
        self.assertEqual(state.status, "continue")
        state = apply_probe_observation(state, self._observation(state, route=ROUTE_NULL_CONSISTENT, calibration_digest=calibration))
        self.assertEqual(state.status, STATUS_COMPLETE)
        self.assertEqual(state.route, ROUTE_NULL_CONSISTENT)
        self.assertEqual(state.reason, "ordinary_propagation_consistent")

    def test_repeated_or_out_of_order_probe_fails_closed(self):
        state = start_sequential_evidence(self._base(), policy=self._policy())
        first = self._observation(state, route=None)
        state = apply_probe_observation(state, first)
        repeated = ProbeObservation(
            action_id=first.action_id,
            step=2,
            target=first.target,
            input_digest=_digest("repeat-input"),
            output_digest=_digest("repeat-output"),
        )
        updated = apply_probe_observation(state, repeated)
        self.assertEqual(updated.route, ROUTE_INSUFFICIENT)
        self.assertEqual(updated.reason, "action_out_of_order")

    def test_probe_failure_routes_to_review(self):
        state = start_sequential_evidence(self._base(), policy=self._policy())
        failed = self._observation(state, route=None, ok=False, output_digest=None, failure_reason="decoder_error")
        updated = apply_probe_observation(state, failed)
        self.assertEqual(updated.route, ROUTE_REVIEW)
        self.assertEqual(updated.reason, "probe_failed")
        self.assertTrue(result_from_state(updated).abstained)

    def test_calibration_digest_mismatch_and_route_flip_abstain(self):
        calibration = _digest("calibration")
        state = start_sequential_evidence(self._base(), policy=self._policy())
        state = apply_probe_observation(state, self._observation(state, route=ROUTE_NULL_CONSISTENT, calibration_digest=calibration))
        mismatch = apply_probe_observation(
            state,
            self._observation(state, route=ROUTE_NULL_CONSISTENT, calibration_digest=_digest("other")),
        )
        self.assertEqual(mismatch.route, ROUTE_INSUFFICIENT)
        self.assertEqual(mismatch.reason, "calibration_profile_mismatch")

        state = start_sequential_evidence(self._base(), policy=self._policy())
        state = apply_probe_observation(state, self._observation(state, route=ROUTE_NULL_CONSISTENT, calibration_digest=calibration))
        flipped = apply_probe_observation(state, self._observation(state, route=ROUTE_CANDIDATE, calibration_digest=calibration))
        self.assertEqual(flipped.route, ROUTE_REVIEW)
        self.assertEqual(flipped.reason, "route_flip")

    def test_replay_digest_is_stable_and_extra_trace_is_not_ignored(self):
        calibration = _digest("calibration")
        policy = self._policy()
        initial = start_sequential_evidence(self._base(), policy=policy)
        first = self._observation(initial, route=None)
        after_first = apply_probe_observation(initial, first)
        second = self._observation(after_first, route=ROUTE_CANDIDATE, calibration_digest=calibration)
        one = run_sequential_evidence(self._base(), (first, second), policy=policy)
        two = run_sequential_evidence(self._base(), (first, second), policy=policy)
        self.assertEqual(one.evidence_digest, two.evidence_digest)
        self.assertEqual(one.policy_digest, two.policy_digest)
        self.assertEqual(one.route, ROUTE_CANDIDATE)
        extra = self._observation(after_first, route=ROUTE_CANDIDATE, calibration_digest=calibration)
        three = run_sequential_evidence(self._base(), (first, second, extra), policy=policy)
        self.assertEqual(three.route, ROUTE_INSUFFICIENT)
        self.assertEqual(three.reason, "trace_after_terminal")

    def test_policy_null_profile_reports_empirical_fpr_and_wilson_ci(self):
        policy_digest = _digest("policy")
        examples = [
            PolicyNullExample(f"g-{index}", ROUTE_CANDIDATE if index == 0 else ROUTE_NULL_CONSISTENT, False, policy_digest)
            for index in range(4)
        ]
        profile = fit_policy_null_profile(examples, policy_digest=policy_digest)
        result = evaluate_policy_fpr(profile, config=PolicyCalibrationConfig(minimum_null_count=4))
        self.assertTrue(result.evaluated)
        self.assertEqual(result.false_positive_count, 1)
        self.assertAlmostEqual(result.empirical_fpr, 0.25)
        self.assertLessEqual(result.ci_low, result.empirical_fpr)
        self.assertGreaterEqual(result.ci_high, result.empirical_fpr)
        self.assertNotIn("probability", result.to_dict())

    def test_policy_null_profile_fails_closed_on_small_support_or_mismatch(self):
        policy_digest = _digest("policy")
        profile = fit_policy_null_profile(
            [PolicyNullExample("g-1", ROUTE_NULL_CONSISTENT, False, policy_digest)],
            policy_digest=policy_digest,
        )
        result = evaluate_policy_fpr(profile, config=PolicyCalibrationConfig(minimum_null_count=2))
        self.assertFalse(result.evaluated)
        self.assertEqual(result.reason, "insufficient_policy_null_support")
        mismatch = evaluate_policy_fpr(profile, policy_digest=_digest("other"))
        self.assertFalse(mismatch.evaluated)
        self.assertEqual(mismatch.reason, "policy_digest_mismatch")

    def test_raw_evidence_cannot_smuggle_probability_field(self):
        with self.assertRaises(ValueError):
            ProbeObservation(
                action_id="verify_provenance",
                step=1,
                target="asset",
                input_digest=_digest("input"),
                output_digest=_digest("output"),
                raw_evidence={"score_raw": 0.3, "aigc_probability": 0.99},
            )


if __name__ == "__main__":
    unittest.main()
