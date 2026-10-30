import unittest

from aigc.evidence_graph import (
    GraphEdge,
    GraphNode,
    EvidenceGraphConfig,
    ROUTE_BRANCH_CONFLICT,
    ROUTE_GRAPH_CONSISTENT,
    ROUTE_INSUFFICIENT,
    ROUTE_PROPAGATION_LEAK,
    ROUTE_TRAJECTORY_INCONSISTENT,
    evaluate_evidence_graph,
)


def _d(char: str) -> str:
    return char * 64


def _node(node_id: str, support: float, regions=None, *, kind="version", asset="asset-1", quality=0.9, source=0.9):
    return GraphNode(
        node_id=node_id,
        asset_id=asset,
        node_kind=kind,
        manifest_digest=_d("a"),
        canonical_frame_digest=_d("b"),
        detector_version="detector-v1",
        score_schema="regional-score-v1",
        support_raw=support,
        region_support=regions or {"r1": support},
        quality_score=quality,
        source_match_score=source,
        evidence_digest=_d("c"),
    )


def _edge(edge_id: str, parent: str, child: str, *, scope="content_edit", regions=("r1",), mask=True, null=True):
    return GraphEdge(
        edge_id=edge_id,
        parent_id=parent,
        child_id=child,
        operation_scope=scope,
        operation_type="inpaint" if scope == "content_edit" else "jpeg_reencode",
        transform_digest=_d("d"),
        null_profile_digest=_d("e") if null else None,
        declared_mask_digest=_d("f") if mask else None,
        declared_region_ids=regions,
        upstream_evidence_digest=_d("1"),
    )


class EvidenceGraphTests(unittest.TestCase):
    def test_consistent_content_path(self):
        result = evaluate_evidence_graph(
            [_node("source", 0.05, {"r1": 0.05}, kind="registered_source"), _node("edit", 0.7, {"r1": 0.7}, kind="observed")],
            [_edge("e1", "source", "edit")],
        )
        self.assertEqual(result.route, ROUTE_GRAPH_CONSISTENT)
        self.assertEqual(result.root_ids, ("source",))
        self.assertEqual(result.leaf_ids, ("edit",))
        self.assertAlmostEqual(result.edge_audits[0].new_support_raw, 0.65)

    def test_ordinary_propagation_leak(self):
        result = evaluate_evidence_graph(
            [_node("source", 0.05, {"r1": 0.05}, kind="registered_source"), _node("prop", 0.7, {"r1": 0.7}, kind="ordinary_null")],
            [_edge("e1", "source", "prop", scope="ordinary_propagation", regions=(), mask=False)],
        )
        self.assertEqual(result.route, ROUTE_PROPAGATION_LEAK)
        self.assertIn("propagation_leak_above_gate", result.reasons)

    def test_off_mask_support_is_trajectory_inconsistent(self):
        result = evaluate_evidence_graph(
            [_node("source", 0.05, {"r1": 0.05, "r2": 0.0}, kind="registered_source"), _node("edit", 0.8, {"r1": 0.8, "r2": 0.5}, kind="observed")],
            [_edge("e1", "source", "edit", regions=("r1",))],
        )
        self.assertEqual(result.route, ROUTE_TRAJECTORY_INCONSISTENT)
        self.assertGreater(result.off_mask_gain_raw, 0.2)

    def test_branch_conflict(self):
        result = evaluate_evidence_graph(
            [_node("source", 0.1, {"r1": 0.1}, kind="registered_source"), _node("a", 0.9), _node("b", 0.1)],
            [_edge("ea", "source", "a"), _edge("eb", "source", "b")],
        )
        self.assertEqual(result.route, ROUTE_BRANCH_CONFLICT)

    def test_merge_is_fail_closed(self):
        result = evaluate_evidence_graph(
            [_node("source", 0.1, {"r1": 0.1}, kind="registered_source"), _node("a", 0.5), _node("b", 0.5), _node("merge", 0.6)],
            [_edge("ea", "source", "a"), _edge("eb", "source", "b"), _edge("em", "a", "merge"), _edge("em2", "b", "merge")],
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertIn("merge_not_supported", result.reasons)

    def test_cycle_is_fail_closed(self):
        result = evaluate_evidence_graph(
            [_node("a", 0.1), _node("b", 0.2)],
            [_edge("ab", "a", "b"), _edge("ba", "b", "a")],
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertIn("cycle_detected", result.reasons)

    def test_missing_content_mask_and_null_profile(self):
        content = evaluate_evidence_graph(
            [_node("a", 0.1), _node("b", 0.2)], [_edge("e", "a", "b", mask=False)]
        )
        self.assertEqual(content.route, ROUTE_INSUFFICIENT)
        self.assertTrue(any("content_edge_missing_declared_mask" in reason for reason in content.reasons))
        propagation = evaluate_evidence_graph(
            [_node("a", 0.1), _node("b", 0.2)], [_edge("e", "a", "b", scope="ordinary_propagation", regions=(), mask=False, null=False)]
        )
        self.assertEqual(propagation.route, ROUTE_INSUFFICIENT)

    def test_binding_and_quality_gate(self):
        result = evaluate_evidence_graph(
            [_node("a", 0.1, quality=0.1), _node("b", 0.2, asset="other")],
            [_edge("e", "a", "b")],
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertIn("binding_context_mismatch", result.reasons)
        self.assertIn("quality_below_gate", result.reasons)

    def test_trajectory_persistence_failure(self):
        result = evaluate_evidence_graph(
            [_node("source", 0.1, {"r1": 0.1}, kind="registered_source"), _node("edit", 0.7), _node("desc", 0.05)],
            [_edge("e1", "source", "edit"), _edge("e2", "edit", "desc")],
        )
        self.assertEqual(result.route, ROUTE_TRAJECTORY_INCONSISTENT)
        self.assertLess(result.path_persistence_raw, 0.5)

    def test_metadata_rejects_probability_fields(self):
        with self.assertRaises(ValueError):
            _node("a", 0.1, kind="registered_source").__class__(
                node_id="bad", asset_id="asset", node_kind="version", manifest_digest=_d("a"), canonical_frame_digest=_d("b"),
                detector_version="d", score_schema="s", support_raw=0.1, region_support={"r": 0.1}, quality_score=0.9,
                source_match_score=0.9, evidence_digest=_d("c"), metadata={"aigc_probability": 0.4}
            )


if __name__ == "__main__":
    unittest.main()
