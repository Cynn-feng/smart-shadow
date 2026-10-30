import unittest

from aigc.regional_counterfactual import (
    RegionalCounterfactualConfig,
    RegionalObservation,
    fuse_regional_counterfactual,
)
from eval.regional_counterfactual_eval import run_synthetic_evaluation


def observation(
    asset,
    pair,
    region,
    version,
    score,
    family,
    *,
    kind="observed",
    quality=0.9,
    source=0.9,
    detector="detector-v1",
    schema="score-v1",
):
    return RegionalObservation(
        asset_id=asset,
        pair_id=pair,
        region_id=region,
        version_id=version,
        transform_family=family,
        score_raw=score,
        quality_score=quality,
        source_match_score=source,
        kind=kind,
        detector_version=detector,
        score_schema=schema,
        propagation_chain=(family,),
    )


class RegionalCounterfactualTests(unittest.TestCase):
    def paired(self, *, unstable=False):
        values = (0.70, 0.10, 0.70) if unstable else (0.58, 0.60, 0.57)
        observations = []
        for index, delta in enumerate(values):
            family = ("identity", "jpeg_q75", "resize_075")[index]
            observations.extend(
                [
                    observation(
                        "asset",
                        f"pair-{index}",
                        "region-a",
                        f"obs-{index}",
                        0.20 + delta,
                        family,
                    ),
                    observation(
                        "asset",
                        f"pair-{index}",
                        "region-a",
                        f"cf-{index}",
                        0.20,
                        family,
                        kind="counterfactual",
                    ),
                ]
            )
        return observations

    def test_delta_coverage_and_quality_weight_are_audited(self):
        observations = [
            observation("asset", "p1", "r1", "o1", 0.80, "identity", quality=0.9),
            observation(
                "asset", "p1", "r1", "c1", 0.20, "identity", kind="counterfactual", quality=0.9
            ),
            observation("asset", "p2", "r2", "o2", 0.40, "jpeg_q75", quality=0.4),
            observation(
                "asset", "p2", "r2", "c2", 0.20, "jpeg_q75", kind="counterfactual", quality=0.4
            ),
        ]
        result = fuse_regional_counterfactual(observations)
        self.assertTrue(result.has_score)
        self.assertFalse(result.abstained)
        self.assertEqual(result.reason, "stable_regional_counterfactual")
        self.assertEqual(result.coverage_raw, 1.0)
        self.assertEqual(result.paired_region_count, 2)
        # The high-quality pair has more influence than the low-quality pair.
        self.assertGreater(result.weighted_delta_raw, 0.40)
        self.assertAlmostEqual(result.positive_delta_raw, result.weighted_delta_raw)
        self.assertEqual(result.accepted_pair_keys, ("p1::r1", "p2::r2"))
        self.assertTrue(all(item["accepted"] for item in result.pair_audit))

    def test_stable_delta_exposes_signed_and_stability_adjusted_raw_values(self):
        result = fuse_regional_counterfactual(self.paired())
        self.assertTrue(result.has_score)
        self.assertAlmostEqual(result.weighted_delta_raw, 0.5833333333333334, places=6)
        self.assertGreater(result.stability_score, 0.9)
        self.assertGreater(result.stability_adjusted_delta_raw, 0.5)
        self.assertEqual(result.weighted_observed_score_raw - result.weighted_counterfactual_score_raw,
                         result.weighted_delta_raw)

    def test_missing_region_counterfactual_abstains_on_coverage(self):
        observations = self.paired()[:4]
        observations.append(
            observation("asset", "missing", "region-b", "obs-missing", 0.7, "identity")
        )
        result = fuse_regional_counterfactual(observations)
        self.assertFalse(result.has_score)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "coverage_below_threshold")
        self.assertAlmostEqual(result.coverage_raw, 2 / 3)
        self.assertIn("missing::region-b", result.rejected_pair_keys)
        self.assertEqual(
            next(item for item in result.pair_audit if item["pair_key"] == "missing::region-b")["rejection_reason"],
            "missing_counterfactual",
        )

    def test_delta_instability_abstains_even_with_full_coverage(self):
        result = fuse_regional_counterfactual(self.paired(unstable=True))
        self.assertFalse(result.has_score)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "delta_instability")
        self.assertEqual(result.coverage_raw, 1.0)
        self.assertGreater(result.delta_dispersion_raw, 0.15)
        self.assertEqual(result.stability_score, 0.0)

    def test_quality_transform_identity_and_duplicate_boundaries(self):
        low_quality = self.paired()
        low_quality[0] = observation(
            "asset", "pair-0", "region-a", "obs-0", 0.8, "identity", quality=0.2
        )
        result = fuse_regional_counterfactual(low_quality)
        self.assertEqual(result.reason, "coverage_below_threshold")
        self.assertEqual(
            next(item for item in result.pair_audit if item["pair_key"] == "pair-0::region-a")["rejection_reason"],
            "quality_below_threshold",
        )

        mismatch = self.paired()
        mismatch[1] = observation(
            "asset", "pair-0", "region-a", "cf-0", 0.2, "other", kind="counterfactual"
        )
        self.assertEqual(fuse_regional_counterfactual(mismatch).reason, "coverage_below_threshold")

        duplicate = self.paired() + [
            observation("asset", "pair-0", "region-a", "o-duplicate", 0.5, "identity")
        ]
        self.assertEqual(
            fuse_regional_counterfactual(duplicate).reason,
            "duplicate_region_observation",
        )

        wrong_schema = self.paired()
        wrong_schema[1] = observation(
            "asset", "pair-0", "region-a", "cf-0", 0.2, "identity",
            kind="counterfactual", schema="score-v2"
        )
        self.assertEqual(fuse_regional_counterfactual(wrong_schema).reason, "score_schema_conflict")

    def test_constructor_and_config_reject_ambiguous_values(self):
        with self.assertRaises(ValueError):
            observation("asset", "pair", "region", "v", True, "identity")
        with self.assertRaises(ValueError):
            observation("asset", "pair", "region", "v", 0.5, "identity", kind="other")
        with self.assertRaises(ValueError):
            RegionalCounterfactualConfig(minimum_pairs=1)
        with self.assertRaises(ValueError):
            RegionalCounterfactualConfig(quality_power=0.0)

    def test_fixture_runner_is_deterministic_and_explicitly_limited(self):
        first = run_synthetic_evaluation()
        second = run_synthetic_evaluation()
        self.assertEqual(first["dataset_digest"], second["dataset_digest"])
        self.assertEqual(first["config_digest"], second["config_digest"])
        self.assertEqual(first["count"], 5)
        self.assertIn("synthetic regression only", first["interpretation"])
        self.assertEqual(first["summary"]["stable_positive_acceptance_rate"], 0.5)
        self.assertEqual(first["summary"]["negative_abstention_rate"], 2 / 3)


if __name__ == "__main__":
    unittest.main()
