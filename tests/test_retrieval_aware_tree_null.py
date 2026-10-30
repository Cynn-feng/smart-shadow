import unittest

from aigc.retrieval_aware_tree_null import (
    MEMBERSHIP_EXACT,
    MEMBERSHIP_MATCHED,
    MEMBERSHIP_OUTSIDE,
    MEMBERSHIP_UNCERTAIN,
    OPERATION_CONTENT_EDIT,
    OPERATION_ORDINARY_PROPAGATION,
    ROUTE_INSUFFICIENT,
    ROUTE_OPEN_SET_UNKNOWN,
    ROUTE_RETRIEVAL_CONTAMINATED,
    ROUTE_RETRIEVAL_TREE_CANDIDATE,
    ROUTE_RETRIEVAL_TREE_NULL,
    RSCPTNConfig,
    RetrievalCandidate,
    RetrievalEvent,
    evaluate_retrieval_aware_tree_null,
    fit_rscptn_null_profile,
)


HEX = "a" * 64


def _candidate(event_id, index, *, membership=MEMBERSHIP_EXACT, delta=0.01,
               asset_id=None, operation=OPERATION_ORDINARY_PROPAGATION,
               parent=None, generator_family="known"):
    return RetrievalCandidate(
        candidate_id=f"{event_id}-c{index}",
        candidate_rank=index,
        membership_tier=membership,
        asset_id=asset_id or f"asset-{event_id}",
        tree_id=f"tree-{event_id}",
        version_id=f"{event_id}-v{index}",
        parent_version_id=parent,
        branch_id="main",
        depth=index - 1,
        paired_delta_raw=delta,
        quality_score=0.95,
        source_match_score=0.95,
        canonical_frame_digest=HEX,
        detector_version="detector-v1",
        score_schema="paired-delta-v1",
        input_digest=HEX,
        evidence_digest=HEX,
        transform_family="jpeg",
        quality_bucket="high",
        transport_bucket="same",
        time_bucket="t0",
        operation_scope=operation,
        selection_group_id=f"group-{event_id}",
        generator_family=generator_family,
    )


def _event(event_id, *, split="calibration", operation=OPERATION_ORDINARY_PROPAGATION,
           membership=MEMBERSHIP_EXACT, delta=0.01, asset_id=None,
           generator_family="known", open_set=False, reference_route="reference_specific_candidate",
           invariant_route="invariant_candidate", poisoning_stress_route="clean",
           poisoning_route_flip=False, candidates=None, query_asset_id=None):
    split_digest = "b" * 64 if split == "calibration" else "c" * 64
    if candidates is None:
        candidates = (_candidate(event_id, 1, membership=membership, delta=delta,
                                 asset_id=asset_id, operation=operation,
                                 generator_family=generator_family),)
    return RetrievalEvent(
        event_id=event_id,
        query_digest=HEX,
        retrieval_policy_digest=HEX,
        candidates=tuple(candidates),
        manifest_digest="d" * 64,
        split_digest=split_digest,
        calibration_split_digest="b" * 64,
        evaluation_split_digest="c" * 64,
        selection_policy_digest=HEX,
        selection_key_digest=HEX,
        canonical_frame_digest=HEX,
        detector_version="detector-v1",
        score_schema="paired-delta-v1",
        action_budget=2,
        input_digest=HEX,
        evidence_digest=HEX,
        retrieval_archive_digest=HEX,
        membership_policy_digest=HEX,
        decoy_injection_digest=HEX,
        split=split,
        query_asset_id=query_asset_id or f"query-{event_id}",
        operation_scope=operation,
        candidate_count=len(candidates),
        reference_route=reference_route,
        invariant_route=invariant_route,
        open_set=open_set,
        poisoning_stress_route=poisoning_stress_route,
        poisoning_route_flip=poisoning_route_flip,
        generator_family=generator_family,
    )


