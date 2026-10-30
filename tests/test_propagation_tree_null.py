import unittest

from aigc.propagation_tree_null import (
    CONTENT_EDIT,
    ORDINARY_PROPAGATION,
    ROUTE_INSUFFICIENT,
    ROUTE_TREE_AMBIGUOUS,
    ROUTE_TREE_CANDIDATE,
    ROUTE_TREE_NULL,
    PropagationTree,
    PropagationTreeConfig,
    PropagationTreeNode,
    evaluate_propagation_tree_null,
    fit_propagation_tree_null_profile,
)


class PropagationTreeNullTests(unittest.TestCase):
    def setUp(self):
        self.config = PropagationTreeConfig(
            minimum_tree_support=8,
            minimum_nodes_per_tree=3,
            alpha=0.20,
            minimum_selected_delta=0.01,
        )
        self.manifest = "a" * 64
        self.calibration_split = "b" * 64
        self.evaluation_split = "c" * 64

    def tree(self, tree_id, *, split="calibration", split_digest=None, scope=ORDINARY_PROPAGATION,
             deltas=(0.01, 0.02, 0.03), quality=(0.95, 0.95, 0.95), source=(0.95, 0.95, 0.95),
             asset_id=None, transform="jpeg", time="t0"):
        asset_id = asset_id or f"asset-{tree_id}"
        split_digest = split_digest or (self.calibration_split if split == "calibration" else self.evaluation_split)
        nodes = []
        for index, delta in enumerate(deltas):
            nodes.append(
                PropagationTreeNode(
                    version_id=f"{tree_id}-v{index}",
                    parent_version_id=None if index == 0 else f"{tree_id}-v{index - 1}",
                    asset_id=asset_id,
                    tree_id=tree_id,
                    transform_family=transform,
                    quality_bucket="high",
                    time_bucket=time,
                    source_match_bucket="matched",
                    operation_scope=scope,
                    paired_delta_raw=delta,
                    quality_score=quality[index],
                    source_match_score=source[index],
                    node_order=index,
                )
            )
        return PropagationTree(
            tree_id=tree_id,
            asset_id=asset_id,
            manifest_digest=self.manifest,
            split_digest=split_digest,
            detector_version="detector-v1",
            score_schema="paired-delta-v1",
            transform_family=transform,
            quality_bucket="high",
            time_bucket=time,
            source_match_bucket="matched",
            nodes=tuple(nodes),
            split=split,
        )

    def profile(self, deltas=(0.01, 0.02, 0.03)):
        trees = [self.tree(f"null-{index}", deltas=deltas) for index in range(8)]
        return fit_propagation_tree_null_profile(trees, self.config)

    def test_tree_max_is_calibrated_as_one_statistic(self):
        profile = self.profile()
        query = self.tree("query", split="evaluation", scope=CONTENT_EDIT, deltas=(0.70, 0.80, 0.75))
        result = evaluate_propagation_tree_null(query, profile, self.config)
        self.assertEqual(result.route, ROUTE_TREE_CANDIDATE)
        self.assertEqual(result.selected_max_raw, 0.8)
        self.assertEqual(result.selected_version_ids, ("query-v1",))
        self.assertEqual(result.p_value_raw, 1 / 9)
        self.assertEqual(result.null_support, 8)

    def test_ordinary_tree_never_becomes_candidate(self):
        profile = self.profile()
        query = self.tree("query", split="evaluation", deltas=(0.8, 0.7, 0.6))
        result = evaluate_propagation_tree_null(query, profile, self.config)
        self.assertEqual(result.route, ROUTE_TREE_NULL)
        self.assertFalse(result.abstained)
        self.assertEqual(result.reason, "ordinary_propagation_scope")

    def test_selection_not_supported_routes_ambiguous(self):
        profile = self.profile(deltas=(0.03, 0.03, 0.03))
        query = self.tree("query", split="evaluation", scope=CONTENT_EDIT, deltas=(0.03, 0.025, 0.02))
        result = evaluate_propagation_tree_null(query, profile, self.config)
        self.assertEqual(result.route, ROUTE_TREE_AMBIGUOUS)
        self.assertTrue(result.abstained)
        self.assertEqual(result.p_value_raw, 1.0)

    def test_split_leakage_fails_closed(self):
        profile = self.profile()
        query = self.tree("query", split="evaluation", split_digest=self.calibration_split, scope=CONTENT_EDIT, deltas=(0.8, 0.7, 0.6))
        result = evaluate_propagation_tree_null(query, profile, self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertTrue(result.abstained)

    def test_binding_and_stratum_mismatch_fail_closed(self):
        profile = self.profile()
        wrong_transform = self.tree("query", split="evaluation", scope=CONTENT_EDIT, transform="resize", deltas=(0.8, 0.7, 0.6))
        wrong_detector = PropagationTree(
            **{**wrong_transform.__dict__, "detector_version": "other-v1"}
        )
        self.assertEqual(evaluate_propagation_tree_null(wrong_transform, profile, self.config).route, ROUTE_INSUFFICIENT)
        self.assertEqual(evaluate_propagation_tree_null(wrong_detector, profile, self.config).route, ROUTE_INSUFFICIENT)

    def test_quality_and_source_support_fail_closed(self):
        profile = self.profile()
        query = self.tree(
            "query", split="evaluation", scope=CONTENT_EDIT, deltas=(0.8, 0.7, 0.6),
            quality=(0.2, 0.2, 0.2), source=(0.2, 0.2, 0.2),
        )
        result = evaluate_propagation_tree_null(query, profile, self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)

    def test_profile_rejects_content_edit_and_repeated_asset(self):
        with self.assertRaises(ValueError):
            fit_propagation_tree_null_profile(
                [self.tree(f"n-{i}", scope=CONTENT_EDIT) for i in range(8)], self.config
            )
        with self.assertRaises(ValueError):
            fit_propagation_tree_null_profile(
                [self.tree(f"n-{i}", asset_id="same") for i in range(8)], self.config
            )

    def test_tree_topology_rejects_missing_parent_cycle_and_multiple_roots(self):
        with self.assertRaises(ValueError):
            self.tree("bad", deltas=(0.1, 0.2, 0.3)).__class__(
                **{**self.tree("bad").__dict__, "nodes": tuple(
                    [PropagationTreeNode(**{**node.__dict__, "parent_version_id": "missing"})
                     if node.node_order == 1 else node for node in self.tree("bad").nodes]
                )}
            )
        with self.assertRaises(ValueError):
            nodes = tuple(
                PropagationTreeNode(**{**node.__dict__, "parent_version_id": "bad-v2"})
                if node.node_order == 1 else node for node in self.tree("cycle").nodes
            )
            PropagationTree(**{**self.tree("cycle").__dict__, "nodes": nodes})
        with self.assertRaises(ValueError):
            nodes = tuple(
                PropagationTreeNode(**{**node.__dict__, "parent_version_id": None})
                if node.node_order == 1 else node for node in self.tree("roots").nodes
            )
            PropagationTree(**{**self.tree("roots").__dict__, "nodes": nodes})

    def test_order_does_not_change_profile_digest(self):
        trees = [self.tree(f"null-{index}") for index in range(8)]
        forward = fit_propagation_tree_null_profile(trees, self.config)
        reverse = fit_propagation_tree_null_profile(tuple(reversed(trees)), self.config)
        self.assertEqual(forward.profile_digest, reverse.profile_digest)
        self.assertEqual(forward.dataset_digest, reverse.dataset_digest)

    def test_result_is_raw_evidence_only(self):
        profile = self.profile()
        result = evaluate_propagation_tree_null(
            self.tree("query", split="evaluation", scope=CONTENT_EDIT, deltas=(0.8, 0.7, 0.6)),
            profile,
            self.config,
        )
        payload = result.to_dict()
        self.assertNotIn("probability", json_keys(payload))
        self.assertNotIn("human_supported", json_keys(payload))
        self.assertNotIn("ai_generated_supported", json_keys(payload))


def json_keys(value):
    if isinstance(value, dict):
        keys = set(value)
        for child in value.values():
            keys.update(json_keys(child))
        return keys
    if isinstance(value, (list, tuple)):
        keys = set()
        for child in value:
            keys.update(json_keys(child))
        return keys
    return set()


if __name__ == "__main__":
    unittest.main()
