import unittest

from aigc.evidence_grounded_explanation import (
    ExplanationAuditConfig,
    ExplanationAuditObservation,
    OPERATION_SCOPE_CONTENT,
    OPERATION_SCOPE_PROPAGATION,
    ROUTE_GROUNDED_CONSISTENT,
    ROUTE_INCONCLUSIVE,
    ROUTE_INSUFFICIENT,
    ROUTE_MASKOUT_INCONSISTENT,
    evaluate_explanation_audit,
)


HEX = "a" * 64


def _observation(*, before=0.80, after=0.40, null_before=0.50,
                 null_after=0.45, swap_after=0.30,
                 null_swap_after=0.48,
                 operation_scope=OPERATION_SCOPE_CONTENT,
                 quality=0.90, source_match=0.90,
                 null_quality=0.90, null_source_match=0.90,
                 mask_out=True, null_mask_out=True,
                 region_swap=True, null_region_swap=True,
                 artifact_category="boundary", evidence_region_ids=("region-1",),
                 operator_digest="d" * 64,
                 null_operator_digest="d" * 64,
                 metadata=None, score_direction="higher_is_more_suspicious"):
    """Build a complete source-conditioned matched-intervention fixture."""
    return ExplanationAuditObservation(
        asset_id="asset-1",
        pair_id="pair-observed",
        transform_family="identity",
        transform_spec_digest="0" * 64,
        reference_digest="1" * 64,
        observed_digest="2" * 64,
        null_digest="3" * 64,
        manifest_digest=HEX,
        canonical_frame_digest="b" * 64,
        detector_version="source-residual-v1",
        score_schema="source-residual-score-v1",
        operation_scope=operation_scope,
        evidence_region_ids=evidence_region_ids,
        taxonomy_version="artifact-taxonomy-v1",
        artifact_category=artifact_category,
        proposal_mask_digest="c" * 64,
        intervention_operator_digest=operator_digest,
        null_intervention_operator_digest=null_operator_digest,
        evidence_digest="e" * 64,
        crop_policy_digest="f" * 64,
        control_pair_id="pair-null",
        null_profile_digest="1" * 64,
        intervention_execution_digest="4" * 64,
        quality_score=quality,
        source_match_raw=source_match,
        null_quality_score=null_quality,
        null_source_match_raw=null_source_match,
        score_before_raw=before,
        score_after_maskout_raw=after,
        score_after_region_swap_raw=swap_after if region_swap else None,
        null_score_before_raw=null_before,
        null_score_after_maskout_raw=null_after,
        null_score_after_region_swap_raw=null_swap_after if null_region_swap else None,
        observed_mask_out_executed=mask_out,
        null_mask_out_executed=null_mask_out,
        observed_region_swap_executed=region_swap,
        null_region_swap_executed=null_region_swap,
        human_review_ref="2" * 64,
        metadata=metadata,
        score_direction=score_direction,
    )


