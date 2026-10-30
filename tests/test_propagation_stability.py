import unittest

from aigc.propagation_stability import (
    PropagationObservation,
    StabilityConfig,
    fuse_propagation_stability,
)
from eval.propagation_stability_eval import run_synthetic_evaluation


def observation(asset, version, score, family, *, kind="observed", quality=0.9, source=0.92):
    return PropagationObservation(
        asset_id=asset,
        version_id=version,
        score_raw=score,
        quality_score=quality,
        source_match_score=source,
        transform_family=family,
        detector_version="detector-v1",
        score_schema="score-v1",
        kind=kind,
        propagation_chain=(family,),
    )


class PropagationStabilityTests(unittest.TestCase):
    def paired(self, observed_scores=(0.8, 0.78), counterfactual_scores=(0.1, 0.12)):
        families = ("identity", "jpeg_q75")
        observations = [
            observation("asset", f"o-{i}", score, family)
            for i, (score, family) in enumerate(zip(observed_scores, families))
        ]
        observations.extend(
            observation("asset", f"c-{i}", score, family, kind="counterfactual")
            for i, (score, family) in enumerate(zip(counterfactual_scores, families))
        )
        return observations

    def test_stable_score_is_counterfactual_corrected_and_accepted(self):
        result = fuse_propagation_stability(self.paired())
        self.assertTrue(result.has_score)
        self.assertFalse(result.abstained)
        self.assertEqual(result.reason, "stable_with_counterfactual_baseline")
        self.assertAlmostEqual(result.weighted_score_raw, 0.79)
        self.assertAlmostEqual(result.counterfactual_p95_raw, 0.12)
        self.assertAlmostEqual(result.adjusted_score_raw, 0.67)
        self.assertGreater(result.consistency_score, 0.8)
        self.assertEqual(result.accepted_version_ids, ("o-0", "o-1"))

    def test_score_instability_abstains_even_when_mean_is_high(self):
        result = fuse_propagation_stability(
            self.paired(observed_scores=(0.95, 0.20), counterfactual_scores=(0.08, 0.10))
        )
        self.assertFalse(result.has_score)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "propagation_score_instability")
        self.assertIsNotNone(result.weighted_score_raw)
        self.assertLess(result.consistency_score, 0.0 + 0.01)

    def test_high_counterfactual_blocks_high_observed_score(self):
        result = fuse_propagation_stability(
            self.paired(observed_scores=(0.80, 0.82), counterfactual_scores=(0.55, 0.58))
        )
        self.assertFalse(result.has_score)
        self.assertEqual(result.reason, "counterfactual_high_score")
        self.assertGreater(result.counterfactual_p95_raw, 0.35)

    def test_missing_or_unpaired_counterfactual_abstains(self):
        observed_only = [
            observation("asset", "o-0", 0.8, "identity"),
            observation("asset", "o-1", 0.78, "jpeg_q75"),
        ]
        missing = fuse_propagation_stability(observed_only)
        self.assertTrue(missing.abstained)
        self.assertEqual(missing.reason, "missing_counterfactual_baseline")

        unpaired = fuse_propagation_stability(
            observed_only
            + [observation("asset", "c-0", 0.1, "identity", kind="counterfactual")]
        )
        self.assertEqual(unpaired.reason, "counterfactual_coverage_gap")

        repeated_family = fuse_propagation_stability(
            [
                observation("asset", "o-0", 0.8, "identity"),
                observation("asset", "o-1", 0.78, "identity"),
                observation("asset", "c-0", 0.1, "identity", kind="counterfactual"),
            ]
        )
        self.assertEqual(repeated_family.reason, "counterfactual_coverage_gap")

    def test_quality_and_identity_boundaries_are_audited(self):
        low = self.paired()
        low[0] = observation("asset", "o-0", 0.9, "identity", quality=0.2)
        result = fuse_propagation_stability(low)
        self.assertEqual(result.reason, "insufficient_stable_views")
        self.assertIn("o-0", result.rejected_version_ids)
        self.assertEqual(result.version_audit[0]["rejection_reason"], "quality_below_threshold")

        wrong = self.paired() + [observation("other", "x", 0.2, "identity")]
        self.assertEqual(fuse_propagation_stability(wrong).reason, "asset_identity_conflict")

    def test_fixture_runner_is_deterministic_and_explicitly_limited(self):
        first = run_synthetic_evaluation()
        second = run_synthetic_evaluation()
        self.assertEqual(first["dataset_digest"], second["dataset_digest"])
        self.assertEqual(first["config_digest"], second["config_digest"])
        self.assertEqual(first["count"], 5)
        self.assertEqual(first["summary"]["stable_positive_acceptance_rate"], 1 / 3)
        self.assertEqual(first["summary"]["negative_abstention_rate"], 0.5)
        self.assertIn("synthetic regression only", first["interpretation"])

    def test_config_rejects_ambiguous_values(self):
        with self.assertRaises(ValueError):
            StabilityConfig(minimum_views=1)
        with self.assertRaises(ValueError):
            StabilityConfig(quality_power=0.0)
        with self.assertRaises(ValueError):
            observation("asset", "v", 0.5, "identity", kind="prediction")


if __name__ == "__main__":
    unittest.main()
