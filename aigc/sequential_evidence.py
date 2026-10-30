"""Replayable, fail-closed sequential evidence acquisition.

The existing :mod:`aigc.evidence_budget` module creates a bounded *plan*.
This module is the small execution/replay layer for A9.  It deliberately does
not call a model or turn a raw detector score into a probability.  A probe
executor supplies a :class:`ProbeObservation`; the state machine validates the
fixed action order, budget, digests and route gates, then records the result.

The state machine is intentionally immutable.  Replaying the same initial
state, policy and observations therefore produces the same policy/evidence
digests.  A production executor can attach image input/output hashes, timing
and model-side calibration digests without putting those operations into this
dependency-light package.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .evidence_budget import (
    ACTION_BUILD_COUNTERFACTUAL,
    ACTION_REALIGN_REGION,
    ACTION_REPEAT_DETECTOR,
    ACTION_VERIFY_PROVENANCE,
    ACTION_ZOOM_REGION,
    EvidenceAcquisitionConfig,
    EvidenceAcquisitionState,
    EvidenceAction,
    PLAN_ACQUIRE,
    plan_evidence_acquisition,
)


VERSION = "sequential-evidence-v1"
RESULT_SCHEMA = "sequential-evidence-result-v1"

ROUTE_CANDIDATE = "candidate_edit"
ROUTE_NULL_CONSISTENT = "null_consistent"
ROUTE_CONFLICT_REVIEW = "conflict_review"
ROUTE_REVIEW = "review"
ROUTE_INSUFFICIENT = "insufficient"

STATUS_CONTINUE = "continue"
STATUS_COMPLETE = "complete"

_ROUTES = {
    ROUTE_CANDIDATE,
    ROUTE_NULL_CONSISTENT,
    ROUTE_CONFLICT_REVIEW,
    ROUTE_REVIEW,
    ROUTE_INSUFFICIENT,
}
_TERMINAL_ABSTAIN_ROUTES = {
    ROUTE_CONFLICT_REVIEW,
    ROUTE_REVIEW,
    ROUTE_INSUFFICIENT,
}
_ACTIONS = {
    ACTION_VERIFY_PROVENANCE,
    ACTION_REALIGN_REGION,
    ACTION_BUILD_COUNTERFACTUAL,
    ACTION_ZOOM_REGION,
    ACTION_REPEAT_DETECTOR,
}


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _hex_digest(name: str, value: str, *, allow_none: bool = False) -> Optional[str]:
    if value is None and allow_none:
        return None
    value = _text(name, value)
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
    return value.lower()


def _unit(name: str, value: Optional[float], *, allow_none: bool = False) -> Optional[float]:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    return normalized


def _positive_int(name: str, value: int, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be a {qualifier} integer")
    return value


def _normalise_json_mapping(name: str, value: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")

    def reject_probability_key(key: Any) -> None:
        key_text = str(key).lower()
        # A calibrated p-value is valid raw evidence metadata.  What this
        # contract forbids is silently labelling a detector score as a
        # probability (or serializing an AIGC probability that this module
        # never computed).
        if "probability" in key_text or key_text in {"aigc_prob", "ai_prob"}:
            raise ValueError(f"{name} cannot contain probability fields; retain raw evidence only")

    def normalise(item: Any) -> Any:
        if isinstance(item, Mapping):
            result: Dict[str, Any] = {}
            for key, child in item.items():
                reject_probability_key(key)
                if not isinstance(key, str):
                    raise ValueError(f"{name} keys must be strings")
                result[key] = normalise(child)
            return dict(sorted(result.items()))
        if isinstance(item, (list, tuple)):
            return [normalise(child) for child in item]
        if isinstance(item, bool) or item is None or isinstance(item, (str, int)):
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError(f"{name} must not contain non-finite numbers")
            return float(item)
        raise ValueError(f"{name} contains a non-JSON value")

    return normalise(value)


@dataclass(frozen=True)
class PolicyAction:
    """One action in the versioned policy execution order."""

    action_id: str
    cost_units: int
    target: str = "asset"
    reason: str = ""

    def __post_init__(self) -> None:
        action_id = _text("action_id", self.action_id)
        if action_id not in _ACTIONS:
            raise ValueError(f"unsupported action_id: {action_id}")
        object.__setattr__(self, "action_id", action_id)
        _positive_int("cost_units", self.cost_units)
        _text("target", self.target)
        if self.reason:
            _text("reason", self.reason)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "cost_units": self.cost_units,
            "target": self.target,
            "reason": self.reason,
        }


_DEFAULT_ACTION_ORDER = (
    ACTION_VERIFY_PROVENANCE,
    ACTION_BUILD_COUNTERFACTUAL,
    ACTION_REALIGN_REGION,
    ACTION_ZOOM_REGION,
    ACTION_REPEAT_DETECTOR,
)
_DEFAULT_COSTS = {
    ACTION_VERIFY_PROVENANCE: 1,
    ACTION_BUILD_COUNTERFACTUAL: 2,
    ACTION_REALIGN_REGION: 2,
    ACTION_ZOOM_REGION: 2,
    ACTION_REPEAT_DETECTOR: 2,
}


@dataclass(frozen=True)
class SequentialPolicyConfig:
    """Versioned policy gates used to build a replayable action queue."""

    max_actions: int = 3
    max_cost_units: int = 5
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    minimum_coverage: float = 0.75
    uncertainty_trigger: float = 0.50
    action_order: Tuple[str, ...] = _DEFAULT_ACTION_ORDER
    action_costs: Tuple[Tuple[str, int], ...] = tuple(_DEFAULT_COSTS.items())
    version: str = VERSION

    def __post_init__(self) -> None:
        _positive_int("max_actions", self.max_actions)
        _positive_int("max_cost_units", self.max_cost_units)
        for name in (
            "minimum_quality",
            "minimum_source_match",
            "minimum_coverage",
            "uncertainty_trigger",
        ):
            _unit(name, getattr(self, name))
        if isinstance(self.action_order, (str, bytes)) or not self.action_order:
            raise ValueError("action_order must be a non-empty sequence")
        order = tuple(_text("action_id", item) for item in self.action_order)
        if len(set(order)) != len(order) or any(item not in _ACTIONS for item in order):
            raise ValueError("action_order must contain unique supported actions")
        costs = tuple((
            _text("action_id", action),
            _positive_int("cost_units", cost),
        ) for action, cost in self.action_costs)
        if len({action for action, _ in costs}) != len(costs):
            raise ValueError("action_costs must contain unique action IDs")
        cost_map = dict(costs)
        if any(action not in cost_map for action in order):
            raise ValueError("action_costs must cover action_order")
        object.__setattr__(self, "action_order", order)
        object.__setattr__(self, "action_costs", tuple(sorted(costs)))
        _text("version", self.version)

    @property
    def cost_map(self) -> Dict[str, int]:
        return dict(self.action_costs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "max_actions": self.max_actions,
            "max_cost_units": self.max_cost_units,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "minimum_coverage": self.minimum_coverage,
            "uncertainty_trigger": self.uncertainty_trigger,
            "action_order": list(self.action_order),
            "action_costs": [[key, value] for key, value in self.action_costs],
        }

    @property
    def policy_digest(self) -> str:
        return _digest(self.to_dict())

    # ``digest`` is a convenient alias used by the other calibration modules.
    @property
    def digest(self) -> str:
        return self.policy_digest


@dataclass(frozen=True)
class ProbeObservation:
    """A single executed probe, including failure and raw evidence audit."""

    action_id: str
    step: int
    target: str
    input_digest: str
    output_digest: Optional[str] = None
    parameters: Mapping[str, Any] = None  # type: ignore[assignment]
    raw_evidence: Mapping[str, Any] = None  # type: ignore[assignment]
    calibration_digest: Optional[str] = None
    elapsed_ms: Optional[float] = None
    failure_reason: Optional[str] = None
    route: Optional[str] = None
    ok: bool = True
    stop_requested: bool = False

    def __post_init__(self) -> None:
        action_id = _text("action_id", self.action_id)
        if action_id not in _ACTIONS:
            raise ValueError(f"unsupported action_id: {action_id}")
        object.__setattr__(self, "action_id", action_id)
        _positive_int("step", self.step)
        object.__setattr__(self, "target", _text("target", self.target))
        _hex_digest("input_digest", self.input_digest)
        _hex_digest("output_digest", self.output_digest, allow_none=True)
        params = _normalise_json_mapping("parameters", self.parameters or {})
        evidence = _normalise_json_mapping("raw_evidence", self.raw_evidence or {})
        object.__setattr__(self, "parameters", params)
        object.__setattr__(self, "raw_evidence", evidence)
        _hex_digest("calibration_digest", self.calibration_digest, allow_none=True)
        if self.elapsed_ms is not None:
            if isinstance(self.elapsed_ms, bool) or not isinstance(self.elapsed_ms, (int, float)):
                raise ValueError("elapsed_ms must be finite and non-negative")
            elapsed = float(self.elapsed_ms)
            if not math.isfinite(elapsed) or elapsed < 0.0:
                raise ValueError("elapsed_ms must be finite and non-negative")
            object.__setattr__(self, "elapsed_ms", elapsed)
        if self.route is not None:
            route = _text("route", self.route)
            if route not in _ROUTES:
                raise ValueError("invalid raw evidence route")
            object.__setattr__(self, "route", route)
        if not isinstance(self.ok, bool) or not isinstance(self.stop_requested, bool):
            raise ValueError("ok and stop_requested must be bool")
        if not self.ok:
            if not self.failure_reason or not self.failure_reason.strip():
                raise ValueError("failed probe requires failure_reason")
            if self.route not in (None, ROUTE_REVIEW, ROUTE_CONFLICT_REVIEW, ROUTE_INSUFFICIENT):
                raise ValueError("failed probe cannot claim a concordant route")
        elif self.failure_reason is not None and self.failure_reason.strip():
            raise ValueError("successful probe cannot have failure_reason")
        if self.route in (ROUTE_CANDIDATE, ROUTE_NULL_CONSISTENT) and not self.ok:
            raise ValueError("failed probe cannot claim candidate/null route")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "step": self.step,
            "target": self.target,
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "parameters": dict(self.parameters),
            "raw_evidence": dict(self.raw_evidence),
            "calibration_digest": self.calibration_digest,
            "elapsed_ms": self.elapsed_ms,
            "failure_reason": self.failure_reason,
            "route": self.route,
            "ok": self.ok,
            "stop_requested": self.stop_requested,
        }


@dataclass(frozen=True)
class AdaptiveEvidenceState:
    """Immutable state carried between probe executions."""

    asset_id: str
    detector_version: str
    score_schema: str
    quality_score: Optional[float]
    source_match_score: Optional[float]
    current_routes: Tuple[str, ...] = ()
    completed_actions: Tuple[str, ...] = ()
    remaining_actions: Tuple[str, ...] = ()
    spent_cost_units: int = 0
    remaining_cost_units: int = 0
    policy_digest: str = ""
    calibration_digest: Optional[str] = None
    step: int = 0
    action_specs: Tuple[PolicyAction, ...] = ()
    observations: Tuple[ProbeObservation, ...] = ()
    status: str = STATUS_CONTINUE
    route: Optional[str] = None
    reason: str = "ready"

    def __post_init__(self) -> None:
        _text("asset_id", self.asset_id)
        _text("detector_version", self.detector_version)
        _text("score_schema", self.score_schema)
        _unit("quality_score", self.quality_score, allow_none=True)
        _unit("source_match_score", self.source_match_score, allow_none=True)
        _positive_int("spent_cost_units", self.spent_cost_units, allow_zero=True)
        _positive_int("remaining_cost_units", self.remaining_cost_units, allow_zero=True)
        _positive_int("step", self.step, allow_zero=True)
        if self.policy_digest:
            _hex_digest("policy_digest", self.policy_digest)
        _hex_digest("calibration_digest", self.calibration_digest, allow_none=True)
        if self.status not in {STATUS_CONTINUE, STATUS_COMPLETE}:
            raise ValueError("invalid sequential state status")
        if self.route is not None and self.route not in _ROUTES:
            raise ValueError("invalid sequential state route")
        routes = tuple(_text("current_route", route) for route in self.current_routes)
        if any(route not in _ROUTES for route in routes):
            raise ValueError("invalid current route")
        object.__setattr__(self, "current_routes", routes)
        completed = tuple(_text("completed_action", action) for action in self.completed_actions)
        remaining = tuple(_text("remaining_action", action) for action in self.remaining_actions)
        if len(set(completed)) != len(completed) or len(set(remaining)) != len(remaining):
            raise ValueError("completed_actions and remaining_actions must be unique")
        if set(completed).intersection(remaining):
            raise ValueError("an action cannot be completed and remaining")
        if any(action not in _ACTIONS for action in (*completed, *remaining)):
            raise ValueError("unsupported action in state")
        object.__setattr__(self, "completed_actions", completed)
        object.__setattr__(self, "remaining_actions", remaining)
        specs = tuple(self.action_specs)
        if any(not isinstance(spec, PolicyAction) for spec in specs):
            raise ValueError("action_specs must contain PolicyAction values")
        if len({spec.action_id for spec in specs}) != len(specs):
            raise ValueError("action_specs must be unique")
        spec_ids = {spec.action_id for spec in specs}
        if not set(completed).union(remaining).issubset(spec_ids):
            raise ValueError("action_specs must cover state actions")
        object.__setattr__(self, "action_specs", specs)
        observations = tuple(self.observations)
        if any(not isinstance(item, ProbeObservation) for item in observations):
            raise ValueError("observations must contain ProbeObservation values")
        if len(observations) != self.step:
            raise ValueError("step must equal the number of observations")
        object.__setattr__(self, "observations", observations)
        if self.status == STATUS_COMPLETE and self.remaining_actions and self.route is None:
            # A complete state may stop on a fail-closed route, but cannot claim
            # completion while silently dropping executable actions.
            raise ValueError("complete state with remaining actions requires a terminal route")

    @property
    def evidence_digest(self) -> str:
        return _digest({
            "version": VERSION,
            "asset_id": self.asset_id,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "policy_digest": self.policy_digest,
            "action_specs": [spec.to_dict() for spec in self.action_specs],
            "completed_actions": list(self.completed_actions),
            "remaining_actions": list(self.remaining_actions),
            "spent_cost_units": self.spent_cost_units,
            "remaining_cost_units": self.remaining_cost_units,
            "observations": [item.to_dict() for item in self.observations],
            "route": self.route,
            "reason": self.reason,
        })

    @property
    def next_action(self) -> Optional[PolicyAction]:
        if self.status != STATUS_CONTINUE or not self.remaining_actions:
            return None
        by_id = {spec.action_id: spec for spec in self.action_specs}
        return by_id.get(self.remaining_actions[0])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "asset_id": self.asset_id,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "current_routes": list(self.current_routes),
            "completed_actions": list(self.completed_actions),
            "remaining_actions": list(self.remaining_actions),
            "spent_cost_units": self.spent_cost_units,
            "remaining_cost_units": self.remaining_cost_units,
            "policy_digest": self.policy_digest,
            "calibration_digest": self.calibration_digest,
            "step": self.step,
            "action_specs": [spec.to_dict() for spec in self.action_specs],
            "observations": [item.to_dict() for item in self.observations],
            "status": self.status,
            "route": self.route,
            "reason": self.reason,
            "evidence_digest": self.evidence_digest,
        }


@dataclass(frozen=True)
class SequentialEvidenceResult:
    """Serializable result for a complete or still-pending replay."""

    route: str
    abstained: bool
    reason: str
    steps: Tuple[ProbeObservation, ...]
    spent_cost: int
    remaining_cost: int
    policy_digest: str
    calibration_digest: Optional[str]
    evidence_digest: str
    status: str = STATUS_COMPLETE
    current_routes: Tuple[str, ...] = ()
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.route not in _ROUTES:
            raise ValueError("invalid sequential result route")
        if self.route in _TERMINAL_ABSTAIN_ROUTES and not self.abstained:
            raise ValueError("fail-closed routes must abstain")
        if self.route in {ROUTE_CANDIDATE, ROUTE_NULL_CONSISTENT} and self.abstained:
            raise ValueError("concordant routes must not abstain")
        if not isinstance(self.abstained, bool):
            raise ValueError("abstained must be bool")
        _text("reason", self.reason)
        if not isinstance(self.steps, tuple) or any(not isinstance(step, ProbeObservation) for step in self.steps):
            raise ValueError("steps must be a tuple of ProbeObservation values")
        _positive_int("spent_cost", self.spent_cost, allow_zero=True)
        _positive_int("remaining_cost", self.remaining_cost, allow_zero=True)
        _hex_digest("policy_digest", self.policy_digest)
        _hex_digest("calibration_digest", self.calibration_digest, allow_none=True)
        _hex_digest("evidence_digest", self.evidence_digest)
        if self.status not in {STATUS_CONTINUE, STATUS_COMPLETE}:
            raise ValueError("invalid sequential result status")
        routes = tuple(_text("current_route", route) for route in self.current_routes)
        if any(route not in _ROUTES for route in routes):
            raise ValueError("invalid current route")
        object.__setattr__(self, "current_routes", routes)

    @property
    def audit(self) -> Tuple[Dict[str, Any], ...]:
        return tuple(step.to_dict() for step in self.steps)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "result_schema": RESULT_SCHEMA,
            "route": self.route,
            "abstained": self.abstained,
            "reason": self.reason,
            "steps": [step.to_dict() for step in self.steps],
            "audit": list(self.audit),
            "spent_cost": self.spent_cost,
            "remaining_cost": self.remaining_cost,
            "policy_digest": self.policy_digest,
            "calibration_digest": self.calibration_digest,
            "evidence_digest": self.evidence_digest,
            "status": self.status,
            "current_routes": list(self.current_routes),
        }


def _policy_to_planner_config(policy: SequentialPolicyConfig) -> EvidenceAcquisitionConfig:
    return EvidenceAcquisitionConfig(
        max_actions=policy.max_actions,
        max_cost_units=policy.max_cost_units,
        minimum_quality=policy.minimum_quality,
        minimum_source_match=policy.minimum_source_match,
        minimum_coverage=policy.minimum_coverage,
        uncertainty_trigger=policy.uncertainty_trigger,
    )


def _action_specs(actions: Sequence[EvidenceAction], policy: SequentialPolicyConfig) -> Tuple[PolicyAction, ...]:
    cost_map = policy.cost_map
    specs = []
    order_index = {action_id: index for index, action_id in enumerate(policy.action_order)}
    ordered_actions = sorted(actions, key=lambda item: order_index.get(item.action, len(order_index)))
    for action in ordered_actions:
        # The planner's cost is part of its output.  A policy cost mismatch is
        # a configuration error rather than an opportunity to silently change
        # the budget during replay.
        expected_cost = cost_map.get(action.action)
        if expected_cost is None or expected_cost != action.cost_units:
            raise ValueError("planner action cost does not match policy action cost")
        specs.append(PolicyAction(action.action, expected_cost, action.target, action.reason))
    return tuple(specs)


def start_sequential_evidence(
    state: EvidenceAcquisitionState,
    *,
    policy: Optional[SequentialPolicyConfig] = None,
) -> AdaptiveEvidenceState:
    """Create a deterministic A9 state from the existing planner state."""

    if not isinstance(state, EvidenceAcquisitionState):
        raise ValueError("state must be EvidenceAcquisitionState")
    cfg = policy or SequentialPolicyConfig()
    plan = plan_evidence_acquisition(state, config=_policy_to_planner_config(cfg))
    pending_specs = list(_action_specs(plan.actions, cfg))
    specs = list(pending_specs)
    # ``EvidenceAcquisitionState.completed_actions`` may refer to actions
    # performed before the A9 replay began.  Keep those IDs in the immutable
    # audit schema so the state cannot silently forget them, while retaining
    # only planner-selected actions in the pending queue.
    spec_ids = {spec.action_id for spec in specs}
    for action_id in state.completed_actions:
        if action_id not in spec_ids:
            specs.append(PolicyAction(
                action_id,
                cfg.cost_map[action_id],
                "asset",
                "completed_before_policy_start",
            ))
    order_index = {action_id: index for index, action_id in enumerate(cfg.action_order)}
    specs = tuple(sorted(specs, key=lambda item: order_index.get(item.action_id, len(order_index))))
    terminal = plan.status != PLAN_ACQUIRE
    reason = plan.reason if terminal else "evidence_gaps_within_policy"
    return AdaptiveEvidenceState(
        asset_id=state.asset_id,
        detector_version=state.detector_version,
        score_schema=state.score_schema,
        quality_score=state.quality_score,
        source_match_score=state.source_match_score,
        current_routes=(),
        completed_actions=tuple(state.completed_actions),
        remaining_actions=tuple(spec.action_id for spec in pending_specs),
        spent_cost_units=0,
        remaining_cost_units=plan.spent_cost_units,
        policy_digest=cfg.policy_digest,
        calibration_digest=None,
        step=0,
        action_specs=specs,
        observations=(),
        status=STATUS_COMPLETE if terminal else STATUS_CONTINUE,
        route=ROUTE_INSUFFICIENT if terminal else None,
        reason=reason,
    )


def initialize_sequential_evidence(
    state: EvidenceAcquisitionState,
    *,
    policy: Optional[SequentialPolicyConfig] = None,
) -> AdaptiveEvidenceState:
    """Alias with an explicit initialization verb for callers."""

    return start_sequential_evidence(state, policy=policy)


def next_sequential_action(state: AdaptiveEvidenceState) -> Optional[PolicyAction]:
    if not isinstance(state, AdaptiveEvidenceState):
        raise ValueError("state must be AdaptiveEvidenceState")
    return state.next_action


def _terminal_state(
    state: AdaptiveEvidenceState,
    *,
    route: str,
    reason: str,
    observations: Optional[Tuple[ProbeObservation, ...]] = None,
    spent: Optional[int] = None,
    remaining: Optional[Tuple[str, ...]] = None,
    remaining_cost: Optional[int] = None,
    current_routes: Optional[Tuple[str, ...]] = None,
    calibration_digest: Optional[str] = None,
) -> AdaptiveEvidenceState:
    return replace(
        state,
        current_routes=state.current_routes if current_routes is None else current_routes,
        remaining_actions=state.remaining_actions if remaining is None else remaining,
        spent_cost_units=state.spent_cost_units if spent is None else spent,
        remaining_cost_units=state.remaining_cost_units if remaining_cost is None else remaining_cost,
        calibration_digest=state.calibration_digest if calibration_digest is None else calibration_digest,
        observations=state.observations if observations is None else observations,
        status=STATUS_COMPLETE,
        route=route,
        reason=reason,
    )


def apply_probe_observation(
    state: AdaptiveEvidenceState,
    observation: ProbeObservation,
    *,
    current_routes: Optional[Sequence[str]] = None,
    calibration_digest: Optional[str] = None,
) -> AdaptiveEvidenceState:
    """Apply exactly one probe, preserving fail-closed replay invariants.

    Structural input errors raise ``ValueError``.  A well-formed but failed,
    repeated or out-of-order probe returns a terminal ``insufficient`` or
    ``review`` state so callers cannot accidentally continue as if it had
    succeeded.
    """

    if not isinstance(state, AdaptiveEvidenceState):
        raise ValueError("state must be AdaptiveEvidenceState")
    if not isinstance(observation, ProbeObservation):
        raise ValueError("observation must be ProbeObservation")
    supplied_calibration = calibration_digest or observation.calibration_digest
    _hex_digest("calibration_digest", supplied_calibration, allow_none=True)
    if state.status != STATUS_CONTINUE:
        return _terminal_state(state, route=state.route or ROUTE_INSUFFICIENT, reason="policy_already_terminal")
    expected = state.next_action
    if expected is None:
        return _terminal_state(state, route=ROUTE_INSUFFICIENT, reason="no_action_available")
    if observation.action_id != expected.action_id:
        return _terminal_state(state, route=ROUTE_INSUFFICIENT, reason="action_out_of_order")
    if observation.step != state.step + 1:
        return _terminal_state(state, route=ROUTE_INSUFFICIENT, reason="step_mismatch")
    if expected.action_id in state.completed_actions:
        return _terminal_state(state, route=ROUTE_INSUFFICIENT, reason="repeated_action")
    if observation.target != expected.target:
        return _terminal_state(state, route=ROUTE_INSUFFICIENT, reason="target_mismatch")
    if observation.ok and observation.output_digest is None:
        return _terminal_state(state, route=ROUTE_INSUFFICIENT, reason="output_digest_missing")
    if expected.cost_units > state.remaining_cost_units:
        return _terminal_state(state, route=ROUTE_INSUFFICIENT, reason="budget_exhausted")
    if (
        state.calibration_digest is not None
        and supplied_calibration is not None
        and supplied_calibration != state.calibration_digest
    ):
        return _terminal_state(state, route=ROUTE_INSUFFICIENT, reason="calibration_profile_mismatch")

    observations = state.observations + (observation,)
    completed = state.completed_actions + (expected.action_id,)
    remaining = state.remaining_actions[1:]
    spent = state.spent_cost_units + expected.cost_units
    remaining_cost = state.remaining_cost_units - expected.cost_units
    active_calibration = state.calibration_digest or supplied_calibration
    routes = tuple(current_routes) if current_routes is not None else state.current_routes
    if observation.route is not None:
        routes = routes + (observation.route,)
    if any(route not in _ROUTES for route in routes):
        return _terminal_state(
            replace(state, observations=observations, completed_actions=completed, remaining_actions=remaining, step=observation.step, spent_cost_units=spent, remaining_cost_units=remaining_cost),
            route=ROUTE_INSUFFICIENT,
            reason="invalid_route_update",
        )

    base = replace(
        state,
        current_routes=routes,
        completed_actions=completed,
        remaining_actions=remaining,
        spent_cost_units=spent,
        remaining_cost_units=remaining_cost,
        calibration_digest=active_calibration,
        step=observation.step,
        observations=observations,
    )
    if not observation.ok:
        return _terminal_state(base, route=ROUTE_REVIEW, reason="probe_failed")

    route = observation.route
    if route is None and routes:
        route = routes[-1]
    previous_route = state.current_routes[-1] if state.current_routes else None
    if previous_route in {ROUTE_CANDIDATE, ROUTE_NULL_CONSISTENT} and route not in (None, previous_route):
        return _terminal_state(base, route=ROUTE_REVIEW, reason="route_flip")
    if route in (ROUTE_CANDIDATE, ROUTE_NULL_CONSISTENT) and active_calibration is None:
        return _terminal_state(base, route=ROUTE_INSUFFICIENT, reason="calibration_unavailable")
    if route in (ROUTE_REVIEW, ROUTE_CONFLICT_REVIEW):
        return _terminal_state(base, route=ROUTE_REVIEW, reason="evidence_conflict")
    if route == ROUTE_INSUFFICIENT:
        if not remaining:
            return _terminal_state(base, route=ROUTE_INSUFFICIENT, reason="evidence_insufficient")
        return replace(base, status=STATUS_CONTINUE, route=None, reason="continue_after_insufficient_probe")
    if route == ROUTE_CANDIDATE:
        return _terminal_state(base, route=ROUTE_CANDIDATE, reason="candidate_edit_for_review")
    if route == ROUTE_NULL_CONSISTENT:
        if observation.stop_requested or not remaining:
            return _terminal_state(base, route=ROUTE_NULL_CONSISTENT, reason="ordinary_propagation_consistent")
        return replace(base, status=STATUS_CONTINUE, route=None, reason="continue_after_null_consistent")
    if not remaining:
        return _terminal_state(base, route=ROUTE_INSUFFICIENT, reason="budget_exhausted")
    return replace(base, status=STATUS_CONTINUE, route=None, reason="probe_recorded")


def advance_sequential_evidence(
    state: AdaptiveEvidenceState,
    observation: ProbeObservation,
    *,
    current_routes: Optional[Sequence[str]] = None,
    calibration_digest: Optional[str] = None,
) -> AdaptiveEvidenceState:
    """Readable alias for :func:`apply_probe_observation`."""

    return apply_probe_observation(
        state,
        observation,
        current_routes=current_routes,
        calibration_digest=calibration_digest,
    )


def result_from_state(state: AdaptiveEvidenceState) -> SequentialEvidenceResult:
    """Serialize the current state; pending states remain explicitly pending."""

    if not isinstance(state, AdaptiveEvidenceState):
        raise ValueError("state must be AdaptiveEvidenceState")
    route = state.route or ROUTE_INSUFFICIENT
    abstained = route in _TERMINAL_ABSTAIN_ROUTES
    return SequentialEvidenceResult(
        route=route,
        abstained=abstained,
        reason=state.reason,
        steps=state.observations,
        spent_cost=state.spent_cost_units,
        remaining_cost=state.remaining_cost_units,
        policy_digest=state.policy_digest,
        calibration_digest=state.calibration_digest,
        evidence_digest=state.evidence_digest,
        status=state.status,
        current_routes=state.current_routes,
    )


def run_sequential_evidence(
    state: EvidenceAcquisitionState,
    observations: Iterable[ProbeObservation],
    *,
    policy: Optional[SequentialPolicyConfig] = None,
) -> SequentialEvidenceResult:
    """Replay a complete or partial observation trace under one policy."""

    if isinstance(observations, (str, bytes)):
        raise ValueError("observations must be an iterable of ProbeObservation")
    current = start_sequential_evidence(state, policy=policy)
    for observation in observations:
        if current.status == STATUS_COMPLETE:
            current = _terminal_state(current, route=ROUTE_INSUFFICIENT, reason="trace_after_terminal")
            break
        current = apply_probe_observation(current, observation)
    return result_from_state(current)


def replay_sequential_evidence(
    state: EvidenceAcquisitionState,
    observations: Iterable[ProbeObservation],
    *,
    policy: Optional[SequentialPolicyConfig] = None,
) -> SequentialEvidenceResult:
    """Alias emphasizing that the trace can be persisted and replayed."""

    return run_sequential_evidence(state, observations, policy=policy)


# Names used by early A9 design notes; keeping aliases avoids forcing callers
# to couple to one spelling while the research slice is still offline.
AdaptiveEvidenceConfig = SequentialPolicyConfig
sequential_evidence = run_sequential_evidence


__all__ = [
    "VERSION",
    "RESULT_SCHEMA",
    "ROUTE_CANDIDATE",
    "ROUTE_NULL_CONSISTENT",
    "ROUTE_CONFLICT_REVIEW",
    "ROUTE_REVIEW",
    "ROUTE_INSUFFICIENT",
    "STATUS_CONTINUE",
    "STATUS_COMPLETE",
    "PolicyAction",
    "SequentialPolicyConfig",
    "AdaptiveEvidenceConfig",
    "ProbeObservation",
    "AdaptiveEvidenceState",
    "SequentialEvidenceResult",
    "start_sequential_evidence",
    "initialize_sequential_evidence",
    "next_sequential_action",
    "apply_probe_observation",
    "advance_sequential_evidence",
    "result_from_state",
    "run_sequential_evidence",
    "replay_sequential_evidence",
    "sequential_evidence",
]