class EvidenceGroundedExplanationTests(unittest.TestCase):
    def test_matched_intervention_contrast_can_be_grounded(self):
        result = evaluate_explanation_audit(_observation())

        self.assertEqual(result.route, ROUTE_GROUNDED_CONSISTENT)
        self.assertFalse(result.abstained)
        self.assertAlmostEqual(result.faithfulness_delta_raw, 0.40)
        self.assertAlmostEqual(result.null_effect_raw, 0.05)
        self.assertAlmostEqual(result.contrast_faithfulness_raw, 0.35)
        self.assertAlmostEqual(result.region_swap_delta_raw, 0.50)
        self.assertAlmostEqual(result.null_region_swap_delta_raw, 0.02)
        self.assertAlmostEqual(result.swap_contrast_raw, 0.48)

    def test_null_effect_can_remove_a_false_maskout_claim(self):
        result = evaluate_explanation_audit(
            _observation(null_after=0.15),
            config=ExplanationAuditConfig(minimum_matched_contrast_raw=0.35),
        )

        self.assertEqual(result.route, ROUTE_MASKOUT_INCONSISTENT)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "matched_contrast_below_threshold")
        self.assertAlmostEqual(result.null_effect_raw, 0.35)

    def test_maskout_failure_is_distinct_from_missing_swap(self):
        result = evaluate_explanation_audit(_observation(after=0.76))
        self.assertEqual(result.route, ROUTE_MASKOUT_INCONSISTENT)
        self.assertEqual(result.reason, "maskout_drop_below_threshold")

        missing_swap = evaluate_explanation_audit(
            _observation(region_swap=False, null_region_swap=False)
        )
        self.assertEqual(missing_swap.route, ROUTE_INCONCLUSIVE)
        self.assertEqual(missing_swap.reason, "matched_region_swap_missing")

    def test_swap_contrast_is_required_after_both_swaps_pass(self):
        result = evaluate_explanation_audit(
            _observation(swap_after=0.60, null_swap_after=0.32)
        )
        self.assertEqual(result.route, ROUTE_INCONCLUSIVE)
        self.assertEqual(result.reason, "matched_swap_contrast_below_threshold")
        self.assertAlmostEqual(result.region_swap_delta_raw, 0.20)
        self.assertAlmostEqual(result.null_region_swap_delta_raw, 0.18)
        self.assertAlmostEqual(result.swap_contrast_raw, 0.02)

    def test_ordinary_propagation_is_fail_closed(self):
        result = evaluate_explanation_audit(
            _observation(operation_scope=OPERATION_SCOPE_PROPAGATION)
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "ordinary_propagation_or_mixed_scope")

    def test_quality_and_source_gates_fail_closed_for_observed_and_null(self):
        low_quality = evaluate_explanation_audit(_observation(quality=0.20))
        self.assertEqual(low_quality.route, ROUTE_INSUFFICIENT)
        self.assertEqual(low_quality.reason, "quality_below_threshold")

        low_source = evaluate_explanation_audit(_observation(source_match=0.20))
        self.assertEqual(low_source.route, ROUTE_INSUFFICIENT)
        self.assertEqual(low_source.reason, "source_match_below_threshold")

        low_null_quality = evaluate_explanation_audit(
            _observation(null_quality=0.20)
        )
        self.assertEqual(low_null_quality.route, ROUTE_INSUFFICIENT)
        self.assertEqual(low_null_quality.reason, "null_quality_below_threshold")

        low_null_source = evaluate_explanation_audit(
            _observation(null_source_match=0.20)
        )
        self.assertEqual(low_null_source.route, ROUTE_INSUFFICIENT)
        self.assertEqual(low_null_source.reason, "null_source_match_below_threshold")

    def test_missing_execution_evidence_fails_closed_for_each_side(self):
        observed_missing = evaluate_explanation_audit(_observation(mask_out=False))
        self.assertEqual(observed_missing.route, ROUTE_INSUFFICIENT)
        self.assertEqual(observed_missing.reason, "matched_mask_out_not_executed")

        null_missing = evaluate_explanation_audit(_observation(null_mask_out=False))
        self.assertEqual(null_missing.route, ROUTE_INSUFFICIENT)
        self.assertEqual(null_missing.reason, "matched_mask_out_not_executed")

    def test_null_effect_instability_fails_closed(self):
        result = evaluate_explanation_audit(
            _observation(null_before=0.50, null_after=-0.10)
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "null_effect_unstable")
        self.assertAlmostEqual(result.null_effect_raw, 0.60)

    def test_null_region_swap_instability_fails_closed(self):
        result = evaluate_explanation_audit(
            _observation(null_swap_after=-0.10)
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "null_region_swap_unstable")
        self.assertAlmostEqual(result.null_region_swap_delta_raw, 0.60)

    def test_operator_mismatch_fails_closed(self):
        result = evaluate_explanation_audit(
            _observation(null_operator_digest="9" * 64)
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "intervention_operator_mismatch")

    def test_unknown_artifact_category_is_inconclusive(self):
        result = evaluate_explanation_audit(
            _observation(artifact_category="unknown")
        )
        self.assertEqual(result.route, ROUTE_INCONCLUSIVE)
        self.assertEqual(result.reason, "unknown_artifact_category")

    def test_effect_range_is_not_silently_clipped(self):
        result = evaluate_explanation_audit(
            _observation(
                before=0.90,
                after=-0.80,
                null_before=0.40,
                null_after=0.00,
                swap_after=-0.70,
                null_swap_after=0.00,
            )
        )
        self.assertEqual(result.route, ROUTE_GROUNDED_CONSISTENT)
        self.assertAlmostEqual(result.faithfulness_delta_raw, 1.70)
        self.assertAlmostEqual(result.contrast_faithfulness_raw, 1.30)
        self.assertAlmostEqual(result.swap_contrast_raw, 1.20)

    def test_binding_metadata_and_digests_are_replayable(self):
        observation = _observation(metadata={"note": "raw evidence"})
        first = evaluate_explanation_audit(observation)
        second = evaluate_explanation_audit(_observation(metadata={"note": "raw evidence"}))
        self.assertEqual(first.binding_digest, second.binding_digest)
        self.assertEqual(first.config_digest, second.config_digest)
        self.assertEqual(first.explanation_digest, second.explanation_digest)
        self.assertEqual(observation.to_dict()["null_score_before_raw"], 0.50)
        changed = evaluate_explanation_audit(_observation(null_after=0.44))
        self.assertNotEqual(first.explanation_digest, changed.explanation_digest)
        self.assertNotIn("confidence", first.to_dict())
        self.assertNotIn("probability", first.to_dict())
        self.assertNotIn("aigc_status", first.to_dict())

        with self.assertRaises(ValueError):
            _observation(metadata={"aigc_probability": 0.8})
        with self.assertRaises(ValueError):
            _observation(metadata={"confidence": 0.8})
        with self.assertRaises(ValueError):
            _observation(metadata={"aigc_status": "human_supported"})

    def test_duplicate_regions_and_invalid_category_are_rejected(self):
        with self.assertRaises(ValueError):
            _observation(evidence_region_ids=("region-1", "region-1"))
        with self.assertRaises(ValueError):
            evaluate_explanation_audit(
                _observation(artifact_category="not a taxonomy id")
            )

    def test_score_direction_is_explicit(self):
        with self.assertRaises(ValueError):
            _observation(score_direction="lower_is_more_suspicious")


if __name__ == "__main__":
    unittest.main()
