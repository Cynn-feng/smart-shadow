"""Budgeted active evidence acquisition for the PC-SCFT research protocol.

The policy chooses *which raw observation to acquire next* when a source
conditioned case is inconclusive.  It is intentionally model independent:
the plan is not a detector score, a probability, or an AIGC decision.  Every
planned action has a cost, a reason, and a stable identity so an executor can
later append input/output hashes, timing, and failures to the same evidence
chain.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Optional, Tuple


VERSION = "evidence-acquisition-plan-v1"

ACTION_VERIFY_PROVENANCE = "verify_provenance"
ACTION_REALIGN_REGION = "realign_region"
ACTION_BUILD_COUNTERFACTUAL = "build_counterfactual"
ACTION_ZOOM_REGION = "zoom_region"
ACTION_REPEAT_DETECTOR = "repeat_detector"

PLAN_ACQUIRE = "acquire"
PLAN_NO_ACTION = "no_action"
PLAN_REVIEW = "review"
PLAN_INSUFFICIENT = "insufficient"


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _unit(name: str, value: float, *, allow_none: bool = False) -> Optional[float]:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return normalized


def _positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True)
class EvidenceAcquisitionState:
    """Raw state available before an additional observation is requested."""

    asset_id: str
    detector_version: str
    score_schema: str
    quality_score: Optional[float]
    source_match_score: Optional[float]
    regional_coverage_raw: Optional[float] = None
    null_evaluated: bool = False
    null_rejected: bool = False
    shape_ambiguous: bool = False
    provenance_verified: bool = False
    uncertainty_raw: Optional[float] = None
    completed_actions: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _non_empty("asset_id", self.asset_id)
        _non_empty("detector_version", self.detector_version)
        _non_empty("score_schema", self.score_schema)
        _unit("quality_score", self.quality_score, allow_none=True)
        _unit("source_match_score", self.source_match_score, allow_none=True)
        _unit("regional_coverage_raw", self.regional_coverage_raw, allow_none=True)
        _unit("uncertainty_raw", self.uncertainty_raw, allow_none=True)
        for name, value in (
            ("null_evaluated", self.null_evaluated),
            ("null_rejected", self.null_rejected),
            ("shape_ambiguous", self.shape_ambiguous),
            ("provenance_verified", self.provenance_verified),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a bool")
        if isinstance(self.completed_actions, (str, bytes)):
            raise ValueError("completed_actions must be a sequence")
        actions = tuple(_non_empty("completed_action", value) for value in self.completed_actions)
        if len(set(actions)) != len(actions):
            raise ValueError("completed_actions must be unique")
        object.__setattr__(self, "completed_actions", actions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "regional_coverage_raw": self.regional_coverage_raw,
            "null_evaluated": self.null_evaluated,
            "null_rejected": self.null_rejected,
            "shape_ambiguous": self.shape_ambiguous,
            "provenance_verified": self.provenance_verified,
            "uncertainty_raw": self.uncertainty_raw,
            "completed_actions": list(self.completed_actions),
        }


@dataclass(frozen=True)
class EvidenceAcquisitionConfig:
    """Hard limits and quality gates for the action planner."""

    max_actions: int = 2
    max_cost_units: int = 4
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    minimum_coverage: float = 0.75
    uncertainty_trigger: float = 0.50

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_actions": self.max_actions,
            "max_cost_units": self.max_cost_units,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "minimum_coverage": self.minimum_coverage,
            "uncertainty_trigger": self.uncertainty_trigger,
        }

    @property
    def digest(self) -> str:
        return _digest({"version": VERSION, "config": self.to_dict()})


@dataclass(frozen=True)
class EvidenceAction:
    """One planned raw observation; it has not been executed yet."""

    action: str
    cost_units: int
    priority_raw: float
    reason: str
    target: str = "asset"

    def __post_init__(self) -> None:
        _non_empty("action", self.action)
        _positive_int("cost_units", self.cost_units)
        _unit("priority_raw", self.priority_raw)
        _non_empty("reason", self.reason)
        _non_empty("target", self.target)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "cost_units": self.cost_units,
            "priority_raw": self.priority_raw,
            "reason": self.reason,
            "target": self.target,
        }


@dataclass(frozen=True)
class EvidenceAcquisitionPlan:
    """Auditable, bounded plan returned before executing any action."""

    status: str
    reason: str
    asset_id: str
    detector_version: str
    score_schema: str
    actions: Tuple[EvidenceAction, ...]
    spent_cost_units: int
    remaining_cost_units: int
    config_digest: str
    plan_digest: str
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.status not in {PLAN_ACQUIRE, PLAN_NO_ACTION, PLAN_REVIEW, PLAN_INSUFFICIENT}:
            raise ValueError("invalid evidence acquisition plan status")
        _non_empty("reason", self.reason)
        _non_empty("asset_id", self.asset_id)
        _non_empty("detector_version", self.detector_version)
        _non_empty("score_schema", self.score_schema)
        if isinstance(self.actions, (str, bytes)):
            raise ValueError("actions must be a sequence")
        actions = tuple(self.actions)
        if any(not isinstance(action, EvidenceAction) for action in actions):
            raise ValueError("actions must contain EvidenceAction values")
        if len({action.action for action in actions}) != len(actions):
            raise ValueError("actions must have unique action names")
        object.__setattr__(self, "actions", actions)
        if self.spent_cost_units < 0 or self.remaining_cost_units < 0:
            raise ValueError("cost units cannot be negative")
        if len(self.config_digest) != 64 or len(self.plan_digest) != 64:
            raise ValueError("digests must be SHA-256 hex strings")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "reason": self.reason,
            "asset_id": self.asset_id,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "actions": [action.to_dict() for action in self.actions],
            "spent_cost_units": self.spent_cost_units,
            "remaining_cost_units": self.remaining_cost_units,
            "config_digest": self.config_digest,
            "plan_digest": self.plan_digest,
        }


def _make_plan(
    state: EvidenceAcquisitionState,
    config: EvidenceAcquisitionConfig,
    *,
    status: str,
    reason: str,
    actions: Tuple[EvidenceAction, ...],
    spent: int,
) -> EvidenceAcquisitionPlan:
    body = {
        "version": VERSION,
        "state": state.to_dict(),
        "config": config.to_dict(),
        "status": status,
        "reason": reason,
        "actions": [action.to_dict() for action in actions],
        "spent_cost_units": spent,
    }
    return EvidenceAcquisitionPlan(
        status=status,
        reason=reason,
        asset_id=state.asset_id,
        detector_version=state.detector_version,
        score_schema=state.score_schema,
        actions=actions,
        spent_cost_units=spent,
        remaining_cost_units=config.max_cost_units - spent,
        config_digest=config.digest,
        plan_digest=_digest(body),
    )


def plan_evidence_acquisition(
    state: EvidenceAcquisitionState,
    *,
    config: Optional[EvidenceAcquisitionConfig] = None,
) -> EvidenceAcquisitionPlan:
    """Choose bounded follow-up observations from raw evidence gaps.

    The priority order is deterministic.  Quality and source-match failures
    stop the plan early because additional calls cannot repair an unusable
    reference.  Otherwise actions are selected greedily by priority while
    respecting both action count and cost budgets.  Completed action names are
    never silently scheduled again.
    """

    if not isinstance(state, EvidenceAcquisitionState):
        raise ValueError("state must be EvidenceAcquisitionState")
    cfg = config or EvidenceAcquisitionConfig()
    if state.quality_score is None or state.quality_score < cfg.minimum_quality:
        return _make_plan(
            state,
            cfg,
            status=PLAN_INSUFFICIENT,
            reason="quality_gate",
            actions=(),
            spent=0,
        )
    if state.source_match_score is None or state.source_match_score < cfg.minimum_source_match:
        return _make_plan(
            state,
            cfg,
            status=PLAN_INSUFFICIENT,
            reason="source_match_gate",
            actions=(),
            spent=0,
        )

    completed = set(state.completed_actions)
    candidates = []

    def add(action: str, cost: int, priority: float, reason: str, target: str = "asset") -> None:
        if action not in completed:
            candidates.append(EvidenceAction(action, cost, priority, reason, target))

    if not state.provenance_verified:
        add(ACTION_VERIFY_PROVENANCE, 1, 1.00, "provenance_unverified")
    if not state.null_evaluated:
        add(ACTION_BUILD_COUNTERFACTUAL, 2, 0.95, "paired_null_unavailable")
    if state.shape_ambiguous:
        add(ACTION_REALIGN_REGION, 2, 0.90, "patch_shape_ambiguous", "regions")
    if state.regional_coverage_raw is None or state.regional_coverage_raw < cfg.minimum_coverage:
        add(ACTION_ZOOM_REGION, 2, 0.85, "regional_coverage_low", "uncovered_regions")
    if state.uncertainty_raw is not None and state.uncertainty_raw >= cfg.uncertainty_trigger:
        add(ACTION_REPEAT_DETECTOR, 2, 0.60, "detector_uncertainty_high")

    candidates.sort(key=lambda item: (-item.priority_raw, item.cost_units, item.action))
    selected = []
    spent = 0
    for action in candidates:
        if len(selected) >= cfg.max_actions:
            break
        if spent + action.cost_units > cfg.max_cost_units:
            continue
        selected.append(action)
        spent += action.cost_units

    if selected:
        return _make_plan(
            state,
            cfg,
            status=PLAN_ACQUIRE,
            reason="evidence_gaps_within_budget",
            actions=tuple(selected),
            spent=spent,
        )
    if candidates:
        return _make_plan(
            state,
            cfg,
            status=PLAN_REVIEW,
            reason="budget_cannot_cover_next_observation",
            actions=(),
            spent=0,
        )
    return _make_plan(
        state,
        cfg,
        status=PLAN_NO_ACTION,
        reason="no_policy_gap",
        actions=(),
        spent=0,
    )
