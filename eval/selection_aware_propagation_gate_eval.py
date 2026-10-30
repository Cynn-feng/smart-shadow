"""Synthetic contract runner for D-073 SAEA propagation gating.

The cases exercise only route binding, replay integrity and fail-closed
behaviour.  They do not load a model and must not be interpreted as AIGC
accuracy, open-set generalisation, or a legal finding.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any, Dict

from aigc.selection_aware_acquisition import (
    GENERATOR_ROUTE_CONFLICT_REVIEW,
    GENERATOR_ROUTE_EVIDENCE_NOT_REQUIRED,
    GENERATOR_ROUTE_KNOWN_FAMILY_SUPPORTED,
    GENERATOR_ROUTE_OPEN_SET_UNKNOWN,
    GENERATOR_ROUTE_REAL_CONSISTENT,
    OPERATION_SCOPE_ORDINARY_PROPAGATION,
    RETRIEVAL_REPLAY_ROUTE_CONSISTENT,
    RETRIEVAL_REPLAY_ROUTE_POISONING,
    SelectionAwareAcquisitionConfig,
    SelectionAwareEvidenceState,
    compute_generator_evidence_digest,
    compute_retrieval_event_digest,
    plan_selection_aware_acquisition,
)


def _hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _state(config: SelectionAwareAcquisitionConfig, case_id: str = "gate-case", **overrides: Any) -> SelectionAwareEvidenceState:
    policy = config.gate_policy_digest
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
        "generator_route": GENERATOR_ROUTE_KNOWN_FAMILY_SUPPORTED,
        "generator_profile_digest": _hex("generator-profile"),
        "generator_input_digest": _hex(f"{case_id}-generator-input"),
        "gate_policy_digest": policy,
        "retrieval_replay_route": RETRIEVAL_REPLAY_ROUTE_CONSISTENT,
    }
    values["generator_evidence_digest"] = compute_generator_evidence_digest(
        values["generator_route"],
        values["generator_profile_digest"],
        values["generator_input_digest"],
        policy,
    )
    values["retrieval_event_digest"] = compute_retrieval_event_digest(
        values["retrieval_replay_route"],
        case_id=case_id,
        asset_id=values["asset_id"],
        manifest_digest=values["manifest_digest"],
        gate_policy_digest=policy,
    )
    values.update(overrides)
    return SelectionAwareEvidenceState(**values)


def run() -> Dict[str, Any]:
    config = SelectionAwareAcquisitionConfig(max_actions=3, max_cost_units=5)
    states = {
        "known_replay_pass": _state(config),
        "generator_evidence_not_required": _state(
            config,
            generator_route=GENERATOR_ROUTE_EVIDENCE_NOT_REQUIRED,
            generator_profile_digest=None,
            generator_input_digest=None,
            generator_evidence_digest=None,
        ),
        "missing_gate": _state(
            config,
            generator_route=None,
            generator_profile_digest=None,
            generator_input_digest=None,
            generator_evidence_digest=None,
            retrieval_replay_route=None,
            retrieval_event_digest=None,
            gate_policy_digest=None,
        ),
        "open_set_unknown": _state(config, generator_route=GENERATOR_ROUTE_OPEN_SET_UNKNOWN),
        "generator_conflict": _state(config, generator_route=GENERATOR_ROUTE_CONFLICT_REVIEW),
        "real_only_neutral": _state(config, generator_route=GENERATOR_ROUTE_REAL_CONSISTENT),
        "ordinary_propagation": _state(
            config,
            operation_scope=OPERATION_SCOPE_ORDINARY_PROPAGATION,
            generator_route=GENERATOR_ROUTE_OPEN_SET_UNKNOWN,
            retrieval_replay_route=RETRIEVAL_REPLAY_ROUTE_POISONING,
        ),
        "generator_digest_mismatch": _state(config, generator_evidence_digest=_hex("tampered-generator")),
        "replay_digest_mismatch": _state(config, retrieval_event_digest=_hex("tampered-replay")),
        "replay_poisoning": _state(config, retrieval_replay_route=RETRIEVAL_REPLAY_ROUTE_POISONING),
    }
    cases = {
        name: plan_selection_aware_acquisition(state, config=config).to_dict()
        for name, state in states.items()
    }
    route_counts: Dict[str, int] = {}
    for result in cases.values():
        route = result["route"]
        route_counts[route] = route_counts.get(route, 0) + 1
    dataset_digest = hashlib.sha256(
        json.dumps(cases, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "version": "selection-aware-propagation-gate-synthetic-v1",
        "count": len(cases),
        "dataset_digest": dataset_digest,
        "gate_policy_digest": config.gate_policy_digest,
        "route_counts": route_counts,
        "cases": cases,
        "interpretation": "synthetic raw contract only; no AIGC probability, authorship, copyright, legal, or deployment claim",
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
