"""Contract tests for the counterfactual intervention validity gate.

These tests exercise the fail-closed routing contract only.  They use scalar
digests and scores; no image, detector, AIGC probability, or legal conclusion
is involved.
"""

from __future__ import annotations

import math
import unittest

from aigc.counterfactual_validity import (
    CONTENT_EDIT,
    DECOY,
    ORDINARY_PROPAGATION,
    WRONG_REFERENCE,
    CIVGConfig,
    CIVGObservation,
    ROUTE_INSUFFICIENT,
    ROUTE_INVALID,
    ROUTE_SPILLOVER,
    ROUTE_VALID,
    evaluate_civg,
)


HEX = "a" * 64


def _observation(**overrides) -> CIVGObservation:
    """Build a fully supported, valid content-edit observation."""

    values = {
        "asset_id": "asset-1",
        "pair_id": "pair-1",
        "intervention_scope": CONTENT_EDIT,
        "reference_digest": "b" * 64,
        "observed_digest": "c" * 64,
        "counterfactual_digest": "d" * 64,
        "canonical_frame": "frame-v1",
        "detector_version": "detector-v1",
        "score_schema": "civg-score-v1",
        "authorized": True,
        "executed": True,
        "pair_binding_digest": "e" * 64,
        "ordinary_null_digest": "f" * 64,
        "target_mask_digest": "1" * 64,
        "operator_digest": "2" * 64,
        "execution_digest": "3" * 64,
        "quality_score": 0.95,
        "source_match_score": 0.90,
        "target_effect_raw": 0.80,
        "non_target_preservation_raw": 0.95,
        "mask_leakage_raw": 0.05,
        "semantic_consistency_raw": 0.90,
        "causal_consistency_raw": 0.88,
        "minimum_intervention_raw": 0.92,
    }
    values.update(overrides)
    return CIVGObservation(**values)


