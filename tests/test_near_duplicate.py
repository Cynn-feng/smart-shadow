import math
import unittest

from aigc.near_duplicate import (
    NearDuplicateObservation,
    aggregate_near_duplicates,
    fuse_near_duplicate_scores,
)


class NearDuplicateFusionTests(unittest.TestCase):
    def observations(self):
        return [
            NearDuplicateObservation(
                "asset-1", "v-original", 0.90, 0.90, "det-v1", "score-v1", ("original",)
            ),
            NearDuplicateObservation(
                "asset-1", "v-jpeg", 0.20, 0.80, "det-v1", "score-v1", ("jpeg:q75",)
            ),
            NearDuplicateObservation(
                "asset-1", "v-screenshot", 0.99, 0.10, "det-v1", "score-v1", ("screenshot",)
            ),
        ]

    def test_quality_weighted_score_excludes_low_quality_and_keeps_audit(self):
        result = fuse_near_duplicate_scores(
            self.observations(), minimum_quality=0.35, quality_power=2.0
        )
        expected = (0.90 * 0.90**2 + 0.20 * 0.80**2) / (0.90**2 + 0.80**2)
        self.assertAlmostEqual(result.weighted_score_raw, expected)
        self.assertEqual(result.accepted_version_ids, ("v-original", "v-jpeg"))
        self.assertEqual(result.rejected_version_ids, ("v-screenshot",))
        self.assertAlmostEqual(result.quality_min, 0.80)
        self.assertAlmostEqual(result.effective_quality, (0.90**3 + 0.80**3) / (0.90**2 + 0.80**2))
        self.assertEqual(result.version_audit[2]["rejection_reason"], "quality_below_threshold")
        self.assertEqual(result.version_audit[1]["propagation_chain"], ["jpeg:q75"])
        payload = result.to_dict()
        self.assertEqual(payload["schema"], "quality-aware-near-duplicate-v1")
        self.assertNotIn("human_supported", str(payload))
        self.assertNotIn("ai_generated_supported", str(payload))

    def test_empty_identity_and_version_boundaries_return_no_score(self):
        empty = aggregate_near_duplicates([])
        self.assertFalse(empty.has_score)
        self.assertEqual(empty.reason, "no_versions")

        wrong_asset = fuse_near_duplicate_scores(self.observations(), asset_id="asset-other")
        self.assertFalse(wrong_asset.has_score)
        self.assertEqual(wrong_asset.reason, "asset_identity_conflict")

        mixed_assets = self.observations()
        mixed_assets.append(
            NearDuplicateObservation("asset-2", "v-other", 0.4, 0.9, "det-v1", "score-v1")
        )
        self.assertEqual(fuse_near_duplicate_scores(mixed_assets).reason, "asset_identity_conflict")

        duplicate = self.observations() + [self.observations()[0]]
        duplicate_result = fuse_near_duplicate_scores(duplicate)
        self.assertFalse(duplicate_result.has_score)
        self.assertEqual(duplicate_result.reason, "duplicate_version_id")

        detector_mismatch = self.observations()
        detector_mismatch[1] = NearDuplicateObservation("asset-1", "v-jpeg", 0.2, 0.8, "det-v2", "score-v1")
        self.assertEqual(fuse_near_duplicate_scores(detector_mismatch).reason, "detector_version_conflict")

        schema_mismatch = self.observations()
        schema_mismatch[1] = NearDuplicateObservation("asset-1", "v-jpeg", 0.2, 0.8, "det-v1", "score-v2")
        self.assertEqual(fuse_near_duplicate_scores(schema_mismatch).reason, "score_schema_conflict")

    def test_all_low_quality_and_zero_weight_are_explicit(self):
        low = [NearDuplicateObservation("asset-1", "v1", 0.9, 0.1)]
        result = fuse_near_duplicate_scores(low, minimum_quality=0.35)
        self.assertIsNone(result.raw_score)
        self.assertEqual(result.reason, "all_versions_below_quality_threshold")
        self.assertEqual(result.rejected_version_ids, ("v1",))

        zero = [NearDuplicateObservation("asset-1", "v1", 0.9, 0.0)]
        result = fuse_near_duplicate_scores(zero, minimum_quality=0.0)
        self.assertIsNone(result.raw_score)
        self.assertEqual(result.reason, "zero_quality_weight")

    def test_observation_and_fusion_parameters_reject_ambiguous_values(self):
        with self.assertRaises(ValueError):
            NearDuplicateObservation("asset", "version", math.nan, 0.8)
        with self.assertRaises(ValueError):
            NearDuplicateObservation("asset", "version", 0.8, True)
        with self.assertRaises(ValueError):
            NearDuplicateObservation("asset", "version", 0.8, 0.8, propagation_chain="jpeg")
        with self.assertRaises(ValueError):
            fuse_near_duplicate_scores(self.observations(), minimum_quality=math.nan)
        with self.assertRaises(ValueError):
            fuse_near_duplicate_scores(self.observations(), quality_power=0.0)
        with self.assertRaises(ValueError):
            fuse_near_duplicate_scores(["not-an-observation"])


if __name__ == "__main__":
    unittest.main()
