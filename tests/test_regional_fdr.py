import unittest

from aigc.regional_fdr import (
    ROUTE_CANDIDATE,
    ROUTE_INSUFFICIENT,
    ROUTE_NULL_CONSISTENT,
    RegionalFDRConfig,
    RegionNullDelta,
    RegionalQueryDelta,
    evaluate_regional_fdr,
    fit_regional_fdr_profile,
)


REGIONS = (
    ("r0", "object"),
    ("r1", "stuff"),
    ("r2", "background"),
    ("r3", "object"),
)


def null_stream(count=24):
    values = []
    for index in range(count):
        for offset, (region_id, region_type) in enumerate(REGIONS):
            values.append(
                RegionNullDelta(
                    group_id=f"null-{index}",
                    transform_family="jpeg_q75",
                    quality_score=0.90,
                    region_id=region_id,
                    region_type=region_type,
                    delta_raw=0.02 + ((index + offset) % 3) * 0.01,
                    detector_version="synthetic-detector-v1",
                    score_schema="synthetic-delta-v1",
                )
            )
    return values


def query(values, *, quality=0.90, source_match=0.90):
    return [
        RegionalQueryDelta(
            region_id=region_id,
            region_type=region_type,
            delta_raw=delta,
            quality_score=quality,
            source_match_score=source_match,
            transform_family="jpeg_q75",
            detector_version="synthetic-detector-v1",
            score_schema="synthetic-delta-v1",
        )
        for (region_id, region_type), delta in zip(REGIONS, values)
    ]


class RegionalFDRTests(unittest.TestCase):
    def setUp(self):
        self.config = RegionalFDRConfig(minimum_null_count=10, q_value=0.20)
        self.profile = fit_regional_fdr_profile(null_stream(), config=self.config)

    def test_local_region_is_selected_with_bh_q_value(self):
        result = evaluate_regional_fdr(self.profile, query((0.80, 0.03, 0.02, 0.04)), config=self.config)
        self.assertEqual(result.route, ROUTE_CANDIDATE)
        self.assertFalse(result.abstained)
        self.assertTrue(result.candidate_supported)
        self.assertEqual(result.selected_region_ids, ("r0",))
        self.assertEqual(len(result.selections), 4)
        self.assertLessEqual(result.selections[0].q_value_raw, self.config.q_value)

    def test_ordinary_propagation_is_null_consistent(self):
        result = evaluate_regional_fdr(self.profile, query((0.03, 0.04, 0.02, 0.03)), config=self.config)
        self.assertEqual(result.route, ROUTE_NULL_CONSISTENT)
        self.assertFalse(result.candidate_supported)
        self.assertFalse(result.abstained)
        self.assertEqual(result.selected_region_ids, ())

    def test_missing_region_null_is_insufficient(self):
        values = query((0.80, 0.03, 0.02, 0.04))
        values.append(
            RegionalQueryDelta(
                region_id="unseen",
                region_type="object",
                delta_raw=0.8,
                quality_score=0.9,
                source_match_score=0.9,
                transform_family="jpeg_q75",
                detector_version="synthetic-detector-v1",
                score_schema="synthetic-delta-v1",
            )
        )
        result = evaluate_regional_fdr(self.profile, values, config=self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertTrue(result.abstained)
        self.assertEqual(result.unsupported_region_ids, ("unseen",))

    def test_quality_and_source_gates_are_fail_closed(self):
        result = evaluate_regional_fdr(
            self.profile,
            query((0.80, 0.03, 0.02, 0.04), quality=0.20),
            config=self.config,
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertTrue(result.abstained)
        result = evaluate_regional_fdr(
            self.profile,
            query((0.80, 0.03, 0.02, 0.04), source_match=0.20),
            config=self.config,
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)

    def test_profile_and_result_digests_are_deterministic(self):
        first = fit_regional_fdr_profile(null_stream(), config=self.config)
        second = fit_regional_fdr_profile(list(reversed(null_stream())), config=self.config)
        self.assertEqual(first.to_dict(), second.to_dict())
        first_result = evaluate_regional_fdr(first, query((0.80, 0.03, 0.02, 0.04)), config=self.config)
        second_result = evaluate_regional_fdr(second, list(reversed(query((0.80, 0.03, 0.02, 0.04)))), config=self.config)
        self.assertEqual(first_result.to_dict(), second_result.to_dict())
        self.assertEqual(len(first.profile_digest), 64)
        self.assertEqual(len(first_result.evidence_digest), 64)

    def test_duplicate_or_mismatched_schema_is_rejected(self):
        values = null_stream()
        with self.assertRaises(ValueError):
            fit_regional_fdr_profile(values + [values[0]], config=self.config)
        bad_query = query((0.80, 0.03, 0.02, 0.04))
        bad_query[0] = RegionalQueryDelta(
            region_id="r0",
            region_type="object",
            delta_raw=0.8,
            quality_score=0.9,
            source_match_score=0.9,
            transform_family="jpeg_q75",
            detector_version="other-detector-v1",
            score_schema="synthetic-delta-v1",
        )
        with self.assertRaises(ValueError):
            evaluate_regional_fdr(self.profile, bad_query, config=self.config)

    def test_config_digest_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_regional_fdr(
                self.profile,
                query((0.80, 0.03, 0.02, 0.04)),
                config=RegionalFDRConfig(minimum_null_count=10, q_value=0.05),
            )

    def test_negative_delta_cannot_be_selected(self):
        result = evaluate_regional_fdr(self.profile, query((-0.8, -0.4, -0.2, -0.1)), config=self.config)
        self.assertEqual(result.route, ROUTE_NULL_CONSISTENT)
        self.assertEqual(result.selected_region_ids, ())


if __name__ == "__main__":
    unittest.main()
