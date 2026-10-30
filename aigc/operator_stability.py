"""Multi-operator stability audit for source-conditioned interventions.

This module is a quality gate around ``explanation_audit_v1``.  It consumes
already executed, source-bound evidence for several pre-registered operators
and checks that each operator supports the same observed-minus-null contrast.
It deliberately does not average operators, fit a detector, or emit an AIGC
probability.  The old single-operator explanation schema remains replayable.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


VERSION = "operator-stability-v1"
SCHEMA = "operator-stability-result-v1"

ROUTE_STABLE_GROUNDED = "operator_stable_grounded"
ROUTE_INCONSISTENT = "operator_inconsistent"
ROUTE_INCONCLUSIVE = "operator_inconclusive"
ROUTE_INSUFFICIENT = "insufficient"

EXPLANATION_ROUTES = {
    "grounded_consistent",
    "maskout_inconsistent",
    "inconclusive",
    "insufficient",
}


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _hex(name: str, value: str) -> str:
    value = _text(name, value).lower()
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
    return value


def _finite(name: str, value: float, *, lower: float = -2.0, upper: float = 2.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or value < lower or value > upper:
        raise ValueError(f"{name} must be finite and between {lower} and {upper}")
    return value


def _unit(name: str, value: float) -> float:
    return _finite(name, value, lower=0.0, upper=1.0)


def _optional_effect(name: str, value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return _finite(name, value)


@dataclass(frozen=True)
class OperatorStabilityConfig:
    """Fixed gates for the multi-operator audit."""

    minimum_operator_count: int = 2
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    minimum_contrast_raw: float = 0.05
    minimum_swap_contrast_raw: float = 0.05
    maximum_abs_null_effect_raw: float = 0.40
    maximum_contrast_spread_raw: float = 0.20
    maximum_swap_contrast_spread_raw: float = 0.20

    def __post_init__(self) -> None:
        if isinstance(self.minimum_operator_count, bool) or not isinstance(
            self.minimum_operator_count, int
        ):
            raise ValueError("minimum_operator_count must be an integer")
        if self.minimum_operator_count < 2:
            raise ValueError("minimum_operator_count must be at least two")
        for name in (
            "minimum_quality",
            "minimum_source_match",
            "minimum_contrast_raw",
            "minimum_swap_contrast_raw",
            "maximum_abs_null_effect_raw",
        ):
            _unit(name, getattr(self, name))
        _finite(
            "maximum_contrast_spread_raw",
            self.maximum_contrast_spread_raw,
            lower=0.0,
            upper=4.0,
        )
        _finite(
            "maximum_swap_contrast_spread_raw",
            self.maximum_swap_contrast_spread_raw,
            lower=0.0,
            upper=4.0,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "minimum_operator_count": self.minimum_operator_count,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "minimum_contrast_raw": self.minimum_contrast_raw,
            "minimum_swap_contrast_raw": self.minimum_swap_contrast_raw,
            "maximum_abs_null_effect_raw": self.maximum_abs_null_effect_raw,
            "maximum_contrast_spread_raw": self.maximum_contrast_spread_raw,
            "maximum_swap_contrast_spread_raw": self.maximum_swap_contrast_spread_raw,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class OperatorStabilityObservation:
    """One operator's already executed D-050 raw evidence."""

    operator_id: str
    operator_config_digest: str
    operator_execution_digest: str
    binding_digest: str
    asset_id: str
    pair_id: str
    manifest_digest: str
    canonical_frame_digest: str
    proposal_mask_digest: str
    detector_version: str
    score_schema: str
    null_profile_digest: str
    quality_score: float
    source_match_raw: float
    null_quality_score: float
    null_source_match_raw: float
    operator_route: str
    operator_validity: bool
    mask_out_executed: bool
    region_swap_executed: bool
    observed_effect_raw: Optional[float]
    null_effect_raw: Optional[float]
    contrast_raw: Optional[float]
    observed_swap_effect_raw: Optional[float]
    null_swap_effect_raw: Optional[float]
    swap_contrast_raw: Optional[float]
    failure_reason: Optional[str] = None

    def __post_init__(self) -> None:
        for name in (
            "operator_id",
            "asset_id",
            "pair_id",
            "detector_version",
            "score_schema",
        ):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        for name in (
            "operator_config_digest",
            "operator_execution_digest",
            "binding_digest",
            "manifest_digest",
            "canonical_frame_digest",
            "proposal_mask_digest",
            "null_profile_digest",
        ):
            object.__setattr__(self, name, _hex(name, getattr(self, name)))
        if self.operator_route not in EXPLANATION_ROUTES:
            raise ValueError("unsupported operator_route")
        if not isinstance(self.operator_validity, bool):
            raise ValueError("operator_validity must be bool")
        if not isinstance(self.mask_out_executed, bool):
            raise ValueError("mask_out_executed must be bool")
        if not isinstance(self.region_swap_executed, bool):
            raise ValueError("region_swap_executed must be bool")
        for name in (
            "quality_score",
            "source_match_raw",
            "null_quality_score",
            "null_source_match_raw",
        ):
            _unit(name, getattr(self, name))
        for name in (
            "observed_effect_raw",
            "null_effect_raw",
            "contrast_raw",
            "observed_swap_effect_raw",
            "null_swap_effect_raw",
            "swap_contrast_raw",
        ):
            object.__setattr__(self, name, _optional_effect(name, getattr(self, name)))
        if self.failure_reason is not None:
            object.__setattr__(self, "failure_reason", _text("failure_reason", self.failure_reason))
        if not self.operator_validity and self.failure_reason is None:
            raise ValueError("invalid operator evidence requires failure_reason")

    @property
    def context_key(self) -> Tuple[Any, ...]:
        return (
            self.binding_digest,
            self.asset_id,
            self.pair_id,
            self.manifest_digest,
            self.canonical_frame_digest,
            self.proposal_mask_digest,
            self.detector_version,
            self.score_schema,
            self.null_profile_digest,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operator_id": self.operator_id,
            "operator_config_digest": self.operator_config_digest,
            "operator_execution_digest": self.operator_execution_digest,
            "binding_digest": self.binding_digest,
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "manifest_digest": self.manifest_digest,
            "canonical_frame_digest": self.canonical_frame_digest,
            "proposal_mask_digest": self.proposal_mask_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "null_profile_digest": self.null_profile_digest,
            "quality_score": self.quality_score,
            "source_match_raw": self.source_match_raw,
            "null_quality_score": self.null_quality_score,
            "null_source_match_raw": self.null_source_match_raw,
            "operator_route": self.operator_route,
            "operator_validity": self.operator_validity,
            "mask_out_executed": self.mask_out_executed,
            "region_swap_executed": self.region_swap_executed,
            "observed_effect_raw": self.observed_effect_raw,
            "null_effect_raw": self.null_effect_raw,
            "contrast_raw": self.contrast_raw,
            "observed_swap_effect_raw": self.observed_swap_effect_raw,
            "null_swap_effect_raw": self.null_swap_effect_raw,
            "swap_contrast_raw": self.swap_contrast_raw,
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class OperatorStabilityResult:
    """Replayable multi-operator raw-evidence result."""

    route: str
    abstained: bool
    reason: str
    operator_count: int
    valid_operator_count: int
    operator_ids: Tuple[str, ...]
    contrast_effects_raw: Tuple[float, ...]
    swap_contrast_effects_raw: Tuple[float, ...]
    contrast_spread_raw: Optional[float]
    swap_contrast_spread_raw: Optional[float]
    pair_id: str
    binding_digest: str
    config_digest: str
    stability_digest: str
    operators: Tuple[Mapping[str, Any], ...]
    version: str = VERSION
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.route not in {
            ROUTE_STABLE_GROUNDED,
            ROUTE_INCONSISTENT,
            ROUTE_INCONCLUSIVE,
            ROUTE_INSUFFICIENT,
        }:
            raise ValueError("unsupported stability route")
        if self.route == ROUTE_STABLE_GROUNDED and self.abstained:
            raise ValueError("operator_stable_grounded cannot be abstained")
        if self.route != ROUTE_STABLE_GROUNDED and not self.abstained:
            raise ValueError("conservative stability routes must be abstained")
        if isinstance(self.operator_count, bool) or self.operator_count < 0:
            raise ValueError("operator_count must be non-negative")
        if isinstance(self.valid_operator_count, bool) or self.valid_operator_count < 0:
            raise ValueError("valid_operator_count must be non-negative")
        object.__setattr__(self, "reason", _text("reason", self.reason))
        object.__setattr__(self, "pair_id", _text("pair_id", self.pair_id))
        object.__setattr__(self, "binding_digest", _hex("binding_digest", self.binding_digest))
        object.__setattr__(self, "config_digest", _hex("config_digest", self.config_digest))
        object.__setattr__(self, "stability_digest", _hex("stability_digest", self.stability_digest))
        ids = tuple(_text("operator_ids", item) for item in self.operator_ids)
        if len(set(ids)) != len(ids):
            raise ValueError("operator_ids must be unique")
        object.__setattr__(self, "operator_ids", ids)
        object.__setattr__(
            self,
            "contrast_effects_raw",
            tuple(_finite("contrast_effects_raw", item) for item in self.contrast_effects_raw),
        )
        object.__setattr__(
            self,
            "swap_contrast_effects_raw",
            tuple(_finite("swap_contrast_effects_raw", item) for item in self.swap_contrast_effects_raw),
        )
        if self.contrast_spread_raw is not None:
            _finite("contrast_spread_raw", self.contrast_spread_raw, lower=0.0, upper=4.0)
        if self.swap_contrast_spread_raw is not None:
            _finite("swap_contrast_spread_raw", self.swap_contrast_spread_raw, lower=0.0, upper=4.0)
        if self.schema != SCHEMA:
            raise ValueError("unsupported stability schema")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "schema": self.schema,
            "route": self.route,
            "abstained": self.abstained,
            "reason": self.reason,
            "operator_count": self.operator_count,
            "valid_operator_count": self.valid_operator_count,
            "operator_ids": list(self.operator_ids),
            "contrast_effects_raw": list(self.contrast_effects_raw),
            "swap_contrast_effects_raw": list(self.swap_contrast_effects_raw),
            "contrast_spread_raw": self.contrast_spread_raw,
            "swap_contrast_spread_raw": self.swap_contrast_spread_raw,
            "pair_id": self.pair_id,
            "binding_digest": self.binding_digest,
            "config_digest": self.config_digest,
            "stability_digest": self.stability_digest,
            "operators": [dict(item) for item in self.operators],
        }


