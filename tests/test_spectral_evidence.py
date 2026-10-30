import unittest

try:
    import numpy as np
except ModuleNotFoundError:  # pragma: no cover - dependency gate
    np = None

from aigc.spectral_evidence import (
    SpectralEvidenceConfig,
    SpectralRegion,
    compute_spectral_evidence,
    score_spectral_regions,
)


@unittest.skipUnless(np is not None, "NumPy is required")
class SpectralEvidenceTests(unittest.TestCase):
    def grids(self):
        yy, xx = np.mgrid[0:64, 0:64]
        reference = (0.18 + 0.003 * xx + 0.004 * yy).astype(np.float32)
        counterfactual = reference + 0.08
        edited = counterfactual.copy()
        edited[20:40, 22:42] = np.clip(edited[20:40, 22:42] + 0.25, 0.0, 1.0)
        return reference, edited, counterfactual

    def test_local_edit_is_positive_after_counterfactual_correction(self):
        reference, edited, counterfactual = self.grids()
        result = compute_spectral_evidence(reference, edited, counterfactual)
        self.assertTrue(result.accepted, result.to_dict())
        score = result.scores[0]
        self.assertGreater(score.score_raw, 0.2)
        self.assertGreater(score.query_score_raw, score.counterfactual_score_raw)
        self.assertAlmostEqual(score.score_raw, score.paired_delta_raw)
        self.assertEqual(score.detector_version, "source-spectral-phase-v1")
        self.assertEqual(score.score_schema, "source-spectral-score-v1")

    def test_global_change_and_ordinary_hard_negative_are_corrected(self):
        reference, _, _ = self.grids()
        global_change = reference + 0.08
        global_result = compute_spectral_evidence(reference, global_change, global_change)
        self.assertTrue(global_result.accepted, global_result.to_dict())
        self.assertLess(global_result.scores[0].score_raw, 0.02)
        ordinary = global_change.copy()
        ordinary[5:12, 5:12] += 0.01
        hard_negative = compute_spectral_evidence(reference, ordinary, ordinary)
        self.assertTrue(hard_negative.accepted, hard_negative.to_dict())
        self.assertLess(hard_negative.scores[0].score_raw, 1e-5)

    def test_region_windows_have_stable_coordinate_frame_and_digest(self):
        reference, edited, counterfactual = self.grids()
        regions = (
            SpectralRegion("edited", (16, 16, 48, 48)),
            SpectralRegion("background", (0, 0, 16, 16)),
        )
        first = score_spectral_regions(reference, edited, counterfactual, regions=regions)
        second = score_spectral_regions(reference, edited, counterfactual, regions=regions)
        self.assertTrue(first.accepted, first.to_dict())
        self.assertEqual(first.evidence_digest, second.evidence_digest)
        self.assertEqual(first.config_digest, second.config_digest)
        self.assertGreater(first.scores[0].score_raw, first.scores[1].score_raw)
        self.assertEqual(first.scores[0].bbox_xyxy, (16, 16, 48, 48))

    def test_nonfinite_and_shape_fail_closed(self):
        reference, edited, counterfactual = self.grids()
        nonfinite = edited.copy()
        nonfinite[0, 0] = np.nan
        result = compute_spectral_evidence(reference, nonfinite, counterfactual)
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "nonfinite_input")
        mismatch = compute_spectral_evidence(reference, edited[:32, :], counterfactual)
        self.assertFalse(mismatch.accepted)
        self.assertEqual(mismatch.reason, "shape_mismatch")
        bad_region = score_spectral_regions(
            reference,
            edited,
            counterfactual,
            regions=(SpectralRegion("outside", (50, 50, 70, 70)),),
        )
        self.assertFalse(bad_region.accepted)
        self.assertEqual(bad_region.reason, "region_bbox_out_of_bounds")

    def test_missing_counterfactual_is_explicit_and_config_digest_changes(self):
        reference, edited, _ = self.grids()
        result = compute_spectral_evidence(reference, edited)
        self.assertTrue(result.accepted, result.to_dict())
        self.assertFalse(result.paired)
        self.assertIn("counterfactual_missing", result.scores[0].warnings)
        changed = compute_spectral_evidence(
            reference,
            edited,
            config=SpectralEvidenceConfig(amplitude_scale=0.25),
        )
        self.assertNotEqual(result.config_digest, changed.config_digest)


if __name__ == "__main__":
    unittest.main()
