import unittest

from aigc.mpcf import (
    MPCFConfig,
    MPCFControlDelta,
    MPCFTarget,
    ROUTE_CANDIDATE_EDIT,
    ROUTE_CONTROL_CONSISTENT,
    ROUTE_INSUFFICIENT,
    evaluate_mpcf,
)
from aigc.regional_fdr import RegionalQueryDelta


DIGESTS = {
    "manifest": "a" * 64,
    "other_manifest": "b" * 64,
    "frame": "c" * 64,
    "spec": "d" * 64,
}


def make_target(*, delta=0.80, quality=0.90, source_match=0.90):
    return MPCFTarget(
        asset_id="asset-1",
        pair_id="pair-1",
        manifest_digest=DIGESTS["manifest"],
        coordinate_frame_digest=DIGESTS["frame"],
        transform_spec_digest=DIGESTS["spec"],
        query_delta=RegionalQueryDelta(
            region_id="r0",
            region_type="object",
            delta_raw=delta,
            quality_score=quality,
            source_match_score=source_match,
            transform_family="jpeg_q75",
            detector_version="source-residual-v1",
            score_schema="source-residual-score-v1",
        ),
    )


def make_controls(values, *, quality=0.90, source_match=0.90, **overrides):
    return [
        MPCFControlDelta(
            control_id=f"control-{index}",
            asset_id=overrides.get("asset_id", "asset-1"),
            pair_id=overrides.get("pair_id", "pair-1"),
            manifest_digest=overrides.get("manifest_digest", DIGESTS["manifest"]),
            region_id=overrides.get("region_id", "r0"),
            region_type=overrides.get("region_type", "object"),
            transform_family=overrides.get("transform_family", "jpeg_q75"),
            detector_version=overrides.get("detector_version", "source-residual-v1"),
            score_schema=overrides.get("score_schema", "source-residual-score-v1"),
            coordinate_frame_digest=overrides.get("coordinate_frame_digest", DIGESTS["frame"]),
            transform_spec_digest=overrides.get("transform_spec_digest", DIGESTS["spec"]),
            quality_score=quality,
            source_match_score=source_match,
            delta_raw=value,
        )
        for index, value in enumerate(values)
    ]