def _empty_digest(label: str) -> str:
    return _digest({"version": VERSION, "missing": label})


def _result(
    observations: Sequence[OperatorStabilityObservation],
    config: OperatorStabilityConfig,
    *,
    route: str,
    reason: str,
    contrast_effects_raw: Tuple[float, ...] = (),
    swap_contrast_effects_raw: Tuple[float, ...] = (),
    contrast_spread_raw: Optional[float] = None,
    swap_contrast_spread_raw: Optional[float] = None,
) -> OperatorStabilityResult:
    rows = tuple(sorted((item.to_dict() for item in observations), key=lambda item: item["operator_id"]))
    binding_digest = observations[0].binding_digest if observations else _empty_digest("binding")
    pair_id = observations[0].pair_id if observations else "unknown"
    valid_count = sum(1 for item in observations if item.operator_validity)
    payload = {
        "version": VERSION,
        "schema": SCHEMA,
        "route": route,
        "reason": reason,
        "config_digest": config.digest,
        "binding_digest": binding_digest,
        "operators": list(rows),
        "contrast_effects_raw": list(contrast_effects_raw),
        "swap_contrast_effects_raw": list(swap_contrast_effects_raw),
        "contrast_spread_raw": contrast_spread_raw,
        "swap_contrast_spread_raw": swap_contrast_spread_raw,
    }
    return OperatorStabilityResult(
        route=route,
        abstained=route != ROUTE_STABLE_GROUNDED,
        reason=reason,
        operator_count=len(observations),
        valid_operator_count=valid_count,
        operator_ids=tuple(item["operator_id"] for item in rows),
        contrast_effects_raw=contrast_effects_raw,
        swap_contrast_effects_raw=swap_contrast_effects_raw,
        contrast_spread_raw=contrast_spread_raw,
        swap_contrast_spread_raw=swap_contrast_spread_raw,
        pair_id=pair_id,
        binding_digest=binding_digest,
        config_digest=config.digest,
        stability_digest=_digest(payload),
        operators=rows,
    )


