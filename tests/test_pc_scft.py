import unittest

from aigc.paired_delta_calibration import (
    PairedDeltaCalibrationConfig,
    PairedDeltaGroup,
    fit_paired_delta_profile,
)
from aigc.patch_coverage import (
    STATUS_GLOBAL,
    PatchCoverageConfig,
    PatchDelta,
    summarize_patch_coverage,
)
from aigc.pc_scft import (
    STATUS_CANDIDATE,
    STATUS_INSUFFICIENT,
    STATUS_NULL_CONSISTENT,
    STATUS_REVIEW,
    PCSCFTConfig,
    decide_pc_scft,
)
from aigc.regional_counterfactual import (
    RegionalCounterfactualConfig,
    RegionalObservation,
    fuse_regional_counterfactual,
)


DETECTOR = "source-residual-v1"
SCHEMA = "source-residual-score-v1"


def _group(group_id, deltas, *, family="identity", quality=0.9):
    return PairedDeltaGroup(
        group_id=group_id,
        transform_family=family,
        quality_score=quality,
        region_deltas=tuple(deltas),
        detector_version=DETECTOR,
        score_schema=SCHEMA,
    )


def _calibration(*, query_deltas=(0.8, 0.7), family="identity", quality=0.9, alpha=0.2):
    null_groups = [
        _group(f"null-{index}", (0.01 + index * 0.002, 0.0))
        for index in range(6)
    ]
    profile = fit_paired_delta_profile(
        null_groups,
        config=PairedDeltaCalibrationConfig(
            minimum_stratum_count=3,
            alpha=alpha,
            allow_family_fallback=False,
            allow_global_fallback=False,
        ),
    )
    return profile.evaluate(_group("query", query_deltas, family=family, quality=quality))


def _family_fallback_calibration():
    null_groups = [_group(f"null-{index}", (0.01, 0.0)) for index in range(6)]
    profile = fit_paired_delta_profile(
        null_groups,
        config=PairedDeltaCalibrationConfig(
            minimum_stratum_count=3,
            alpha=0.2,
            allow_family_fallback=True,
            allow_global_fallback=False,
        ),
    )
    return profile.evaluate(_group("query-fallback", (0.8,), family="identity", quality=0.2))


def _regional(*, delta=0.7, quality=0.9, source_match=0.9):
    observations = []
    for index, family in enumerate(("identity", "jpeg_q75", "resize_075")):
        for region_id, observed, counterfactual in (
            ("edited", 0.80 if delta > 0.1 else 0.12, 0.10),
            ("scene", 0.12, 0.10),
        ):
            observations.extend(
                [
                    RegionalObservation(
                        asset_id="asset-1",
                        pair_id=f"pair-{index}",
                        region_id=region_id,
                        version_id=f"observed-{index}-{region_id}",
                        transform_family=family,
                        score_raw=observed,
                        quality_score=quality,
                        source_match_score=source_match,
                        kind="observed",
                        detector_version=DETECTOR,
                        score_schema=SCHEMA,
                    ),
                    RegionalObservation(
                        asset_id="asset-1",
                        pair_id=f"pair-{index}",
                        region_id=region_id,
                        version_id=f"counterfactual-{index}-{region_id}",
                        transform_family=family,
                        score_raw=counterfactual,
                        quality_score=quality,
                        source_match_score=source_match,
                        kind="counterfactual",
                        detector_version=DETECTOR,
                        score_schema=SCHEMA,
                    ),
                ]
            )
    return fuse_regional_counterfactual(
        observations,
        config=RegionalCounterfactualConfig(
            minimum_pairs=2,
            minimum_region_views=2,
            minimum_coverage=0.75,
            minimum_quality=0.35,
            minimum_source_match=0.60,
        ),
    )


def _coverage(values=(0.45, 0.42, 0.48, 0.44), *, ambiguous=False):
    if ambiguous:
        values = (0.80, 0.80, 0.02, 0.02)
    types = ("object", "stuff", "background", "object")
    return summarize_patch_coverage(
        [
            PatchDelta(
                region_id=f"r{index}",
                delta_raw=value,
                quality_score=0.9,
                source_match_score=0.9,
                detector_version=DETECTOR,
                score_schema=SCHEMA,
                region_type=types[index],
            )
            for index, value in enumerate(values)
        ],
        config=PatchCoverageConfig(require_region_type_diversity=True),
    )


class PCSCFTDecisionTests(unittest.TestCase):
    def test_null_rejection_and_distributed_shape_make_candidate_route(self):
        regional = _regional()
        calibration = _calibration()
        coverage = _coverage()
        self.assertEqual(coverage.status, STATUS_GLOBAL)
        result = decide_pc_scft(regional, calibration, coverage)
        self.assertEqual(result.status, STATUS_CANDIDATE)
        self.assertTrue(result.candidate_supported)
        self.assertFalse(result.abstained)
        self.assertEqual(result.route, "global_forensic_review")
        self.assertTrue(result.null_rejected)
        self.assertEqual(len(result.evidence_digest), 64)

    def test_null_consistent_never_becomes_human_or_candidate(self):
        result = decide_pc_scft(
            _regional(delta=0.0),
            _calibration(query_deltas=(0.02, 0.01)),
            _coverage(),
        )
        self.assertEqual(result.status, STATUS_NULL_CONSISTENT)
        self.assertFalse(result.candidate_supported)
        self.assertFalse(result.null_rejected)
        self.assertNotIn("human", result.to_dict())
        self.assertNotIn("ai_generated", result.to_dict())

    def test_ambiguous_shape_requires_manual_review_after_null_rejection(self):
        result = decide_pc_scft(
            _regional(),
            _calibration(),
            _coverage(ambiguous=True),
        )
        self.assertEqual(result.status, STATUS_REVIEW)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "patch_shape:mixed_patch_coverage")

    def test_unavailable_calibration_is_insufficient(self):
        regional = _regional()
        null_groups = [_group(f"small-{index}", (0.01,)) for index in range(2)]
        profile = fit_paired_delta_profile(
            null_groups,
            config=PairedDeltaCalibrationConfig(
                minimum_stratum_count=3,
                alpha=0.2,
                allow_family_fallback=False,
                allow_global_fallback=False,
            ),
        )
        calibration = profile.evaluate(_group("query", (0.8,), family="new_engine"))
        result = decide_pc_scft(regional, calibration, _coverage())
        self.assertEqual(result.status, STATUS_INSUFFICIENT)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "calibration_unavailable")

    def test_fallback_is_explicitly_rejected_by_strict_default(self):
        calibration = _family_fallback_calibration()
        result = decide_pc_scft(_regional(), calibration, _coverage())
        self.assertEqual(result.status, STATUS_INSUFFICIENT)
        self.assertEqual(result.reason, "calibration_fallback_not_allowed")

    def test_identity_conflict_cannot_be_fused(self):
        calibration = _calibration()
        wrong = _coverage()
        wrong_patch = PatchDelta(
            region_id="wrong",
            delta_raw=0.4,
            quality_score=0.9,
            source_match_score=0.9,
            detector_version="other-detector",
            score_schema=SCHEMA,
        )
        wrong = summarize_patch_coverage(
            [wrong_patch, PatchDelta("r1", 0.4, 0.9, 0.9, detector_version="other-detector", score_schema=SCHEMA)],
        )
        with self.assertRaises(ValueError):
            decide_pc_scft(_regional(), calibration, wrong)


if __name__ == "__main__":
    unittest.main()
