"""Counterfactual intervention validity gate.

The source-conditioned pipeline already binds a reference, query, mask and
ordinary-propagation control.  This module adds the missing input-quality
boundary: a counterfactual must demonstrate that the target changed, the
non-target stayed sufficiently stable, and the intervention itself is
replayable before its effect can enter a downstream raw-evidence route.

The gate does not run a detector, fit a null profile, or emit an AIGC label.
``valid_intervention`` means only that the input is eligible for a later
source-conditioned audit.  All scores are raw observations.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Optional, Tuple


VERSION = "counterfactual-intervention-validity-gate-v1"
SCHEMA = "counterfactual-intervention-validity-result-v1"

ROUTE_VALID = "valid_intervention"
ROUTE_SPILLOVER = "spillover_review"
ROUTE_INVALID = "counterfactual_invalid"
ROUTE_INSUFFICIENT = "insufficient"
ROUTES = {ROUTE_VALID, ROUTE_SPILLOVER, ROUTE_INVALID, ROUTE_INSUFFICIENT}

CONTENT_EDIT = "content_edit"
ORDINARY_PROPAGATION = "ordinary_propagation"
DECOY = "decoy"
WRONG_REFERENCE = "wrong_reference"
INTERVENTION_SCOPES = {CONTENT_EDIT, ORDINARY_PROPAGATION, DECOY, WRONG_REFERENCE}

_DIGEST_FIELDS = (
    "reference_digest",
    "observed_digest",
    "counterfactual_digest",
    "pair_binding_digest",
    "ordinary_null_digest",
    "target_mask_digest",
    "operator_digest",
    "execution_digest",
)
_SCORE_FIELDS = (
    "quality_score",
    "source_match_score",
    "target_effect_raw",
    "non_target_preservation_raw",
    "mask_leakage_raw",
    "semantic_consistency_raw",
    "causal_consistency_raw",
    "minimum_intervention_raw",
)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_digest(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _check_unit(name: str, value: Optional[float]) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number or None")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")


def _check_text(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True)
class CIVGConfig:
    """Conservative raw gates used by the offline contract."""

    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    minimum_target_effect: float = 0.20
    minimum_non_target_preservation: float = 0.80
    maximum_mask_leakage: float = 0.20
    minimum_semantic_consistency: float = 0.60
    minimum_causal_consistency: float = 0.60
    minimum_intervention: float = 0.60

    def __post_init__(self) -> None:
        for name in (
            "minimum_quality",
            "minimum_source_match",
            "minimum_target_effect",
            "minimum_non_target_preservation",
            "maximum_mask_leakage",
            "minimum_semantic_consistency",
            "minimum_causal_consistency",
            "minimum_intervention",
        ):
            _check_unit(name, getattr(self, name))

    def to_dict(self) -> Dict[str, float]:
        return {
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "minimum_target_effect": self.minimum_target_effect,
            "minimum_non_target_preservation": self.minimum_non_target_preservation,
            "maximum_mask_leakage": self.maximum_mask_leakage,
            "minimum_semantic_consistency": self.minimum_semantic_consistency,
            "minimum_causal_consistency": self.minimum_causal_consistency,
            "minimum_intervention": self.minimum_intervention,
        }

    @property
    def digest(self) -> str:
        return _digest({"version": VERSION, "config": self.to_dict()})


@dataclass(frozen=True)
class CIVGObservation:
    """One bound observed/query/counterfactual validity observation."""

    asset_id: str
    pair_id: str
    intervention_scope: str
    reference_digest: str
    observed_digest: str
    counterfactual_digest: str
    canonical_frame: str
    detector_version: str
    score_schema: str
    authorized: bool
    executed: bool
    pair_binding_digest: Optional[str] = None
    ordinary_null_digest: Optional[str] = None
    target_mask_digest: Optional[str] = None
    operator_digest: Optional[str] = None
    execution_digest: Optional[str] = None
    quality_score: Optional[float] = None
    source_match_score: Optional[float] = None
    target_effect_raw: Optional[float] = None
    non_target_preservation_raw: Optional[float] = None
    mask_leakage_raw: Optional[float] = None
    semantic_consistency_raw: Optional[float] = None
    causal_consistency_raw: Optional[float] = None
    minimum_intervention_raw: Optional[float] = None

    def __post_init__(self) -> None:
        for name in (
            "asset_id",
            "pair_id",
            "canonical_frame",
            "detector_version",
            "score_schema",
        ):
            _check_text(name, getattr(self, name))
        if self.intervention_scope not in INTERVENTION_SCOPES:
            raise ValueError("unsupported intervention_scope")
        for name in (
            "reference_digest",
            "observed_digest",
            "counterfactual_digest",
        ):
            if not _is_digest(getattr(self, name)):
                raise ValueError(f"{name} must be a SHA-256 hex digest")
        for name in (
            "pair_binding_digest",
            "ordinary_null_digest",
            "target_mask_digest",
            "operator_digest",
            "execution_digest",
        ):
            value = getattr(self, name)
            if value is not None and not _is_digest(value):
                raise ValueError(f"{name} must be a SHA-256 hex digest or None")
        for name in _SCORE_FIELDS:
            _check_unit(name, getattr(self, name))
        if not isinstance(self.authorized, bool) or not isinstance(self.executed, bool):
            raise ValueError("authorized and executed must be bools")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "counterfactual-intervention-validity-observation-v1",
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "intervention_scope": self.intervention_scope,
            "reference_digest": self.reference_digest,
            "observed_digest": self.observed_digest,
            "counterfactual_digest": self.counterfactual_digest,
            "canonical_frame": self.canonical_frame,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "authorized": self.authorized,
            "executed": self.executed,
            "pair_binding_digest": self.pair_binding_digest,
            "ordinary_null_digest": self.ordinary_null_digest,
            "target_mask_digest": self.target_mask_digest,
            "operator_digest": self.operator_digest,
            "execution_digest": self.execution_digest,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "target_effect_raw": self.target_effect_raw,
            "non_target_preservation_raw": self.non_target_preservation_raw,
            "mask_leakage_raw": self.mask_leakage_raw,
            "semantic_consistency_raw": self.semantic_consistency_raw,
            "causal_consistency_raw": self.causal_consistency_raw,
            "minimum_intervention_raw": self.minimum_intervention_raw,
        }


@dataclass(frozen=True)
class CIVGResult:
    """Fail-closed raw route; never an AIGC or legal conclusion."""

    route: str
    abstained: bool
    downstream_eligible: bool
    reason: str
    asset_id: str
    pair_id: str
    intervention_scope: str
    failure_reasons: Tuple[str, ...]
    target_effect_raw: Optional[float]
    non_target_preservation_raw: Optional[float]
    mask_leakage_raw: Optional[float]
    semantic_consistency_raw: Optional[float]
    causal_consistency_raw: Optional[float]
    minimum_intervention_raw: Optional[float]
    quality_score: Optional[float]
    source_match_score: Optional[float]
    config_digest: str
    evidence_digest: str
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.route not in ROUTES:
            raise ValueError("invalid CIVG route")
        if self.route == ROUTE_VALID and (self.abstained or not self.downstream_eligible):
            raise ValueError("valid_intervention requires downstream eligibility")
        if self.route != ROUTE_VALID and (not self.abstained or self.downstream_eligible):
            raise ValueError("non-valid routes must abstain")
        _check_text("reason", self.reason)
        _check_text("asset_id", self.asset_id)
        _check_text("pair_id", self.pair_id)
        if self.intervention_scope not in INTERVENTION_SCOPES:
            raise ValueError("unsupported intervention_scope")
        if not isinstance(self.failure_reasons, tuple):
            raise ValueError("failure_reasons must be a tuple")
        for name in (
            "target_effect_raw",
            "non_target_preservation_raw",
            "mask_leakage_raw",
            "semantic_consistency_raw",
            "causal_consistency_raw",
            "minimum_intervention_raw",
            "quality_score",
            "source_match_score",
        ):
            _check_unit(name, getattr(self, name))
        if not _is_digest(self.config_digest) or not _is_digest(self.evidence_digest):
            raise ValueError("config_digest and evidence_digest must be SHA-256 hex digests")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": SCHEMA,
            "version": self.version,
            "route": self.route,
            "abstained": self.abstained,
            "downstream_eligible": self.downstream_eligible,
            "reason": self.reason,
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "intervention_scope": self.intervention_scope,
            "failure_reasons": list(self.failure_reasons),
            "target_effect_raw": self.target_effect_raw,
            "non_target_preservation_raw": self.non_target_preservation_raw,
            "mask_leakage_raw": self.mask_leakage_raw,
            "semantic_consistency_raw": self.semantic_consistency_raw,
            "causal_consistency_raw": self.causal_consistency_raw,
            "minimum_intervention_raw": self.minimum_intervention_raw,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "config_digest": self.config_digest,
            "evidence_digest": self.evidence_digest,
        }


def _result(
    observation: CIVGObservation,
    config: CIVGConfig,
    route: str,
    reason: str,
    failure_reasons: Tuple[str, ...],
    *,
    downstream_eligible: bool,
) -> CIVGResult:
    evidence_digest = _digest(
        {
            "version": VERSION,
            "observation": observation.to_dict(),
            "config": config.to_dict(),
            "decision": {
                "route": route,
                "reason": reason,
                "failure_reasons": list(failure_reasons),
            },
        }
    )
    return CIVGResult(
        route=route,
        abstained=route != ROUTE_VALID,
        downstream_eligible=downstream_eligible,
        reason=reason,
        asset_id=observation.asset_id,
        pair_id=observation.pair_id,
        intervention_scope=observation.intervention_scope,
        failure_reasons=failure_reasons,
        target_effect_raw=observation.target_effect_raw,
        non_target_preservation_raw=observation.non_target_preservation_raw,
        mask_leakage_raw=observation.mask_leakage_raw,
        semantic_consistency_raw=observation.semantic_consistency_raw,
        causal_consistency_raw=observation.causal_consistency_raw,
        minimum_intervention_raw=observation.minimum_intervention_raw,
        quality_score=observation.quality_score,
        source_match_score=observation.source_match_score,
        config_digest=config.digest,
        evidence_digest=evidence_digest,
    )


def evaluate_civg(
    observation: CIVGObservation,
    *,
    config: Optional[CIVGConfig] = None,
) -> CIVGResult:
    """Evaluate one intervention validity observation with fixed fail-closed order."""

    if not isinstance(observation, CIVGObservation):
        raise ValueError("observation must be CIVGObservation")
    cfg = config or CIVGConfig()

    if observation.intervention_scope != CONTENT_EDIT:
        return _result(
            observation,
            cfg,
            ROUTE_INVALID,
            "scope_not_content_edit",
            ("scope_not_content_edit",),
            downstream_eligible=False,
        )
    if not observation.authorized:
        return _result(
            observation,
            cfg,
            ROUTE_INSUFFICIENT,
            "unauthorized_input",
            ("unauthorized_input",),
            downstream_eligible=False,
        )
    if not observation.executed:
        return _result(
            observation,
            cfg,
            ROUTE_INSUFFICIENT,
            "execution_missing",
            ("execution_missing",),
            downstream_eligible=False,
        )

    required_bindings = (
        "pair_binding_digest",
        "ordinary_null_digest",
        "target_mask_digest",
        "operator_digest",
        "execution_digest",
    )
    missing_bindings = tuple(
        f"missing_{name}"
        for name in required_bindings
        if getattr(observation, name) is None
    )
    if missing_bindings:
        return _result(
            observation,
            cfg,
            ROUTE_INSUFFICIENT,
            "binding_incomplete",
            missing_bindings,
            downstream_eligible=False,
        )
    if observation.observed_digest == observation.counterfactual_digest:
        return _result(
            observation,
            cfg,
            ROUTE_INVALID,
            "observed_counterfactual_identical",
            ("observed_counterfactual_identical",),
            downstream_eligible=False,
        )
    if observation.quality_score is None or observation.quality_score < cfg.minimum_quality:
        return _result(
            observation,
            cfg,
            ROUTE_INSUFFICIENT,
            "quality_below_threshold",
            ("quality_below_threshold",),
            downstream_eligible=False,
        )
    if observation.source_match_score is None or observation.source_match_score < cfg.minimum_source_match:
        return _result(
            observation,
            cfg,
            ROUTE_INSUFFICIENT,
            "source_match_below_threshold",
            ("source_match_below_threshold",),
            downstream_eligible=False,
        )

    required_scores = (
        "target_effect_raw",
        "non_target_preservation_raw",
        "mask_leakage_raw",
        "semantic_consistency_raw",
        "causal_consistency_raw",
        "minimum_intervention_raw",
    )
    missing_scores = tuple(
        f"missing_{name}"
        for name in required_scores
        if getattr(observation, name) is None
    )
    if missing_scores:
        return _result(
            observation,
            cfg,
            ROUTE_INSUFFICIENT,
            "validity_signal_missing",
            missing_scores,
            downstream_eligible=False,
        )

    assert observation.target_effect_raw is not None
    assert observation.non_target_preservation_raw is not None
    assert observation.mask_leakage_raw is not None
    assert observation.semantic_consistency_raw is not None
    assert observation.causal_consistency_raw is not None
    assert observation.minimum_intervention_raw is not None

    invalid_reasons = []
    if observation.target_effect_raw < cfg.minimum_target_effect:
        invalid_reasons.append("target_effect_below_threshold")
    if observation.semantic_consistency_raw < cfg.minimum_semantic_consistency:
        invalid_reasons.append("semantic_consistency_below_threshold")
    if observation.causal_consistency_raw < cfg.minimum_causal_consistency:
        invalid_reasons.append("causal_consistency_below_threshold")
    if observation.minimum_intervention_raw < cfg.minimum_intervention:
        invalid_reasons.append("minimum_intervention_below_threshold")
    if invalid_reasons:
        return _result(
            observation,
            cfg,
            ROUTE_INVALID,
            invalid_reasons[0],
            tuple(invalid_reasons),
            downstream_eligible=False,
        )

    spillover_reasons = []
    if observation.non_target_preservation_raw < cfg.minimum_non_target_preservation:
        spillover_reasons.append("non_target_preservation_below_threshold")
    if observation.mask_leakage_raw > cfg.maximum_mask_leakage:
        spillover_reasons.append("mask_leakage_above_threshold")
    if spillover_reasons:
        return _result(
            observation,
            cfg,
            ROUTE_SPILLOVER,
            spillover_reasons[0],
            tuple(spillover_reasons),
            downstream_eligible=False,
        )

    return _result(
        observation,
        cfg,
        ROUTE_VALID,
        "validity_gate_passed",
        (),
        downstream_eligible=True,
    )


__all__ = [
    "VERSION",
    "SCHEMA",
    "ROUTE_VALID",
    "ROUTE_SPILLOVER",
    "ROUTE_INVALID",
    "ROUTE_INSUFFICIENT",
    "CONTENT_EDIT",
    "ORDINARY_PROPAGATION",
    "DECOY",
    "WRONG_REFERENCE",
    "CIVGConfig",
    "CIVGObservation",
    "CIVGResult",
    "evaluate_civg",
]
