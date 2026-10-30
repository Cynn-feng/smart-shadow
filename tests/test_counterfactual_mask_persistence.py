import unittest

from aigc.counterfactual_mask_persistence import (
    KIND_DECOY,
    KIND_FACTUAL,
    KIND_ORDINARY_PROPAGATION,
    KIND_WRONG_REFERENCE,
    ROUTE_INSUFFICIENT,
    ROUTE_MASK_INCONSISTENT,
    ROUTE_NULL_CONSISTENT,
    ROUTE_PERSISTENT_CANDIDATE,
    MaskPersistenceConfig,
    MaskPersistenceObservation,
    evaluate_counterfactual_mask_persistence,
)


HEX = "a" * 64
REF = "b" * 64
WRONG_REF = "c" * 64
OBSERVED = "d" * 64


def _row(
    kind, view, regions=(), *, reference=REF, quality=0.90, source=0.90,
    overlap=0.90, executed=True, **kwargs
):
    return MaskPersistenceObservation(
        asset_id="asset-1",
        pair_id="pair-1",
        view_id=f"view-{view}",
        view_order=view,
        kind=kind,
        canonical_frame_digest=HEX,
        manifest_digest="e" * 64,
        detector_version="source-residual-v1",
        score_schema="source-residual-score-v1",
        proposal_mask_digest="f" * 64,
        operator_digest="1" * 64,
        view_spec_digest=("2" * 63) + str(view),
        reference_digest=reference,
        observed_digest=OBSERVED,
        evidence_region_ids=tuple(regions),
        quality_score=quality,
        source_match_score=source,
        mask_overlap_raw=overlap if kind == KIND_FACTUAL else None,
        intervention_executed=executed,
        metadata=kwargs.pop("metadata", {}),
        **kwargs,
    )


def _case(
    factual=("r1", "r2"), ordinary=(), decoy=(), wrong=(), *,
    wrong_reference=WRONG_REF, factual_overlap=0.90,
):
    rows = []
    for view in (1, 2, 3):
        rows.append(_row(KIND_FACTUAL, view, factual, overlap=factual_overlap))
        rows.append(_row(KIND_ORDINARY_PROPAGATION, view, ordinary))
        rows.append(_row(KIND_DECOY, view, decoy))
        rows.append(_row(KIND_WRONG_REFERENCE, view, wrong, reference=wrong_reference))
    return rows


class CounterfactualMaskPersistenceTests(unittest.TestCase):
    def test_persistent_factual_mask_with_quiet_controls_is_candidate(self):
        result = evaluate_counterfactual_mask_persistence(_case())
        self.assertEqual(result.route, ROUTE_PERSISTENT_CANDIDATE)
        self.assertFalse(result.abstained)
        self.assertAlmostEqual(result.factual_mask_persistence_raw, 1.0)
        self.assertAlmostEqual(result.factual_set_jaccard_raw, 1.0)
        self.assertEqual(result.null_mask_hallucination_rate_raw, 0.0)
        self.assertEqual(result.consensus_region_ids, ("r1", "r2"))

    def test_same_label_null_overlap_is_reported_as_hallucination(self):
        result = evaluate_counterfactual_mask_persistence(
            _case(ordinary=("r1",))
        )
        self.assertEqual(result.route, ROUTE_NULL_CONSISTENT)
        self.assertTrue(result.abstained)
        self.assertAlmostEqual(result.control_persistence_raw[KIND_ORDINARY_PROPAGATION], 1.0)
        self.assertEqual(result.reason, "counterfactual_mask_hallucination")

    def test_unrelated_decoy_mask_does_not_count_as_target_hallucination(self):
        result = evaluate_counterfactual_mask_persistence(
            _case(decoy=("unrelated",))
        )
        self.assertEqual(result.route, ROUTE_PERSISTENT_CANDIDATE)
        self.assertEqual(result.control_persistence_raw[KIND_DECOY], 0.0)

    def test_factual_mask_inconsistency_abstains(self):
        rows = []
        for view, region in ((1, "r1"), (2, "r2"), (3, "r3")):
            rows.append(_row(KIND_FACTUAL, view, (region,)))
            rows.append(_row(KIND_ORDINARY_PROPAGATION, view))
            rows.append(_row(KIND_DECOY, view))
            rows.append(_row(KIND_WRONG_REFERENCE, view, reference=WRONG_REF))
        result = evaluate_counterfactual_mask_persistence(rows)
        self.assertEqual(result.route, ROUTE_MASK_INCONSISTENT)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "no_persistent_factual_region")

    def test_missing_control_support_fails_closed(self):
        result = evaluate_counterfactual_mask_persistence(
            [row for row in _case() if row.kind != KIND_DECOY]
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "decoy_view_support_insufficient")

    def test_wrong_reference_must_be_distinct(self):
        result = evaluate_counterfactual_mask_persistence(
            _case(wrong_reference=REF)
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "wrong_reference_not_distinct")

    def test_controls_must_share_factual_reference_and_view_set(self):
        rows = _case()
        rows[1] = _row(KIND_ORDINARY_PROPAGATION, 1, reference=WRONG_REF)
        result = evaluate_counterfactual_mask_persistence(rows)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "ordinary_propagation_reference_mismatch")

        rows = _case()
        rows[1] = _row(KIND_ORDINARY_PROPAGATION, 4)
        result = evaluate_counterfactual_mask_persistence(rows)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "ordinary_propagation_view_set_mismatch")

    def test_quality_and_execution_gates_fail_closed(self):
        rows = _case()
        rows[0] = _row(KIND_FACTUAL, 1, ("r1", "r2"), quality=0.2)
        result = evaluate_counterfactual_mask_persistence(rows)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "factual_quality_below_threshold")

        rows = _case()
        rows[0] = _row(KIND_FACTUAL, 1, ("r1", "r2"), executed=False)
        result = evaluate_counterfactual_mask_persistence(rows)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "intervention_not_executed")

    def test_binding_duplicate_and_metadata_contracts(self):
        rows = _case()
        rows[1] = _row(KIND_ORDINARY_PROPAGATION, 1, metadata={"note": "raw"})
        rows[2] = _row(KIND_DECOY, 1, metadata={"note": "raw"})
        first = evaluate_counterfactual_mask_persistence(rows)
        second = evaluate_counterfactual_mask_persistence(rows)
        self.assertEqual(first.binding_digest, second.binding_digest)
        self.assertEqual(first.evidence_digest, second.evidence_digest)
        duplicate = rows + [_row(KIND_FACTUAL, 1, ("r1", "r2"))]
        duplicate_result = evaluate_counterfactual_mask_persistence(duplicate)
        self.assertEqual(duplicate_result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(duplicate_result.reason, "duplicate_kind_view")
        with self.assertRaises(ValueError):
            _row(KIND_FACTUAL, 1, ("r1",), metadata={"confidence": 0.9})

    def test_optional_factual_roi_overlap_can_be_required(self):
        result = evaluate_counterfactual_mask_persistence(
            _case(factual_overlap=0.20),
            config=MaskPersistenceConfig(require_factual_mask_overlap=True),
        )
        self.assertEqual(result.route, ROUTE_MASK_INCONSISTENT)
        self.assertEqual(result.reason, "factual_mask_overlap_below_threshold")


if __name__ == "__main__":
    unittest.main()
