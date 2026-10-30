import unittest

from aigc.open_set_routing import (
    FEATURE_SCHEMA,
    ROUTE_CONFLICT_REVIEW,
    ROUTE_INSUFFICIENT,
    ROUTE_KNOWN_FAMILY,
    ROUTE_OPEN_SET_UNKNOWN,
    ROUTE_REAL_CONSISTENT,
    GeneratorFamilyExample,
    OpenSetQuery,
    OpenSetRoutingConfig,
    evaluate_open_set_route,
    fit_generator_family_profile,
)


class OpenSetRoutingTests(unittest.TestCase):
    def setUp(self):
        self.config = OpenSetRoutingConfig(
            minimum_family_support=3,
            maximum_family_distance=0.12,
            minimum_family_margin=0.02,
        )
        self.real_digest = "a" * 64
        self.real_dataset_digest = "b" * 64
        rows = []
        for index in range(4):
            rows.append(
                GeneratorFamilyExample(
                    sample_id=f"a-{index}",
                    group_id=f"ga-{index}",
                    family_id="family-a",
                    feature=(0.02 * index, 0.01 * index),
                    detector_version="adapter-v1",
                )
            )
            rows.append(
                GeneratorFamilyExample(
                    sample_id=f"b-{index}",
                    group_id=f"gb-{index}",
                    family_id="family-b",
                    feature=(1.0 + 0.02 * index, 1.0 + 0.01 * index),
                    detector_version="adapter-v1",
                )
            )
        self.profile = fit_generator_family_profile(
            rows,
            self.config,
            real_profile_digest=self.real_digest,
            real_calibration_dataset_digest=self.real_dataset_digest,
            real_calibration_support_count=32,
        )

    def query(self, sample_id, feature, p_value=0.01, **kwargs):
        return OpenSetQuery(
            sample_id,
            feature,
            FEATURE_SCHEMA,
            "adapter-v1",
            input_digest="c" * 64,
            real_p_value_raw=p_value,
            real_profile_digest=self.real_digest,
            **kwargs,
        )

    def test_known_family_and_real_rejection_agree(self):
        result = evaluate_open_set_route(self.query("known", (0.03, 0.02)), self.profile, self.config)
        self.assertEqual(result.route, ROUTE_KNOWN_FAMILY)
        self.assertEqual(result.family_id, "family-a")
        self.assertFalse(result.abstained)
        self.assertEqual(len(result.evidence_digest), 64)

    def test_known_family_conflicts_with_real_only(self):
        result = evaluate_open_set_route(
            self.query("conflict", (0.03, 0.02), p_value=0.8), self.profile, self.config
        )
        self.assertEqual(result.route, ROUTE_CONFLICT_REVIEW)
        self.assertEqual(result.reason, "family_and_real_only_stream_conflict")

    def test_far_query_real_consistent(self):
        result = evaluate_open_set_route(
            self.query("real", (0.45, 0.45), p_value=0.8), self.profile, self.config
        )
        self.assertEqual(result.route, ROUTE_REAL_CONSISTENT)
        self.assertTrue(result.abstained is False)

    def test_far_query_is_open_set_unknown_when_real_rejected(self):
        result = evaluate_open_set_route(
            self.query("unknown", (0.45, 0.45), p_value=0.01), self.profile, self.config
        )
        self.assertEqual(result.route, ROUTE_OPEN_SET_UNKNOWN)
        self.assertTrue(result.abstained)

    def test_far_midpoint_is_unknown_instead_of_ambiguous(self):
        result = evaluate_open_set_route(
            self.query("ambiguous", (0.525, 0.525), p_value=0.01), self.profile, self.config
        )
        self.assertEqual(result.route, ROUTE_OPEN_SET_UNKNOWN)
        self.assertEqual(result.reason, "real_rejected_but_no_supported_family")

    def test_missing_real_calibration_fails_closed(self):
        query = OpenSetQuery("missing", (0.02, 0.02), FEATURE_SCHEMA, "adapter-v1")
        result = evaluate_open_set_route(query, self.profile, self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "real_calibration_missing")

    def test_binding_and_quality_fail_closed(self):
        bad_profile_query = self.query("schema", (0.02, 0.02))
        bad_profile_query = OpenSetQuery(
            bad_profile_query.sample_id,
            bad_profile_query.feature,
            "other-schema",
            bad_profile_query.detector_version,
            input_digest="c" * 64,
            real_p_value_raw=bad_profile_query.real_p_value_raw,
            real_profile_digest=self.real_digest,
        )
        self.assertEqual(
            evaluate_open_set_route(bad_profile_query, self.profile, self.config).route,
            ROUTE_INSUFFICIENT,
        )
        low_quality = self.query("low-quality", (0.02, 0.02), quality_score=0.1)
        result = evaluate_open_set_route(low_quality, self.profile, self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "quality_below_gate")

    def test_profile_is_deterministic_under_input_order(self):
        rows = []
        for family, base in (("family-a", 0.0), ("family-b", 1.0)):
            for index in range(4):
                rows.append(
                    GeneratorFamilyExample(
                        f"{family}-{index}", f"g-{family}-{index}", family,
                        (base + 0.02 * index, base + 0.01 * index),
                        detector_version="adapter-v1",
                    )
                )
        first = fit_generator_family_profile(
            rows,
            self.config,
            real_profile_digest=self.real_digest,
            real_calibration_dataset_digest=self.real_dataset_digest,
            real_calibration_support_count=32,
        )
        second = fit_generator_family_profile(
            list(reversed(rows)),
            self.config,
            real_profile_digest=self.real_digest,
            real_calibration_dataset_digest=self.real_dataset_digest,
            real_calibration_support_count=32,
        )
        self.assertEqual(first.profile_digest, second.profile_digest)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_group_cannot_span_families(self):
        rows = [
            GeneratorFamilyExample("one", "same", "family-a", (0.0, 0.0), detector_version="adapter-v1"),
            GeneratorFamilyExample("two", "same", "family-b", (1.0, 1.0), detector_version="adapter-v1"),
        ]
        with self.assertRaises(ValueError):
            fit_generator_family_profile(rows, self.config, real_profile_digest=self.real_digest)

    def test_real_profile_binding_mismatch(self):
        query = OpenSetQuery(
            "wrong-real-profile",
            (0.02, 0.02),
            FEATURE_SCHEMA,
            "adapter-v1",
            real_p_value_raw=0.01,
            input_digest="c" * 64,
            real_profile_digest="b" * 64,
        )
        result = evaluate_open_set_route(query, self.profile, self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "real_profile_binding_mismatch")

    def test_config_and_profile_integrity_are_bound(self):
        mismatch = OpenSetRoutingConfig(
            minimum_family_support=3,
            maximum_family_distance=0.2,
            minimum_family_margin=0.02,
        )
        result = evaluate_open_set_route(self.query("config", (0.03, 0.02)), self.profile, mismatch)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "config_binding_mismatch")

        from dataclasses import replace

        tampered = replace(self.profile, detector_version="tampered-adapter")
        result = evaluate_open_set_route(self.query("tampered", (0.03, 0.02)), tampered, self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "profile_integrity_mismatch")

    def test_single_family_has_no_invented_margin_and_unknown_hides_nearest_family(self):
        one_family_rows = [
            GeneratorFamilyExample(
                f"single-{index}", f"single-group-{index}", "family-a",
                (0.01 * index, 0.01 * index), detector_version="adapter-v1"
            )
            for index in range(4)
        ]
        profile = fit_generator_family_profile(
            one_family_rows,
            self.config,
            real_profile_digest=self.real_digest,
            real_calibration_dataset_digest=self.real_dataset_digest,
            real_calibration_support_count=32,
        )
        result = evaluate_open_set_route(self.query("single", (0.03, 0.03)), profile, self.config)
        self.assertIsNone(result.family_margin_raw)
        unknown = evaluate_open_set_route(self.query("far", (0.8, 0.8)), profile, self.config)
        self.assertEqual(unknown.route, ROUTE_OPEN_SET_UNKNOWN)
        self.assertIsNone(unknown.family_id)


if __name__ == "__main__":
    unittest.main()
