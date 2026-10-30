import hashlib
import unittest
from dataclasses import replace

from aigc.selection_aware_acquisition import (
    GENERATOR_ROUTE_CONFLICT_REVIEW,
    GENERATOR_ROUTE_EVIDENCE_NOT_REQUIRED,
    GENERATOR_ROUTE_KNOWN_FAMILY_SUPPORTED,
    GENERATOR_ROUTE_OPEN_SET_UNKNOWN,
    GENERATOR_ROUTE_REAL_CONSISTENT,
    OPERATION_SCOPE_ORDINARY_PROPAGATION,
    RETRIEVAL_REPLAY_ROUTE_CONSISTENT,
    RETRIEVAL_REPLAY_ROUTE_POISONING,
    ROUTE_INSUFFICIENT,
    ROUTE_NULL_CONSISTENT,
    ROUTE_REVIEW,
    SelectionAwareAcquisitionConfig,
    SelectionAwareEvidenceState,
    SelectionAwarePropagationGate,
    compute_generator_evidence_digest,
    compute_retrieval_event_digest,
    plan_selection_aware_acquisition,
)


def _hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SelectionAwarePropagationGateTests(unittest.TestCase):
    def setUp(self):
        self.config = SelectionAwareAcquisitionConfig()
        self.policy_digest = self.config.gate_policy_digest

    def _state(self, **overrides):
        values = {
            "case_id": "gate-case",
            "asset_id": "asset-1",
            "manifest_digest": _hex("manifest"),
            "detector_version": "detector-v1",
            "score_schema": "score-v1",
            "quality_score": 0.9,
            "source_match_score": 0.9,
            "selection_route": "selection_specific_candidate",
            "selection_p_value_raw": 0.01,
            "specificity_gap_raw": 0.4,
            "invariant_route": "invariant_candidate",
            "null_support": 20,
            "null_profile_digest": _hex("null"),
            "selection_evidence_digest": _hex("selection"),
            "invariant_evidence_digest": _hex("invariant"),
            "generator_route": GENERATOR_ROUTE_KNOWN_FAMILY_SUPPORTED,
            "generator_profile_digest": _hex("generator-profile"),
            "generator_input_digest": _hex("generator-input"),
            "gate_policy_digest": self.policy_digest,
            "retrieval_replay_route": RETRIEVAL_REPLAY_ROUTE_CONSISTENT,
        }
        values["generator_evidence_digest"] = compute_generator_evidence_digest(
            values["generator_route"],
            values["generator_profile_digest"],
            values["generator_input_digest"],
            values["gate_policy_digest"],
        )
        values["retrieval_event_digest"] = compute_retrieval_event_digest(
            values["retrieval_replay_route"],
            case_id=values["case_id"],
            asset_id=values["asset_id"],
            manifest_digest=values["manifest_digest"],
            gate_policy_digest=values["gate_policy_digest"],
        )
        values.update(overrides)
        return SelectionAwareEvidenceState(**values)

    def test_known_family_and_replay_pass_gate(self):
        result = plan_selection_aware_acquisition(self._state(), config=self.config)
        self.assertEqual(result.status, "candidate")
        self.assertEqual(result.route, "selection_specific_candidate")

    def test_explicit_generator_evidence_not_required_is_auditable(self):
        result = plan_selection_aware_acquisition(
            self._state(
                generator_route=GENERATOR_ROUTE_EVIDENCE_NOT_REQUIRED,
                generator_profile_digest=None,
                generator_input_digest=None,
                generator_evidence_digest=None,
            ),
            config=self.config,
        )
        self.assertEqual(result.route, "selection_specific_candidate")

    def test_missing_gate_is_terminal_and_cannot_probe_to_candidate(self):
        state = self._state(
            generator_route=None,
            generator_profile_digest=None,
            generator_input_digest=None,
            generator_evidence_digest=None,
            retrieval_replay_route=None,
            retrieval_event_digest=None,
            gate_policy_digest=None,
        )
        result = plan_selection_aware_acquisition(state, config=self.config)
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "propagation_gate_missing")
        self.assertEqual(result.actions, ())

    def test_unknown_generator_and_conflict_are_review_routes(self):
        for route in (GENERATOR_ROUTE_OPEN_SET_UNKNOWN, GENERATOR_ROUTE_CONFLICT_REVIEW):
            result = plan_selection_aware_acquisition(self._state(generator_route=route), config=self.config)
            self.assertEqual(result.route, ROUTE_REVIEW)
            self.assertEqual(result.actions, ())

    def test_profile_input_and_evidence_digest_bindings_fail_closed(self):
        cases = (
            {"generator_profile_digest": _hex("tampered-profile")},
            {"generator_input_digest": _hex("tampered-input")},
            {"generator_evidence_digest": _hex("tampered-evidence")},
            {"gate_policy_digest": _hex("tampered-policy")},
        )
        for updates in cases:
            result = plan_selection_aware_acquisition(self._state(**updates), config=self.config)
            self.assertEqual(result.route, ROUTE_INSUFFICIENT)
            self.assertIn("digest", result.reason)

    def test_retrieval_event_digest_binding_fails_closed(self):
        result = plan_selection_aware_acquisition(
            self._state(retrieval_event_digest=_hex("tampered-event")), config=self.config
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "retrieval_event_digest_mismatch")

    def test_real_consistent_is_neutral(self):
        result = plan_selection_aware_acquisition(
            self._state(generator_route=GENERATOR_ROUTE_REAL_CONSISTENT), config=self.config
        )
        self.assertEqual(result.route, ROUTE_REVIEW)
        self.assertEqual(result.reason, "generator_real_consistent_neutral")
        self.assertEqual(result.actions, ())

    def test_ordinary_propagation_is_null_even_with_positive_generator_signal(self):
        result = plan_selection_aware_acquisition(
            self._state(
                operation_scope=OPERATION_SCOPE_ORDINARY_PROPAGATION,
                generator_route=GENERATOR_ROUTE_OPEN_SET_UNKNOWN,
                retrieval_replay_route=RETRIEVAL_REPLAY_ROUTE_POISONING,
            ),
            config=self.config,
        )
        self.assertEqual(result.route, ROUTE_NULL_CONSISTENT)
        self.assertEqual(result.reason, "ordinary_propagation_scope")
        self.assertEqual(result.actions, ())

    def test_replay_poisoning_cannot_be_repaired_by_probe(self):
        result = plan_selection_aware_acquisition(
            self._state(retrieval_replay_route=RETRIEVAL_REPLAY_ROUTE_POISONING), config=self.config
        )
        self.assertEqual(result.route, ROUTE_REVIEW)
        self.assertEqual(result.reason, "retrieval_replay_not_safe")
        self.assertEqual(result.actions, ())

    def test_gate_object_populates_flat_state_and_digest_is_stable(self):
        base = self._state()
        gate = SelectionAwarePropagationGate(
            generator_route=base.generator_route,
            generator_profile_digest=base.generator_profile_digest,
            generator_input_digest=base.generator_input_digest,
            generator_evidence_digest=base.generator_evidence_digest,
            retrieval_replay_route=base.retrieval_replay_route,
            retrieval_event_digest=base.retrieval_event_digest,
            gate_policy_digest=base.gate_policy_digest,
        )
        state = SelectionAwareEvidenceState(
            case_id=base.case_id,
            asset_id=base.asset_id,
            manifest_digest=base.manifest_digest,
            detector_version=base.detector_version,
            score_schema=base.score_schema,
            quality_score=base.quality_score,
            source_match_score=base.source_match_score,
            selection_route=base.selection_route,
            selection_p_value_raw=base.selection_p_value_raw,
            specificity_gap_raw=base.specificity_gap_raw,
            invariant_route=base.invariant_route,
            null_support=base.null_support,
            null_profile_digest=base.null_profile_digest,
            selection_evidence_digest=base.selection_evidence_digest,
            invariant_evidence_digest=base.invariant_evidence_digest,
            propagation_gate=gate,
        )
        first = plan_selection_aware_acquisition(state, config=self.config)
        second = plan_selection_aware_acquisition(state, config=self.config)
        self.assertEqual(first.plan_digest, second.plan_digest)
        self.assertEqual(state.generator_route, GENERATOR_ROUTE_KNOWN_FAMILY_SUPPORTED)

    def test_probability_field_stays_forbidden_in_probe_updates(self):
        with self.assertRaises(ValueError):
            from aigc.selection_aware_acquisition import SelectionAwareObservation

            SelectionAwareObservation(
                action_id="append_matched_decoy",
                step=1,
                input_digest=self._state().input_digest,
                output_digest=_hex("out"),
                raw_updates={"aigc_probability": 0.9},
            )

    def test_gate_digest_and_input_digest_repeat_exactly(self):
        state = self._state()
        self.assertEqual(state.input_digest, self._state().input_digest)
        self.assertEqual(
            compute_generator_evidence_digest(
                state.generator_route,
                state.generator_profile_digest,
                state.generator_input_digest,
                state.gate_policy_digest,
            ),
            state.generator_evidence_digest,
        )


if __name__ == "__main__":
    unittest.main()
