import unittest

from eval.propagation_envelope_eval import run_synthetic_evaluation
from aigc.propagation_envelope import (
    CONTENT_EDIT,
    ORDINARY_PROPAGATION,
    ROUTE_CURVE_INCONSISTENT,
    ROUTE_ENVELOPE_CANDIDATE,
    ROUTE_INSUFFICIENT,
    ROUTE_NULL_CONSISTENT,
    EnvelopeConfig,
    EnvelopeObservation,
    evaluate_propagation_envelope,
    fit_propagation_envelope_profile,
)


class PropagationEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.config = EnvelopeConfig(
            severity_levels=(0, 1, 2),
            minimum_groups_per_level=3,
            alpha=0.20,
            minimum_positive_levels=2,
            minimum_positive_fraction=0.60,
            maximum_curve_discontinuity=0.75,
        )
        self.manifest = "a" * 64
        self.calibration_split = "b" * 64
        self.evaluation_split = "c" * 64

    def observation(
        self,
        group_id,
        severity,
        *,
        asset_id=None,
        split="calibration",
        split_digest=None,
        scope=ORDINARY_PROPAGATION,
        paired_delta=0.02,
        transform="jpeg",
        quality=0.90,
        source=0.90,
        edit_mask=None,
        detector="detector-v1",
        schema="paired-delta-v1",
    ):
        asset_id = asset_id or f"asset-{group_id}"
        split_digest = split_digest or (
            self.calibration_split if split == "calibration" else self.evaluation_split
        )
        # Keep the counterfactual at zero so fixtures state their paired delta
        # directly.  The implementation still computes it from both fields.
        return EnvelopeObservation(
            group_id=group_id,
            asset_id=asset_id,
            severity_level=severity,
            transform_family=transform,
            operation_scope=scope,
            observed_delta_raw=paired_delta,
            counterfactual_delta_raw=0.0,
            quality_score=quality,
            source_match_score=source,
            manifest_digest=self.manifest,
            canonical_frame="canonical-v1",
            split=split,
            split_digest=split_digest,
            detector_version=detector,
            score_schema=schema,
            edit_mask_digest=edit_mask,
        )

    def profile(self, *, deltas=(0.01, 0.02, 0.03, 0.025)):
        rows = [
            self.observation(
                f"null-{group}",
                severity,
                paired_delta=deltas[group],
            )
            for group in range(len(deltas))
            for severity in self.config.severity_levels
        ]
        return fit_propagation_envelope_profile(rows, self.config)

    def query(self, *, values=(0.70, 0.70, 0.70), scope=CONTENT_EDIT, **kwargs):
        mask = kwargs.pop("edit_mask", "f" * 64) if scope == CONTENT_EDIT else None
        return [
            self.observation(
                "query",
                severity,
                asset_id="query-asset",
                split="evaluation",
                split_digest=self.evaluation_split,
                scope=scope,
                paired_delta=value,
                edit_mask=mask,
                **kwargs,
            )
            for severity, value in zip(self.config.severity_levels, values)
        ]

    def test_profile_strata_have_support_and_are_order_invariant(self):
        rows = [
            self.observation(f"null-{group}", severity, paired_delta=0.01 + group * 0.01)
            for group in range(4)
            for severity in self.config.severity_levels
        ]
        forward = fit_propagation_envelope_profile(rows, self.config)
        reverse = fit_propagation_envelope_profile(list(reversed(rows)), self.config)
        self.assertEqual(forward.to_dict(), reverse.to_dict())
        self.assertEqual([item.support for item in forward.strata], [4, 4, 4])
        self.assertEqual(len(forward.profile_digest), 64)

    def test_candidate_requires_persistent_curve_over_levels(self):
        result = evaluate_propagation_envelope(
            self.query(values=(0.70, 0.72, 0.71)), self.profile(), self.config
        )
        self.assertEqual(result.route, ROUTE_ENVELOPE_CANDIDATE)
        self.assertFalse(result.abstained)
        self.assertEqual(result.positive_level_fraction_raw, 1.0)
        self.assertGreater(result.auc_excess_raw, 0.0)
        self.assertNotIn("probability", str(result.to_dict()).lower())

    def test_ordinary_propagation_isolated_from_candidate_route(self):
        result = evaluate_propagation_envelope(
            self.query(values=(0.90, 0.90, 0.90), scope=ORDINARY_PROPAGATION),
            self.profile(),
            self.config,
        )
        self.assertEqual(result.route, ROUTE_NULL_CONSISTENT)
        self.assertFalse(result.abstained)
        self.assertEqual(result.reason, "ordinary_propagation_scope")

    def test_null_consistent_curve_and_isolated_spike(self):
        profile = self.profile()
        null_result = evaluate_propagation_envelope(
            self.query(values=(0.01, 0.02, 0.03)), profile, self.config
        )
        self.assertEqual(null_result.route, ROUTE_NULL_CONSISTENT)
        spike = evaluate_propagation_envelope(
            self.query(values=(0.80, 0.01, 0.01)), profile, self.config
        )
        self.assertEqual(spike.route, ROUTE_CURVE_INCONSISTENT)
        self.assertTrue(spike.abstained)
        self.assertEqual(spike.reason, "insufficient_curve_persistence")

    def test_missing_severity_mask_and_split_leak_are_insufficient(self):
        profile = self.profile()
        missing = self.query(values=(0.80, 0.80))
        result = evaluate_propagation_envelope(missing, profile, self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "severity_level_missing")

        with self.assertRaises(ValueError):
            self.observation(
                "query", 0, asset_id="query-asset", split="evaluation",
                split_digest=self.evaluation_split, scope=CONTENT_EDIT,
                paired_delta=0.80,
            )

        leaked = self.query(values=(0.80, 0.80, 0.80))
        leaked = [
            EnvelopeObservation(
                **{
                    **item.__dict__,
                    "split": "calibration",
                    "split_digest": self.calibration_split,
                }
            )
            for item in leaked
        ]
        leaked_result = evaluate_propagation_envelope(leaked, profile, self.config)
        self.assertEqual(leaked_result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(leaked_result.reason, "evaluation_split_leakage")

        reused = [
            EnvelopeObservation(
                **{
                    **item.__dict__,
                    "asset_id": "asset-null-0",
                }
            )
            for item in self.query(values=(0.80, 0.80, 0.80))
        ]
        reused_result = evaluate_propagation_envelope(reused, profile, self.config)
        self.assertEqual(reused_result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(reused_result.reason, "calibration_asset_reuse")

    def test_binding_schema_and_quality_fail_closed(self):
        profile = self.profile()
        rows = self.query(values=(0.80, 0.80, 0.80))
        mismatch = list(rows)
        mismatch[1] = self.observation(
            "query", 1, asset_id="query-asset", split="evaluation",
            split_digest=self.evaluation_split, scope=CONTENT_EDIT,
            paired_delta=0.80, edit_mask="f" * 64, transform="resize",
        )
        self.assertEqual(
            evaluate_propagation_envelope(mismatch, profile, self.config).reason,
            "binding_mismatch",
        )
        low = self.query(values=(0.80, 0.80, 0.80), quality=0.20)
        self.assertEqual(
            evaluate_propagation_envelope(low, profile, self.config).reason,
            "quality_below_minimum",
        )

        # Reconstructing an invalid content-edit row is rejected by the schema;
        # this is the fail-closed boundary for missing masks.
        with self.assertRaises(ValueError):
            self.observation(
                "query", 0, asset_id="query-asset", split="evaluation",
                split_digest=self.evaluation_split, scope=CONTENT_EDIT,
                paired_delta=0.80, edit_mask=None,
            )

    def test_profile_rejects_content_edits_and_reused_assets(self):
        with self.assertRaises(ValueError):
            fit_propagation_envelope_profile(
                [
                    self.observation(
                        f"edit-{group}", severity, scope=CONTENT_EDIT,
                        edit_mask="f" * 64,
                    )
                    for group in range(4)
                    for severity in self.config.severity_levels
                ],
                self.config,
            )
        reused = [
            self.observation(
                f"null-{group}", severity, asset_id="same-asset"
            )
            for group in range(4)
            for severity in self.config.severity_levels
        ]
        with self.assertRaises(ValueError):
            fit_propagation_envelope_profile(reused, self.config)

    def test_result_is_deterministic_and_excludes_decision_claims(self):
        profile = self.profile()
        rows = self.query(values=(0.70, 0.72, 0.71))
        first = evaluate_propagation_envelope(rows, profile, self.config)
        second = evaluate_propagation_envelope(list(reversed(rows)), profile, self.config)
        self.assertEqual(first.to_dict(), second.to_dict())
        payload = str(first.to_dict()).lower()
        for forbidden in ("probability", "human_supported", "ai_generated_supported", "copyright"):
            self.assertNotIn(forbidden, payload)

    def test_fixture_runner_is_deterministic_and_limited(self):
        first = run_synthetic_evaluation()
        second = run_synthetic_evaluation()
        self.assertEqual(first["dataset_digest"], second["dataset_digest"])
        self.assertEqual(first["profile_digest"], second["profile_digest"])
        self.assertEqual(first["count"], 6)
        self.assertEqual(
            first["route_counts"],
            {
                "curve_inconsistent": 1,
                "envelope_candidate": 1,
                "insufficient": 2,
                "null_consistent": 2,
            },
        )
        self.assertIn("synthetic raw contract only", first["interpretation"])


if __name__ == "__main__":
    unittest.main()
