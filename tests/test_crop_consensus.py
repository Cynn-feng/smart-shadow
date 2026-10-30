import unittest

from aigc.crop_consensus import (
    CropConsensusConfig,
    CropNullSample,
    CropView,
    ROUTE_CONSENSUS_CANDIDATE,
    ROUTE_INSUFFICIENT,
    ROUTE_NULL_CONSISTENT,
    ROUTE_VIEW_INCONSISTENT,
    evaluate_crop_consensus,
)


DIGESTS = {"manifest": "a" * 64, "frame": "b" * 64}


def make_views(rows, **overrides):
    return [
        CropView(
            view_id=f"view-{index}",
            consensus_id=overrides.get("consensus_id", "cc-1"),
            asset_id=overrides.get("asset_id", "asset-1"),
            pair_id=overrides.get("pair_id", "pair-1"),
            manifest_digest=overrides.get("manifest_digest", DIGESTS["manifest"]),
            canonical_frame_digest=overrides.get("canonical_frame_digest", DIGESTS["frame"]),
            crop_spec_digest=(f"{index + 1:064x}"),
            transform_family=overrides.get("transform_family", "jpeg_q75"),
            detector_version=overrides.get("detector_version", "source-residual-v1"),
            score_schema=overrides.get("score_schema", "source-residual-score-v1"),
            quality_score=overrides.get("quality_score", 0.9),
            source_match_score=overrides.get("source_match_score", 0.9),
            delta_by_region=row,
        )
        for index, row in enumerate(rows)
    ]


def make_nulls(values, **overrides):
    return [
        CropNullSample(
            sample_id=f"null-{index}",
            consensus_id=overrides.get("consensus_id", "cc-1"),
            asset_id=overrides.get("asset_id", "asset-1"),
            pair_id=overrides.get("pair_id", "pair-1"),
            manifest_digest=overrides.get("manifest_digest", DIGESTS["manifest"]),
            canonical_frame_digest=overrides.get("canonical_frame_digest", DIGESTS["frame"]),
            transform_family=overrides.get("transform_family", "jpeg_q75"),
            detector_version=overrides.get("detector_version", "source-residual-v1"),
            score_schema=overrides.get("score_schema", "source-residual-score-v1"),
            quality_score=overrides.get("quality_score", 0.9),
            source_match_score=overrides.get("source_match_score", 0.9),
            positive_view_fraction_raw=1.0,
            view_set_overlap_raw=value,
            consensus_raw=value,
        )
        for index, value in enumerate(values)
    ]


