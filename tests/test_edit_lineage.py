import unittest

from aigc.edit_lineage import (
    EditLineageConfig,
    EditLineageTrace,
    EditRegionEvidence,
    EditTraceStep,
    ROUTE_CONSISTENT,
    ROUTE_INCONSISTENT,
    ROUTE_INSUFFICIENT,
    OPERATION_SCOPE_PROPAGATION,
    OPERATION_SCOPE_CONTENT,
    evaluate_edit_lineage,
    fuse_edit_lineage,
)


MASK = "a" * 64


def _trace(*steps):
    return EditLineageTrace(
        asset_id="asset-1",
        source_version_id="source-1",
        observed_version_id="observed-1",
        detector_version="source-residual-v1",
        score_schema="regional-delta-v1",
        steps=steps,
        pair_id="pair-1",
        transform_family="identity",
        canonical_frame_digest="b" * 64,
        manifest_digest="c" * 64,
        binding_digest="d" * 64,
    )


def _evidence(step_id, region_id, delta=0.4, *, quality=0.9, source=0.95, overlap=0.8):
    return EditRegionEvidence(
        step_id=step_id,
        region_id=region_id,
        delta_raw=delta,
        quality_score=quality,
        source_match_score=source,
        mask_overlap_raw=overlap,
    )


