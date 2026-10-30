import unittest

from aigc.operator_stability import (
    OperatorStabilityConfig,
    OperatorStabilityObservation,
    ROUTE_INCONCLUSIVE,
    ROUTE_INCONSISTENT,
    ROUTE_INSUFFICIENT,
    ROUTE_STABLE_GROUNDED,
    evaluate_operator_stability,
)


def _row(
    operator_id: str,
    *,
    contrast: float = 0.35,
    swap_contrast: float = 0.30,
    route: str = "grounded_consistent",
    binding: str = "b" * 64,
    mask_out: bool = True,
    region_swap: bool = True,
    valid: bool = True,
    failure_reason=None,
    execution_char=None,
    config_char=None,
) -> OperatorStabilityObservation:
    config_char = config_char or {"blur": "a", "swap": "b"}.get(operator_id, "a")
    execution_char = execution_char or {"blur": "1", "swap": "2"}.get(operator_id, "3")
    return OperatorStabilityObservation(
        operator_id=operator_id,
        operator_config_digest=(config_char * 64),
        operator_execution_digest=(execution_char * 64),
        binding_digest=binding,
        asset_id="asset-1",
        pair_id="pair-1",
        manifest_digest="c" * 64,
        canonical_frame_digest="d" * 64,
        proposal_mask_digest="f" * 64,
        detector_version="detector-v1",
        score_schema="score-v1",
        null_profile_digest="1" * 64,
        quality_score=0.9,
        source_match_raw=0.9,
        null_quality_score=0.9,
        null_source_match_raw=0.9,
        operator_route=route,
        operator_validity=valid,
        mask_out_executed=mask_out,
        region_swap_executed=region_swap,
        observed_effect_raw=0.5 if mask_out else None,
        null_effect_raw=0.05 if mask_out else None,
        contrast_raw=contrast if mask_out else None,
        observed_swap_effect_raw=0.45 if region_swap else None,
        null_swap_effect_raw=0.05 if region_swap else None,
        swap_contrast_raw=swap_contrast if region_swap else None,
        failure_reason=failure_reason,
    )


class OperatorStabilityTests(unittest.TestCase):
    def test_stable_result_preserves_per_operator_effects_without_averaging(self):
        result = evaluate_operator_stability(
            [
                _row("blur", contrast=0.35, swap_contrast=0.30, execution_char="1"),
                _row("swap", contrast=0.40, swap_contrast=0.25, execution_char="2"),
            ]
        )

        self.assertEqual(result.route, ROUTE_STABLE_GROUNDED)
        self.assertFalse(result.abstained)
        self.assertEqual(result.operator_ids, ("blur", "swap"))
        self.assertEqual(result.contrast_effects_raw, (0.35, 0.40))
        self.assertEqual(result.swap_contrast_effects_raw, (0.30, 0.25))
        self.assertNotIn("aggregate_contrast_raw", result.to_dict())
        self.assertAlmostEqual(result.contrast_spread_raw, 0.05)

    def test_support_and_binding_are_fail_closed(self):
        support = evaluate_operator_stability([_row("blur", execution_char="1")])
        self.assertEqual(support.route, ROUTE_INSUFFICIENT)
        self.assertEqual(support.reason, "operator_support_insufficient")

        mismatch = evaluate_operator_stability(
            [_row("blur", execution_char="1"), _row("swap", binding="9" * 64, execution_char="2")]
        )
        self.assertEqual(mismatch.route, ROUTE_INSUFFICIENT)
        self.assertEqual(mismatch.reason, "operator_binding_mismatch")

    def test_operator_route_and_spread_fail_closed(self):
        inconsistent = evaluate_operator_stability(
            [
                _row("blur", execution_char="1"),
                _row("swap", route="maskout_inconsistent", execution_char="2"),
            ]
        )
        self.assertEqual(inconsistent.route, ROUTE_INCONSISTENT)
        self.assertTrue(inconsistent.abstained)

        spread = evaluate_operator_stability(
            [
                _row("blur", contrast=0.10, execution_char="1"),
                _row("swap", contrast=0.60, execution_char="2"),
            ]
        )
        self.assertEqual(spread.route, ROUTE_INCONSISTENT)
        self.assertEqual(spread.reason, "operator_contrast_spread_exceeded")
        self.assertAlmostEqual(spread.contrast_spread_raw, 0.50)

    def test_missing_execution_is_inconclusive(self):
        result = evaluate_operator_stability(
            [
                _row("blur", execution_char="1"),
                _row("swap", region_swap=False, execution_char="2"),
            ]
        )
        self.assertEqual(result.route, ROUTE_INCONCLUSIVE)
        self.assertEqual(result.reason, "operator_intervention_missing")

    def test_invalid_operator_requires_reason(self):
        with self.assertRaises(ValueError):
            _row("blur", valid=False)

        result = evaluate_operator_stability(
            [
                _row("blur", execution_char="1"),
                _row("swap", valid=False, failure_reason="operator_ood", execution_char="2"),
            ]
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "operator_invalid")

    def test_config_and_digest_are_deterministic_and_config_is_versioned(self):
        rows = [_row("blur", execution_char="1"), _row("swap", execution_char="2")]
        config = OperatorStabilityConfig(maximum_contrast_spread_raw=0.25)
        first = evaluate_operator_stability(rows, config=config)
        second = evaluate_operator_stability(list(reversed(rows)), config=config)
        self.assertEqual(first.config_digest, second.config_digest)
        self.assertEqual(first.stability_digest, second.stability_digest)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertNotIn("probability", str(first.to_dict()).lower())


if __name__ == "__main__":
    unittest.main()
