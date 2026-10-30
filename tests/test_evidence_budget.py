import unittest

from aigc.evidence_budget import (
    ACTION_BUILD_COUNTERFACTUAL,
    ACTION_REALIGN_REGION,
    ACTION_VERIFY_PROVENANCE,
    EvidenceAcquisitionConfig,
    EvidenceAcquisitionState,
    PLAN_ACQUIRE,
    PLAN_INSUFFICIENT,
    PLAN_NO_ACTION,
    PLAN_REVIEW,
    plan_evidence_acquisition,
)


class EvidenceBudgetTests(unittest.TestCase):
    def _state(self, **overrides):
        values = {
            "asset_id": "asset-1",
            "detector_version": "source-residual-v1",
            "score_schema": "source-residual-score-v1",
            "quality_score": 0.9,
            "source_match_score": 0.9,
        }
        values.update(overrides)
        return EvidenceAcquisitionState(**values)

    def test_plan_is_bounded_and_prioritized(self):
        plan = plan_evidence_acquisition(
            self._state(null_evaluated=False, shape_ambiguous=True),
            config=EvidenceAcquisitionConfig(max_actions=2, max_cost_units=3),
        )
        self.assertEqual(plan.status, PLAN_ACQUIRE)
        self.assertEqual(
            [action.action for action in plan.actions],
            [ACTION_VERIFY_PROVENANCE, ACTION_BUILD_COUNTERFACTUAL],
        )
        self.assertEqual(plan.spent_cost_units, 3)
        self.assertEqual(plan.remaining_cost_units, 0)
        self.assertEqual(len(plan.plan_digest), 64)

    def test_low_quality_stops_before_spending_budget(self):
        plan = plan_evidence_acquisition(self._state(quality_score=0.2))
        self.assertEqual(plan.status, PLAN_INSUFFICIENT)
        self.assertEqual(plan.reason, "quality_gate")
        self.assertEqual(plan.actions, ())
        self.assertEqual(plan.spent_cost_units, 0)

    def test_source_mismatch_is_not_repaired_by_repeated_detector_calls(self):
        plan = plan_evidence_acquisition(self._state(source_match_score=0.2))
        self.assertEqual(plan.status, PLAN_INSUFFICIENT)
        self.assertEqual(plan.reason, "source_match_gate")

    def test_completed_actions_are_not_scheduled_again(self):
        plan = plan_evidence_acquisition(
            self._state(
                provenance_verified=True,
                null_evaluated=True,
                completed_actions=(ACTION_REALIGN_REGION,),
                shape_ambiguous=True,
                regional_coverage_raw=0.4,
            )
        )
        self.assertEqual(plan.status, PLAN_ACQUIRE)
        names = [action.action for action in plan.actions]
        self.assertNotIn(ACTION_REALIGN_REGION, names)
        self.assertEqual(names, ["zoom_region"])

    def test_budget_shortfall_is_explicit(self):
        plan = plan_evidence_acquisition(
            self._state(null_evaluated=False),
            config=EvidenceAcquisitionConfig(max_actions=1, max_cost_units=1),
        )
        self.assertEqual(plan.status, PLAN_ACQUIRE)
        self.assertEqual([action.action for action in plan.actions], [ACTION_VERIFY_PROVENANCE])

        blocked = plan_evidence_acquisition(
            self._state(null_evaluated=False, provenance_verified=True),
            config=EvidenceAcquisitionConfig(max_actions=1, max_cost_units=1),
        )
        self.assertEqual(blocked.status, PLAN_REVIEW)
        self.assertEqual(blocked.reason, "budget_cannot_cover_next_observation")

    def test_complete_state_has_no_action_and_is_not_aigc_label(self):
        plan = plan_evidence_acquisition(
            self._state(
                provenance_verified=True,
                null_evaluated=True,
                regional_coverage_raw=0.95,
                uncertainty_raw=0.1,
            )
        )
        self.assertEqual(plan.status, PLAN_NO_ACTION)
        self.assertEqual(plan.reason, "no_policy_gap")
        self.assertNotIn("human_supported", plan.to_dict())
        self.assertNotIn("ai_generated_supported", plan.to_dict())


if __name__ == "__main__":
    unittest.main()
