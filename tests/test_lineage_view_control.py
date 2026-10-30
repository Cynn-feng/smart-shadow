import unittest

from aigc.edit_lineage import EditLineageTrace, EditTraceStep
from aigc.lineage_view_control import (
    CONTROL_CANDIDATE,
    CONTROL_CONSISTENT,
    CONTROL_INSUFFICIENT,
    LineageViewControlConfig,
    LineageViewControlObservation,
    ROUTE_CONSISTENT,
    ROUTE_INCONSISTENT,
    ROUTE_INSUFFICIENT,
    evaluate_lineage_view_control,
)


def _trace(*steps, content=True):
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


def _observations(trace, support_by_step, *, mismatch=False, control_route=None):
    rows = []
    for view_order in (1, 2, 3):
        view_id = f"view-{view_order}"
        for step in trace.steps:
            supported = view_order in support_by_step.get(step.step_id, set())
            row_control_route = control_route or (CONTROL_CANDIDATE if supported else CONTROL_CONSISTENT)
            rows.append(LineageViewControlObservation(
                trace_digest=trace.trace_digest,
                asset_id=trace.asset_id if not mismatch else "other-asset",
                pair_id=trace.pair_id,
                transform_family=trace.transform_family,
                canonical_frame_digest=trace.canonical_frame_digest,
                manifest_digest=trace.manifest_digest,
                binding_digest=trace.binding_digest,
                detector_version=trace.detector_version,
                score_schema=trace.score_schema,
                view_id=view_id,
                view_order=view_order,
                view_spec_digest=("e" * 64),
                step_id=step.step_id,
                region_id=step.output_region_ids[0],
                operation_type=step.operation_type,
                delta_raw=0.65 if supported else 0.12,
                quality_score=0.9,
                source_match_score=0.95,
                control_route=row_control_route,
                control_contrast_raw=0.5 if supported else -0.01,
                control_p_value_raw=0.02 if supported else 0.8,
                control_digest="f" * 64,
                mask_overlap_raw=0.85,
            ))
    return rows


class LineageViewControlTests(unittest.TestCase):
    def content_trace(self):
        return _trace(
            EditTraceStep("s1", 1, "add", output_region_ids=("r1",), mask_digest="a" * 64),
            EditTraceStep("s2", 2, "replace", parent_step_ids=("s1",), input_region_ids=("r1",), output_region_ids=("r2",), mask_digest="a" * 64),
        )

    def test_stable_step_order_and_control_support_are_consistent(self):
        trace = self.content_trace()
        rows = _observations(trace, {"s1": {1, 2, 3}, "s2": {2, 3}})
        result = evaluate_lineage_view_control(trace, rows)

        self.assertEqual(result.route, ROUTE_CONSISTENT)
        self.assertFalse(result.abstained)
        self.assertEqual(result.reason, "controlled_lineage_consistent")
        self.assertEqual(result.step_audit[0].first_support_view_order, 1)
        self.assertEqual(result.step_audit[1].first_support_view_order, 2)
        self.assertEqual(result.ordered_consistency_raw, 1.0)

    def test_reversed_step_onset_is_trajectory_inconsistent(self):
        trace = self.content_trace()
        rows = _observations(trace, {"s1": {2, 3}, "s2": {1, 2}})
        result = evaluate_lineage_view_control(trace, rows)

        self.assertEqual(result.route, ROUTE_INCONSISTENT)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "step_onset_order_inconsistent")
        self.assertEqual(result.ordered_consistency_raw, 0.0)

    def test_binding_and_control_support_fail_closed(self):
        trace = self.content_trace()
        mismatch = evaluate_lineage_view_control(trace, _observations(trace, {"s1": {1, 2, 3}, "s2": {2, 3}}, mismatch=True))
        self.assertEqual(mismatch.route, ROUTE_INSUFFICIENT)
        self.assertEqual(mismatch.reason, "binding_mismatch")

        insufficient = evaluate_lineage_view_control(trace, _observations(trace, {"s1": {1, 2, 3}, "s2": {2, 3}}, control_route=CONTROL_INSUFFICIENT))
        self.assertEqual(insufficient.route, ROUTE_INSUFFICIENT)
        self.assertEqual(insufficient.reason, "control_summary_insufficient")

    def test_ordinary_propagation_is_separate_from_content_route(self):
        trace = _trace(EditTraceStep("s1", 1, "identity", output_region_ids=("r1",)))
        row = LineageViewControlObservation(
            trace_digest=trace.trace_digest,
            asset_id=trace.asset_id,
            pair_id=trace.pair_id,
            transform_family=trace.transform_family,
            canonical_frame_digest=trace.canonical_frame_digest,
            manifest_digest=trace.manifest_digest,
            binding_digest=trace.binding_digest,
            detector_version=trace.detector_version,
            score_schema=trace.score_schema,
            view_id="view-1",
            view_order=1,
            view_spec_digest="e" * 64,
            step_id="s1",
            region_id="r1",
            operation_type="identity",
            delta_raw=0.01,
            quality_score=0.9,
            source_match_score=0.9,
            control_route=CONTROL_CONSISTENT,
            control_contrast_raw=-0.01,
            control_p_value_raw=0.9,
            control_digest="f" * 64,
        )
        result = evaluate_lineage_view_control(trace, [row])
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "ordinary_propagation_scope")
        self.assertEqual(result.operation_scope, "ordinary_propagation")

    def test_config_and_evidence_digests_are_replayable(self):
        trace = self.content_trace()
        rows = _observations(trace, {"s1": {1, 2, 3}, "s2": {2, 3}})
        cfg = LineageViewControlConfig(quality_power=2.0)
        first = evaluate_lineage_view_control(trace, rows, config=cfg)
        second = evaluate_lineage_view_control(trace, rows, config=cfg)
        self.assertEqual(first.config_digest, second.config_digest)
        self.assertEqual(first.evidence_digest, second.evidence_digest)
        self.assertEqual(first.control_digest, second.control_digest)


if __name__ == "__main__":
    unittest.main()