def _spread(values: Sequence[float]) -> float:
    return max(values) - min(values)


def evaluate_operator_stability(
    observations: Sequence[OperatorStabilityObservation],
    *,
    config: Optional[OperatorStabilityConfig] = None,
) -> OperatorStabilityResult:
    """Evaluate per-operator evidence with fail-closed stability gates."""

    cfg = config or OperatorStabilityConfig()
    try:
        rows = tuple(observations)
    except TypeError as exc:
        raise ValueError("observations must be a sequence") from exc
    if not all(isinstance(item, OperatorStabilityObservation) for item in rows):
        raise ValueError("observations must contain OperatorStabilityObservation values")
    if len(rows) < cfg.minimum_operator_count:
        return _result(rows, cfg, route=ROUTE_INSUFFICIENT, reason="operator_support_insufficient")

    operator_ids = [item.operator_id for item in rows]
    if len(set(operator_ids)) != len(operator_ids):
        return _result(rows, cfg, route=ROUTE_INSUFFICIENT, reason="duplicate_operator_id")
    operator_digests = [item.operator_config_digest for item in rows]
    if len(set(operator_digests)) != len(operator_digests):
        return _result(rows, cfg, route=ROUTE_INSUFFICIENT, reason="duplicate_operator_config")
    execution_digests = [item.operator_execution_digest for item in rows]
    if len(set(execution_digests)) != len(execution_digests):
        return _result(rows, cfg, route=ROUTE_INSUFFICIENT, reason="duplicate_operator_execution")

    context = rows[0].context_key
    if any(item.context_key != context for item in rows[1:]):
        return _result(rows, cfg, route=ROUTE_INSUFFICIENT, reason="operator_binding_mismatch")

    for item in rows:
        if (
            item.quality_score < cfg.minimum_quality
            or item.null_quality_score < cfg.minimum_quality
            or item.source_match_raw < cfg.minimum_source_match
            or item.null_source_match_raw < cfg.minimum_source_match
        ):
            return _result(rows, cfg, route=ROUTE_INSUFFICIENT, reason="operator_quality_or_source_gate")
        if not item.operator_validity:
            return _result(rows, cfg, route=ROUTE_INSUFFICIENT, reason="operator_invalid")
        if item.operator_route == "insufficient":
            return _result(rows, cfg, route=ROUTE_INSUFFICIENT, reason="operator_evidence_insufficient")
        if not item.mask_out_executed or not item.region_swap_executed:
            return _result(rows, cfg, route=ROUTE_INCONCLUSIVE, reason="operator_intervention_missing")
        required = (
            item.observed_effect_raw,
            item.null_effect_raw,
            item.contrast_raw,
            item.observed_swap_effect_raw,
            item.null_swap_effect_raw,
            item.swap_contrast_raw,
        )
        if any(value is None for value in required):
            return _result(rows, cfg, route=ROUTE_INCONCLUSIVE, reason="operator_effect_missing")
        if abs(float(item.null_effect_raw)) > cfg.maximum_abs_null_effect_raw:
            return _result(rows, cfg, route=ROUTE_INSUFFICIENT, reason="operator_null_effect_unstable")
        if abs(float(item.null_swap_effect_raw)) > cfg.maximum_abs_null_effect_raw:
            return _result(rows, cfg, route=ROUTE_INSUFFICIENT, reason="operator_null_swap_unstable")
        if item.operator_route != "grounded_consistent":
            return _result(rows, cfg, route=ROUTE_INCONSISTENT, reason="operator_route_inconsistent")

    contrasts = tuple(float(item.contrast_raw) for item in sorted(rows, key=lambda item: item.operator_id))
    swap_contrasts = tuple(
        float(item.swap_contrast_raw) for item in sorted(rows, key=lambda item: item.operator_id)
    )
    if any(value < cfg.minimum_contrast_raw for value in contrasts):
        return _result(
            rows,
            cfg,
            route=ROUTE_INCONSISTENT,
            reason="operator_contrast_below_threshold",
            contrast_effects_raw=contrasts,
            swap_contrast_effects_raw=swap_contrasts,
            contrast_spread_raw=_spread(contrasts),
            swap_contrast_spread_raw=_spread(swap_contrasts),
        )
    if any(value < cfg.minimum_swap_contrast_raw for value in swap_contrasts):
        return _result(
            rows,
            cfg,
            route=ROUTE_INCONSISTENT,
            reason="operator_swap_contrast_below_threshold",
            contrast_effects_raw=contrasts,
            swap_contrast_effects_raw=swap_contrasts,
            contrast_spread_raw=_spread(contrasts),
            swap_contrast_spread_raw=_spread(swap_contrasts),
        )
    contrast_spread = _spread(contrasts)
    swap_spread = _spread(swap_contrasts)
    if contrast_spread > cfg.maximum_contrast_spread_raw:
        return _result(
            rows,
            cfg,
            route=ROUTE_INCONSISTENT,
            reason="operator_contrast_spread_exceeded",
            contrast_effects_raw=contrasts,
            swap_contrast_effects_raw=swap_contrasts,
            contrast_spread_raw=contrast_spread,
            swap_contrast_spread_raw=swap_spread,
        )
    if swap_spread > cfg.maximum_swap_contrast_spread_raw:
        return _result(
            rows,
            cfg,
            route=ROUTE_INCONSISTENT,
            reason="operator_swap_contrast_spread_exceeded",
            contrast_effects_raw=contrasts,
            swap_contrast_effects_raw=swap_contrasts,
            contrast_spread_raw=contrast_spread,
            swap_contrast_spread_raw=swap_spread,
        )
    return _result(
        rows,
        cfg,
        route=ROUTE_STABLE_GROUNDED,
        reason="operator_stability_consistent",
        contrast_effects_raw=contrasts,
        swap_contrast_effects_raw=swap_contrasts,
        contrast_spread_raw=contrast_spread,
        swap_contrast_spread_raw=swap_spread,
    )