class RetrievalAwareTreeNullContractTest(unittest.TestCase):
    def setUp(self):
        self.config = RSCPTNConfig(alpha=0.20, minimum_selected_delta=0.15)
        self.calibration = [
            _event(f"null-{index}", delta=0.01 + index * 0.001)
            for index in range(8)
        ]
        self.profile = fit_rscptn_null_profile(self.calibration, self.config)

    def test_dual_null_gate_candidate(self):
        event = _event("query", split="evaluation", operation=OPERATION_CONTENT_EDIT, delta=0.80)
        result = evaluate_retrieval_aware_tree_null(event, self.profile, self.config)
        self.assertEqual(result.route, ROUTE_RETRIEVAL_TREE_CANDIDATE)
        self.assertEqual(result.p_joint_raw, max(result.p_tree_raw, result.p_retrieval_raw))

    def test_ordinary_propagation_is_null_consistent(self):
        event = _event("ordinary-query", split="evaluation", delta=0.80)
        result = evaluate_retrieval_aware_tree_null(event, self.profile, self.config)
        self.assertEqual(result.route, ROUTE_RETRIEVAL_TREE_NULL)
        self.assertEqual(result.reason, "ordinary_propagation_scope")

    def test_wrong_reference_and_poisoning_fail_closed(self):
        wrong_reference = _event(
            "wrong-reference", split="evaluation", operation=OPERATION_CONTENT_EDIT,
            delta=0.80, reference_route="reference_ambiguous",
        )
        poisoned = _event(
            "poisoned", split="evaluation", operation=OPERATION_CONTENT_EDIT,
            delta=0.80, poisoning_stress_route="poisoning",
        )
        self.assertEqual(
            evaluate_retrieval_aware_tree_null(wrong_reference, self.profile, self.config).route,
            ROUTE_RETRIEVAL_CONTAMINATED,
        )
        self.assertEqual(
            evaluate_retrieval_aware_tree_null(poisoned, self.profile, self.config).route,
            ROUTE_RETRIEVAL_CONTAMINATED,
        )

    def test_same_tree_selection_tie_is_contaminated(self):
        tie_profile = fit_rscptn_null_profile([
            _event(
                f"tie-null-{index}",
                candidates=(
                    _candidate(f"tie-null-{index}", 1, delta=0.01),
                    _candidate(f"tie-null-{index}", 2, delta=0.01),
                ),
            ) for index in range(8)
        ], self.config)
        tied = _event(
            "tie", split="evaluation", operation=OPERATION_CONTENT_EDIT,
            candidates=(
                _candidate("tie", 1, delta=0.80, operation=OPERATION_CONTENT_EDIT),
                _candidate("tie", 2, delta=0.80, operation=OPERATION_CONTENT_EDIT),
            ),
        )
        result = evaluate_retrieval_aware_tree_null(tied, tie_profile, self.config)
        self.assertEqual(result.route, ROUTE_RETRIEVAL_CONTAMINATED)

    def test_membership_contamination_is_not_soft_weighted(self):
        candidates = (
            _candidate("contaminated", 1, membership=MEMBERSHIP_EXACT, delta=0.80,
                       operation=OPERATION_CONTENT_EDIT),
            _candidate("contaminated", 2, membership=MEMBERSHIP_UNCERTAIN, delta=0.75,
                       operation=OPERATION_CONTENT_EDIT),
        )
        calibration = [
            _event(f"contam-null-{index}", candidates=(
                _candidate(f"contam-null-{index}", 1, membership=MEMBERSHIP_EXACT, delta=0.01),
                _candidate(f"contam-null-{index}", 2, membership=MEMBERSHIP_UNCERTAIN, delta=0.01),
            )) for index in range(8)
        ]
        profile = fit_rscptn_null_profile(calibration, self.config)
        result = evaluate_retrieval_aware_tree_null(
            _event("contaminated", split="evaluation", operation=OPERATION_CONTENT_EDIT,
                   candidates=candidates), profile, self.config,
        )
        self.assertEqual(result.route, ROUTE_RETRIEVAL_CONTAMINATED)
        self.assertEqual(result.reason, "retrieval_contamination_detected")

    def test_open_set_route_requires_matching_open_set_profile(self):
        calibration = [
            _event(f"unknown-null-{index}", generator_family="unknown")
            for index in range(8)
        ]
        profile = fit_rscptn_null_profile(calibration, self.config)
        event = _event(
            "unknown-query", split="evaluation", operation=OPERATION_CONTENT_EDIT,
            delta=0.80, generator_family="unknown", open_set=True,
        )
        result = evaluate_retrieval_aware_tree_null(event, profile, self.config)
        self.assertEqual(result.route, ROUTE_OPEN_SET_UNKNOWN)

    def test_asset_and_selection_group_leakage_is_insufficient(self):
        event = _event(
            "leak", split="evaluation", operation=OPERATION_CONTENT_EDIT, delta=0.80,
            query_asset_id="asset-null-0",
        )
        result = evaluate_retrieval_aware_tree_null(event, self.profile, self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertIn("leaks", result.reason)

    def test_deterministic_serialization_and_field_hygiene(self):
        event = _event("stable", split="evaluation", operation=OPERATION_CONTENT_EDIT, delta=0.80)
        result = evaluate_retrieval_aware_tree_null(event, self.profile, self.config)
        self.assertEqual(result.to_dict(), evaluate_retrieval_aware_tree_null(event, self.profile, self.config).to_dict())
        forbidden = {"aigc_probability", "confidence", "author", "copyright", "legal"}
        self.assertTrue(forbidden.isdisjoint(result.to_dict()))

    def test_outside_candidate_construction_is_valid_but_not_supported(self):
        event = _event(
            "outside", split="evaluation", operation=OPERATION_CONTENT_EDIT,
            candidates=(_candidate("outside", 1, membership=MEMBERSHIP_OUTSIDE, delta=0.80,
                                   operation=OPERATION_CONTENT_EDIT),),
        )
        result = evaluate_retrieval_aware_tree_null(event, self.profile, self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)


if __name__ == "__main__":
    unittest.main()
