import math
import unittest

from aigc.calibration import (
    NegativeConformalProfile,
    evaluate_negative_conformal,
    fit_conservative_ai_threshold,
    fit_negative_conformal_profile,
)
from aigc.fusion import CalibrationProfile


class CalibrationTests(unittest.TestCase):
    def conformal_calibration(self):
        return CalibrationProfile(
            calibration_id="calibration-negative-v1",
            detector_version="detector-v1",
            score_schema="score-v1",
            dataset_digest="c" * 64,
        )

    def test_zero_fpr_operating_point_is_conservative(self):
        point = fit_conservative_ai_threshold(
            [0.05, 0.10, 0.20, 0.80, 0.90],
            [0, 0, 0, 1, 1],
            detector_version="detector-v1",
            score_schema="score-v1",
            target_fpr=0.0,
        )
        self.assertEqual(point.empirical_fpr, 0.0)
        self.assertEqual(point.threshold, 0.8)
        self.assertEqual(point.validation_recall, 1.0)
        self.assertTrue(point.accepts(0.8))
        self.assertFalse(point.accepts(0.2))

    def test_calibration_rejects_one_class_or_nonfinite_input(self):
        with self.assertRaises(ValueError):
            fit_conservative_ai_threshold(
                [0.1, 0.2],
                [0, 0],
                detector_version="detector-v1",
                score_schema="score-v1",
            )
        with self.assertRaises(ValueError):
            fit_conservative_ai_threshold(
                [math.nan, 0.2],
                [0, 1],
                detector_version="detector-v1",
                score_schema="score-v1",
            )

    def test_calibration_digest_and_id_are_reproducible(self):
        kwargs = {
            "detector_version": "detector-v1",
            "score_schema": "score-v1",
            "target_fpr": 0.05,
        }
        first = fit_conservative_ai_threshold([0.1, 0.3, 0.7, 0.9], [0, 0, 1, 1], **kwargs)
        second = fit_conservative_ai_threshold([0.1, 0.3, 0.7, 0.9], [0, 0, 1, 1], **kwargs)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(len(first.dataset_digest), 64)

    def test_negative_conformal_p_value_is_tie_safe_and_rejects_unknown(self):
        profile = fit_negative_conformal_profile(
            [0.10, 0.20, 0.40, 0.60],
            calibration=self.conformal_calibration(),
            alpha=0.25,
        )
        # p=(1 + count(negative >= query))/(n+1), with ties included.
        self.assertAlmostEqual(profile.negative_p_value(0.60), 0.40)
        self.assertAlmostEqual(profile.negative_p_value(0.61), 0.20)
        self.assertAlmostEqual(profile.negative_p_value(0.00), 1.00)
        supported = profile.evaluate(
            0.60,
            detector_version="detector-v1",
            score_schema="score-v1",
            calibration_id="calibration-negative-v1",
        )
        self.assertFalse(supported.unknown)
        self.assertTrue(supported.consistent_with_negative_stream)
        rejected = evaluate_negative_conformal(
            0.61,
            profile,
            detector_version="detector-v1",
            score_schema="score-v1",
            calibration_id="calibration-negative-v1",
        )
        self.assertTrue(rejected.unknown)
        self.assertEqual(rejected.unknown_reason, "negative_conformal_reject")
        self.assertEqual(rejected.to_dict()["calibration_id"], "calibration-negative-v1")

    def test_negative_conformal_preserves_calibration_identity_and_rejects_mismatch(self):
        profile = NegativeConformalProfile.from_scores(
            [0.1, 0.2, 0.3],
            calibration=self.conformal_calibration(),
        )
        self.assertEqual(profile.to_dict()["detector_version"], "detector-v1")
        self.assertEqual(profile.to_dict()["score_schema"], "score-v1")
        self.assertEqual(profile.to_dict()["negative_count"], 3)
        with self.assertRaises(ValueError):
            profile.evaluate(0.9, detector_version="other-detector")
        with self.assertRaises(ValueError):
            profile.evaluate(0.9, score_schema="other-score")
        with self.assertRaises(ValueError):
            profile.evaluate(0.9, calibration_id="other-calibration")

    def test_negative_conformal_rejects_invalid_alpha_stream_and_result_contract(self):
        calibration = self.conformal_calibration()
        for alpha in (0.0, 1.0, math.nan, True):
            with self.assertRaises(ValueError):
                fit_negative_conformal_profile([0.1], calibration=calibration, alpha=alpha)
        with self.assertRaises(ValueError):
            fit_negative_conformal_profile([], calibration=calibration)
        with self.assertRaises(ValueError):
            fit_negative_conformal_profile([math.nan], calibration=calibration)
        with self.assertRaises(ValueError):
            fit_negative_conformal_profile([0.1], calibration="not-a-profile")


if __name__ == "__main__":
    unittest.main()
