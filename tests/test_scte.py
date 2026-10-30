import unittest

from aigc.regional_counterfactual import RegionalObservation
from aigc.regional_fdr import RegionalFDRConfig, evaluate_regional_fdr, fit_regional_fdr_profile
from aigc.scte import (
    ROUTE_ACCEPTED,
    ROUTE_INSUFFICIENT,
    SCTEAlignmentFrame,
    SCTEBinding,
    build_scte_query_deltas,
)


DIGESTS = {
    "manifest": "a" * 64,
    "reference": "b" * 64,
    "observed": "c" * 64,
    "counterfactual": "d" * 64,
    "transform": "e" * 64,
    "config": "f" * 64,
}


def binding(*, frame_delta=0, region_ids=("r0", "r1"), chain=("jpeg_q75",)):
    observed_frame = SCTEAlignmentFrame(
        role="observed",
        aligned_shape=(16, 16),
        reference_offset=(0, 0),
        query_offset=(frame_delta, 0),
        dx=frame_delta,
        dy=0,
        alignment_version="regional-alignment-v2",
        resize_version="bilinear-grid-resize-v1",
        config_digest=DIGESTS["config"],
    )
    counterfactual_frame = SCTEAlignmentFrame(
        role="counterfactual",
        aligned_shape=(16, 16),
        reference_offset=(0, 0),
        query_offset=(frame_delta, 0),
        dx=frame_delta,
        dy=0,
        alignment_version="regional-alignment-v2",
        resize_version="bilinear-grid-resize-v1",
        config_digest=DIGESTS["config"],
    )
    return SCTEBinding(
        asset_id="asset-1",
        pair_id="pair-1",
        manifest_digest=DIGESTS["manifest"],
        reference_digest=DIGESTS["reference"],
        observed_digest=DIGESTS["observed"],
        counterfactual_digest=DIGESTS["counterfactual"],
        transform_family="jpeg_q75",
        transform_spec_digest=DIGESTS["transform"],
        propagation_chain=chain,
        observed_alignment=observed_frame,
        counterfactual_alignment=counterfactual_frame,
        region_ids=region_ids,
        detector_version="source-residual-v1",
        score_schema="source-residual-score-v1",
        region_types={region_id: "object" if region_id == "r0" else "background" for region_id in region_ids},
    )


def observations(*, values=((0.80, 0.10), (0.10, 0.08)), chain=("jpeg_q75",), asset="asset-1", pair="pair-1"):
    rows = []
    for index, (observed_score, null_score) in enumerate(values):
        region_id = f"r{index}"
        rows.extend(
            [
                RegionalObservation(
                    asset_id=asset,
                    pair_id=pair,
                    region_id=region_id,
                    version_id=f"obs-{region_id}",
                    transform_family="jpeg_q75",
                    score_raw=observed_score,
                    quality_score=0.9,
                    source_match_score=0.9,
                    kind="observed",
                    detector_version="source-residual-v1",
                    score_schema="source-residual-score-v1",
                    propagation_chain=chain,
                ),
                RegionalObservation(
                    asset_id=asset,
                    pair_id=pair,
                    region_id=region_id,
                    version_id=f"cf-{region_id}",
                    transform_family="jpeg_q75",
                    score_raw=null_score,
                    quality_score=0.9,
                    source_match_score=0.9,
                    kind="counterfactual",
                    detector_version="source-residual-v1",
                    score_schema="source-residual-score-v1",
                    propagation_chain=chain,
                ),
            ]
        )
    return rows