class MPCFTests(unittest.TestCase):
    def test_candidate_reports_ties_inclusive_p_median_contrast_and_spread(self):
        config = MPCFConfig(minimum_control_count=4, alpha=0.20)
        # Three controls are strictly below the target.  One exact tie must
        # count in the upper tail: p=(1+1)/(4+1)=0.4, so this is consistent.
        result = evaluate_mpcf(make_target(delta=0.80), make_controls((0.10, 0.10, 0.10, 0.80)), config=config)
        self.assertEqual(result.route, ROUTE_CONTROL_CONSISTENT)
        self.assertEqual(result.exceedance_count, 1)
        self.assertAlmostEqual(result.p_value_raw, 0.40)
        self.assertAlmostEqual(result.control_median_raw, 0.10)
        self.assertAlmostEqual(result.contrast_raw, 0.70)
        self.assertAlmostEqual(result.control_spread_raw, 0.70)

        # With no tie the finite-sample floor is 1/(n+1), yielding a candidate.
        result = evaluate_mpcf(make_target(delta=0.80), make_controls((0.10, 0.10, 0.10, 0.10)), config=config)
        self.assertEqual(result.route, ROUTE_CANDIDATE_EDIT)
        self.assertEqual(result.exceedance_count, 0)
        self.assertAlmostEqual(result.p_value_raw, 0.20)

    def test_control_consistent_route_is_raw_evidence_only(self):
        result = evaluate_mpcf(
            make_target(delta=0.12),
            make_controls((0.08, 0.10, 0.12, 0.14)),
            config=MPCFConfig(minimum_control_count=4, alpha=0.05),
        )
        self.assertEqual(result.route, ROUTE_CONTROL_CONSISTENT)
        self.assertFalse(result.abstained)
        self.assertIn("matched_placebo", result.reason)
        self.assertNotIn(result.route, {"human_supported", "ai_generated_supported", "ai_edited_supported"})

    def test_control_order_does_not_change_digest_or_statistics(self):
        config = MPCFConfig(minimum_control_count=4, alpha=0.20)
        controls = make_controls((0.10, 0.11, 0.12, 0.13))
        first = evaluate_mpcf(make_target(delta=0.80), controls, config=config)
        second = evaluate_mpcf(make_target(delta=0.80), list(reversed(controls)), config=config)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(len(first.evidence_digest), 64)
        self.assertEqual(len(first.binding_digest), 64)

    def test_identity_mismatch_fails_closed_and_exposes_no_statistics(self):
        result = evaluate_mpcf(
            make_target(),
            make_controls((0.01, 0.02, 0.03, 0.04), pair_id="other-pair"),
            config=MPCFConfig(minimum_control_count=4),
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "control_identity_mismatch")
        self.assertIsNone(result.p_value_raw)
        self.assertEqual(result.control_deltas, ())

        result = evaluate_mpcf(
            make_target(),
            make_controls((0.01, 0.02, 0.03, 0.04), manifest_digest=DIGESTS["other_manifest"]),
            config=MPCFConfig(minimum_control_count=4),
        )
        self.assertEqual(result.reason, "control_identity_mismatch")

        result = evaluate_mpcf(
            make_target(),
            make_controls((0.01, 0.02, 0.03, 0.04), coordinate_frame_digest=DIGESTS["other_manifest"]),
            config=MPCFConfig(minimum_control_count=4),
        )
        self.assertEqual(result.reason, "control_identity_mismatch")

        result = evaluate_mpcf(
            make_target(),
            make_controls((0.01, 0.02, 0.03, 0.04), transform_spec_digest=DIGESTS["other_manifest"]),
            config=MPCFConfig(minimum_control_count=4),
        )
        self.assertEqual(result.reason, "control_identity_mismatch")

    def test_quality_bucket_mismatch_fails_closed(self):
        # q3 target versus q2 controls, even though both exceed the minimum.
        result = evaluate_mpcf(
            make_target(quality=0.90),
            make_controls((0.01, 0.02, 0.03, 0.04), quality=0.79),
            config=MPCFConfig(minimum_control_count=4),
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "control_quality_bucket_mismatch")

    def test_quality_and_source_match_fail_closed(self):
        result = evaluate_mpcf(
            make_target(),
            make_controls((0.01, 0.02, 0.03, 0.04), quality=0.20),
            config=MPCFConfig(minimum_control_count=4),
        )
        self.assertEqual(result.reason, "control_quality_below_threshold")
        result = evaluate_mpcf(
            make_target(),
            make_controls((0.01, 0.02, 0.03, 0.04), source_match=0.20),
            config=MPCFConfig(minimum_control_count=4),
        )
        self.assertEqual(result.reason, "control_source_match_below_threshold")
        result = evaluate_mpcf(
            make_target(quality=0.20),
            make_controls((0.01, 0.02, 0.03, 0.04)),
            config=MPCFConfig(minimum_control_count=4),
        )
        self.assertEqual(result.reason, "target_quality_below_threshold")

    def test_sample_and_duplicate_fail_closed(self):
        result = evaluate_mpcf(
            make_target(),
            make_controls((0.01, 0.02, 0.03)),
            config=MPCFConfig(minimum_control_count=4),
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "control_sample_insufficient")

        controls = make_controls((0.01, 0.02, 0.03, 0.04))
        controls[-1] = MPCFControlDelta(
            control_id=controls[0].control_id,
            asset_id=controls[-1].asset_id,
            pair_id=controls[-1].pair_id,
            manifest_digest=controls[-1].manifest_digest,
            region_id=controls[-1].region_id,
            region_type=controls[-1].region_type,
            transform_family=controls[-1].transform_family,
            detector_version=controls[-1].detector_version,
            score_schema=controls[-1].score_schema,
            coordinate_frame_digest=controls[-1].coordinate_frame_digest,
            transform_spec_digest=controls[-1].transform_spec_digest,
            quality_score=controls[-1].quality_score,
            source_match_score=controls[-1].source_match_score,
            delta_raw=controls[-1].delta_raw,
        )
        result = evaluate_mpcf(make_target(), controls, config=MPCFConfig(minimum_control_count=4))
        self.assertEqual(result.reason, "duplicate_control_id")

    def test_invalid_controls_and_target_are_not_silently_coerced(self):
        result = evaluate_mpcf(
            make_target(),
            [*make_controls((0.01, 0.02, 0.03)), {"delta_raw": 0.04}],
            config=MPCFConfig(minimum_control_count=3),
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "invalid_control_type")
        with self.assertRaises(ValueError):
            MPCFControlDelta(
                control_id="bad",
                asset_id="asset-1",
                pair_id="pair-1",
                manifest_digest=DIGESTS["manifest"],
                region_id="r0",
                region_type="object",
                transform_family="jpeg_q75",
                detector_version="source-residual-v1",
                score_schema="source-residual-score-v1",
                coordinate_frame_digest=DIGESTS["frame"],
                transform_spec_digest=DIGESTS["spec"],
                quality_score=0.9,
                source_match_score=0.9,
                delta_raw=float("nan"),
            )


if __name__ == "__main__":
    unittest.main()