class CounterfactualValidityTests(unittest.TestCase):
    def test_valid_intervention_passes_all_raw_gates(self):
        result = evaluate_civg(_observation())

        self.assertEqual(result.route, ROUTE_VALID)
        self.assertFalse(result.abstained)
        self.assertTrue(result.downstream_eligible)
        self.assertEqual(result.reason, "validity_gate_passed")
        self.assertEqual(result.failure_reasons, ())

    def test_spillover_route_captures_non_target_and_mask_leakage_failures(self):
        result = evaluate_civg(
            _observation(non_target_preservation_raw=0.50, mask_leakage_raw=0.80)
        )

        self.assertEqual(result.route, ROUTE_SPILLOVER)
        self.assertTrue(result.abstained)
        self.assertFalse(result.downstream_eligible)
        self.assertEqual(
            result.failure_reasons,
            ("non_target_preservation_below_threshold", "mask_leakage_above_threshold"),
        )

    def test_target_semantic_causal_and_minimum_failures_are_invalid(self):
        failures = (
            ("target_effect_raw", "target_effect_below_threshold"),
            ("semantic_consistency_raw", "semantic_consistency_below_threshold"),
            ("causal_consistency_raw", "causal_consistency_below_threshold"),
            ("minimum_intervention_raw", "minimum_intervention_below_threshold"),
        )
        for field, reason in failures:
            with self.subTest(field=field):
                result = evaluate_civg(_observation(**{field: 0.0}))
                self.assertEqual(result.route, ROUTE_INVALID)
                self.assertTrue(result.abstained)
                self.assertFalse(result.downstream_eligible)
                self.assertEqual(result.reason, reason)
                self.assertIn(reason, result.failure_reasons)

    def test_missing_causal_signal_is_insufficient(self):
        result = evaluate_civg(_observation(causal_consistency_raw=None))

        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "validity_signal_missing")
        self.assertEqual(result.failure_reasons, ("missing_causal_consistency_raw",))

    def test_non_content_scopes_never_become_valid_interventions(self):
        for scope in (ORDINARY_PROPAGATION, DECOY, WRONG_REFERENCE):
            with self.subTest(scope=scope):
                result = evaluate_civg(_observation(intervention_scope=scope))
                self.assertEqual(result.route, ROUTE_INVALID)
                self.assertEqual(result.reason, "scope_not_content_edit")
                self.assertTrue(result.abstained)
                self.assertFalse(result.downstream_eligible)

    def test_unauthorized_and_unexecuted_inputs_fail_closed(self):
        unauthorized = evaluate_civg(_observation(authorized=False))
        self.assertEqual(unauthorized.route, ROUTE_INSUFFICIENT)
        self.assertEqual(unauthorized.reason, "unauthorized_input")
        self.assertEqual(unauthorized.failure_reasons, ("unauthorized_input",))

        unexecuted = evaluate_civg(_observation(executed=False))
        self.assertEqual(unexecuted.route, ROUTE_INSUFFICIENT)
        self.assertEqual(unexecuted.reason, "execution_missing")
        self.assertEqual(unexecuted.failure_reasons, ("execution_missing",))

    def test_missing_binding_is_insufficient_and_reports_each_field(self):
        result = evaluate_civg(
            _observation(pair_binding_digest=None, target_mask_digest=None)
        )

        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "binding_incomplete")
        self.assertEqual(
            result.failure_reasons,
            ("missing_pair_binding_digest", "missing_target_mask_digest"),
        )

    def test_primary_pair_digests_are_required_at_observation_boundary(self):
        for field in ("reference_digest", "observed_digest", "counterfactual_digest"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "must be a SHA-256 hex digest"):
                    _observation(**{field: None})

    def test_identical_observed_and_counterfactual_is_invalid(self):
        result = evaluate_civg(
            _observation(counterfactual_digest="c" * 64)
        )

        self.assertEqual(result.route, ROUTE_INVALID)
        self.assertEqual(result.reason, "observed_counterfactual_identical")
        self.assertEqual(result.failure_reasons, ("observed_counterfactual_identical",))

    def test_quality_and_source_match_gates_are_insufficient(self):
        low_quality = evaluate_civg(_observation(quality_score=0.1))
        self.assertEqual(low_quality.route, ROUTE_INSUFFICIENT)
        self.assertEqual(low_quality.reason, "quality_below_threshold")

        low_source_match = evaluate_civg(_observation(source_match_score=0.1))
        self.assertEqual(low_source_match.route, ROUTE_INSUFFICIENT)
        self.assertEqual(low_source_match.reason, "source_match_below_threshold")

    def test_non_finite_scores_are_rejected_at_observation_boundary(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "between 0 and 1"):
                    _observation(target_effect_raw=value)

    def test_config_rejects_non_finite_and_out_of_unit_thresholds(self):
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            CIVGConfig(minimum_quality=math.nan)
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            CIVGConfig(maximum_mask_leakage=1.1)

    def test_digests_and_serialization_are_deterministic(self):
        observation = _observation()
        first = evaluate_civg(observation)
        second = evaluate_civg(observation)

        self.assertEqual(first.config_digest, second.config_digest)
        self.assertEqual(first.evidence_digest, second.evidence_digest)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.to_dict()["failure_reasons"], [])

    def test_raw_result_has_no_forbidden_claim_fields(self):
        payload = str(evaluate_civg(_observation()).to_dict()).lower()
        for forbidden in (
            "probability",
            "aigc_probability",
            "human_supported",
            "ai_generated_supported",
            "copyright",
            "legal_finding",
            "author_identity",
        ):
            self.assertNotIn(forbidden, payload)

    def test_result_rejects_invalid_route_invariants(self):
        result = evaluate_civg(_observation())
        with self.assertRaises(ValueError):
            type(result)(
                route=ROUTE_VALID,
                abstained=True,
                downstream_eligible=False,
                reason=result.reason,
                asset_id=result.asset_id,
                pair_id=result.pair_id,
                intervention_scope=result.intervention_scope,
                failure_reasons=(),
                target_effect_raw=result.target_effect_raw,
                non_target_preservation_raw=result.non_target_preservation_raw,
                mask_leakage_raw=result.mask_leakage_raw,
                semantic_consistency_raw=result.semantic_consistency_raw,
                causal_consistency_raw=result.causal_consistency_raw,
                minimum_intervention_raw=result.minimum_intervention_raw,
                quality_score=result.quality_score,
                source_match_score=result.source_match_score,
                config_digest=result.config_digest,
                evidence_digest=result.evidence_digest,
            )


if __name__ == "__main__":
    unittest.main()
