import unittest
from dataclasses import replace
from hashlib import sha256

from aigc.reference_specificity import (
    ROUTE_INSUFFICIENT,
    ROUTE_REFERENCE_AMBIGUOUS,
    ROUTE_REFERENCE_NULL_CONSISTENT,
    ROUTE_REFERENCE_SPECIFIC,
    ReferenceSpecificityBatch,
    ReferenceSpecificityConfig,
    ReferenceSpecificityObservation,
    evaluate_reference_specificity,
)


HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
HEX_D = "d" * 64
HEX_E = "e" * 64
HEX_F = "f" * 64
HEX_G = "1" * 64
HEX_H = "2" * 64


class ReferenceSpecificityTests(unittest.TestCase):
    def observation(self, observation_id, reference_digest, role, contrast):
        return ReferenceSpecificityObservation(
            observation_id=observation_id,
            reference_digest=reference_digest,
            role=role,
            contrast_raw=contrast,
            quality_score=0.90,
            source_match_score=0.85,
            quality_bucket="high",
            source_match_bucket="matched",
        )

    def batch(self, candidate=0.80, decoys=None):
        if decoys is None:
            # With a ties-inclusive finite-sample p-value, three decoys cannot
            # reach alpha=0.05.  Keep the default candidate case large enough
            # to exercise the specific route while small explicit fixtures
            # continue to cover ambiguous/null/support gates.
            decoys = (0.10, 0.15, 0.20) + (0.20,) * 21
        decoy_refs = tuple(
            sha256(f"reference-specificity-decoy-{index}".encode("utf-8")).hexdigest()
            for index in range(len(decoys))
        )
        decoy_rows = tuple(
            self.observation(f"decoy-{index}", decoy_refs[index], "decoy", value)
            for index, value in enumerate(decoys)
        )
        return ReferenceSpecificityBatch(
            query_digest=HEX_A,
            evaluation_split_digest=HEX_B,
            selection_split_digest=HEX_H,
            manifest_digest=HEX_C,
            canonical_frame_digest=HEX_D,
            transform_spec_digest=HEX_E,
            operator_digest=HEX_F,
            detector_version="detector-v1",
            score_schema="contrast-v1",
            quality_bucket="high",
            source_match_bucket="matched",
            selection_policy_digest=HEX_G,
            candidate=self.observation("candidate", HEX_B, "candidate", candidate),
            decoys=decoy_rows,
        )

    def test_candidate_requires_specificity_against_blind_decoys(self):
        result = evaluate_reference_specificity(self.batch())
        self.assertEqual(result.route, ROUTE_REFERENCE_SPECIFIC)
        self.assertTrue(result.candidate_supported)
        self.assertFalse(result.abstained)
        self.assertEqual(result.decoy_count, 24)
        self.assertGreater(result.specificity_gap_raw, 0.5)
        self.assertLess(result.decoy_exceedance_p_value_raw, 0.05)

    def test_similar_decoys_route_to_ambiguous_review(self):
        result = evaluate_reference_specificity(self.batch(candidate=0.80, decoys=(0.72, 0.76, 0.78)))
        self.assertEqual(result.route, ROUTE_REFERENCE_AMBIGUOUS)
        self.assertTrue(result.abstained)
        self.assertFalse(result.candidate_supported)
        self.assertIn("not_specific", result.reason)

    def test_specificity_gap_uses_difference_range(self):
        result = evaluate_reference_specificity(self.batch(candidate=2.0, decoys=(-2.0, -2.0, -2.0)))
        self.assertEqual(result.route, ROUTE_REFERENCE_AMBIGUOUS)
        self.assertEqual(result.specificity_gap_raw, 4.0)

    def test_low_candidate_is_null_consistent(self):
        result = evaluate_reference_specificity(self.batch(candidate=0.01, decoys=(0.02, 0.03, 0.04)))
        self.assertEqual(result.route, ROUTE_REFERENCE_NULL_CONSISTENT)
        self.assertFalse(result.abstained)
        self.assertFalse(result.candidate_supported)

    def test_split_leakage_is_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            replace(self.batch(), selection_split_digest=HEX_B)

    def test_quality_bucket_mismatch_fails_closed(self):
        changed = replace(self.batch().decoys[0], quality_bucket="medium")
        batch = replace(self.batch(), decoys=(changed, *self.batch().decoys[1:]))
        result = evaluate_reference_specificity(batch)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertTrue(result.abstained)
        self.assertIsNone(result.specificity_gap_raw)

    def test_source_match_bucket_mismatch_fails_closed(self):
        changed = replace(self.batch().decoys[0], source_match_bucket="weak")
        batch = replace(self.batch(), decoys=(changed, *self.batch().decoys[1:]))
        result = evaluate_reference_specificity(batch)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "source_match_bucket_mismatch")

    def test_duplicate_decoy_identity_is_rejected(self):
        first = self.batch().decoys[0]
        with self.assertRaises(ValueError):
            replace(self.batch(), decoys=(first, replace(first, contrast_raw=0.2), self.batch().decoys[2]))

    def test_candidate_reference_cannot_be_a_decoy(self):
        candidate = self.batch().candidate
        with self.assertRaises(ValueError):
            replace(self.batch(), decoys=(replace(self.batch().decoys[0], reference_digest=candidate.reference_digest), *self.batch().decoys[1:]))

    def test_minimum_decoy_support_is_fail_closed(self):
        batch = self.batch(decoys=(0.10, 0.15))
        result = evaluate_reference_specificity(batch)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "decoy_sample_insufficient")

    def test_result_is_order_invariant_and_digest_stable(self):
        batch = self.batch()
        result_a = evaluate_reference_specificity(batch)
        result_b = evaluate_reference_specificity(replace(batch, decoys=tuple(reversed(batch.decoys))))
        self.assertEqual(result_a.to_dict(), result_b.to_dict())
        self.assertEqual(result_a.evidence_digest, result_b.evidence_digest)

    def test_raw_result_does_not_smuggle_probability(self):
        result = evaluate_reference_specificity(self.batch())
        payload = result.to_dict()
        self.assertNotIn("probability", payload)
        self.assertNotIn("aigc_probability", payload)
        self.assertIn("decoy_exceedance_p_value_raw", payload)

    def test_nonfinite_contrast_is_rejected(self):
        with self.assertRaises(ValueError):
            self.observation("bad", HEX_C, "decoy", float("nan"))


if __name__ == "__main__":
    unittest.main()
