import unittest
from dataclasses import replace
from hashlib import sha256

from aigc.selection_aware_calibration import (
    OPERATION_ORDINARY_PROPAGATION,
    ROUTE_INSUFFICIENT,
    ROUTE_NULL_CONSISTENT,
    ROUTE_SELECTION_AMBIGUOUS,
    ROUTE_SELECTION_SPECIFIC,
    SelectionAwareBatch,
    SelectionAwareCalibrationConfig,
    SelectionCalibrationGroup,
    evaluate_selection_aware_calibration,
)


HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
HEX_D = "d" * 64
HEX_E = "e" * 64
HEX_F = "f" * 64
HEX_G = "1" * 64
HEX_H = "2" * 64
HEX_I = "3" * 64
HEX_J = "4" * 64
HEX_K = "5" * 64


class SelectionAwareCalibrationTests(unittest.TestCase):
    def batch(self, *, candidate=0.80, invariant_route="invariant_candidate", operation_scope="content_edit", query_group_id="query-0", quality=0.90, source_match=0.90, decoys=None):
        if decoys is None:
            decoys = (0.10, 0.15, 0.20) + (0.20,) * 21
        refs = tuple(sha256(f"saec-decoy-{index}".encode()).hexdigest() for index in range(len(decoys)))
        return SelectionAwareBatch(
            query_digest=HEX_A,
            query_group_id=query_group_id,
            candidate_reference_digest=HEX_B,
            candidate_contrast_raw=candidate,
            decoy_reference_digests=refs,
            decoy_contrasts_raw=tuple(decoys),
            candidate_quality_score=quality,
            candidate_source_match_raw=source_match,
            invariant_route=invariant_route,
            manifest_digest=HEX_C,
            canonical_frame_digest=HEX_D,
            transform_family="jpeg",
            quality_bucket="high",
            source_match_bucket="matched",
            detector_version="detector-v1",
            score_schema="contrast-v1",
            operator_set_digest=HEX_E,
            selection_policy_digest=HEX_F,
            selection_split_digest=HEX_G,
            calibration_split_digest=HEX_H,
            evaluation_split_digest=HEX_I,
            calibration_dataset_digest=HEX_J,
            profile_level="exact",
            null_profile_digest=HEX_K,
            operation_scope=operation_scope,
        )

    def groups(self, *, values=None, query_group_id=None, decoy_count=24):
        values = values if values is not None else [0.01] * 20
        result = []
        for index, value in enumerate(values):
            group_id = f"g-{index}"
            if query_group_id is not None and index == 0:
                group_id = query_group_id
            result.append(
                SelectionCalibrationGroup(
                    group_id=group_id,
                    max_statistic_raw=value,
                    decoy_count=decoy_count,
                    calibration_dataset_digest=HEX_J,
                    calibration_split_digest=HEX_H,
                    selection_policy_digest=HEX_F,
                    profile_level="exact",
                    null_profile_digest=HEX_K,
                    manifest_digest=sha256(f"saec-manifest-{index}".encode()).hexdigest(),
                    detector_version="detector-v1",
                    score_schema="contrast-v1",
                    operator_set_digest=HEX_E,
                    transform_family="jpeg",
                    quality_bucket="high",
                    source_match_bucket="matched",
                )
            )
        return tuple(result)

    def test_selection_specific_candidate(self):
        result = evaluate_selection_aware_calibration(self.batch(), self.groups())
        self.assertEqual(result.route, ROUTE_SELECTION_SPECIFIC)
        self.assertTrue(result.candidate_supported)
        self.assertFalse(result.abstained)
        self.assertAlmostEqual(result.selection_p_value_raw, 1.0 / 21.0)
        self.assertGreater(result.specificity_gap_raw, 0.5)

    def test_calibration_max_tie_is_ambiguous(self):
        result = evaluate_selection_aware_calibration(self.batch(), self.groups(values=[0.80] + [0.01] * 19))
        self.assertEqual(result.route, ROUTE_SELECTION_AMBIGUOUS)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "selection_p_value_not_supported")

    def test_decoy_tie_is_ambiguous(self):
        result = evaluate_selection_aware_calibration(self.batch(decoys=(0.80,) * 24), self.groups())
        self.assertEqual(result.route, ROUTE_SELECTION_AMBIGUOUS)
        self.assertEqual(result.reason, "decoy_gap_below_threshold")

    def test_ordinary_propagation_routes_null(self):
        batch = self.batch(operation_scope=OPERATION_ORDINARY_PROPAGATION)
        result = evaluate_selection_aware_calibration(batch, ())
        self.assertEqual(result.route, ROUTE_NULL_CONSISTENT)
        self.assertEqual(result.reason, "ordinary_propagation_scope")

    def test_low_candidate_contrast_routes_null(self):
        result = evaluate_selection_aware_calibration(self.batch(candidate=0.01), self.groups())
        self.assertEqual(result.route, ROUTE_NULL_CONSISTENT)
        self.assertEqual(result.reason, "candidate_contrast_below_threshold")

    def test_invariant_route_must_be_stable(self):
        result = evaluate_selection_aware_calibration(self.batch(invariant_route="view_operator_inconsistent"), self.groups())
        self.assertEqual(result.route, ROUTE_SELECTION_AMBIGUOUS)
        self.assertEqual(result.reason, "invariant_route_not_candidate")

    def test_calibration_support_is_fail_closed(self):
        result = evaluate_selection_aware_calibration(self.batch(), self.groups(values=[0.01] * 19))
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "calibration_group_support_insufficient")

    def test_split_leakage_is_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            replace(self.batch(), calibration_split_digest=HEX_G)

    def test_query_group_cannot_be_calibration_group(self):
        result = evaluate_selection_aware_calibration(self.batch(), self.groups(query_group_id="query-0"))
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "query_group_leaks_into_calibration")

    def test_group_binding_mismatch_fails_closed(self):
        changed = replace(self.groups()[0], transform_family="resize")
        result = evaluate_selection_aware_calibration(self.batch(), (changed, *self.groups()[1:]))
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "calibration_transform_family_mismatch")

    def test_profile_level_mismatch_fails_closed(self):
        config = SelectionAwareCalibrationConfig(profile_level="global")
        result = evaluate_selection_aware_calibration(self.batch(), self.groups(), config=config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "profile_level_mismatch")

    def test_quality_gate_fails_closed(self):
        result = evaluate_selection_aware_calibration(self.batch(quality=0.20), self.groups())
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "candidate_quality_below_threshold")

    def test_duplicate_group_id_fails_closed(self):
        groups = self.groups()
        duplicate = replace(groups[1], group_id=groups[0].group_id)
        result = evaluate_selection_aware_calibration(self.batch(), (groups[0], duplicate, *groups[2:]))
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "duplicate_calibration_group_id")

    def test_order_invariant_and_digest_stable(self):
        batch = self.batch()
        groups = self.groups(values=[0.01 + index * 0.001 for index in range(20)])
        result_a = evaluate_selection_aware_calibration(batch, groups)
        result_b = evaluate_selection_aware_calibration(replace(batch, decoy_reference_digests=tuple(reversed(batch.decoy_reference_digests)), decoy_contrasts_raw=tuple(reversed(batch.decoy_contrasts_raw))), tuple(reversed(groups)))
        self.assertEqual(result_a.to_dict(), result_b.to_dict())
        self.assertEqual(result_a.evidence_digest, result_b.evidence_digest)

    def test_result_has_no_probability_or_legal_fields(self):
        payload = evaluate_selection_aware_calibration(self.batch(), self.groups()).to_dict()
        for forbidden in ("probability", "confidence", "human_supported", "ai_generated_supported", "author_identity", "copyright"):
            self.assertNotIn(forbidden, payload)
        self.assertIn("selection_p_value_raw", payload)


if __name__ == "__main__":
    unittest.main()
