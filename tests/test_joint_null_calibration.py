import unittest

from aigc.joint_null_calibration import (
    ROUTE_CANDIDATE,
    ROUTE_CONFLICT_REVIEW,
    ROUTE_INSUFFICIENT,
    ROUTE_NULL_CONSISTENT,
    JointNullConfig,
    JointNullExample,
    evaluate_joint_null,
    fit_joint_null_profile,
)


DATASET_DIGEST = "a" * 64


def null_examples(count=20):
    return [
        JointNullExample(
            group_id=f"null-{index}",
            p_values={
                "pixel_residual": 0.52 + 0.01 * (index % 3),
                "spectral": 0.58 + 0.01 * (index % 4),
            },
        )
        for index in range(count)
    ]


class JointNullCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.profile = fit_joint_null_profile(
            null_examples(),
            dataset_digest=DATASET_DIGEST,
            minimum_count=20,
        )
        self.config = JointNullConfig(minimum_null_count=20)

    def test_concordant_moderate_streams_can_be_calibrated_jointly(self):
        result = evaluate_joint_null(
            {"pixel_residual": 0.04, "spectral": 0.04},
            self.profile,
            config=self.config,
        )
        self.assertEqual(result.route, ROUTE_CANDIDATE)
        self.assertFalse(result.abstained)
        self.assertEqual(result.support_stream_count, 2)
        self.assertLessEqual(result.calibrated_p_value, self.config.alpha)

    def test_ordinary_null_is_not_promoted_to_human(self):
        result = evaluate_joint_null(
            {"pixel_residual": 0.90, "spectral": 0.90},
            self.profile,
            config=self.config,
        )
        self.assertEqual(result.route, ROUTE_NULL_CONSISTENT)
        self.assertFalse(result.abstained)
        self.assertEqual(result.reason, "joint_null_consistent")

    def test_stream_disagreement_routes_to_review(self):
        result = evaluate_joint_null(
            {"pixel_residual": 0.001, "spectral": 0.95},
            self.profile,
            config=self.config,
        )
        self.assertEqual(result.route, ROUTE_CONFLICT_REVIEW)
        self.assertTrue(result.abstained)
        self.assertGreater(result.p_spread_raw, self.config.maximum_p_spread)

    def test_missing_profile_or_stream_set_fails_closed(self):
        missing = evaluate_joint_null(
            {"pixel_residual": 0.04, "spectral": 0.04},
            None,
            config=self.config,
        )
        self.assertEqual(missing.route, ROUTE_INSUFFICIENT)
        mismatch = evaluate_joint_null(
            {"pixel_residual": 0.04},
            self.profile,
            config=self.config,
        )
        self.assertEqual(mismatch.route, ROUTE_INSUFFICIENT)
        self.assertTrue(mismatch.abstained)

    def test_profile_requires_group_and_stream_integrity(self):
        with self.assertRaises(ValueError):
            fit_joint_null_profile(
                null_examples(2) + [null_examples(2)[0]],
                dataset_digest=DATASET_DIGEST,
                minimum_count=1,
            )
        with self.assertRaises(ValueError):
            fit_joint_null_profile(
                [
                    JointNullExample("a", {"pixel_residual": 0.5, "spectral": 0.5}),
                    JointNullExample("b", {"pixel_residual": 0.5, "other": 0.5}),
                ],
                dataset_digest=DATASET_DIGEST,
                minimum_count=1,
            )

    def test_low_quality_examples_are_excluded_and_minimum_support_is_enforced(self):
        profile = fit_joint_null_profile(
            [
                JointNullExample(
                    f"q-{index}",
                    {"pixel_residual": 0.55, "spectral": 0.60},
                    quality_score=0.2 if index == 0 else 0.9,
                )
                for index in range(21)
            ],
            dataset_digest=DATASET_DIGEST,
            minimum_quality=0.35,
            minimum_count=20,
        )
        self.assertEqual(profile.count, 20)
        result = evaluate_joint_null(
            {"pixel_residual": 0.04, "spectral": 0.04},
            profile,
            config=JointNullConfig(minimum_null_count=21),
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)

    def test_digest_and_serialization_are_deterministic(self):
        first = evaluate_joint_null(
            {"spectral": 0.04, "pixel_residual": 0.04},
            self.profile,
            config=self.config,
        )
        second = evaluate_joint_null(
            {"pixel_residual": 0.04, "spectral": 0.04},
            self.profile,
            config=self.config,
        )
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(len(first.evidence_digest), 64)
        self.assertEqual(len(first.config_digest), 64)
        self.assertEqual(len(self.profile.profile_digest), 64)


if __name__ == "__main__":
    unittest.main()
