import unittest
from dataclasses import replace

from aigc.invariant_effect import (
    InvariantEffectConfig,
    InvariantEffectObservation,
    InvariantNullSample,
    OPERATION_ORDINARY_PROPAGATION,
    ROUTE_INVARIANT_CANDIDATE,
    ROUTE_INSUFFICIENT,
    ROUTE_NULL_CONSISTENT,
    ROUTE_VIEW_OPERATOR_INCONSISTENT,
    evaluate_invariant_effect,
)


def _digest(char: str) -> str:
    return char * 64


def _observations(*, contrast=0.6, spread_operator=None, scope="content_edit"):
    rows = []
    for view_index in range(3):
        for operator_index, operator_id in enumerate(("blur", "swap")):
            value = contrast
            if spread_operator == operator_id:
                value = contrast + 0.6
            for region_id in ("r0", "r1"):
                rows.append(
                    InvariantEffectObservation(
                        observation_id=f"o-{view_index}-{operator_id}-{region_id}",
                        asset_id="asset-1",
                        pair_id="pair-1",
                        manifest_digest=_digest("a"),
                        canonical_frame_digest=_digest("b"),
                        view_id=f"view-{view_index}",
                        view_digest=_digest(str(view_index + 1)),
                        operator_id=operator_id,
                        operator_config_digest=_digest("c" if operator_id == "blur" else "d"),
                        operator_execution_digest=_digest(str(operator_index + 5)),
                        region_id=region_id,
                        detector_version="detector-v1",
                        score_schema="score-v1",
                        null_profile_digest=_digest("e"),
                        quality_score=0.9,
                        source_match_raw=0.9,
                        observed_effect_raw=value + 0.1,
                        null_effect_raw=0.1,
                        operation_scope=scope,
                    )
                )
    return rows


def _nulls(count=20, *, statistic=0.05):
    return [
        InvariantNullSample(
            sample_id=f"n-{index}",
            group_id=f"g-{index}",
            calibration_dataset_digest=_digest("f"),
            null_profile_digest=_digest("e"),
            detector_version="detector-v1",
            score_schema="score-v1",
            transform_family="jpeg",
            quality_bucket="q2",
            statistic_raw=statistic,
        )
        for index in range(count)
    ]


class InvariantEffectTests(unittest.TestCase):
    def test_stable_cross_view_and_operator_effect_is_candidate(self):
        result = evaluate_invariant_effect(_observations(), _nulls())
        self.assertEqual(result.route, ROUTE_INVARIANT_CANDIDATE)
        self.assertFalse(result.abstained)
        self.assertEqual(result.view_count, 3)
        self.assertEqual(result.operator_count, 2)
        self.assertEqual(result.region_count, 2)
        self.assertGreater(result.invariant_effect_raw, 0.4)
        self.assertNotIn("probability", str(result.to_dict()).lower())

    def test_null_consistent_effect_does_not_become_candidate(self):
        result = evaluate_invariant_effect(_observations(contrast=0.01), _nulls(statistic=0.10))
        self.assertEqual(result.route, ROUTE_NULL_CONSISTENT)
        self.assertTrue(result.abstained)

    def test_spread_across_operator_is_inconsistent(self):
        result = evaluate_invariant_effect(_observations(spread_operator="swap"), _nulls())
        self.assertEqual(result.route, ROUTE_VIEW_OPERATOR_INCONSISTENT)
        self.assertTrue(result.abstained)

    def test_ordinary_propagation_scope_never_becomes_candidate(self):
        result = evaluate_invariant_effect(
            _observations(scope=OPERATION_ORDINARY_PROPAGATION), _nulls()
        )
        self.assertEqual(result.route, ROUTE_NULL_CONSISTENT)

    def test_view_operator_and_null_support_are_fail_closed(self):
        self.assertEqual(
            evaluate_invariant_effect(_observations()[:4], _nulls()).route,
            ROUTE_INSUFFICIENT,
        )
        self.assertEqual(
            evaluate_invariant_effect(_observations(), _nulls(19)).route,
            ROUTE_INSUFFICIENT,
        )

    def test_binding_mismatch_and_duplicate_are_rejected(self):
        rows = _observations()
        rows[0] = replace(rows[0], manifest_digest=_digest("9"))
        self.assertEqual(evaluate_invariant_effect(rows, _nulls()).route, ROUTE_INSUFFICIENT)
        duplicate = _observations()
        duplicate.append(duplicate[0])
        self.assertEqual(evaluate_invariant_effect(duplicate, _nulls()).route, ROUTE_INSUFFICIENT)

    def test_result_is_order_invariant_and_digest_stable(self):
        config = InvariantEffectConfig(maximum_effect_spread=0.3)
        first = evaluate_invariant_effect(_observations(), _nulls(), config=config)
        second = evaluate_invariant_effect(
            list(reversed(_observations())), list(reversed(_nulls())), config=config
        )
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.binding_digest, second.binding_digest)
        self.assertEqual(first.config_digest, second.config_digest)


if __name__ == "__main__":
    unittest.main()
