"""Selection-aware evidence acquisition for the offline AIGC protocol.

SAEA is a bounded policy layer on top of D-054, D-058 and SAEC.  It does
not run a detector, choose a reference, or turn a score into a probability.
It reads the failure reason of already executed evidence and chooses one
pre-registered next probe.  Every action and observation is digest-bound so
the policy can be replayed under an independent policy-calibration split.

The module is deliberately a separate schema.  It does not rewrite the
existing sequential-evidence state machine or ``aigc_result_v1``.  A
candidate route therefore remains a review route until real authorized data
shows that the same-budget policy reduces selective risk or review cost.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


VERSION = "selection-aware-acquisition-v1"
SCHEMA = "selection-aware-acquisition-result-v1"
POLICY_SCHEMA = "selection-aware-acquisition-policy-v1"
GATE_VERSION = "selection-aware-propagation-gate-v1"
GATE_SCHEMA = "selection-aware-propagation-gate-v1"

ROUTE_SELECTION_SPECIFIC = "selection_specific_candidate"
ROUTE_SELECTION_AMBIGUOUS = "selection_ambiguous"
ROUTE_NULL_CONSISTENT = "null_consistent"
ROUTE_REVIEW = "review"
ROUTE_INSUFFICIENT = "insufficient"

ACTION_APPEND_DECOY = "append_matched_decoy"
ACTION_BUILD_NULL = "build_matched_null"
ACTION_ALTERNATE_VIEW = "alternate_view"
ACTION_ALTERNATE_OPERATOR = "alternate_operator"
ACTION_REALIGN_QUALITY = "realign_quality"

STATUS_ACQUIRE = "acquire"
STATUS_CANDIDATE = "candidate"
STATUS_REVIEW = "review"
STATUS_INSUFFICIENT = "insufficient"

# D-073 keeps the upstream generator/open-set and retrieval replay decisions
# explicit.  These values intentionally mirror the route names used by the
# open-set and retrieval replay adapters, while the two ``*_not_required``
# values make an explicit bypass auditable instead of treating a missing gate
# as success.
GENERATOR_ROUTE_KNOWN_FAMILY_SUPPORTED = "known_family_supported"
GENERATOR_ROUTE_EVIDENCE_NOT_REQUIRED = "generator_evidence_not_required"
GENERATOR_ROUTE_REAL_CONSISTENT = "real_consistent"
GENERATOR_ROUTE_OPEN_SET_UNKNOWN = "open_set_unknown"
GENERATOR_ROUTE_CONFLICT_REVIEW = "conflict_review"
GENERATOR_ROUTE_INSUFFICIENT = "insufficient"
GENERATOR_ROUTE_NOT_EVALUATED = "not_evaluated"

RETRIEVAL_REPLAY_ROUTE_CONSISTENT = "replay_consistent"
RETRIEVAL_REPLAY_ROUTE_NOT_REQUIRED = "replay_not_required"
RETRIEVAL_REPLAY_ROUTE_OPEN_SET_UNKNOWN = "open_set_unknown"
RETRIEVAL_REPLAY_ROUTE_CONFLICT_REVIEW = "conflict_review"
RETRIEVAL_REPLAY_ROUTE_REVIEW = "review"
RETRIEVAL_REPLAY_ROUTE_INSUFFICIENT = "insufficient"
RETRIEVAL_REPLAY_ROUTE_NOT_EVALUATED = "not_evaluated"
RETRIEVAL_REPLAY_ROUTE_POISONING = "poisoning"
RETRIEVAL_REPLAY_ROUTE_ROUTE_FLIP = "route_flip"
RETRIEVAL_REPLAY_ROUTE_CANDIDATE = "candidate"

OPERATION_SCOPE_CONTENT_EDIT = "content_edit"
OPERATION_SCOPE_ORDINARY_PROPAGATION = "ordinary_propagation"

_SELECTION_ROUTES = {
    ROUTE_SELECTION_SPECIFIC,
    ROUTE_SELECTION_AMBIGUOUS,
    ROUTE_NULL_CONSISTENT,
    ROUTE_INSUFFICIENT,
}
_INVARIANT_ROUTES = {
    "invariant_candidate",
    ROUTE_NULL_CONSISTENT,
    "view_operator_inconsistent",
    ROUTE_INSUFFICIENT,
}
_ACTION_IDS = {
    ACTION_APPEND_DECOY,
    ACTION_BUILD_NULL,
    ACTION_ALTERNATE_VIEW,
    ACTION_ALTERNATE_OPERATOR,
    ACTION_REALIGN_QUALITY,
}
_UPDATE_KEYS = {
    "selection_route",
    "selection_p_value_raw",
    "specificity_gap_raw",
    "invariant_route",
    "null_support",
    "null_profile_digest",
    "quality_score",
    "source_match_score",
    "alignment_ok",
    "selection_evidence_digest",
    "invariant_evidence_digest",
    "operation_scope",
    "generator_route",
    "generator_profile_digest",
    "generator_input_digest",
    "generator_evidence_digest",
    "retrieval_replay_route",
    "retrieval_event_digest",
    "gate_policy_digest",
}

_GENERATOR_ROUTES = {
    GENERATOR_ROUTE_KNOWN_FAMILY_SUPPORTED,
    GENERATOR_ROUTE_EVIDENCE_NOT_REQUIRED,
    GENERATOR_ROUTE_REAL_CONSISTENT,
    GENERATOR_ROUTE_OPEN_SET_UNKNOWN,
    GENERATOR_ROUTE_CONFLICT_REVIEW,
    GENERATOR_ROUTE_INSUFFICIENT,
    GENERATOR_ROUTE_NOT_EVALUATED,
}
_RETRIEVAL_REPLAY_ROUTES = {
    RETRIEVAL_REPLAY_ROUTE_CONSISTENT,
    RETRIEVAL_REPLAY_ROUTE_NOT_REQUIRED,
    RETRIEVAL_REPLAY_ROUTE_OPEN_SET_UNKNOWN,
    RETRIEVAL_REPLAY_ROUTE_CONFLICT_REVIEW,
    RETRIEVAL_REPLAY_ROUTE_REVIEW,
    RETRIEVAL_REPLAY_ROUTE_INSUFFICIENT,
    RETRIEVAL_REPLAY_ROUTE_NOT_EVALUATED,
    RETRIEVAL_REPLAY_ROUTE_POISONING,
    RETRIEVAL_REPLAY_ROUTE_ROUTE_FLIP,
    RETRIEVAL_REPLAY_ROUTE_CANDIDATE,
}
_OPERATION_SCOPES = {
    OPERATION_SCOPE_CONTENT_EDIT,
    OPERATION_SCOPE_ORDINARY_PROPAGATION,
}


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_gate_policy_digest(*, policy_version: str = GATE_VERSION) -> str:
    """Return the digest for the fixed D-073 gate policy.

    The gate policy is deliberately independent from the SAEA action policy:
    changing action costs must not silently change the open-set/replay binding
    contract, and vice versa.
    """

    _text("policy_version", policy_version)
    return _digest(
        {
            "schema": GATE_SCHEMA,
            "version": policy_version,
            "accepted_generator_routes": [
                GENERATOR_ROUTE_KNOWN_FAMILY_SUPPORTED,
                GENERATOR_ROUTE_EVIDENCE_NOT_REQUIRED,
            ],
            "accepted_retrieval_replay_routes": [
                RETRIEVAL_REPLAY_ROUTE_CONSISTENT,
                RETRIEVAL_REPLAY_ROUTE_NOT_REQUIRED,
            ],
            "ordinary_propagation_route": ROUTE_NULL_CONSISTENT,
            "real_consistent_is_neutral": True,
        }
    )


def compute_generator_evidence_digest(
    generator_route: str,
    generator_profile_digest: Optional[str],
    generator_input_digest: Optional[str],
    gate_policy_digest: str,
) -> str:
    """Build the canonical binding digest for generator/open-set evidence."""

    if generator_route not in _GENERATOR_ROUTES:
        raise ValueError("unsupported generator_route")
    _hex("generator_profile_digest", generator_profile_digest, allow_none=True)
    _hex("generator_input_digest", generator_input_digest, allow_none=True)
    _hex("gate_policy_digest", gate_policy_digest)
    return _digest(
        {
            "schema": GATE_SCHEMA,
            "kind": "generator_evidence",
            "generator_route": generator_route,
            "generator_profile_digest": generator_profile_digest,
            "generator_input_digest": generator_input_digest,
            "gate_policy_digest": gate_policy_digest,
        }
    )


def compute_retrieval_event_digest(
    retrieval_replay_route: str,
    *,
    case_id: str,
    asset_id: str,
    manifest_digest: str,
    gate_policy_digest: str,
) -> str:
    """Build the canonical binding digest for retrieval replay evidence."""

    if retrieval_replay_route not in _RETRIEVAL_REPLAY_ROUTES:
        raise ValueError("unsupported retrieval_replay_route")
    _text("case_id", case_id)
    _text("asset_id", asset_id)
    _hex("manifest_digest", manifest_digest)
    _hex("gate_policy_digest", gate_policy_digest)
    return _digest(
        {
            "schema": GATE_SCHEMA,
            "kind": "retrieval_event",
            "retrieval_replay_route": retrieval_replay_route,
            "case_id": case_id,
            "asset_id": asset_id,
            "manifest_digest": manifest_digest,
            "gate_policy_digest": gate_policy_digest,
        }
    )


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _hex(name: str, value: str, *, allow_none: bool = False) -> Optional[str]:
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
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    return value


def _finite_raw(name: str, value: Optional[float], *, allow_none: bool = True) -> Optional[float]:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _positive_int(name: str, value: int, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be a {qualifier} integer")
    return value


def _normalise_mapping(name: str, value: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")

    def normalise(item: Any) -> Any:
        if isinstance(item, Mapping):
            result: Dict[str, Any] = {}
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError(f"{name} keys must be strings")
                lowered = key.lower()
                if "probability" in lowered or lowered in {"aigc_prob", "ai_prob"}:
                    raise ValueError(f"{name} cannot contain probability fields")
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
class SelectionAwareAcquisitionConfig:
    """Pre-registered gates and costs for one SAEA policy."""

    max_actions: int = 3
    max_cost_units: int = 5
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    minimum_null_support: int = 20
    minimum_selection_p: float = 0.05
    minimum_specificity_gap: float = 0.10
    action_costs: Tuple[Tuple[str, int], ...] = (
        (ACTION_APPEND_DECOY, 1),
        (ACTION_BUILD_NULL, 2),
        (ACTION_ALTERNATE_VIEW, 2),
        (ACTION_ALTERNATE_OPERATOR, 2),
        (ACTION_REALIGN_QUALITY, 2),
    )
    policy_version: str = POLICY_SCHEMA
    gate_policy_version: str = GATE_VERSION

    def __post_init__(self) -> None:
        _positive_int("max_actions", self.max_actions)
        _positive_int("max_cost_units", self.max_cost_units)
        _unit("minimum_quality", self.minimum_quality)
        _unit("minimum_source_match", self.minimum_source_match)
        _positive_int("minimum_null_support", self.minimum_null_support)
        p_value = _unit("minimum_selection_p", self.minimum_selection_p)
        if p_value is None or p_value <= 0.0 or p_value >= 1.0:
            raise ValueError("minimum_selection_p must be strictly between 0 and 1")
        _finite_raw("minimum_specificity_gap", self.minimum_specificity_gap, allow_none=False)
        if self.minimum_specificity_gap < 0.0:
            raise ValueError("minimum_specificity_gap must be non-negative")
        if isinstance(self.action_costs, (str, bytes)) or not self.action_costs:
            raise ValueError("action_costs must be a non-empty sequence")
        costs = tuple((_text("action_id", action), _positive_int("cost_units", cost)) for action, cost in self.action_costs)
        if len({action for action, _ in costs}) != len(costs) or any(action not in _ACTION_IDS for action, _ in costs):
            raise ValueError("action_costs must contain each supported action at most once")
        if set(costs) and any(action not in dict(costs) for action in _ACTION_IDS):
            raise ValueError("action_costs must cover every supported action")
        object.__setattr__(self, "action_costs", tuple(sorted(costs)))
        _text("policy_version", self.policy_version)
        _text("gate_policy_version", self.gate_policy_version)

    @property
    def cost_map(self) -> Dict[str, int]:
        return dict(self.action_costs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.policy_version,
            "schema": POLICY_SCHEMA,
            "max_actions": self.max_actions,
            "max_cost_units": self.max_cost_units,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "minimum_null_support": self.minimum_null_support,
            "minimum_selection_p": self.minimum_selection_p,
            "minimum_specificity_gap": self.minimum_specificity_gap,
            "action_costs": [[action, cost] for action, cost in self.action_costs],
        }

    @property
    def policy_digest(self) -> str:
        return _digest(self.to_dict())

    @property
    def gate_policy_digest(self) -> str:
        return compute_gate_policy_digest(policy_version=self.gate_policy_version)


@dataclass(frozen=True)
class SelectionAwarePropagationGate:
    """Versioned upstream gate attached to one SAEA evidence state.

    This object carries only route and digest metadata.  It does not execute
    a generator detector or retrieval replay.  A caller may pass it through
    ``SelectionAwareEvidenceState(propagation_gate=...)``; the state mirrors
    the fields into its flat, digestable schema so old replay code can inspect
    one canonical mapping.
    """

    generator_route: str
    generator_profile_digest: Optional[str]
    generator_input_digest: Optional[str]
    generator_evidence_digest: Optional[str]
    retrieval_replay_route: str
    retrieval_event_digest: Optional[str]
    gate_policy_digest: str
    operation_scope: str = OPERATION_SCOPE_CONTENT_EDIT

    def __post_init__(self) -> None:
        if self.generator_route not in _GENERATOR_ROUTES:
            raise ValueError("unsupported generator_route")
        if self.retrieval_replay_route not in _RETRIEVAL_REPLAY_ROUTES:
            raise ValueError("unsupported retrieval_replay_route")
        if self.operation_scope not in _OPERATION_SCOPES:
            raise ValueError("unsupported operation_scope")
        _hex("generator_profile_digest", self.generator_profile_digest, allow_none=True)
        _hex("generator_input_digest", self.generator_input_digest, allow_none=True)
        _hex("generator_evidence_digest", self.generator_evidence_digest, allow_none=True)
        _hex("retrieval_event_digest", self.retrieval_event_digest, allow_none=True)
        _hex("gate_policy_digest", self.gate_policy_digest)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": GATE_SCHEMA,
            "version": GATE_VERSION,
            "operation_scope": self.operation_scope,
            "generator_route": self.generator_route,
            "generator_profile_digest": self.generator_profile_digest,
            "generator_input_digest": self.generator_input_digest,
            "generator_evidence_digest": self.generator_evidence_digest,
            "retrieval_replay_route": self.retrieval_replay_route,
            "retrieval_event_digest": self.retrieval_event_digest,
            "gate_policy_digest": self.gate_policy_digest,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class SelectionAwareEvidenceState:
    """Bound evidence summary consumed by the policy planner."""

    case_id: str
    asset_id: str
    manifest_digest: str
    detector_version: str
    score_schema: str
    quality_score: Optional[float]
    source_match_score: Optional[float]
    selection_route: str
    selection_p_value_raw: Optional[float]
    specificity_gap_raw: Optional[float]
    invariant_route: str
    null_support: int
    null_profile_digest: Optional[str]
    selection_evidence_digest: Optional[str]
    invariant_evidence_digest: Optional[str]
    alignment_ok: bool = True
    completed_actions: Tuple[str, ...] = ()
    operation_scope: str = OPERATION_SCOPE_CONTENT_EDIT
    generator_route: Optional[str] = None
    generator_profile_digest: Optional[str] = None
    generator_input_digest: Optional[str] = None
    generator_evidence_digest: Optional[str] = None
    retrieval_replay_route: Optional[str] = None
    retrieval_event_digest: Optional[str] = None
    gate_policy_digest: Optional[str] = None
    propagation_gate: Optional[SelectionAwarePropagationGate] = None

    def __post_init__(self) -> None:
        for name in ("case_id", "asset_id", "manifest_digest", "detector_version", "score_schema"):
            if name == "manifest_digest":
                _hex(name, getattr(self, name))
            else:
                _text(name, getattr(self, name))
        _unit("quality_score", self.quality_score, allow_none=True)
        _unit("source_match_score", self.source_match_score, allow_none=True)
        if self.selection_route not in _SELECTION_ROUTES:
            raise ValueError("unsupported selection_route")
        if self.invariant_route not in _INVARIANT_ROUTES:
            raise ValueError("unsupported invariant_route")
        p_value = _unit("selection_p_value_raw", self.selection_p_value_raw, allow_none=True)
        if p_value is not None and p_value <= 0.0:
            raise ValueError("selection_p_value_raw must be greater than zero")
        _finite_raw("specificity_gap_raw", self.specificity_gap_raw)
        _positive_int("null_support", self.null_support, allow_zero=True)
        _hex("null_profile_digest", self.null_profile_digest, allow_none=True)
        _hex("selection_evidence_digest", self.selection_evidence_digest, allow_none=True)
        _hex("invariant_evidence_digest", self.invariant_evidence_digest, allow_none=True)
        if not isinstance(self.alignment_ok, bool):
            raise ValueError("alignment_ok must be bool")
        actions = tuple(_text("completed_action", item) for item in self.completed_actions)
        if len(actions) != len(set(actions)) or any(item not in _ACTION_IDS for item in actions):
            raise ValueError("completed_actions must be unique supported actions")
        object.__setattr__(self, "completed_actions", actions)
        if self.operation_scope not in _OPERATION_SCOPES:
            raise ValueError("unsupported operation_scope")
        if self.generator_route is not None and self.generator_route not in _GENERATOR_ROUTES:
            raise ValueError("unsupported generator_route")
        if self.retrieval_replay_route is not None and self.retrieval_replay_route not in _RETRIEVAL_REPLAY_ROUTES:
            raise ValueError("unsupported retrieval_replay_route")
        _hex("generator_profile_digest", self.generator_profile_digest, allow_none=True)
        _hex("generator_input_digest", self.generator_input_digest, allow_none=True)
        _hex("generator_evidence_digest", self.generator_evidence_digest, allow_none=True)
        _hex("retrieval_event_digest", self.retrieval_event_digest, allow_none=True)
        _hex("gate_policy_digest", self.gate_policy_digest, allow_none=True)
        if self.propagation_gate is not None:
            if not isinstance(self.propagation_gate, SelectionAwarePropagationGate):
                raise ValueError("propagation_gate must be SelectionAwarePropagationGate")
            gate = self.propagation_gate
            gate_fields = {
                "operation_scope": gate.operation_scope,
                "generator_route": gate.generator_route,
                "generator_profile_digest": gate.generator_profile_digest,
                "generator_input_digest": gate.generator_input_digest,
                "generator_evidence_digest": gate.generator_evidence_digest,
                "retrieval_replay_route": gate.retrieval_replay_route,
                "retrieval_event_digest": gate.retrieval_event_digest,
                "gate_policy_digest": gate.gate_policy_digest,
            }
            for name, value in gate_fields.items():
                current = getattr(self, name)
                if current is not None and current != value:
                    # ``operation_scope`` has a content-edit default for
                    # backwards-compatible constructors.  Let an explicit
                    # gate object override that default when it declares an
                    # ordinary-propagation null case.
                    if (
                        name == "operation_scope"
                        and current == OPERATION_SCOPE_CONTENT_EDIT
                        and value == OPERATION_SCOPE_ORDINARY_PROPAGATION
                    ):
                        object.__setattr__(self, name, value)
                        continue
                    raise ValueError(f"propagation_gate_{name}_mismatch")
                if current is None:
                    object.__setattr__(self, name, value)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "asset_id": self.asset_id,
            "manifest_digest": self.manifest_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "selection_route": self.selection_route,
            "selection_p_value_raw": self.selection_p_value_raw,
            "specificity_gap_raw": self.specificity_gap_raw,
            "invariant_route": self.invariant_route,
            "null_support": self.null_support,
            "null_profile_digest": self.null_profile_digest,
            "selection_evidence_digest": self.selection_evidence_digest,
            "invariant_evidence_digest": self.invariant_evidence_digest,
            "alignment_ok": self.alignment_ok,
            "completed_actions": list(self.completed_actions),
            "operation_scope": self.operation_scope,
            "generator_route": self.generator_route,
            "generator_profile_digest": self.generator_profile_digest,
            "generator_input_digest": self.generator_input_digest,
            "generator_evidence_digest": self.generator_evidence_digest,
            "retrieval_replay_route": self.retrieval_replay_route,
            "retrieval_event_digest": self.retrieval_event_digest,
            "gate_policy_digest": self.gate_policy_digest,
        }

    @property
    def input_digest(self) -> str:
        return _digest(self.to_dict())


def _gate_digest_for_state(state: SelectionAwareEvidenceState) -> str:
    return _digest(
        {
            "schema": GATE_SCHEMA,
            "version": GATE_VERSION,
            "operation_scope": state.operation_scope,
            "generator_route": state.generator_route,
            "generator_profile_digest": state.generator_profile_digest,
            "generator_input_digest": state.generator_input_digest,
            "generator_evidence_digest": state.generator_evidence_digest,
            "retrieval_replay_route": state.retrieval_replay_route,
            "retrieval_event_digest": state.retrieval_event_digest,
            "gate_policy_digest": state.gate_policy_digest,
        }
    )


def _propagation_gate_decision(
    state: SelectionAwareEvidenceState,
    config: SelectionAwareAcquisitionConfig,
) -> Tuple[str, str]:
    """Return ``(decision, reason)`` for the D-073 gate.

    ``candidate`` is returned only for a complete, digest-bound known-family
    and retrieval replay route.  ``null`` is an intentionally safe terminal
    route for ordinary propagation.  Every other decision is terminal review
    or insufficient, so a probe cannot repair an absent or contradictory
    upstream gate.
    """

    if state.operation_scope == OPERATION_SCOPE_ORDINARY_PROPAGATION:
        return "null", "ordinary_propagation_scope"
    if state.operation_scope != OPERATION_SCOPE_CONTENT_EDIT:
        return "insufficient", "operation_scope_invalid"
    if state.generator_route is None or state.retrieval_replay_route is None:
        return "insufficient", "propagation_gate_missing"
    if state.gate_policy_digest is None:
        return "insufficient", "gate_policy_digest_missing"
    if state.gate_policy_digest != config.gate_policy_digest:
        return "insufficient", "gate_policy_digest_mismatch"

    if state.generator_route == GENERATOR_ROUTE_REAL_CONSISTENT:
        return "review", "generator_real_consistent_neutral"
    if state.generator_route in {
        GENERATOR_ROUTE_OPEN_SET_UNKNOWN,
        GENERATOR_ROUTE_CONFLICT_REVIEW,
    }:
        return "review", "generator_open_set_or_conflict"
    if state.generator_route in {
        GENERATOR_ROUTE_INSUFFICIENT,
        GENERATOR_ROUTE_NOT_EVALUATED,
    }:
        return "insufficient", "generator_gate_not_evaluated"
    if state.generator_route not in {
        GENERATOR_ROUTE_KNOWN_FAMILY_SUPPORTED,
        GENERATOR_ROUTE_EVIDENCE_NOT_REQUIRED,
    }:
        return "insufficient", "generator_route_not_candidate_safe"

    if state.generator_route == GENERATOR_ROUTE_KNOWN_FAMILY_SUPPORTED:
        if state.generator_profile_digest is None:
            return "insufficient", "generator_profile_digest_missing"
        if state.generator_input_digest is None:
            return "insufficient", "generator_input_digest_missing"
        if state.generator_evidence_digest is None:
            return "insufficient", "generator_evidence_digest_missing"
        expected = compute_generator_evidence_digest(
            state.generator_route,
            state.generator_profile_digest,
            state.generator_input_digest,
            state.gate_policy_digest,
        )
        if state.generator_evidence_digest != expected:
            return "insufficient", "generator_evidence_digest_mismatch"
    else:
        # An explicit no-generator-evidence route is safe only when no stale
        # profile/input/evidence values are attached to it.  A partially
        # populated binding is ambiguous and therefore cannot pass.
        if any(
            value is not None
            for value in (
                state.generator_profile_digest,
                state.generator_input_digest,
                state.generator_evidence_digest,
            )
        ):
            return "insufficient", "generator_not_required_binding_mismatch"

    if state.retrieval_replay_route == RETRIEVAL_REPLAY_ROUTE_CONSISTENT:
        if state.retrieval_event_digest is None:
            return "insufficient", "retrieval_event_digest_missing"
        expected = compute_retrieval_event_digest(
            state.retrieval_replay_route,
            case_id=state.case_id,
            asset_id=state.asset_id,
            manifest_digest=state.manifest_digest,
            gate_policy_digest=state.gate_policy_digest,
        )
        if state.retrieval_event_digest != expected:
            return "insufficient", "retrieval_event_digest_mismatch"
    elif state.retrieval_replay_route == RETRIEVAL_REPLAY_ROUTE_NOT_REQUIRED:
        if state.retrieval_event_digest is not None:
            return "insufficient", "retrieval_not_required_binding_mismatch"
    elif state.retrieval_replay_route in {
        RETRIEVAL_REPLAY_ROUTE_OPEN_SET_UNKNOWN,
        RETRIEVAL_REPLAY_ROUTE_CONFLICT_REVIEW,
        RETRIEVAL_REPLAY_ROUTE_REVIEW,
        RETRIEVAL_REPLAY_ROUTE_POISONING,
        RETRIEVAL_REPLAY_ROUTE_ROUTE_FLIP,
    }:
        return "review", "retrieval_replay_not_safe"
    elif state.retrieval_replay_route == RETRIEVAL_REPLAY_ROUTE_CANDIDATE:
        # A replay result labelled merely ``candidate`` does not prove that
        # the replay itself was consistent.  Require the explicit
        # ``replay_consistent`` route to prevent route-name confusion.
        return "insufficient", "retrieval_replay_route_not_explicit"
    elif state.retrieval_replay_route in {
        RETRIEVAL_REPLAY_ROUTE_INSUFFICIENT,
        RETRIEVAL_REPLAY_ROUTE_NOT_EVALUATED,
    }:
        return "insufficient", "retrieval_replay_not_evaluated"
    else:
        return "insufficient", "retrieval_replay_route_not_candidate_safe"
    return "candidate", "propagation_gate_passed"


@dataclass(frozen=True)
class SelectionAwareAction:
    action_id: str
    cost_units: int
    reason: str
    target: str = "evidence"

    def __post_init__(self) -> None:
        if self.action_id not in _ACTION_IDS:
            raise ValueError("unsupported action_id")
        _positive_int("cost_units", self.cost_units)
        _text("reason", self.reason)
        _text("target", self.target)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "cost_units": self.cost_units,
            "reason": self.reason,
            "target": self.target,
        }


@dataclass(frozen=True)
class SelectionAwarePlan:
    status: str
    route: str
    reason: str
    case_id: str
    actions: Tuple[SelectionAwareAction, ...]
    spent_cost_units: int
    remaining_cost_units: int
    policy_digest: str
    input_digest: str
    plan_digest: str
    version: str = VERSION
    propagation_gate_digest: Optional[str] = None
    generator_route: Optional[str] = None
    retrieval_replay_route: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in {STATUS_ACQUIRE, STATUS_CANDIDATE, STATUS_REVIEW, STATUS_INSUFFICIENT}:
            raise ValueError("unsupported plan status")
        if self.route not in {ROUTE_SELECTION_SPECIFIC, ROUTE_SELECTION_AMBIGUOUS, ROUTE_NULL_CONSISTENT, ROUTE_REVIEW, ROUTE_INSUFFICIENT}:
            raise ValueError("unsupported plan route")
        _text("reason", self.reason)
        _text("case_id", self.case_id)
        actions = tuple(self.actions)
        if any(not isinstance(action, SelectionAwareAction) for action in actions):
            raise ValueError("actions must contain SelectionAwareAction")
        if len({action.action_id for action in actions}) != len(actions):
            raise ValueError("actions must be unique")
        object.__setattr__(self, "actions", actions)
        _positive_int("spent_cost_units", self.spent_cost_units, allow_zero=True)
        _positive_int("remaining_cost_units", self.remaining_cost_units, allow_zero=True)
        _hex("policy_digest", self.policy_digest)
        _hex("input_digest", self.input_digest)
        _hex("plan_digest", self.plan_digest)
        _hex("propagation_gate_digest", self.propagation_gate_digest, allow_none=True)
        if self.generator_route is not None and self.generator_route not in _GENERATOR_ROUTES:
            raise ValueError("unsupported generator_route")
        if self.retrieval_replay_route is not None and self.retrieval_replay_route not in _RETRIEVAL_REPLAY_ROUTES:
            raise ValueError("unsupported retrieval_replay_route")

    @property
    def next_action(self) -> Optional[SelectionAwareAction]:
        return self.actions[0] if self.actions else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "route": self.route,
            "reason": self.reason,
            "case_id": self.case_id,
            "actions": [action.to_dict() for action in self.actions],
            "spent_cost_units": self.spent_cost_units,
            "remaining_cost_units": self.remaining_cost_units,
            "policy_digest": self.policy_digest,
            "input_digest": self.input_digest,
            "plan_digest": self.plan_digest,
            "propagation_gate_digest": self.propagation_gate_digest,
            "generator_route": self.generator_route,
            "retrieval_replay_route": self.retrieval_replay_route,
        }


@dataclass(frozen=True)
class SelectionAwareObservation:
    action_id: str
    step: int
    input_digest: str
    output_digest: Optional[str]
    raw_updates: Mapping[str, Any]
    ok: bool = True
    failure_reason: Optional[str] = None
    elapsed_ms: Optional[float] = None

    def __post_init__(self) -> None:
        if self.action_id not in _ACTION_IDS:
            raise ValueError("unsupported action_id")
        _positive_int("step", self.step)
        _hex("input_digest", self.input_digest)
        _hex("output_digest", self.output_digest, allow_none=True)
        updates = _normalise_mapping("raw_updates", self.raw_updates)
        if any(key not in _UPDATE_KEYS for key in updates):
            raise ValueError("raw_updates contains an unsupported field")
        object.__setattr__(self, "raw_updates", updates)
        if not isinstance(self.ok, bool):
            raise ValueError("ok must be bool")
        if self.ok and self.output_digest is None:
            raise ValueError("successful observation requires output_digest")
        if self.ok and self.failure_reason:
            raise ValueError("successful observation cannot have failure_reason")
        if not self.ok and not self.failure_reason:
            raise ValueError("failed observation requires failure_reason")
        if self.elapsed_ms is not None:
            if isinstance(self.elapsed_ms, bool) or not isinstance(self.elapsed_ms, (int, float)):
                raise ValueError("elapsed_ms must be finite and non-negative")
            elapsed = float(self.elapsed_ms)
            if not math.isfinite(elapsed) or elapsed < 0.0:
                raise ValueError("elapsed_ms must be finite and non-negative")
            object.__setattr__(self, "elapsed_ms", elapsed)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "step": self.step,
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "raw_updates": dict(self.raw_updates),
            "ok": self.ok,
            "failure_reason": self.failure_reason,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True)
class SelectionAwareAcquisitionResult:
    route: str
    status: str
    abstained: bool
    reason: str
    case_id: str
    steps: Tuple[SelectionAwareObservation, ...]
    spent_cost_units: int
    remaining_cost_units: int
    policy_digest: str
    evidence_digest: str
    trace_digest: str
    version: str = VERSION
    propagation_gate_digest: Optional[str] = None
    generator_route: Optional[str] = None
    retrieval_replay_route: Optional[str] = None

    def __post_init__(self) -> None:
        if self.route not in {ROUTE_SELECTION_SPECIFIC, ROUTE_SELECTION_AMBIGUOUS, ROUTE_NULL_CONSISTENT, ROUTE_REVIEW, ROUTE_INSUFFICIENT}:
            raise ValueError("unsupported result route")
        if self.status not in {STATUS_ACQUIRE, STATUS_CANDIDATE, STATUS_REVIEW, STATUS_INSUFFICIENT}:
            raise ValueError("unsupported result status")
        if not isinstance(self.abstained, bool):
            raise ValueError("abstained must be bool")
        if self.route in {ROUTE_REVIEW, ROUTE_INSUFFICIENT, ROUTE_SELECTION_AMBIGUOUS} and not self.abstained:
            raise ValueError("ambiguous/review/insufficient result must abstain")
        _text("reason", self.reason)
        _text("case_id", self.case_id)
        if any(not isinstance(step, SelectionAwareObservation) for step in self.steps):
            raise ValueError("steps must contain SelectionAwareObservation")
        _positive_int("spent_cost_units", self.spent_cost_units, allow_zero=True)
        _positive_int("remaining_cost_units", self.remaining_cost_units, allow_zero=True)
        _hex("policy_digest", self.policy_digest)
        _hex("evidence_digest", self.evidence_digest)
        _hex("trace_digest", self.trace_digest)
        _hex("propagation_gate_digest", self.propagation_gate_digest, allow_none=True)
        if self.generator_route is not None and self.generator_route not in _GENERATOR_ROUTES:
            raise ValueError("unsupported generator_route")
        if self.retrieval_replay_route is not None and self.retrieval_replay_route not in _RETRIEVAL_REPLAY_ROUTES:
            raise ValueError("unsupported retrieval_replay_route")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "schema": SCHEMA,
            "route": self.route,
            "status": self.status,
            "abstained": self.abstained,
            "reason": self.reason,
            "case_id": self.case_id,
            "steps": [step.to_dict() for step in self.steps],
            "spent_cost_units": self.spent_cost_units,
            "remaining_cost_units": self.remaining_cost_units,
            "policy_digest": self.policy_digest,
            "evidence_digest": self.evidence_digest,
            "trace_digest": self.trace_digest,
            "propagation_gate_digest": self.propagation_gate_digest,
            "generator_route": self.generator_route,
            "retrieval_replay_route": self.retrieval_replay_route,
        }


def _candidate_ready(state: SelectionAwareEvidenceState, config: SelectionAwareAcquisitionConfig) -> bool:
    gate_decision, _ = _propagation_gate_decision(state, config)
    return (
        gate_decision == "candidate"
        and state.selection_route == ROUTE_SELECTION_SPECIFIC
        and state.invariant_route == "invariant_candidate"
        and state.null_support >= config.minimum_null_support
        and state.selection_p_value_raw is not None
        and state.selection_p_value_raw <= config.minimum_selection_p
        and state.specificity_gap_raw is not None
        and state.specificity_gap_raw >= config.minimum_specificity_gap
        and state.quality_score is not None
        and state.quality_score >= config.minimum_quality
        and state.source_match_score is not None
        and state.source_match_score >= config.minimum_source_match
        and state.alignment_ok
        and state.null_profile_digest is not None
        and state.selection_evidence_digest is not None
        and state.invariant_evidence_digest is not None
    )


def _reasoned_action(state: SelectionAwareEvidenceState, config: SelectionAwareAcquisitionConfig) -> Tuple[str, str]:
    completed = set(state.completed_actions)
    if state.quality_score is None or state.quality_score < config.minimum_quality or not state.alignment_ok:
        return ACTION_REALIGN_QUALITY, "quality_or_alignment_gate"
    if state.source_match_score is None or state.source_match_score < config.minimum_source_match:
        return ACTION_REALIGN_QUALITY, "source_match_gate"
    if state.selection_route == ROUTE_SELECTION_AMBIGUOUS and ACTION_APPEND_DECOY not in completed:
        return ACTION_APPEND_DECOY, "selection_ambiguity_requires_matched_decoy"
    if (state.selection_route == ROUTE_INSUFFICIENT or state.null_support < config.minimum_null_support or state.null_profile_digest is None) and ACTION_BUILD_NULL not in completed:
        return ACTION_BUILD_NULL, "ordinary_null_support_or_binding_insufficient"
    if state.invariant_route == "view_operator_inconsistent":
        if ACTION_ALTERNATE_VIEW not in completed:
            return ACTION_ALTERNATE_VIEW, "view_stability_inconsistent"
        if ACTION_ALTERNATE_OPERATOR not in completed:
            return ACTION_ALTERNATE_OPERATOR, "operator_stability_inconsistent"
    if state.selection_route == ROUTE_SELECTION_SPECIFIC and state.invariant_route == ROUTE_INSUFFICIENT and ACTION_BUILD_NULL not in completed:
        return ACTION_BUILD_NULL, "invariant_evidence_insufficient"
    return "", ""


def plan_selection_aware_acquisition(
    state: SelectionAwareEvidenceState,
    *,
    config: Optional[SelectionAwareAcquisitionConfig] = None,
    spent_cost_units: int = 0,
) -> SelectionAwarePlan:
    """Return one deterministic next action or a terminal fail-closed route."""

    if not isinstance(state, SelectionAwareEvidenceState):
        raise ValueError("state must be SelectionAwareEvidenceState")
    config = config or SelectionAwareAcquisitionConfig()
    _positive_int("spent_cost_units", spent_cost_units, allow_zero=True)
    gate_decision, gate_reason = _propagation_gate_decision(state, config)
    if gate_decision == "null":
        status, route, reason, actions = STATUS_REVIEW, ROUTE_NULL_CONSISTENT, gate_reason, ()
    elif gate_decision == "review":
        status, route, reason, actions = STATUS_REVIEW, ROUTE_REVIEW, gate_reason, ()
    elif gate_decision == "insufficient":
        status, route, reason, actions = STATUS_INSUFFICIENT, ROUTE_INSUFFICIENT, gate_reason, ()
    elif spent_cost_units > config.max_cost_units:
        status, route, reason, actions = STATUS_INSUFFICIENT, ROUTE_INSUFFICIENT, "budget_exhausted", ()
    elif _candidate_ready(state, config):
        status, route, reason, actions = STATUS_CANDIDATE, ROUTE_SELECTION_SPECIFIC, "all_registered_gates_pass", ()
    else:
        action_id, reason = _reasoned_action(state, config)
        if not action_id:
            if state.selection_route == ROUTE_NULL_CONSISTENT or state.invariant_route == ROUTE_NULL_CONSISTENT:
                status, route, reason, actions = STATUS_REVIEW, ROUTE_NULL_CONSISTENT, "ordinary_propagation_consistent_or_no_positive_gate", ()
            elif state.selection_route == ROUTE_SELECTION_AMBIGUOUS:
                status, route, reason, actions = STATUS_REVIEW, ROUTE_SELECTION_AMBIGUOUS, "selection_ambiguity_unresolved", ()
            else:
                status, route, reason, actions = STATUS_INSUFFICIENT, ROUTE_INSUFFICIENT, "no_registered_probe_can_repair_state", ()
        elif action_id in state.completed_actions:
            status, route, reason, actions = STATUS_INSUFFICIENT, ROUTE_INSUFFICIENT, "required_probe_already_completed", ()
        else:
            cost = config.cost_map[action_id]
            if len(state.completed_actions) >= config.max_actions or spent_cost_units + cost > config.max_cost_units:
                status, route, reason, actions = STATUS_REVIEW, ROUTE_REVIEW, "budget_or_action_limit_reached", ()
            else:
                status, route, actions = STATUS_ACQUIRE, ROUTE_REVIEW, (SelectionAwareAction(action_id, cost, reason),)
    plan_body = {
        "version": VERSION,
        "state_digest": state.input_digest,
        "config": config.to_dict(),
        "status": status,
        "route": route,
        "reason": reason,
        "actions": [action.to_dict() for action in actions],
        "spent_cost_units": spent_cost_units,
    }
    return SelectionAwarePlan(
        status=status,
        route=route,
        reason=reason,
        case_id=state.case_id,
        actions=actions,
        spent_cost_units=spent_cost_units,
        remaining_cost_units=max(0, config.max_cost_units - spent_cost_units),
        policy_digest=config.policy_digest,
        input_digest=state.input_digest,
        plan_digest=_digest(plan_body),
        propagation_gate_digest=_gate_digest_for_state(state),
        generator_route=state.generator_route,
        retrieval_replay_route=state.retrieval_replay_route,
    )


def _apply_updates(state: SelectionAwareEvidenceState, updates: Mapping[str, Any]) -> SelectionAwareEvidenceState:
    fields = state.to_dict()
    fields.update(dict(updates))
    fields["completed_actions"] = state.completed_actions
    return SelectionAwareEvidenceState(**fields)


def _result_from_state(
    state: SelectionAwareEvidenceState,
    *,
    config: SelectionAwareAcquisitionConfig,
    steps: Tuple[SelectionAwareObservation, ...],
    status: str,
    route: str,
    reason: str,
    spent: int,
) -> SelectionAwareAcquisitionResult:
    trace_digest = _digest([step.to_dict() for step in steps])
    evidence_digest = _digest({"state": state.to_dict(), "policy_digest": config.policy_digest, "trace_digest": trace_digest})
    abstained = route in {ROUTE_SELECTION_AMBIGUOUS, ROUTE_NULL_CONSISTENT, ROUTE_REVIEW, ROUTE_INSUFFICIENT}
    return SelectionAwareAcquisitionResult(
        route=route,
        status=status,
        abstained=abstained,
        reason=reason,
        case_id=state.case_id,
        steps=steps,
        spent_cost_units=spent,
        remaining_cost_units=max(0, config.max_cost_units - spent),
        policy_digest=config.policy_digest,
        evidence_digest=evidence_digest,
        trace_digest=trace_digest,
        propagation_gate_digest=_gate_digest_for_state(state),
        generator_route=state.generator_route,
        retrieval_replay_route=state.retrieval_replay_route,
    )


def run_selection_aware_acquisition(
    state: SelectionAwareEvidenceState,
    observations: Iterable[SelectionAwareObservation],
    *,
    config: Optional[SelectionAwareAcquisitionConfig] = None,
) -> SelectionAwareAcquisitionResult:
    """Replay a trace; malformed order, failures and budget overrun abstain."""

    if isinstance(observations, (str, bytes)):
        raise ValueError("observations must be an iterable of SelectionAwareObservation")
    config = config or SelectionAwareAcquisitionConfig()
    current = state
    steps: Tuple[SelectionAwareObservation, ...] = ()
    spent = 0
    for observation in observations:
        plan = plan_selection_aware_acquisition(current, config=config, spent_cost_units=spent)
        if plan.status != STATUS_ACQUIRE or plan.next_action is None:
            return _result_from_state(current, config=config, steps=steps, status=plan.status, route=plan.route, reason="trace_after_terminal", spent=spent)
        expected = plan.next_action
        if observation.action_id != expected.action_id or observation.step != len(steps) + 1 or observation.input_digest != current.input_digest:
            return _result_from_state(current, config=config, steps=steps, status=STATUS_INSUFFICIENT, route=ROUTE_INSUFFICIENT, reason="action_order_or_input_mismatch", spent=spent)
        cost = expected.cost_units
        if spent + cost > config.max_cost_units:
            return _result_from_state(current, config=config, steps=steps, status=STATUS_REVIEW, route=ROUTE_REVIEW, reason="budget_exhausted", spent=spent)
        steps = steps + (observation,)
        spent += cost
        completed = current.completed_actions + (observation.action_id,)
        if not observation.ok:
            current = replace(current, completed_actions=completed)
            return _result_from_state(current, config=config, steps=steps, status=STATUS_REVIEW, route=ROUTE_REVIEW, reason="probe_failed", spent=spent)
        try:
            current = _apply_updates(replace(current, completed_actions=completed), observation.raw_updates)
        except ValueError:
            return _result_from_state(current, config=config, steps=steps, status=STATUS_INSUFFICIENT, route=ROUTE_INSUFFICIENT, reason="probe_update_invalid", spent=spent)
    plan = plan_selection_aware_acquisition(current, config=config, spent_cost_units=spent)
    return _result_from_state(current, config=config, steps=steps, status=plan.status, route=plan.route, reason=plan.reason, spent=spent)


def replay_selection_aware_acquisition(
    state: SelectionAwareEvidenceState,
    observations: Iterable[SelectionAwareObservation],
    *,
    config: Optional[SelectionAwareAcquisitionConfig] = None,
) -> SelectionAwareAcquisitionResult:
    return run_selection_aware_acquisition(state, observations, config=config)


__all__ = [
    "VERSION",
    "SCHEMA",
    "POLICY_SCHEMA",
    "GATE_VERSION",
    "GATE_SCHEMA",
    "ROUTE_SELECTION_SPECIFIC",
    "ROUTE_SELECTION_AMBIGUOUS",
    "ROUTE_NULL_CONSISTENT",
    "ROUTE_REVIEW",
    "ROUTE_INSUFFICIENT",
    "ACTION_APPEND_DECOY",
    "ACTION_BUILD_NULL",
    "ACTION_ALTERNATE_VIEW",
    "ACTION_ALTERNATE_OPERATOR",
    "ACTION_REALIGN_QUALITY",
    "STATUS_ACQUIRE",
    "STATUS_CANDIDATE",
    "STATUS_REVIEW",
    "STATUS_INSUFFICIENT",
    "GENERATOR_ROUTE_KNOWN_FAMILY_SUPPORTED",
    "GENERATOR_ROUTE_EVIDENCE_NOT_REQUIRED",
    "GENERATOR_ROUTE_REAL_CONSISTENT",
    "GENERATOR_ROUTE_OPEN_SET_UNKNOWN",
    "GENERATOR_ROUTE_CONFLICT_REVIEW",
    "GENERATOR_ROUTE_INSUFFICIENT",
    "GENERATOR_ROUTE_NOT_EVALUATED",
    "RETRIEVAL_REPLAY_ROUTE_CONSISTENT",
    "RETRIEVAL_REPLAY_ROUTE_NOT_REQUIRED",
    "RETRIEVAL_REPLAY_ROUTE_OPEN_SET_UNKNOWN",
    "RETRIEVAL_REPLAY_ROUTE_CONFLICT_REVIEW",
    "RETRIEVAL_REPLAY_ROUTE_REVIEW",
    "RETRIEVAL_REPLAY_ROUTE_INSUFFICIENT",
    "RETRIEVAL_REPLAY_ROUTE_NOT_EVALUATED",
    "RETRIEVAL_REPLAY_ROUTE_POISONING",
    "RETRIEVAL_REPLAY_ROUTE_ROUTE_FLIP",
    "RETRIEVAL_REPLAY_ROUTE_CANDIDATE",
    "OPERATION_SCOPE_CONTENT_EDIT",
    "OPERATION_SCOPE_ORDINARY_PROPAGATION",
    "compute_gate_policy_digest",
    "compute_generator_evidence_digest",
    "compute_retrieval_event_digest",
    "SelectionAwareAcquisitionConfig",
    "SelectionAwarePropagationGate",
    "SelectionAwareEvidenceState",
    "SelectionAwareAction",
    "SelectionAwarePlan",
    "SelectionAwareObservation",
    "SelectionAwareAcquisitionResult",
    "plan_selection_aware_acquisition",
    "run_selection_aware_acquisition",
    "replay_selection_aware_acquisition",
]