class SCTETests(unittest.TestCase):
    def test_valid_triads_emit_deterministic_region_deltas(self):
        first = build_scte_query_deltas(observations(), binding())
        second = build_scte_query_deltas(list(reversed(observations())), binding())
        self.assertTrue(first.accepted, first.to_dict())
        self.assertEqual(first.route, ROUTE_ACCEPTED)
        self.assertEqual([item.region_id for item in first.query_deltas], ["r0", "r1"])
        self.assertAlmostEqual(first.query_deltas[0].delta_raw, 0.70)
        self.assertAlmostEqual(first.query_deltas[1].delta_raw, 0.02)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(len(first.evidence_digest), 64)
        self.assertEqual(first.binding_digest, first.to_dict()["binding_digest"])

    def test_output_feeds_regional_fdr_without_rewriting_delta(self):
        nulls = []
        for index in range(12):
            for region_id, region_type in (("r0", "object"), ("r1", "background")):
                from aigc.regional_fdr import RegionNullDelta

                nulls.append(
                    RegionNullDelta(
                        group_id=f"null-{index}",
                        transform_family="jpeg_q75",
                        quality_score=0.9,
                        region_id=region_id,
                        region_type=region_type,
                        delta_raw=0.02 + 0.005 * (index % 2),
                        detector_version="source-residual-v1",
                        score_schema="source-residual-score-v1",
                    )
                )
        config = RegionalFDRConfig(minimum_null_count=10, q_value=0.20)
        profile = fit_regional_fdr_profile(nulls, config=config)
        result = build_scte_query_deltas(observations(), binding())
        selected = evaluate_regional_fdr(profile, result.query_deltas, config=config)
        self.assertEqual(selected.route, "candidate_regions")
        self.assertEqual(selected.selected_region_ids, ("r0",))

    def test_missing_counterfactual_fails_closed(self):
        rows = observations()[:-1]
        result = build_scte_query_deltas(rows, binding())
        self.assertFalse(result.accepted)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "incomplete_region_pair")
        self.assertEqual(result.query_deltas, ())

    def test_duplicate_region_fails_closed(self):
        rows = observations()
        rows.append(rows[0])
        result = build_scte_query_deltas(rows, binding())
        self.assertEqual(result.reason, "duplicate_region_observation")
        self.assertEqual(result.query_deltas, ())

    def test_asset_pair_family_chain_and_schema_are_bound(self):
        self.assertEqual(
            build_scte_query_deltas(observations(asset="other"), binding()).reason,
            "asset_identity_mismatch",
        )
        self.assertEqual(
            build_scte_query_deltas(observations(pair="other"), binding()).reason,
            "pair_identity_mismatch",
        )
        self.assertEqual(
            build_scte_query_deltas(observations(chain=("jpeg_q50",)), binding()).reason,
            "propagation_chain_mismatch",
        )
        wrong_schema = observations()
        wrong_schema[0] = RegionalObservation(
            asset_id="asset-1", pair_id="pair-1", region_id="r0", version_id="bad",
            transform_family="jpeg_q75", score_raw=0.8, quality_score=0.9,
            source_match_score=0.9, detector_version="detector-v2",
            score_schema="source-residual-score-v1", propagation_chain=("jpeg_q75",)
        )
        self.assertEqual(build_scte_query_deltas(wrong_schema, binding()).reason, "detector_version_mismatch")

    def test_alignment_geometry_mismatch_is_rejected_before_scoring(self):
        altered = binding()
        altered_frame = SCTEAlignmentFrame(
            role="counterfactual", aligned_shape=(16, 16), reference_offset=(0, 0),
            query_offset=(1, 0), dx=1, dy=0,
            alignment_version="regional-alignment-v2", resize_version="bilinear-grid-resize-v1",
            config_digest=DIGESTS["config"],
        )
        with self.assertRaises(ValueError):
            SCTEBinding(
                asset_id=altered.asset_id, pair_id=altered.pair_id,
                manifest_digest=altered.manifest_digest, reference_digest=altered.reference_digest,
                observed_digest=altered.observed_digest, counterfactual_digest=altered.counterfactual_digest,
                transform_family=altered.transform_family, transform_spec_digest=altered.transform_spec_digest,
                propagation_chain=altered.propagation_chain, observed_alignment=altered.observed_alignment,
                counterfactual_alignment=altered_frame, region_ids=altered.region_ids,
                detector_version=altered.detector_version, score_schema=altered.score_schema,
                region_types=altered.region_types,
            )

    def test_region_set_and_region_types_are_complete(self):
        with self.assertRaises(ValueError):
            binding(region_ids=("r0", "r0"))
        with self.assertRaises(ValueError):
            SCTEBinding(
                asset_id="asset-1", pair_id="pair-1", manifest_digest=DIGESTS["manifest"],
                reference_digest=DIGESTS["reference"], observed_digest=DIGESTS["observed"],
                counterfactual_digest=DIGESTS["counterfactual"], transform_family="jpeg_q75",
                transform_spec_digest=DIGESTS["transform"], propagation_chain=("jpeg_q75",),
                observed_alignment=binding().observed_alignment,
                counterfactual_alignment=binding().counterfactual_alignment,
                region_ids=("r0", "r1"), detector_version="source-residual-v1",
                score_schema="source-residual-score-v1", region_types={"r0": "object"},
            )

    def test_quality_and_source_match_gates_fail_closed(self):
        low_quality = observations()
        low_quality[0] = RegionalObservation(
            asset_id="asset-1", pair_id="pair-1", region_id="r0", version_id="low-quality",
            transform_family="jpeg_q75", score_raw=0.8, quality_score=0.2,
            source_match_score=0.9, kind="observed", propagation_chain=("jpeg_q75",)
        )
        result = build_scte_query_deltas(low_quality, binding())
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "quality_below_threshold")

        low_source_match = observations()
        low_source_match[0] = RegionalObservation(
            asset_id="asset-1", pair_id="pair-1", region_id="r0", version_id="low-source-match",
            transform_family="jpeg_q75", score_raw=0.8, quality_score=0.9,
            source_match_score=0.2, kind="observed", propagation_chain=("jpeg_q75",)
        )
        result = build_scte_query_deltas(low_source_match, binding())
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "source_match_below_threshold")


if __name__ == "__main__":
    unittest.main()
