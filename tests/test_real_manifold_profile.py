import math
import unittest

from aigc.real_manifold_profile import (
    FEATURE_SCHEMA,
    ROUTE_IN_DISTRIBUTION,
    ROUTE_INSUFFICIENT,
    ROUTE_OUT_OF_MANIFOLD,
    ROUTE_PROFILE_MISMATCH,
    ManifoldObservation,
    ManifoldQuery,
    NaturalManifoldConfig,
    adapt_real_manifold_profile,
    evaluate_real_manifold,
    fit_real_manifold_profile,
)


def observations(
    count=20,
    *,
    feature_schema=FEATURE_SCHEMA,
    detector_version="detector-v1",
    quality_score=0.9,
    start=0,
):
    return [
        ManifoldObservation(
            sample_id=f"sample-{index}",
            group_id=f"group-{index}",
            feature=(0.20 + 0.01 * index + start, 0.40 + 0.005 * index + start),
            feature_schema=feature_schema,
            detector_version=detector_version,
            quality_score=quality_score,
        )
        for index in range(count)
    ]


class RealManifoldProfileTests(unittest.TestCase):
    def setUp(self):
        self.config = NaturalManifoldConfig(minimum_support=20, alpha=0.05)
        self.calibration = observations()
        self.profile = fit_real_manifold_profile(self.calibration, config=self.config)

    def test_in_distribution_and_out_of_manifold_routes_are_raw_evidence(self):
        in_result = evaluate_real_manifold(
            ManifoldQuery("query-in", (0.30, 0.45), FEATURE_SCHEMA, "detector-v1"),
            self.profile,
        )
        out_result = evaluate_real_manifold(
            ManifoldQuery("query-out", (10.0, 10.0), FEATURE_SCHEMA, "detector-v1"),
            self.profile,
        )
        self.assertEqual(in_result.route, ROUTE_IN_DISTRIBUTION)
        self.assertEqual(out_result.route, ROUTE_OUT_OF_MANIFOLD)
        self.assertTrue(in_result.evaluated)
        self.assertTrue(out_result.evaluated)
        self.assertGreater(out_result.energy_raw, out_result.threshold)
        self.assertNotIn("ai_generated_supported", out_result.to_dict())
        self.assertNotIn("human_supported", in_result.to_dict())
        self.assertIn("raw natural-manifold evidence only", out_result.to_dict()["interpretation"])

    def test_quality_and_support_gates_route_to_insufficient(self):
        low_quality = evaluate_real_manifold(
            ManifoldQuery("query-low-quality", (0.30, 0.45), FEATURE_SCHEMA, "detector-v1", 0.2),
            self.profile,
        )
        self.assertEqual(low_quality.route, ROUTE_INSUFFICIENT)
        self.assertEqual(low_quality.reason, "quality_below_threshold")
        self.assertFalse(low_quality.evaluated)

        small_profile = fit_real_manifold_profile(
            observations(4),
            config=NaturalManifoldConfig(minimum_support=20),
        )
        unsupported = evaluate_real_manifold(
            ManifoldQuery("query-unsupported", (0.30, 0.45), FEATURE_SCHEMA, "detector-v1"),
            small_profile,
        )
        self.assertEqual(unsupported.route, ROUTE_INSUFFICIENT)
        self.assertEqual(unsupported.reason, "insufficient_profile_support")
        self.assertFalse(unsupported.support_sufficient)

    def test_schema_detector_and_dimension_mismatch_fail_closed(self):
        schema_mismatch = evaluate_real_manifold(
            ManifoldQuery("query-schema", (0.30, 0.45), "other-feature-v1", "detector-v1"),
            self.profile,
        )
        detector_mismatch = evaluate_real_manifold(
            ManifoldQuery("query-detector", (0.30, 0.45), FEATURE_SCHEMA, "detector-v2"),
            self.profile,
        )
        dimension_mismatch = evaluate_real_manifold(
            ManifoldQuery("query-dimension", (0.30, 0.45, 0.60), FEATURE_SCHEMA, "detector-v1"),
            self.profile,
        )
        for result, reason in (
            (schema_mismatch, "feature_schema_mismatch"),
            (detector_mismatch, "detector_version_mismatch"),
            (dimension_mismatch, "feature_dimension_mismatch"),
        ):
            self.assertEqual(result.route, ROUTE_PROFILE_MISMATCH)
            self.assertEqual(result.reason, reason)
            self.assertFalse(result.evaluated)
            self.assertIsNone(result.energy_raw)

    def test_only_authorized_real_calibration_can_fit(self):
        with self.assertRaises(ValueError):
            ManifoldObservation(
                "bad-origin",
                "bad-origin-group",
                (0.1, 0.2),
                origin="camera_photo",
            )
        with self.assertRaises(ValueError):
            ManifoldObservation(
                "bad-auth",
                "bad-auth-group",
                (0.1, 0.2),
                authorized_for_research=False,
            )
        with self.assertRaises(ValueError):
            fit_real_manifold_profile(
                observations(20, quality_score=0.2),
                config=self.config,
            )
        with self.assertRaises(ValueError):
            ManifoldObservation(
                "bad-split",
                "bad-split-group",
                (0.1, 0.2),
                split="validation",
            )

    def test_input_integrity_and_finite_boundaries_are_rejected(self):
        duplicate_sample = observations(20)
        duplicate_sample[-1] = ManifoldObservation(
            "sample-0", "group-last", (0.3, 0.5)
        )
        with self.assertRaises(ValueError):
            fit_real_manifold_profile(duplicate_sample, config=self.config)

        duplicate_group = observations(20)
        duplicate_group[-1] = ManifoldObservation(
            "sample-last", "group-0", (0.3, 0.5)
        )
        with self.assertRaises(ValueError):
            fit_real_manifold_profile(duplicate_group, config=self.config)

        with self.assertRaises(ValueError):
            ManifoldObservation("nan", "nan-group", (math.nan, 0.2))
        with self.assertRaises(ValueError):
            ManifoldObservation("inf", "inf-group", (math.inf, 0.2))

        mixed_schema = observations(20)
        mixed_schema[-1] = ManifoldObservation(
            "sample-last", "group-last", (0.3, 0.5), feature_schema="other-feature-v1"
        )
        with self.assertRaises(ValueError):
            fit_real_manifold_profile(mixed_schema, config=self.config)

    def test_digest_is_order_independent_and_profile_is_versioned(self):
        first = fit_real_manifold_profile(self.calibration, config=self.config)
        second = fit_real_manifold_profile(list(reversed(self.calibration)), config=self.config)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.version_index, 1)
        self.assertEqual(first.parent_profile_digest, None)
        self.assertEqual(len(first.dataset_digest), 64)
        self.assertEqual(len(first.profile_digest), 64)
        self.assertEqual(first.schema, "natural-manifold-profile-v1")

    def test_adaptation_requires_parent_and_complete_replay_and_preserves_rollback(self):
        replay = self.calibration + [
            ManifoldObservation(
                "sample-new-0", "group-new-0", (0.31, 0.46), detector_version="detector-v1"
            ),
            ManifoldObservation(
                "sample-new-1", "group-new-1", (0.32, 0.47), detector_version="detector-v1"
            ),
        ]
        adapted = adapt_real_manifold_profile(
            self.profile,
            replay,
            parent_profile_digest=self.profile.profile_digest,
            prototype_version="real-only-v2",
        )
        self.assertEqual(adapted.version_index, 2)
        self.assertEqual(adapted.parent_profile_digest, self.profile.profile_digest)
        self.assertEqual(adapted.prototype_version, "real-only-v2")
        self.assertNotEqual(adapted.profile_digest, self.profile.profile_digest)
        self.assertEqual(self.profile.parent_profile_digest, None)
        self.assertEqual(self.profile.version_index, 1)

        with self.assertRaises(ValueError):
            adapt_real_manifold_profile(
                self.profile,
                replay,
                parent_profile_digest="0" * 64,
                prototype_version="real-only-v2",
            )
        with self.assertRaises(ValueError):
            adapt_real_manifold_profile(
                self.profile,
                self.calibration,
                parent_profile_digest=self.profile.profile_digest,
                prototype_version="real-only-v2",
            )
        mismatched_replay = replay[:-1] + [
            ManifoldObservation(
                "sample-new-1",
                "group-new-1",
                (0.32, 0.47),
                detector_version="detector-v2",
            )
        ]
        with self.assertRaises(ValueError):
            adapt_real_manifold_profile(
                self.profile,
                mismatched_replay,
                parent_profile_digest=self.profile.profile_digest,
                prototype_version="real-only-v2",
            )

    def test_config_rejects_ambiguous_bounds(self):
        with self.assertRaises(ValueError):
            NaturalManifoldConfig(minimum_support=True)
        with self.assertRaises(ValueError):
            NaturalManifoldConfig(minimum_support=1)
        with self.assertRaises(ValueError):
            NaturalManifoldConfig(alpha=0.0)
        with self.assertRaises(ValueError):
            NaturalManifoldConfig(alpha=1.0)
        with self.assertRaises(ValueError):
            NaturalManifoldConfig(scale_floor=0.0)


if __name__ == "__main__":
    unittest.main()