class EditLineageTests(unittest.TestCase):
    def test_ordered_operation_trace_is_consistent_and_auditable(self):
        trace = _trace(
            EditTraceStep("s1", 1, "add", output_region_ids=("r1",), mask_digest=MASK),
            EditTraceStep(
                "s2", 2, "replace", parent_step_ids=("s1",),
                input_region_ids=("r1",), output_region_ids=("r2",), mask_digest=MASK,
            ),
        )
        result = evaluate_edit_lineage(trace, [_evidence("s1", "r1", 0.6), _evidence("s2", "r2", 0.5)])

        self.assertEqual(result.route, ROUTE_CONSISTENT)
        self.assertFalse(result.abstained)
        self.assertEqual(result.reason, "ordered_lineage_consistent")
        self.assertEqual(result.accepted_step_count, 2)
        self.assertEqual(result.lineage_consistency_raw, 1.0)
        self.assertEqual(result.operation_consistency_raw, 1.0)
        self.assertEqual(len(result.step_audit), 2)
        self.assertEqual(result.to_dict()["result_schema"], "edit-lineage-result-v1")

    def test_future_parent_and_sequence_reordering_fail_closed(self):
        trace = _trace(
            EditTraceStep("s1", 1, "add", parent_step_ids=("s2",), output_region_ids=("r1",), mask_digest=MASK),
            EditTraceStep("s2", 2, "remove", input_region_ids=("r1",), output_region_ids=("r1",), mask_digest=MASK),
        )
        result = evaluate_edit_lineage(trace, [_evidence("s1", "r1"), _evidence("s2", "r1")])

        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "future_parent_step")
        self.assertIn("s1", result.invalid_step_ids)

    def test_region_lineage_gap_is_reviewable_inconsistency(self):
        trace = _trace(
            EditTraceStep("s1", 1, "add", output_region_ids=("r1",), mask_digest=MASK),
            EditTraceStep(
                "s2", 2, "replace", parent_step_ids=("s1",),
                input_region_ids=("r9",), output_region_ids=("r2",), mask_digest=MASK,
            ),
        )
        result = evaluate_edit_lineage(trace, [_evidence("s1", "r1"), _evidence("s2", "r2")])

        self.assertEqual(result.route, ROUTE_INCONSISTENT)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "lineage_region_gap")
        self.assertLess(result.lineage_consistency_raw, 1.0)
        self.assertIn("lineage_region_gap:s1", result.step_audit[1].reasons)

    def test_low_quality_and_missing_step_evidence_are_insufficient(self):
        trace = _trace(
            EditTraceStep("s1", 1, "inpaint", input_region_ids=("r1",), output_region_ids=("r1",), mask_digest=MASK),
            EditTraceStep("s2", 2, "outpaint", parent_step_ids=("s1",), output_region_ids=("r2",), mask_digest=MASK),
        )
        result = evaluate_edit_lineage(trace, [_evidence("s1", "r1", quality=0.1)])

        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "evidence_coverage_below_threshold")
        self.assertEqual(result.accepted_step_count, 0)
        self.assertIn("no_accepted_evidence", result.step_audit[0].reasons)
        self.assertIn("no_accepted_evidence", result.step_audit[1].reasons)

    def test_partial_region_quality_does_not_hide_inside_a_step(self):
        trace = _trace(EditTraceStep("s1", 1, "add", output_region_ids=("r1", "r2"), mask_digest=MASK))
        result = evaluate_edit_lineage(
            trace,
            [_evidence("s1", "r1", quality=0.9), _evidence("s1", "r2", quality=0.1)],
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertLess(result.evidence_coverage_raw, 1.0)
        self.assertIn("evidence_coverage_below_threshold", result.step_audit[0].reasons)

    def test_unsupported_operation_and_mask_overlap_are_not_silent_successes(self):
        trace = _trace(EditTraceStep("s1", 1, "mystery", output_region_ids=("r1",), mask_digest=MASK))
        unsupported = evaluate_edit_lineage(trace, [_evidence("s1", "r1")])
        self.assertEqual(unsupported.route, ROUTE_INCONSISTENT)
        self.assertEqual(unsupported.reason, "operation_semantics_inconsistent")
        self.assertIn("unsupported_operation", unsupported.step_audit[0].reasons)

        low_overlap = evaluate_edit_lineage(
            _trace(EditTraceStep("s1", 1, "add", output_region_ids=("r1",), mask_digest=MASK)),
            [_evidence("s1", "r1", overlap=0.1)],
        )
        self.assertEqual(low_overlap.route, ROUTE_INCONSISTENT)
        self.assertEqual(low_overlap.reason, "mask_overlap_below_threshold")

        mismatch_trace = _trace(EditTraceStep("s1", 1, "add", output_region_ids=("r1",), mask_digest=MASK))
        mismatch = evaluate_edit_lineage(
            mismatch_trace,
            [EditRegionEvidence("s1", "r1", 0.3, 0.9, 0.9, operation_type="remove", mask_overlap_raw=0.8)],
        )
        self.assertEqual(mismatch.route, ROUTE_INCONSISTENT)
        self.assertEqual(mismatch.reason, "operation_semantics_inconsistent")
        self.assertIn("evidence_operation_mismatch", mismatch.step_audit[0].reasons)

    def test_propagation_steps_can_be_recorded_without_edit_mask(self):
        trace = _trace(
            EditTraceStep("s1", 1, "identity", output_region_ids=("r1",)),
            EditTraceStep("s2", 2, "jpeg_reencode", parent_step_ids=("s1",), input_region_ids=("r1",), output_region_ids=("r1",)),
        )
        result = fuse_edit_lineage(trace, [_evidence("s1", "r1", delta=0.01), _evidence("s2", "r1", delta=0.02)])

        self.assertEqual(result.route, ROUTE_CONSISTENT)
        self.assertEqual(result.operation_scope, OPERATION_SCOPE_PROPAGATION)
        self.assertAlmostEqual(result.weighted_delta_raw, 0.015, places=6)

    def test_content_evidence_without_mask_overlap_is_insufficient(self):
        trace = _trace(EditTraceStep("s1", 1, "inpaint", input_region_ids=("r1",), output_region_ids=("r1",), mask_digest=MASK))
        result = evaluate_edit_lineage(
            trace,
            [EditRegionEvidence("s1", "r1", 0.4, 0.9, 0.9, mask_overlap_raw=None)],
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "content_evidence_missing_mask_overlap")
        self.assertEqual(result.operation_scope, OPERATION_SCOPE_CONTENT)
        self.assertTrue(result.abstained)

    def test_duplicate_region_evidence_and_probability_metadata_are_rejected(self):
        trace = _trace(EditTraceStep("s1", 1, "add", output_region_ids=("r1",), mask_digest=MASK))
        with self.assertRaises(ValueError):
            EditRegionEvidence("s1", "r1", 0.2, 0.9, 0.9, metadata={"aigc_probability": 0.2})
        evidence = [_evidence("s1", "r1"), _evidence("s1", "r1")]
        result = evaluate_edit_lineage(trace, evidence)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "duplicate_region_evidence")

    def test_config_digest_and_result_digest_are_deterministic(self):
        trace = _trace(EditTraceStep("s1", 1, "add", output_region_ids=("r1",), mask_digest=MASK))
        evidence = [_evidence("s1", "r1")]
        first = evaluate_edit_lineage(trace, evidence, config=EditLineageConfig(quality_power=2.0))
        second = evaluate_edit_lineage(trace, evidence, config=EditLineageConfig(quality_power=2.0))
        self.assertEqual(first.config_digest, second.config_digest)
        self.assertEqual(first.trace_digest, second.trace_digest)
        self.assertEqual(first.evidence_digest, second.evidence_digest)

    def test_binding_context_is_required_for_authenticated_trace(self):
        trace = EditLineageTrace(
            asset_id="asset-1",
            source_version_id="source-1",
            observed_version_id="observed-1",
            detector_version="source-residual-v1",
            score_schema="regional-delta-v1",
            steps=(EditTraceStep("s1", 1, "add", output_region_ids=("r1",), mask_digest=MASK),),
            pair_id="pair-1",
            transform_family="identity",
            canonical_frame_digest="b" * 64,
            manifest_digest=None,
            binding_digest="d" * 64,
        )
        result = evaluate_edit_lineage(trace, [_evidence("s1", "r1")])
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "binding_context_missing")
        self.assertIsNone(result.manifest_digest)


if __name__ == "__main__":
    unittest.main()
