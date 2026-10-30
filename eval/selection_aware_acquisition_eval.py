"""Synthetic contract runner for SAEA-v1.

This runner checks deterministic action selection, replay, failure closure and
bounded costs.  It uses scalar state summaries only; it is not an AIGC
accuracy, FPR, probability or customer-workflow result.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from aigc.selection_aware_acquisition import (
    ACTION_ALTERNATE_OPERATOR,
    ACTION_ALTERNATE_VIEW,
    ACTION_APPEND_DECOY,
    ACTION_BUILD_NULL,
    ACTION_REALIGN_QUALITY,
    GENERATOR_ROUTE_KNOWN_FAMILY_SUPPORTED,
    RETRIEVAL_REPLAY_ROUTE_CONSISTENT,
    compute_generator_evidence_digest,
    compute_retrieval_event_digest,
    SelectionAwareAcquisitionConfig,
    SelectionAwareEvidenceState,
    SelectionAwareObservation,
    run_selection_aware_acquisition,
)


def _hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _state(case_id: str, **overrides: Any) -> SelectionAwareEvidenceState:
    values: Dict[str, Any] = {
        "case_id": case_id,
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
    }
    values.update(overrides)
    gate_policy = SelectionAwareAcquisitionConfig().gate_policy_digest
    values.setdefault("operation_scope", "content_edit")
    values.setdefault("generator_route", GENERATOR_ROUTE_KNOWN_FAMILY_SUPPORTED)
    values.setdefault("generator_profile_digest", _hex(f"{case_id}-generator-profile"))
    values.setdefault("generator_input_digest", _hex(f"{case_id}-generator-input"))
    values.setdefault("gate_policy_digest", gate_policy)
    values.setdefault(
        "generator_evidence_digest",
        compute_generator_evidence_digest(
            values["generator_route"],
            values["generator_profile_digest"],
            values["generator_input_digest"],
            gate_policy,
        ),
    )
    values.setdefault("retrieval_replay_route", RETRIEVAL_REPLAY_ROUTE_CONSISTENT)
    values.setdefault(
        "retrieval_event_digest",
        compute_retrieval_event_digest(
            values["retrieval_replay_route"],
            case_id=values["case_id"],
            asset_id=values["asset_id"],
            manifest_digest=values["manifest_digest"],
            gate_policy_digest=gate_policy,
        ),
    )
    return SelectionAwareEvidenceState(**values)


def _observation(action: str, state: SelectionAwareEvidenceState, step: int, updates: Dict[str, Any], *, ok: bool = True) -> SelectionAwareObservation:
    return SelectionAwareObservation(
        action_id=action,
        step=step,
        input_digest=state.input_digest,
        output_digest=_hex(f"{state.case_id}-{step}-output") if ok else None,
        raw_updates=updates,
        ok=ok,
        failure_reason=None if ok else "executor_unavailable",
    )


def _run_case(case_id: str, initial: SelectionAwareEvidenceState, updates: List[Dict[str, Any]], *, failed_step: int | None = None, config: SelectionAwareAcquisitionConfig) -> Dict[str, Any]:
    state = initial
    trace: List[SelectionAwareObservation] = []
    for step, update in enumerate(updates, start=1):
        if failed_step == step:
            action = {
                "selection_ambiguous": ACTION_APPEND_DECOY,
                "null_support": ACTION_BUILD_NULL,
                "invariant_route": ACTION_ALTERNATE_VIEW if step == 1 else ACTION_ALTERNATE_OPERATOR,
                "quality": ACTION_REALIGN_QUALITY,
            }.get(case_id, ACTION_APPEND_DECOY)
        else:
            if case_id == "selection_ambiguous":
                action = ACTION_APPEND_DECOY
            elif case_id == "null_support":
                action = ACTION_BUILD_NULL
            elif case_id == "invariant_route":
                action = ACTION_ALTERNATE_VIEW if step == 1 else ACTION_ALTERNATE_OPERATOR
            elif case_id == "quality":
                action = ACTION_REALIGN_QUALITY
            else:
                action = ACTION_APPEND_DECOY
        observation = _observation(action, state, step, update, ok=failed_step != step)
        trace.append(observation)
        if failed_step == step:
            break
        # The next observation must bind to the state after this update.  We
        # replay once per prefix to obtain that state without duplicating the
        # policy transition implementation.
        prefix = run_selection_aware_acquisition(initial, trace, config=config)
        if step < len(updates):
            # Reconstruct the scalar state for the next input from the same
            # update fields; the final result is still produced by full replay.
            current_values = state.to_dict()
            current_values.update(update)
            current_values["completed_actions"] = tuple(item.action_id for item in trace)
            state = SelectionAwareEvidenceState(**current_values)
    result = run_selection_aware_acquisition(initial, trace, config=config)
    return {"case_id": case_id, "result": result.to_dict()}


def run() -> Dict[str, Any]:
    config = SelectionAwareAcquisitionConfig(max_actions=3, max_cost_units=5)
    cases = [
        _run_case(
            "selection_ambiguous",
            _state("selection_ambiguous", selection_route="selection_ambiguous"),
            [{"selection_route": "selection_specific_candidate", "selection_p_value_raw": 0.01, "specificity_gap_raw": 0.4, "selection_evidence_digest": _hex("selection-after-decoy")}],
            config=config,
        ),
        _run_case(
            "null_support",
            _state("null_support", selection_route="insufficient", selection_p_value_raw=None, specificity_gap_raw=None, null_support=0, null_profile_digest=None),
            [{"selection_route": "selection_specific_candidate", "selection_p_value_raw": 0.01, "specificity_gap_raw": 0.4, "null_support": 20, "null_profile_digest": _hex("null-after-build")}],
            config=config,
        ),
        _run_case(
            "invariant_route",
            _state("invariant_route", invariant_route="view_operator_inconsistent"),
            [{"invariant_route": "view_operator_inconsistent"}, {"invariant_route": "invariant_candidate", "invariant_evidence_digest": _hex("invariant-after-operator")}],
            config=config,
        ),
        _run_case(
            "quality",
            _state("quality", quality_score=0.2),
            [{"quality_score": 0.9, "alignment_ok": True}],
            config=config,
        ),
        _run_case(
            "failed_probe",
            _state("failed_probe", selection_route="selection_ambiguous"),
            [{}],
            failed_step=1,
            config=config,
        ),
    ]
    route_counts: Dict[str, int] = {}
    for case in cases:
        route = case["result"]["route"]
        route_counts[route] = route_counts.get(route, 0) + 1
    dataset_digest = hashlib.sha256(json.dumps(cases, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        "version": "selection-aware-acquisition-synthetic-v1",
        "count": len(cases),
        "dataset_digest": dataset_digest,
        "config_digest": config.policy_digest,
        "route_counts": route_counts,
        "cases": cases,
        "interpretation": "synthetic raw contract only; SAEA routes are not AIGC probabilities or legal findings",
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
