import math
import unittest

from aigc.patch_coverage import (
    STATUS_ABSTAINED,
    STATUS_AMBIGUOUS,
    STATUS_GLOBAL,
    STATUS_LOCAL,
    PatchCoverageConfig,
    PatchDelta,
    summarize_patch_coverage,
)


def patch(
    region_id,
    delta,
    *,
    quality=0.9,
    source_match=0.9,
    detector="detector-v1",
    schema="delta-v1",
    region_type="unknown",
):
    return PatchDelta(
        region_id=region_id,
        delta_raw=delta,
        quality_score=quality,
        source_match_score=source_match,
        detector_version=detector,
        score_schema=schema,
        region_type=region_type,
    )


class PatchCoverageTests(unittest.TestCase):
    def test_distributed_evidence_is_global_like(self):
        result = summarize_patch_coverage([patch(str(index), 0.45) for index in range(4)])
        self.assertEqual(result.status, STATUS_GLOBAL)
        self.assertFalse(result.abstained)
        self.assertAlmostEqual(result.coverage_raw, 1.0)
        self.assertAlmostEqual(result.effective_patch_ratio_raw, 1.0)
        self.assertEqual(result.route, "global_forensic_review")

    def test_concentrated_evidence_is_localized_like(self):
        result = summarize_patch_coverage(
            [patch("r0", 0.8), patch("r1", 0.02), patch("r2", 0.01), patch("r3", 0.01)]
        )
        self.assertEqual(result.status, STATUS_LOCAL)
        self.assertEqual(result.positive_region_ids, ("r0",))
        self.assertEqual(result.route, "local_roi_review")
        self.assertGreater(result.concentration_raw, 0.9)

    def test_mixed_coverage_abstains_for_manual_review(self):
        result = summarize_patch_coverage(
            [patch("r0", 0.8), patch("r1", 0.8), patch("r2", 0.02), patch("r3", 0.02)]
        )
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "mixed_patch_coverage")
        self.assertEqual(result.route, "manual_review")

    def test_quality_and_source_gates_are_explicit(self):
        result = summarize_patch_coverage(
            [
                patch("r0", 0.8, quality=0.2),
                patch("r1", 0.8, source_match=0.2),
                patch("r2", 0.1),
            ]
        )
        self.assertEqual(result.status, STATUS_ABSTAINED)
        self.assertEqual(result.reason, "insufficient_accepted_patches")
        self.assertEqual(result.rejected_region_ids, ("r0", "r1"))

    def test_no_positive_delta_does_not_become_human(self):
        result = summarize_patch_coverage([patch("r0", -0.2), patch("r1", 0.1)])
        self.assertEqual(result.status, STATUS_ABSTAINED)
        self.assertEqual(result.reason, "no_positive_delta")
        self.assertEqual(result.coverage_raw, 0.0)

    def test_digest_is_deterministic_and_boundaries_are_rejected(self):
        items = [patch("r0", 0.3), patch("r1", 0.3)]
        first = summarize_patch_coverage(items)
        second = summarize_patch_coverage(list(reversed(items)))
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(len(first.evidence_digest), 64)
        with self.assertRaises(ValueError):
            PatchDelta("bad", math.nan, 0.9, 0.9)
        with self.assertRaises(ValueError):
            summarize_patch_coverage(items + [patch("r0", 0.2)])
        with self.assertRaises(ValueError):
            summarize_patch_coverage([patch("r0", 0.2), patch("r1", 0.2, schema="other")])
        with self.assertRaises(ValueError):
            PatchCoverageConfig(maximum_local_coverage=0.8, minimum_global_coverage=0.7)

    def test_region_type_coverage_is_audited(self):
        result = summarize_patch_coverage(
            [
                patch("object", 0.45, region_type="object"),
                patch("stuff", 0.42, region_type="stuff"),
                patch("background", 0.48, region_type="background"),
            ]
        )
        self.assertEqual(result.status, STATUS_GLOBAL)
        self.assertEqual(result.positive_region_types, ("background", "object", "stuff"))
        self.assertEqual(result.active_region_type_count, 3)
        self.assertEqual(result.region_type_count, 3)
        self.assertAlmostEqual(result.balanced_coverage_raw, 1.0)
        self.assertEqual(
            dict(result.coverage_by_region_type),
            {"background": 1.0, "object": 1.0, "stuff": 1.0},
        )

    def test_strict_region_type_gate_rejects_object_only_global_shortcut(self):
        result = summarize_patch_coverage(
            [patch(f"object-{index}", 0.45, region_type="object") for index in range(4)],
            config=PatchCoverageConfig(require_region_type_diversity=True),
        )
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "insufficient_region_type_support")
        self.assertEqual(result.route, "manual_review")

    def test_unknown_region_type_is_conservative_when_strict(self):
        result = summarize_patch_coverage(
            [
                patch("object", 0.45, region_type="object"),
                patch("unknown", 0.45, region_type="unknown"),
                patch("stuff", 0.45, region_type="stuff"),
                patch("background", 0.45, region_type="background"),
            ],
            config=PatchCoverageConfig(require_region_type_diversity=True),
        )
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertEqual(result.reason, "insufficient_region_type_support")


if __name__ == "__main__":
    unittest.main()
