import unittest

from aigc.patch_contribution import (
    STATUS_AMBIGUOUS_AUDIT,
    STATUS_DISTRACTION_SENSITIVE,
    STATUS_INSUFFICIENT,
    STATUS_STABLE,
    PatchContributionConfig,
    audit_patch_contributions,
)
from aigc.patch_coverage import PatchCoverageConfig, PatchDelta


def patch(region_id, delta, *, quality=0.9, source_match=0.9, detector="detector-v1", schema="delta-v1"):
    return PatchDelta(
        region_id=region_id,
        delta_raw=delta,
        quality_score=quality,
        source_match_score=source_match,
        detector_version=detector,
        score_schema=schema,
    )


class PatchContributionTests(unittest.TestCase):
    def test_distributed_evidence_survives_top_patch_mask_out(self):
        result = audit_patch_contributions([patch(f"r{i}", value) for i, value in enumerate((0.45, 0.42, 0.48, 0.44))])
        self.assertEqual(result.status, STATUS_STABLE)
        self.assertFalse(result.abstained)
        self.assertEqual(result.top_k_removed_region_ids, ("r2",))
        self.assertGreater(result.retained_mass_after_top_k_raw, 0.5)
        self.assertFalse(result.route_flip_after_top_k)
        self.assertEqual(len(result.entries), 4)

    def test_global_single_patch_dominance_is_distraction_sensitive(self):
        result = audit_patch_contributions(
            [patch("r0", 0.95), patch("r1", 0.30), patch("r2", 0.30), patch("r3", 0.30)],
            config=PatchContributionConfig(maximum_global_dominance=0.50),
        )
        self.assertEqual(result.status, STATUS_DISTRACTION_SENSITIVE)
        self.assertTrue(result.abstained)
        self.assertEqual(result.top_k_removed_region_ids, ("r0",))
        self.assertLess(result.retained_mass_after_top_k_raw, 0.5)

    def test_localized_baseline_keeps_review_route_but_records_collapse(self):
        result = audit_patch_contributions(
            [patch("r0", 0.82), patch("r1", 0.02), patch("r2", 0.01), patch("r3", 0.01)]
        )
        self.assertEqual(result.baseline_status, "localized_like")
        self.assertEqual(result.status, STATUS_STABLE)
        self.assertEqual(result.top_k_removed_region_ids, ("r0",))
        self.assertEqual(result.retained_mass_after_top_k_raw, 0.0)

    def test_ambiguous_baseline_stays_conservative(self):
        result = audit_patch_contributions(
            [patch("r0", 0.80), patch("r1", 0.80), patch("r2", 0.02), patch("r3", 0.02)]
        )
        self.assertEqual(result.status, STATUS_AMBIGUOUS_AUDIT)
        self.assertTrue(result.abstained)

    def test_quality_gate_and_no_positive_fail_closed(self):
        low_quality = audit_patch_contributions(
            [patch("r0", 0.8, quality=0.2), patch("r1", 0.8, quality=0.2)]
        )
        self.assertEqual(low_quality.status, STATUS_INSUFFICIENT)
        self.assertEqual(low_quality.reason, "insufficient_accepted_patches")
        no_positive = audit_patch_contributions([patch("r0", 0.01), patch("r1", -0.2)])
        self.assertEqual(no_positive.status, STATUS_INSUFFICIENT)
        self.assertEqual(no_positive.reason, "no_positive_delta")

    def test_digest_and_schema_boundaries_are_deterministic(self):
        items = [patch("r0", 0.45), patch("r1", 0.46), patch("r2", 0.47)]
        first = audit_patch_contributions(items)
        second = audit_patch_contributions(list(reversed(items)))
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(len(first.config_digest), 64)
        self.assertEqual(len(first.evidence_digest), 64)
        with self.assertRaises(ValueError):
            audit_patch_contributions(items + [patch("r0", 0.2)])
        with self.assertRaises(ValueError):
            audit_patch_contributions(items + [patch("r3", 0.2, schema="other")])
        with self.assertRaises(ValueError):
            PatchContributionConfig(top_k=0)

    def test_custom_coverage_gate_is_bound_into_digest(self):
        items = [patch("r0", 0.45), patch("r1", 0.46), patch("r2", 0.47)]
        first = audit_patch_contributions(items)
        second = audit_patch_contributions(items, coverage_config=PatchCoverageConfig(delta_threshold=0.40))
        self.assertNotEqual(first.evidence_digest, second.evidence_digest)


if __name__ == "__main__":
    unittest.main()
