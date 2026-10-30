import unittest

from aigc.regional_alignment import (
    AlignmentConfig,
    align_gray_grids,
    build_paired_regional_observations,
    partition_aligned_regions,
)
from aigc.regional_counterfactual import fuse_regional_counterfactual

try:
    import numpy as np
except ModuleNotFoundError:  # pragma: no cover - dependency gate
    np = None


@unittest.skipUnless(np is not None, "NumPy is required")
class RegionalAlignmentTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(17)
        self.reference = rng.random((32, 32), dtype=np.float32)

    def shifted(self, dx, dy):
        query = np.roll(self.reference, (dy, dx), axis=(0, 1)).copy()
        if dy > 0:
            query[:dy, :] = 0.0
        elif dy < 0:
            query[dy:, :] = 0.0
        if dx > 0:
            query[:, :dx] = 0.0
        elif dx < 0:
            query[:, dx:] = 0.0
        return query

    def test_alignment_recovers_bounded_translation_deterministically(self):
        query = self.shifted(2, -1)
        config = AlignmentConfig(max_translation=4, minimum_match_score=0.80)
        first = align_gray_grids(self.reference, query, config=config)
        second = align_gray_grids(self.reference, query, config=config)
        self.assertTrue(first.accepted, first.to_dict())
        self.assertEqual(first.to_dict(), second.to_dict())
        # The query was rolled right/down; the registration applies the
        # inverse shift to compare the common source coordinates.
        self.assertEqual((first.dx, first.dy), (-2, 1))
        self.assertGreater(first.match_score, 0.99)
        self.assertEqual(first.aligned_shape, (31, 30))

    def test_resize_is_explicit_and_can_be_disabled(self):
        smaller = self.reference[::2, ::2]
        resized = align_gray_grids(
            self.reference,
            smaller,
            config=AlignmentConfig(allow_resize=True, minimum_match_score=0.40),
        )
        self.assertTrue(resized.accepted, resized.to_dict())
        self.assertTrue(resized.resized_query)
        self.assertEqual(resized.resize_version, "bilinear-grid-resize-v1")
        rejected = align_gray_grids(
            self.reference,
            smaller,
            config=AlignmentConfig(allow_resize=False),
        )
        self.assertFalse(rejected.accepted)
        self.assertEqual(rejected.reason, "shape_mismatch")

    def test_invalid_values_do_not_become_alignment_evidence(self):
        with self.assertRaises(ValueError):
            align_gray_grids(self.reference, [[float("nan")] * 32] * 32)
        with self.assertRaises(ValueError):
            align_gray_grids(self.reference, self.reference * 2.0)
        weak = align_gray_grids(
            self.reference,
            np.zeros_like(self.reference),
            config=AlignmentConfig(minimum_match_score=0.99),
        )
        self.assertFalse(weak.accepted)
        self.assertEqual(weak.reason, "match_below_threshold")

    def test_pair_builder_bridges_images_to_pc_scft_raw_observations(self):
        counterfactual = self.reference.copy()
        observed = self.reference.copy()
        # Keep the edit in one quadrant so the regional output remains
        # auditable; no result here is a calibrated AIGC probability.
        observed[2:13, 2:13] = np.clip(observed[2:13, 2:13] + 0.35, 0.0, 1.0)
        batch = build_paired_regional_observations(
            self.reference,
            observed,
            counterfactual,
            asset_id="asset-1",
            pair_id="pair-identity",
            transform_family="identity",
        )
        self.assertTrue(batch.accepted, batch.to_dict())
        self.assertEqual(batch.region_count, 4)
        self.assertEqual(len(batch.observations), 8)
        self.assertEqual(
            {item.kind for item in batch.observations}, {"observed", "counterfactual"}
        )
        self.assertTrue(all(item.detector_version == "source-residual-v1" for item in batch.observations))
        result = fuse_regional_counterfactual(batch.observations)
        self.assertTrue(result.has_score, result.to_dict())
        self.assertFalse(result.abstained)
        self.assertGreater(result.positive_delta_raw, 0.1)
        self.assertLessEqual(result.positive_delta_raw, 1.0)

    def test_pair_builder_rejects_different_reference_coordinate_frames(self):
        counterfactual = self.reference.copy()
        observed = self.shifted(2, 0)
        batch = build_paired_regional_observations(
            self.reference,
            observed,
            counterfactual,
            asset_id="asset-1",
            pair_id="pair-mismatch",
            transform_family="resize_then_jpeg",
        )
        self.assertFalse(batch.accepted, batch.to_dict())
        self.assertEqual(batch.reason, "paired_shape_mismatch")
        self.assertEqual(batch.observations, ())

    def test_partition_rejects_too_small_common_overlap(self):
        alignment = align_gray_grids(
            self.reference,
            self.shifted(4, 4),
            config=AlignmentConfig(grid_rows=4, grid_cols=4, min_region_side=8),
        )
        self.assertTrue(alignment.accepted)
        # 28x28 cannot be split into four 8-pixel regions in both axes.
        with self.assertRaises(ValueError):
            partition_aligned_regions(alignment, config=AlignmentConfig(grid_rows=4, grid_cols=4, min_region_side=8))


if __name__ == "__main__":
    unittest.main()
