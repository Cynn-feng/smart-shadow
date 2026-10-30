import math
import unittest

from aigc.paired_delta_calibration import (
    PairedDeltaCalibrationConfig,
    PairedDeltaGroup,
    evaluate_paired_delta,
    fit_paired_delta_profile,
    quality_bucket,
)


def group(
    group_id,
    family="identity",
    quality=0.9,
    deltas=(0.01, 0.02),
    detector="detector-v1",
    schema="delta-v1",
):
    return PairedDeltaGroup(
        group_id=group_id,
        transform_family=family,
        quality_score=quality,
        region_deltas=tuple(deltas),
        detector_version=detector,
        score_schema=schema,
        region_ids=tuple(f"r{index}" for index in range(len(deltas))),
    )


class PairedDeltaCalibrationTests(unittest.TestCase):
    def profile(self, *, minimum=3, alpha=0.10, groups=None, **kwargs):
        if groups is None:
            groups = [
                group(f"id-{index}", deltas=(0.01 + 0.005 * index, -0.02))
                for index in range(10)
            ]
        config = PairedDeltaCalibrationConfig(
            minimum_stratum_count=minimum,
            alpha=alpha,
            **kwargs,
        )
        return fit_paired_delta_profile(groups, config=config)

    def test_statistic_is_maximum_positive_delta_and_bucket_is_stable(self):
        item = group("g", quality=0.35, deltas=(-0.8, -0.1, 0.23, 0.02))
        self.assertAlmostEqual(item.statistic_raw, 0.23)
        self.assertEqual(quality_bucket(0.35), "q1")
        self.assertEqual(quality_bucket(0.80), "q3")
        self.assertEqual(item.to_dict()["statistic_raw"], 0.23)

    def test_profile_digest_and_strata_are_reproducible(self):
        first = self.profile()
        second = self.profile()
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(len(first.dataset_digest), 64)
        self.assertEqual(len(first.profile_digest), 64)
        self.assertEqual(first.strata[0].count, 10)
        self.assertEqual(first.config_digest, second.config_digest)

    def test_exact_stratum_uses_tie_safe_conformal_p_value(self):
        profile = self.profile()
        rejected = profile.evaluate(group("query-high", deltas=(0.9, -0.2)))
        self.assertTrue(rejected.evaluated)
        self.assertTrue(rejected.unknown)
        self.assertEqual(rejected.unknown_reason, "paired_delta_conformal_reject")
        self.assertEqual(rejected.fallback, "none")
        self.assertAlmostEqual(rejected.raw_p_value, 1.0 / 11.0)
        tied = profile.evaluate(group("query-tie", deltas=(0.055,)))
        # 0.055 is above the largest null statistic (0.055 is a tie only if
        # represented exactly); p remains finite and ties are included.
        self.assertGreater(tied.raw_p_value, 0.0)
        self.assertEqual(tied.detector_version, "detector-v1")
        self.assertEqual(tied.score_schema, "delta-v1")
        self.assertEqual(tied.dataset_digest, profile.dataset_digest)

    def test_family_and_global_fallback_are_explicit(self):
        groups = [
            group("identity-high-0", quality=0.9, deltas=(0.02,)),
            group("identity-high-1", quality=0.9, deltas=(0.03,)),
            group("identity-high-2", quality=0.9, deltas=(0.04,)),
            group("identity-low-0", quality=0.2, deltas=(0.02,)),
            group("identity-low-1", quality=0.2, deltas=(0.03,)),
        ]
        profile = self.profile(groups=groups, minimum=3, alpha=0.1)
        family = profile.evaluate(group("family-query", quality=0.2, deltas=(0.9,)))
        self.assertTrue(family.evaluated)
        self.assertEqual(family.fallback, "family")
        self.assertEqual(family.selected_stratum, "identity::*")
        global_result = profile.evaluate(group("new-family", family="new-engine", quality=0.2, deltas=(0.9,)))
        self.assertTrue(global_result.evaluated)
        self.assertEqual(global_result.fallback, "global")
        self.assertEqual(global_result.selected_stratum, "*::*")
        # The global fallback is deliberately more conservative about support
        # but can still remain null-consistent when the finite-sample p-value
        # is above alpha.
        self.assertFalse(global_result.unknown)

    def test_no_compatible_null_is_not_reported_as_unknown(self):
        profile = self.profile(
            groups=[group("only-0", deltas=(0.01,)), group("only-1", deltas=(0.02,))],
            minimum=3,
            allow_family_fallback=False,
            allow_global_fallback=True,
        )
        result = profile.evaluate(group("query", family="unseen", deltas=(0.99,)))
        self.assertFalse(result.evaluated)
        self.assertFalse(result.unknown)
        self.assertIsNone(result.raw_p_value)
        self.assertEqual(result.reason, "no_compatible_null")
        self.assertEqual(result.fallback, "unavailable")
        self.assertIsNone(result.unknown_reason)

    def test_metadata_and_input_boundaries_are_rejected(self):
        profile = self.profile()
        with self.assertRaises(ValueError):
            profile.evaluate(group("q", detector="other-detector"))
        with self.assertRaises(ValueError):
            profile.evaluate(group("q", schema="other-schema"))
        with self.assertRaises(ValueError):
            group("bad", deltas=(math.nan,))
        with self.assertRaises(ValueError):
            PairedDeltaCalibrationConfig(quality_bins=(0.6, 0.4))
        with self.assertRaises(ValueError):
            fit_paired_delta_profile([group("same"), group("same")])

    def test_output_does_not_claim_aigc_or_human_state(self):
        profile = self.profile()
        result = evaluate_paired_delta(group("q", deltas=(0.8,)), profile)
        serialized = result.to_dict()
        self.assertIn("null_hypothesis", serialized)
        self.assertNotIn("aigc_probability", serialized)
        self.assertNotIn("human_supported", serialized)
        self.assertNotIn("ai_generated_supported", serialized)


if __name__ == "__main__":
    unittest.main()