class CropConsensusTests(unittest.TestCase):
    def config(self):
        return CropConsensusConfig(minimum_view_count=3, minimum_null_count=4, alpha=0.20)

    def test_consensus_candidate_uses_weighted_fraction_overlap_and_tie_safe_p(self):
        result = evaluate_crop_consensus(
            make_views(({"r-target": 0.50, "r-other": 0.01}, {"r-target": 0.55, "r-other": 0.02}, {"r-target": 0.52, "r-other": 0.03})),
            make_nulls((0.05, 0.06, 0.07, 0.08)),
            config=self.config(),
        )
        self.assertEqual(result.route, ROUTE_CONSENSUS_CANDIDATE)
        self.assertEqual(result.summary.candidate_regions, ("r-target",))
        self.assertAlmostEqual(result.summary.weighted_positive_view_fraction, 1.0)
        self.assertAlmostEqual(result.summary.view_set_overlap_raw, 1.0)
        self.assertEqual(result.exceedance_count, 0)
        self.assertAlmostEqual(result.p_value_raw, 0.2)
        self.assertEqual(len(result.observation_digest), 64)

    def test_null_consistent_when_target_is_below_null(self):
        result = evaluate_crop_consensus(
            make_views(({"r-target": 0.50}, {"r-target": 0.51}, {"r-target": 0.52}, {"r-target": 0.53}, {"r-target": 0.01})),
            make_nulls((0.70, 0.71, 0.72, 0.73)),
            config=self.config(),
        )
        self.assertEqual(result.route, ROUTE_NULL_CONSISTENT)

    def test_view_inconsistent_when_positive_sets_disagree(self):
        result = evaluate_crop_consensus(
            make_views(({"r-a": 0.50}, {"r-b": 0.52}, {"r-c": 0.51})),
            make_nulls((0.01, 0.02, 0.03, 0.04)),
            config=self.config(),
        )
        self.assertEqual(result.route, ROUTE_VIEW_INCONSISTENT)
        self.assertEqual(result.reason, "positive_view_consensus_insufficient")

    def test_missing_or_mismatched_bindings_fail_closed(self):
        result = evaluate_crop_consensus(
            make_views(({"r-target": 0.5}, {"r-target": 0.5}, {"r-target": 0.5}), pair_id="pair-2"),
            make_nulls((0.01, 0.02, 0.03, 0.04)),
            config=self.config(),
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "null_identity_mismatch")

        result = evaluate_crop_consensus(
            make_views(({"r-target": 0.5}, {"r-target": 0.5})),
            make_nulls((0.01, 0.02, 0.03, 0.04)),
            config=self.config(),
        )
        self.assertEqual(result.reason, "view_count_insufficient")

        result = evaluate_crop_consensus(
            make_views(({"r-target": 0.5}, {"r-target": 0.5}, {"r-target": 0.5})),
            make_nulls((0.01, 0.02, 0.03)),
            config=self.config(),
        )
        self.assertEqual(result.reason, "null_sample_insufficient")

    def test_quality_source_and_duplicate_fail_closed(self):
        self.assertEqual(
            evaluate_crop_consensus(
                make_views(({"r-target": 0.5}, {"r-target": 0.5}, {"r-target": 0.5}), quality_score=0.2),
                make_nulls((0.01, 0.02, 0.03, 0.04)), config=self.config(),
            ).reason,
            "view_quality_below_threshold",
        )
        self.assertEqual(
            evaluate_crop_consensus(
                make_views(({"r-target": 0.5}, {"r-target": 0.5}, {"r-target": 0.5}), source_match_score=0.2),
                make_nulls((0.01, 0.02, 0.03, 0.04)), config=self.config(),
            ).reason,
            "view_source_match_below_threshold",
        )
        self.assertEqual(
            evaluate_crop_consensus(
                make_views(({"r-target": 0.5}, {"r-target": 0.5}, {"r-target": 0.5})),
                make_nulls((0.01, 0.02, 0.03, 0.04), quality_score=0.79), config=self.config(),
            ).reason,
            "null_quality_bucket_mismatch",
        )
        views = make_views(({"r-target": 0.5}, {"r-target": 0.5}, {"r-target": 0.5}))
        duplicate = CropView(
            view_id=views[0].view_id,
            consensus_id=views[-1].consensus_id,
            asset_id=views[-1].asset_id,
            pair_id=views[-1].pair_id,
            manifest_digest=views[-1].manifest_digest,
            canonical_frame_digest=views[-1].canonical_frame_digest,
            crop_spec_digest=views[-1].crop_spec_digest,
            transform_family=views[-1].transform_family,
            detector_version=views[-1].detector_version,
            score_schema=views[-1].score_schema,
            quality_score=views[-1].quality_score,
            source_match_score=views[-1].source_match_score,
            delta_by_region=views[-1].delta_by_region,
        )
        self.assertEqual(evaluate_crop_consensus([views[0], views[1], duplicate], make_nulls((0.01, 0.02, 0.03, 0.04)), config=self.config()).reason, "duplicate_view_id")

    def test_visible_region_availability_is_retained(self):
        result = evaluate_crop_consensus(
            make_views(({"r-target": 0.5}, {"r-target": 0.52}, {"r-other": 0.5})),
            make_nulls((0.01, 0.02, 0.03, 0.04)),
            config=self.config(),
        )
        self.assertEqual(result.route, ROUTE_VIEW_INCONSISTENT)
        self.assertTrue(any(region == "r-target" for region, _ in result.summary.region_availability))

    def test_invisible_target_region_is_not_treated_as_negative_view(self):
        result = evaluate_crop_consensus(
            make_views(({"r-target": 0.5}, {"r-target": 0.52}, {"r-target": 0.51}, {"r-other": 0.01})),
            make_nulls((0.01, 0.02, 0.03, 0.04)),
            config=self.config(),
        )
        self.assertEqual(result.route, ROUTE_CONSENSUS_CANDIDATE)
        self.assertAlmostEqual(result.summary.view_set_overlap_raw, 1.0)

    def test_order_does_not_change_result(self):
        views = make_views(({"r-target": 0.5}, {"r-target": 0.52}, {"r-target": 0.51}))
        nulls = make_nulls((0.01, 0.02, 0.03, 0.04))
        first = evaluate_crop_consensus(views, nulls, config=self.config())
        second = evaluate_crop_consensus(list(reversed(views)), list(reversed(nulls)), config=self.config())
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_positive_threshold_cannot_be_negative(self):
        with self.assertRaises(ValueError):
            CropConsensusConfig(positive_delta_threshold=-0.01)

    def test_invalid_item_types_are_rejected_before_sorting(self):
        with self.assertRaises(ValueError):
            evaluate_crop_consensus([object()], [], config=self.config())
        with self.assertRaises(ValueError):
            evaluate_crop_consensus([], [object()], config=self.config())

    def test_null_statistic_must_match_its_components(self):
        with self.assertRaises(ValueError):
            CropNullSample(
                sample_id="bad",
                consensus_id="cc-1",
                asset_id="asset-1",
                pair_id="pair-1",
                manifest_digest=DIGESTS["manifest"],
                canonical_frame_digest=DIGESTS["frame"],
                transform_family="jpeg_q75",
                detector_version="source-residual-v1",
                score_schema="source-residual-score-v1",
                quality_score=0.9,
                source_match_score=0.9,
                positive_view_fraction_raw=0.5,
                view_set_overlap_raw=0.5,
                consensus_raw=0.5,
            )


if __name__ == "__main__":
    unittest.main()
