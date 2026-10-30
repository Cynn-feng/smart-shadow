"""Synthetic regression for the replayable A9 sequential policy.

The fixtures exercise a complete ordinary-propagation replay, a deliberate
candidate false positive and a failed probe.  The resulting FPR/interval is
an empirical contract check over these scalar traces only; it is not an AIGC
accuracy, probability or real-image estimate.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from aigc.evidence_budget import EvidenceAcquisitionState
from aigc.policy_calibration import (
    PolicyCalibrationConfig,
    PolicyNullExample,
    evaluate_policy_fpr,
    fit_policy_null_profile,
)
from aigc.sequential_evidence import (
    ProbeObservation,
    ROUTE_CANDIDATE,
    ROUTE_NULL_CONSISTENT,
    SequentialEvidenceResult,
    SequentialPolicyConfig,
    run_sequential_evidence,
)


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _base(case_id: str) -> EvidenceAcquisitionState:
    return EvidenceAcquisitionState(
        asset_id=case_id,
        detector_version="source-residual-v1",
        score_schema="source-residual-score-v1",
        quality_score=0.9,
        source_match_score=0.9,
        regional_coverage_raw=0.95,
        provenance_verified=False,
        null_evaluated=False,
    )


def _trace(case_id: str, policy: SequentialPolicyConfig, kind: str) -> tuple[SequentialEvidenceResult, SequentialEvidenceResult]:
    # Use the first two planner-selected actions.  The same serialized trace
    # is replayed twice to assert policy/evidence digest stability.
    # A partial result is intentionally not treated as a final route; inspect
    # the state through the policy's deterministic action order below.
    from aigc.sequential_evidence import start_sequential_evidence

    state = start_sequential_evidence(_base(case_id), policy=policy)
    first_action = state.next_action
    assert first_action is not None
    calibration = _digest({"policy": state.policy_digest, "case": case_id})
    first = ProbeObservation(
        action_id=first_action.action_id,
        step=1,
        target=first_action.target,
        input_digest=_digest([case_id, "input", 1]),
        output_digest=_digest([case_id, "output", 1]),
        raw_evidence={"probe_index": 1, "score_raw": 0.1},
    )
    # Advance one step only to obtain the second action ID.  Its route is
    # deliberately null/candidate/failure according to the fixture kind.
    from aigc.sequential_evidence import apply_probe_observation

    after_first = apply_probe_observation(state, first)
    second_action = after_first.next_action
    assert second_action is not None
    if kind == "candidate_false_positive":
        second = ProbeObservation(
            action_id=second_action.action_id,
            step=2,
            target=second_action.target,
            input_digest=_digest([case_id, "input", 2]),
            output_digest=_digest([case_id, "output", 2]),
            raw_evidence={"probe_index": 2, "score_raw": 0.9},
            route=ROUTE_CANDIDATE,
            calibration_digest=calibration,
        )
    elif kind == "probe_failure":
        second = ProbeObservation(
            action_id=second_action.action_id,
            step=2,
            target=second_action.target,
            input_digest=_digest([case_id, "input", 2]),
            output_digest=None,
            raw_evidence={"probe_index": 2},
            failure_reason="synthetic_probe_failure",
            ok=False,
        )
    else:
        second = ProbeObservation(
            action_id=second_action.action_id,
            step=2,
            target=second_action.target,
            input_digest=_digest([case_id, "input", 2]),
            output_digest=_digest([case_id, "output", 2]),
            raw_evidence={"probe_index": 2, "score_raw": 0.1},
            route=ROUTE_NULL_CONSISTENT,
            calibration_digest=calibration,
        )
    trace = (first, second)
    one = run_sequential_evidence(_base(case_id), trace, policy=policy)
    two = run_sequential_evidence(_base(case_id), trace, policy=policy)
    return one, two


def run_synthetic_evaluation() -> Dict[str, Any]:
    policy = SequentialPolicyConfig(max_actions=2, max_cost_units=3)
    fixtures = [
        {"case_id": "ordinary-null-1", "kind": "ordinary_null"},
        {"case_id": "ordinary-null-2", "kind": "ordinary_null"},
        {"case_id": "ordinary-null-3", "kind": "ordinary_null"},
        {"case_id": "ordinary-null-4", "kind": "ordinary_null"},
        {"case_id": "ordinary-null-failure", "kind": "probe_failure"},
        {"case_id": "ordinary-null-candidate-artifact", "kind": "candidate_false_positive"},
    ]
    outputs: List[Dict[str, Any]] = []
    examples: List[PolicyNullExample] = []
    replay_stable = True
    for fixture in fixtures:
        one, two = _trace(fixture["case_id"], policy, fixture["kind"])
        replay_stable = replay_stable and one.to_dict() == two.to_dict()
        outputs.append({"case_id": fixture["case_id"], "result": one.to_dict()})
        examples.append(PolicyNullExample.from_result(fixture["case_id"], one))
    profile = fit_policy_null_profile(examples, policy_digest=policy.policy_digest)
    calibration = evaluate_policy_fpr(
        profile,
        policy_digest=policy.policy_digest,
        config=PolicyCalibrationConfig(minimum_null_count=len(examples)),
    )
    route_counts: Dict[str, int] = {}
    for item in outputs:
        route = item["result"]["route"]
        route_counts[route] = route_counts.get(route, 0) + 1
    return {
        "version": "sequential-evidence-synthetic-v1",
        "count": len(outputs),
        "dataset_digest": _digest(fixtures),
        "policy_digest": policy.policy_digest,
        "profile_digest": profile.profile_digest,
        "replay_stable": replay_stable,
        "route_counts": route_counts,
        "policy_calibration": calibration.to_dict(),
        "cases": outputs,
        "interpretation": (
            "synthetic scalar replay only; policy FPR is empirical over the "
            "ordinary-propagation fixtures and does not assign AIGC probability "
            "or prove real-image accuracy"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
