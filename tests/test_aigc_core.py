import hashlib
import math
from pathlib import Path
import tempfile
import unittest

from aigc.fusion import CalibrationProfile, FusionPolicy, fuse_signals
from aigc.compliance import ComplianceLabel, WatermarkSignal, classify_compliance
from aigc.forensic_features import (
    ResidualConfig,
    compare_aligned_regions,
    extract_residual_roi,
)
from aigc.manifest import validate_manifest
from aigc.provenance import inspect_file
from aigc.schema import AIGCResult, AIGCStatus, DetectorSignals
from aigc.source_conditioned import RegionPair, aggregate_region_pairs


class AIGCCoreTests(unittest.TestCase):
    def make_file(self, data: bytes):
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.write(data)
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return handle.name

    def calibrated_policy(self):
        return FusionPolicy(
            calibration=CalibrationProfile(
                calibration_id="calibration-test-v1",
                detector_version="detector-test-v1",
                score_schema="aigc-score-v1",
                dataset_digest="a" * 64,
            )
        )

    def calibrated_signals(self, **kwargs):
        return DetectorSignals(
            **kwargs,
            model_available=True,
            detector_version="detector-test-v1",
            score_schema="aigc-score-v1",
            scores_calibrated=True,
        )

    def test_file_hash_and_weak_metadata_do_not_prove_ai(self):
        path = self.make_file(b"PNG parameters Steps: 20, Sampler: Euler")
        report = inspect_file(path)
        expected = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        self.assertEqual(report.content_sha256, expected)
        self.assertEqual(report.c2pa_status, "missing")
        self.assertTrue(any(item.type == "metadata_weak" for item in report.evidence))

        result = fuse_signals(
            report,
            DetectorSignals(model_available=False),
            self.calibrated_policy(),
        )
        self.assertEqual(result.status, AIGCStatus.UNKNOWN)
        self.assertEqual(result.unknown_reason, "model_unavailable")

    def test_verified_manifest_can_support_ai_without_model(self):
        path = self.make_file(b"verified source")
        report = inspect_file(
            path,
            manifest={"ai_disclosure": True, "provider": "test-provider"},
            manifest_verification="valid",
            manifest_verifier_id="test-verifier-v1",
            manifest_binding_ok=True,
        )
        self.assertEqual(report.c2pa_status, "valid")
        result = fuse_signals(
            report,
            DetectorSignals(model_available=False),
            self.calibrated_policy(),
        )
        self.assertEqual(result.status, AIGCStatus.AI_GENERATED_SUPPORTED)
        self.assertIsNone(result.confidence)

        visual_conflict = fuse_signals(
            report,
            self.calibrated_signals(ai_score=0.05, artifact_score=0.10),
            self.calibrated_policy(),
        )
        self.assertEqual(visual_conflict.status, AIGCStatus.UNKNOWN)
        self.assertEqual(visual_conflict.unknown_reason, "conflicting_evidence")

    def test_manifest_without_trusted_verifier_is_unverified(self):
        path = self.make_file(b"unverified manifest")
        report = inspect_file(
            path,
            manifest={"ai_disclosure": True},
            manifest_verification="valid",
        )
        self.assertEqual(report.c2pa_status, "unverified")
        self.assertIn("missing_verifier_or_binding", report.errors)
        result = fuse_signals(
            report,
            DetectorSignals(model_available=False),
            self.calibrated_policy(),
        )
        self.assertEqual(result.status, AIGCStatus.UNKNOWN)
        self.assertEqual(result.unknown_reason, "provenance_error")

    def test_file_manifest_defaults_to_unverified(self):
        path = self.make_file(b"manifest without verifier")
        report = inspect_file(path, manifest={"ai_disclosure": True})
        self.assertEqual(report.c2pa_status, "unverified")
        self.assertIn("manifest_verification_missing", report.errors)

    def test_model_scores_require_calibration_and_support_unknown(self):
        path = self.make_file(b"ordinary image bytes")
        report = inspect_file(path)
        uncalibrated = fuse_signals(
            report,
            DetectorSignals(
                ai_score=0.95,
                model_available=True,
                detector_version="detector-test-v1",
            ),
            FusionPolicy(),
        )
        self.assertEqual(uncalibrated.status, AIGCStatus.UNKNOWN)
        self.assertEqual(uncalibrated.unknown_reason, "uncalibrated_model")

        high = fuse_signals(
            report,
            self.calibrated_signals(
                ai_score=0.95,
                artifact_score=0.90,
            ),
            self.calibrated_policy(),
        )
        self.assertEqual(high.status, AIGCStatus.AI_GENERATED_SUPPORTED)

        low = fuse_signals(
            report,
            self.calibrated_signals(
                ai_score=0.05,
                artifact_score=0.10,
            ),
            self.calibrated_policy(),
        )
        self.assertEqual(low.status, AIGCStatus.UNKNOWN)
        self.assertEqual(low.unknown_reason, "insufficient_negative_evidence")

    def test_source_conditioned_edit_requires_match_and_calibration(self):
        path = self.make_file(b"ordinary image bytes")
        report = inspect_file(path)
        result = fuse_signals(
            report,
            self.calibrated_signals(
                source_match_score=0.92,
                source_conditioned_edit_score=0.91,
                quality_score=0.95,
            ),
            self.calibrated_policy(),
            regions=({"region_id": "top_left", "score_raw": 0.91},),
        )
        self.assertEqual(result.status, AIGCStatus.AI_EDITED_SUPPORTED)
        self.assertEqual(result.to_dict()["regions"][0]["region_id"], "top_left")

    def test_source_conditioned_aggregation_preserves_roi(self):
        aggregate = aggregate_region_pairs(
            [
                RegionPair("top_left", 0.95, 0.90, 0.92, "align-v1"),
                RegionPair("center", 0.80, 0.60, 0.88, "align-v1"),
                RegionPair("unrelated", 0.30, 0.99, 0.99, "align-v1"),
            ]
        )
        self.assertTrue(aggregate.matched)
        self.assertAlmostEqual(aggregate.source_match_score, 0.95)
        self.assertGreater(aggregate.edit_score, 0.7)
        self.assertEqual([item["region_id"] for item in aggregate.regions], ["top_left", "center"])

        no_match = aggregate_region_pairs(
            [RegionPair("bottom_right", 0.20, 0.95, 0.90)]
        )
        self.assertFalse(no_match.matched)
        self.assertEqual(no_match.reason, "no_source_match")

    def test_source_conditioned_aggregation_rejects_mixed_or_duplicate_inputs(self):
        with self.assertRaises(ValueError):
            aggregate_region_pairs(
                [RegionPair("center", 0.9, 0.8, 0.9)],
                max_regions=True,
            )
        with self.assertRaises(ValueError):
            aggregate_region_pairs(
                [
                    RegionPair("center", 0.9, 0.8, 0.9),
                    RegionPair("center", 0.8, 0.7, 0.9),
                ]
            )
        mixed = aggregate_region_pairs(
            [
                RegionPair("left", 0.9, 0.8, 0.9, "align-v1"),
                RegionPair("right", 0.9, 0.8, 0.9, "align-v2"),
            ]
        )
        self.assertFalse(mixed.matched)
        self.assertEqual(mixed.reason, "alignment_version_conflict")

        with self.assertRaises(ValueError):
            RegionPair("left", 0.9, 0.8, 0.9, "")

    def test_invalid_manifest_never_becomes_human(self):
        path = self.make_file(b"ordinary image bytes")
        report = inspect_file(
            path,
            manifest={"ai_disclosure": False},
            manifest_verification="invalid",
        )
        result = fuse_signals(
            report,
            DetectorSignals(model_available=False),
            self.calibrated_policy(),
        )
        self.assertEqual(result.status, AIGCStatus.UNKNOWN)
        self.assertEqual(result.unknown_reason, "model_unavailable")

        calibrated_low = fuse_signals(
            report,
            self.calibrated_signals(
                ai_score=0.05,
            ),
            self.calibrated_policy(),
        )
        self.assertEqual(calibrated_low.status, AIGCStatus.UNKNOWN)
        self.assertEqual(calibrated_low.unknown_reason, "conflicting_evidence")

    def test_human_supported_requires_signed_non_ai_and_two_streams(self):
        path = self.make_file(b"signed camera source")
        report = inspect_file(
            path,
            manifest={"ai_disclosure": False, "provider": "camera"},
            manifest_verification="valid",
            manifest_verifier_id="test-verifier-v1",
            manifest_binding_ok=True,
        )
        result = fuse_signals(
            report,
            self.calibrated_signals(
                ai_score=0.05,
                artifact_score=0.10,
            ),
            self.calibrated_policy(),
        )
        self.assertEqual(result.status, AIGCStatus.HUMAN_SUPPORTED)

        conflict = fuse_signals(
            report,
            self.calibrated_signals(ai_score=0.95, artifact_score=0.90),
            self.calibrated_policy(),
        )
        self.assertEqual(conflict.status, AIGCStatus.UNKNOWN)
        self.assertEqual(conflict.unknown_reason, "conflicting_evidence")

    def test_raw_scores_and_missing_quality_are_rejected(self):
        path = self.make_file(b"ordinary image bytes")
        report = inspect_file(path)
        raw = fuse_signals(
            report,
            DetectorSignals(
                ai_score=0.95,
                artifact_score=0.95,
                model_available=True,
                detector_version="detector-test-v1",
                score_schema="aigc-score-v1",
                scores_calibrated=False,
            ),
            self.calibrated_policy(),
        )
        self.assertEqual(raw.status, AIGCStatus.UNKNOWN)
        self.assertEqual(raw.unknown_reason, "uncalibrated_model")

        no_quality = fuse_signals(
            report,
            self.calibrated_signals(
                source_match_score=0.95,
                source_conditioned_edit_score=0.95,
            ),
            self.calibrated_policy(),
            regions=({"region_id": "center"},),
        )
        self.assertEqual(no_quality.status, AIGCStatus.UNKNOWN)
        self.assertEqual(no_quality.unknown_reason, "missing_quality")

    def test_manifest_rejects_group_leakage(self):
        records = [
            {
                "sample_id": "a",
                "group_id": "source-1",
                "split": "train",
                "origin": "real",
                "generator_family": "none",
                "license": "owned",
            },
            {
                "sample_id": "b",
                "group_id": "source-1",
                "split": "test",
                "origin": "real",
                "generator_family": "none",
                "license": "owned",
            },
        ]
        errors = validate_manifest(records)
        self.assertIn("group_leakage:source-1:test,train", errors)

    def test_contract_coerces_status_and_rejects_nan_threshold(self):
        result = AIGCResult(
            status="unknown_or_inconclusive",
            confidence=None,
            unknown_reason="model_unavailable",
        )
        self.assertEqual(result.status, AIGCStatus.UNKNOWN)
        self.assertEqual(result.to_dict()["status"], "unknown_or_inconclusive")
        with self.assertRaises(ValueError):
            FusionPolicy(ai_threshold=math.nan)

    def test_detector_contract_rejects_ambiguous_runtime_types(self):
        with self.assertRaises(ValueError):
            DetectorSignals(model_available=1)
        with self.assertRaises(ValueError):
            DetectorSignals(scores_calibrated="yes")
        with self.assertRaises(ValueError):
            DetectorSignals(score_schema="   ")
        with self.assertRaises(ValueError):
            DetectorSignals(detector_version="")

    def test_calibration_requires_integer_negative_stream_count(self):
        base = {
            "calibration_id": "calibration-test-v1",
            "detector_version": "detector-test-v1",
            "score_schema": "aigc-score-v1",
            "dataset_digest": "a" * 64,
        }
        with self.assertRaises(ValueError):
            CalibrationProfile(**base, min_negative_streams=1.5)
        with self.assertRaises(ValueError):
            CalibrationProfile(**base, min_negative_streams=True)
        with self.assertRaises(ValueError):
            FusionPolicy(calibration="calibration-test-v1")

    def test_source_residual_is_deterministic_and_serializable(self):
        reference = [
            [0.10, 0.20, 0.30, 0.40],
            [0.20, 0.30, 0.40, 0.50],
            [0.30, 0.40, 0.50, 0.60],
            [0.40, 0.50, 0.60, 0.70],
        ]
        identical = compare_aligned_regions(reference, reference)
        self.assertEqual(identical.global_shift, 0.0)
        self.assertEqual(identical.mean_abs_residual, 0.0)
        self.assertEqual(identical.edge_delta, 0.0)
        self.assertEqual(identical.edit_score, 0.0)
        self.assertGreater(identical.quality_score, 0.0)

        query = [row[:] for row in reference]
        query[1][1] = 0.90
        changed = compare_aligned_regions(reference, query)
        self.assertGreater(changed.p95_abs_residual, 0.0)
        self.assertGreater(changed.edge_delta, 0.0)
        self.assertGreater(changed.edit_score, identical.edit_score)
        region = changed.to_region_dict("center")
        self.assertEqual(region["region_id"], "center")
        self.assertEqual(region["score_raw"], changed.edit_score)
        self.assertEqual(region["score_schema"], "source-residual-score-v1")

    def test_source_residual_removes_global_brightness_shift_before_edit_score(self):
        reference = [[((x + y) % 8) / 8 for x in range(16)] for y in range(16)]
        brightness = [[min(1.0, value + 0.08) for value in row] for row in reference]
        local_edit = [row[:] for row in reference]
        for row in range(5, 11):
            for column in range(6, 12):
                local_edit[row][column] = min(1.0, local_edit[row][column] + 0.5)
        brightness_evidence = compare_aligned_regions(reference, brightness)
        edit_evidence = compare_aligned_regions(reference, local_edit)
        self.assertAlmostEqual(brightness_evidence.global_shift, 0.08, places=6)
        self.assertLess(brightness_evidence.edit_score, edit_evidence.edit_score)

    def test_source_residual_roi_keeps_global_shift_out_of_local_mask(self):
        reference = tuple(tuple(0.2 + 0.01 * (x + y) for x in range(8)) for y in range(8))
        brightness = tuple(tuple(value + 0.08 for value in row) for row in reference)
        roi = extract_residual_roi(reference, brightness, threshold=0.04)
        self.assertIsNone(roi.bbox)
        self.assertEqual(roi.selected_fraction, 0.0)
        self.assertIn("no_residual_above_threshold", roi.warnings)

    def test_source_residual_roi_returns_local_edit_bbox(self):
        reference = tuple(tuple(0.2 + 0.01 * (x + y) for x in range(8)) for y in range(8))
        query = [list(row) for row in reference]
        for y in range(2, 5):
            for x in range(3, 6):
                query[y][x] = min(1.0, query[y][x] + 0.35)
        roi = extract_residual_roi(reference, query, threshold=0.12)
        self.assertEqual(roi.bbox, (3, 2, 6, 5))
        self.assertAlmostEqual(roi.selected_fraction, 9 / 64)

    def test_source_residual_mask_and_quality_gates(self):
        reference = [[0.2, 0.3], [0.3, 0.4]]
        query = [[0.2, 0.3], [0.3, 0.9]]
        masked = compare_aligned_regions(
            reference,
            query,
            mask=[[0.0, 0.0], [0.0, 1.0]],
        )
        self.assertEqual(masked.mask_fraction, 0.25)
        self.assertIn("insufficient_edge_pairs", masked.warnings)
        self.assertEqual(masked.quality_score, 0.0)

        with self.assertRaises(ValueError):
            compare_aligned_regions(reference, query, mask=[[1.0]])
        with self.assertRaises(ValueError):
            compare_aligned_regions(reference, [[0.2, 0.3, 0.4], [0.3, 0.4, 0.5]])
        with self.assertRaises(ValueError):
            compare_aligned_regions(reference, query, mask=[[0.0, 0.0], [0.0, 0.0]])

    def test_source_residual_rejects_ambiguous_config_values(self):
        with self.assertRaises(ValueError):
            ResidualConfig(mean_scale=0.0)
        with self.assertRaises(ValueError):
            ResidualConfig(coverage_threshold=float("nan"))

    def test_compliance_layer_keeps_no_signal_unknown(self):
        path = self.make_file(b"ordinary image bytes")
        provenance = inspect_file(path)
        observation = classify_compliance(provenance)
        self.assertEqual(observation.label, ComplianceLabel.NO_SIGNAL_OR_UNKNOWN)
        self.assertEqual(observation.reason, "no_reliable_signal")

    def test_compliance_layer_separates_verified_declared_and_suspected(self):
        path = self.make_file(b"source")
        verified = inspect_file(
            path,
            manifest={"ai_disclosure": True},
            manifest_verification="valid",
            manifest_verifier_id="verifier-v1",
            manifest_binding_ok=True,
        )
        self.assertEqual(
            classify_compliance(verified).label,
            ComplianceLabel.VERIFIED_AI,
        )
        declared = inspect_file(path, user_declared_ai=True)
        self.assertEqual(
            classify_compliance(declared).label,
            ComplianceLabel.USER_DECLARED_AI,
        )
        self.assertEqual(
            classify_compliance(
                inspect_file(path),
                watermark=WatermarkSignal("provider-a", "possible", "wm-v1"),
            ).label,
            ComplianceLabel.SUSPECTED_AI,
        )

    def test_compliance_layer_conflict_requires_review(self):
        path = self.make_file(b"signed non-ai")
        provenance = inspect_file(
            path,
            manifest={"ai_disclosure": False},
            manifest_verification="valid",
            manifest_verifier_id="verifier-v1",
            manifest_binding_ok=True,
        )
        observation = classify_compliance(
            provenance,
            watermark=WatermarkSignal("provider-a", "positive", "wm-v1"),
        )
        self.assertEqual(observation.label, ComplianceLabel.NO_SIGNAL_OR_UNKNOWN)
        self.assertEqual(observation.conflicts, ("trusted_non_ai_vs_watermark_positive",))


if __name__ == "__main__":
    unittest.main()
