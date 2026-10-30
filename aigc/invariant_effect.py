"""Cross-view and multi-operator invariant source-conditioned effect audit.

This module consumes already executed matched-intervention observations.  It
does not run a detector or image operation.  A candidate must keep a positive
effect across canonical views *and* pre-registered intervention operators,
while exceeding an independent ordinary-propagation null profile.  The
output is a raw-evidence route, never an AIGC probability or authorship claim.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


VERSION = "invariant-effect-v1"
SCHEMA = "invariant-effect-result-v1"

ROUTE_INVARIANT_CANDIDATE = "invariant_candidate"
ROUTE_NULL_CONSISTENT = "null_consistent"
ROUTE_VIEW_OPERATOR_INCONSISTENT = "view_operator_inconsistent"
ROUTE_INSUFFICIENT = "insufficient"

OPERATION_CONTENT_EDIT = "content_edit"
OPERATION_ORDINARY_PROPAGATION = "ordinary_propagation"


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _hex(name: str, value: str) -> str:
    value = _text(name, value).lower()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return value


def _finite(name: str, value: float, *, lower: float = -4.0, upper: float = 4.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or value < lower or value > upper:
        raise ValueError(f"{name} must be finite and between {lower} and {upper}")
    return value


def _unit(name: str, value: float) -> float:
    value = _finite(name, value, lower=0.0, upper=1.0)
    return value


def _positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _quantile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise ValueError("quantile requires at least one value")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


@dataclass(frozen=True)
class InvariantEffectConfig:
    """Fail-closed gates for the joint nuisance-invariance audit."""

    minimum_view_count: int = 3
    minimum_operator_count: int = 2
    minimum_region_count: int = 2
    minimum_null_count: int = 20
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    positive_contrast_threshold: float = 0.05
    minimum_positive_fraction: float = 0.67
    minimum_invariant_effect: float = 0.05
    maximum_effect_spread: float = 0.20
    lower_quantile: float = 0.25
    alpha: float = 0.05

    def __post_init__(self) -> None:
        _positive_int("minimum_view_count", self.minimum_view_count)
        _positive_int("minimum_operator_count", self.minimum_operator_count)
        _positive_int("minimum_region_count", self.minimum_region_count)
        _positive_int("minimum_null_count", self.minimum_null_count)
        _unit("minimum_quality", self.minimum_quality)
        _unit("minimum_source_match", self.minimum_source_match)
        _finite("positive_contrast_threshold", self.positive_contrast_threshold, lower=-4.0, upper=4.0)
        _unit("minimum_positive_fraction", self.minimum_positive_fraction)
        _finite("minimum_invariant_effect", self.minimum_invariant_effect, lower=-4.0, upper=4.0)
        _finite("maximum_effect_spread", self.maximum_effect_spread, lower=0.0, upper=8.0)
        if isinstance(self.lower_quantile, bool) or not isinstance(self.lower_quantile, (int, float)):
            raise ValueError("lower_quantile must be finite")
        if not 0.0 <= float(self.lower_quantile) <= 0.5:
            raise ValueError("lower_quantile must be between 0 and 0.5")
        alpha = _unit("alpha", self.alpha)
        if alpha <= 0.0 or alpha >= 1.0:
            raise ValueError("alpha must be strictly between 0 and 1")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "minimum_view_count": self.minimum_view_count,
            "minimum_operator_count": self.minimum_operator_count,
            "minimum_region_count": self.minimum_region_count,
            "minimum_null_count": self.minimum_null_count,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "positive_contrast_threshold": self.positive_contrast_threshold,
            "minimum_positive_fraction": self.minimum_positive_fraction,
            "minimum_invariant_effect": self.minimum_invariant_effect,
            "maximum_effect_spread": self.maximum_effect_spread,
            "lower_quantile": float(self.lower_quantile),
            "alpha": self.alpha,
        }

    @property
    def config_digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class InvariantEffectObservation:
    """One executed observed/null matched intervention for one region."""

    observation_id: str
    asset_id: str
    pair_id: str
    manifest_digest: str
    canonical_frame_digest: str
    view_id: str
    view_digest: str
    operator_id: str
    operator_config_digest: str
    operator_execution_digest: str
    region_id: str
    detector_version: str
    score_schema: str
    null_profile_digest: str
    quality_score: float
    source_match_raw: float
    observed_effect_raw: float
    null_effect_raw: float
    operation_scope: str = OPERATION_CONTENT_EDIT
    execution_valid: bool = True

    def __post_init__(self) -> None:
        for name in (
            "observation_id", "asset_id", "pair_id", "view_id", "operator_id", "region_id",
            "detector_version", "score_schema",
        ):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        for name in (
            "manifest_digest", "canonical_frame_digest", "view_digest",
            "operator_config_digest", "operator_execution_digest", "null_profile_digest",
        ):
            object.__setattr__(self, name, _hex(name, getattr(self, name)))
        object.__setattr__(self, "quality_score", _unit("quality_score", self.quality_score))
        object.__setattr__(self, "source_match_raw", _unit("source_match_raw", self.source_match_raw))
        object.__setattr__(self, "observed_effect_raw", _finite("observed_effect_raw", self.observed_effect_raw))
        object.__setattr__(self, "null_effect_raw", _finite("null_effect_raw", self.null_effect_raw))
        if self.operation_scope not in {OPERATION_CONTENT_EDIT, OPERATION_ORDINARY_PROPAGATION}:
            raise ValueError("unsupported operation_scope")
        if not isinstance(self.execution_valid, bool):
            raise ValueError("execution_valid must be bool")

    @property
    def contrast_raw(self) -> float:
        return self.observed_effect_raw - self.null_effect_raw

    @property
    def context_key(self) -> Tuple[str, ...]:
        return (
            self.asset_id, self.pair_id, self.manifest_digest, self.canonical_frame_digest,
            self.detector_version, self.score_schema, self.null_profile_digest,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "manifest_digest": self.manifest_digest,
            "canonical_frame_digest": self.canonical_frame_digest,
            "view_id": self.view_id,
            "view_digest": self.view_digest,
            "operator_id": self.operator_id,
            "operator_config_digest": self.operator_config_digest,
            "operator_execution_digest": self.operator_execution_digest,
            "region_id": self.region_id,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "null_profile_digest": self.null_profile_digest,
            "quality_score": self.quality_score,
            "source_match_raw": self.source_match_raw,
            "observed_effect_raw": self.observed_effect_raw,
            "null_effect_raw": self.null_effect_raw,
            "contrast_raw": self.contrast_raw,
            "operation_scope": self.operation_scope,
            "execution_valid": self.execution_valid,
        }


@dataclass(frozen=True)
class InvariantNullSample:
    """One independent group-level ordinary-propagation null statistic."""

    sample_id: str
    group_id: str
    calibration_dataset_digest: str
    null_profile_digest: str
    detector_version: str
    score_schema: str
    transform_family: str
    quality_bucket: str
    statistic_raw: float
    split: str = "calibration"

    def __post_init__(self) -> None:
        for name in (
            "sample_id", "group_id", "detector_version", "score_schema",
            "transform_family", "quality_bucket",
        ):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        for name in ("calibration_dataset_digest", "null_profile_digest"):
            object.__setattr__(self, name, _hex(name, getattr(self, name)))
        object.__setattr__(self, "statistic_raw", _finite("statistic_raw", self.statistic_raw))
        if self.split != "calibration":
            raise ValueError("invariant null samples must use split=calibration")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "group_id": self.group_id,
            "calibration_dataset_digest": self.calibration_dataset_digest,
            "null_profile_digest": self.null_profile_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "transform_family": self.transform_family,
            "quality_bucket": self.quality_bucket,
            "statistic_raw": self.statistic_raw,
            "split": self.split,
        }


@dataclass(frozen=True)
class InvariantEffectResult:
    route: str
    reason: str
    asset_id: Optional[str]
    invariant_effect_raw: Optional[float]
    positive_fraction_raw: Optional[float]
    effect_spread_raw: Optional[float]
    p_value_raw: Optional[float]
    view_effects_raw: Tuple[Tuple[str, float], ...]
    operator_effects_raw: Tuple[Tuple[str, float], ...]
    view_count: int
    operator_count: int
    region_count: int
    null_count: int
    accepted_observation_ids: Tuple[str, ...]
    rejected_observation_ids: Tuple[str, ...]
    binding_digest: Optional[str]
    config_digest: str
    null_profile_digest: Optional[str]
    version: str = VERSION
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.route not in {
            ROUTE_INVARIANT_CANDIDATE,
            ROUTE_NULL_CONSISTENT,
            ROUTE_VIEW_OPERATOR_INCONSISTENT,
            ROUTE_INSUFFICIENT,
        }:
            raise ValueError("unsupported invariant-effect route")
        object.__setattr__(self, "reason", _text("reason", self.reason))
        if self.asset_id is not None:
            object.__setattr__(self, "asset_id", _text("asset_id", self.asset_id))
        if self.binding_digest is not None:
            object.__setattr__(self, "binding_digest", _hex("binding_digest", self.binding_digest))
        object.__setattr__(self, "config_digest", _hex("config_digest", self.config_digest))
        if self.null_profile_digest is not None:
            object.__setattr__(self, "null_profile_digest", _hex("null_profile_digest", self.null_profile_digest))
        for name in ("invariant_effect_raw", "effect_spread_raw"):
            value = getattr(self, name)
            if value is not None:
                _finite(name, value)
        if self.positive_fraction_raw is not None:
            _unit("positive_fraction_raw", self.positive_fraction_raw)
        if self.p_value_raw is not None:
            value = _unit("p_value_raw", self.p_value_raw)
            if value <= 0.0:
                raise ValueError("p_value_raw must be greater than zero")
        for name in ("view_count", "operator_count", "region_count", "null_count"):
            if isinstance(getattr(self, name), bool) or not isinstance(getattr(self, name), int) or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        object.__setattr__(self, "view_effects_raw", tuple(self.view_effects_raw))
        object.__setattr__(self, "operator_effects_raw", tuple(self.operator_effects_raw))

    @property
    def abstained(self) -> bool:
        return self.route != ROUTE_INVARIANT_CANDIDATE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "schema": self.schema,
            "route": self.route,
            "reason": self.reason,
            "asset_id": self.asset_id,
            "invariant_effect_raw": self.invariant_effect_raw,
            "positive_fraction_raw": self.positive_fraction_raw,
            "effect_spread_raw": self.effect_spread_raw,
            "p_value_raw": self.p_value_raw,
            "view_effects_raw": [[key, value] for key, value in self.view_effects_raw],
            "operator_effects_raw": [[key, value] for key, value in self.operator_effects_raw],
            "view_count": self.view_count,
            "operator_count": self.operator_count,
            "region_count": self.region_count,
            "null_count": self.null_count,
            "accepted_observation_ids": list(self.accepted_observation_ids),
            "rejected_observation_ids": list(self.rejected_observation_ids),
            "binding_digest": self.binding_digest,
            "config_digest": self.config_digest,
            "null_profile_digest": self.null_profile_digest,
        }


def _result(
    *,
    route: str,
    reason: str,
    observations: Sequence[InvariantEffectObservation],
    config: InvariantEffectConfig,
    binding_digest: Optional[str] = None,
    null_profile_digest: Optional[str] = None,
    view_effects: Sequence[Tuple[str, float]] = (),
    operator_effects: Sequence[Tuple[str, float]] = (),
    invariant_effect: Optional[float] = None,
    positive_fraction: Optional[float] = None,
    effect_spread: Optional[float] = None,
    p_value: Optional[float] = None,
    null_count: int = 0,
    rejected: Sequence[str] = (),
) -> InvariantEffectResult:
    return InvariantEffectResult(
        route=route,
        reason=reason,
        asset_id=observations[0].asset_id if observations else None,
        invariant_effect_raw=invariant_effect,
        positive_fraction_raw=positive_fraction,
        effect_spread_raw=effect_spread,
        p_value_raw=p_value,
        view_effects_raw=tuple(view_effects),
        operator_effects_raw=tuple(operator_effects),
        view_count=len({item.view_id for item in observations}),
        operator_count=len({item.operator_id for item in observations}),
        region_count=len({item.region_id for item in observations}),
        null_count=null_count,
        accepted_observation_ids=tuple(sorted(item.observation_id for item in observations if item.execution_valid)),
        rejected_observation_ids=tuple(sorted(rejected)),
        binding_digest=binding_digest,
        config_digest=config.config_digest,
        null_profile_digest=null_profile_digest,
    )


def evaluate_invariant_effect(
    observations: Sequence[InvariantEffectObservation],
    null_samples: Sequence[InvariantNullSample],
    *,
    config: Optional[InvariantEffectConfig] = None,
) -> InvariantEffectResult:
    """Evaluate cross-view/operator invariance with an independent null.

    The lower quantile is applied first within each view/operator axis and then
    across both axes.  This makes a single high-scoring view or operator unable
    to create a candidate by itself.
    """

    config = config or InvariantEffectConfig()
    if not observations:
        return _result(route=ROUTE_INSUFFICIENT, reason="observation_support_missing", observations=(), config=config)
    if any(not isinstance(item, InvariantEffectObservation) for item in observations):
        raise ValueError("observations must contain InvariantEffectObservation values")
    if any(not isinstance(item, InvariantNullSample) for item in null_samples):
        raise ValueError("null_samples must contain InvariantNullSample values")

    observation_ids = [item.observation_id for item in observations]
    if len(set(observation_ids)) != len(observation_ids):
        return _result(route=ROUTE_INSUFFICIENT, reason="duplicate_observation_id", observations=observations, config=config)
    context_keys = {item.context_key for item in observations}
    if len(context_keys) != 1:
        return _result(route=ROUTE_INSUFFICIENT, reason="binding_context_mismatch", observations=observations, config=config)
    view_digests = {}
    operator_digests = {}
    duplicate_keys = set()
    keys = set()
    for item in observations:
        view_digests.setdefault(item.view_id, item.view_digest)
        operator_digests.setdefault(item.operator_id, item.operator_config_digest)
        if view_digests[item.view_id] != item.view_digest or operator_digests[item.operator_id] != item.operator_config_digest:
            return _result(route=ROUTE_INSUFFICIENT, reason="view_or_operator_digest_mismatch", observations=observations, config=config)
        key = (item.view_id, item.operator_id, item.region_id)
        if key in keys:
            duplicate_keys.add(key)
        keys.add(key)
    if duplicate_keys:
        return _result(route=ROUTE_INSUFFICIENT, reason="duplicate_view_operator_region", observations=observations, config=config)

    views = sorted({item.view_id for item in observations})
    operators = sorted({item.operator_id for item in observations})
    regions = sorted({item.region_id for item in observations})
    if len(views) < config.minimum_view_count:
        return _result(route=ROUTE_INSUFFICIENT, reason="view_support_insufficient", observations=observations, config=config)
    if len(operators) < config.minimum_operator_count:
        return _result(route=ROUTE_INSUFFICIENT, reason="operator_support_insufficient", observations=observations, config=config)
    if len(regions) < config.minimum_region_count:
        return _result(route=ROUTE_INSUFFICIENT, reason="region_support_insufficient", observations=observations, config=config)
    expected_pairs = {(view, operator) for view in views for operator in operators}
    grouped: Dict[Tuple[str, str], list[InvariantEffectObservation]] = {}
    rejected = []
    for item in observations:
        if item.quality_score < config.minimum_quality or item.source_match_raw < config.minimum_source_match or not item.execution_valid:
            rejected.append(item.observation_id)
            continue
        grouped.setdefault((item.view_id, item.operator_id), []).append(item)
    if set(grouped) != expected_pairs:
        return _result(route=ROUTE_INSUFFICIENT, reason="view_operator_support_incomplete", observations=observations, config=config, rejected=rejected)
    if any({item.region_id for item in rows} != set(regions) for rows in grouped.values()):
        return _result(route=ROUTE_INSUFFICIENT, reason="region_support_mismatch", observations=observations, config=config, rejected=rejected)

    context = observations[0]
    profile = context.null_profile_digest
    calibration_profiles = {item.null_profile_digest for item in null_samples}
    calibration_datasets = {item.calibration_dataset_digest for item in null_samples}
    groups = {item.group_id for item in null_samples}
    if len(null_samples) < config.minimum_null_count:
        return _result(route=ROUTE_INSUFFICIENT, reason="null_support_insufficient", observations=observations, config=config, null_profile_digest=profile, rejected=rejected)
    if len(groups) != len(null_samples) or len(calibration_profiles) != 1 or len(calibration_datasets) != 1:
        return _result(route=ROUTE_INSUFFICIENT, reason="null_profile_binding_mismatch", observations=observations, config=config, null_profile_digest=profile, rejected=rejected)
    if calibration_profiles != {profile}:
        return _result(route=ROUTE_INSUFFICIENT, reason="null_profile_digest_mismatch", observations=observations, config=config, null_profile_digest=profile, rejected=rejected)
    if any(item.detector_version != context.detector_version or item.score_schema != context.score_schema for item in null_samples):
        return _result(route=ROUTE_INSUFFICIENT, reason="null_schema_mismatch", observations=observations, config=config, null_profile_digest=profile, rejected=rejected)

    pair_stats: Dict[Tuple[str, str], float] = {}
    for key, rows in grouped.items():
        weights = [row.quality_score * row.source_match_raw for row in rows]
        total = math.fsum(weights)
        if total <= 0.0:
            return _result(route=ROUTE_INSUFFICIENT, reason="nonpositive_raw_weight", observations=observations, config=config, null_profile_digest=profile, rejected=rejected)
        pair_stats[key] = math.fsum(weight * row.contrast_raw for weight, row in zip(weights, rows)) / total

    q = float(config.lower_quantile)
    view_effects = tuple((view, _quantile([pair_stats[(view, op)] for op in operators], q)) for view in views)
    operator_effects = tuple((op, _quantile([pair_stats[(view, op)] for view in views], q)) for op in operators)
    invariant_effect = min(_quantile([value for _, value in view_effects], q), _quantile([value for _, value in operator_effects], q))
    positive_fraction = sum(value >= config.positive_contrast_threshold for value in pair_stats.values()) / len(pair_stats)
    ordered_pair_values = sorted(pair_stats.values())
    effect_spread = _quantile(ordered_pair_values, 1.0 - q) - _quantile(ordered_pair_values, q)
    p_value = (1.0 + sum(item.statistic_raw >= invariant_effect for item in null_samples)) / (len(null_samples) + 1.0)
    binding_digest = _digest({
        "context": context.context_key,
        "views": [[view_id, view_digest] for view_id, view_digest in sorted({(row.view_id, row.view_digest) for row in observations})],
        "operators": [[operator_id, operator_digest] for operator_id, operator_digest in sorted({(row.operator_id, row.operator_config_digest) for row in observations})],
        "regions": regions,
        "observation_ids": sorted(observation_ids),
    })

    if any(item.operation_scope == OPERATION_ORDINARY_PROPAGATION for item in observations):
        route = ROUTE_NULL_CONSISTENT
        reason = "ordinary_propagation_scope"
    elif invariant_effect < config.minimum_invariant_effect or p_value > config.alpha:
        # A weak or null-compatible effect is the primary conclusion.  Do not
        # relabel it as view/operator inconsistency merely because the same
        # weak observations also fail the positive-fraction or spread gates.
        route = ROUTE_NULL_CONSISTENT
        reason = "ordinary_propagation_null_consistent"
    elif positive_fraction < config.minimum_positive_fraction:
        route = ROUTE_VIEW_OPERATOR_INCONSISTENT
        reason = "positive_support_fraction_low"
    elif effect_spread > config.maximum_effect_spread:
        route = ROUTE_VIEW_OPERATOR_INCONSISTENT
        reason = "view_operator_effect_spread_exceeded"
    else:
        route = ROUTE_INVARIANT_CANDIDATE
        reason = "cross_view_operator_invariant_effect"

    return _result(
        route=route,
        reason=reason,
        observations=observations,
        config=config,
        binding_digest=binding_digest,
        null_profile_digest=profile,
        view_effects=view_effects,
        operator_effects=operator_effects,
        invariant_effect=invariant_effect,
        positive_fraction=positive_fraction,
        effect_spread=effect_spread,
        p_value=p_value,
        null_count=len(null_samples),
        rejected=rejected,
    )


__all__ = [
    "VERSION", "SCHEMA", "ROUTE_INVARIANT_CANDIDATE", "ROUTE_NULL_CONSISTENT",
    "ROUTE_VIEW_OPERATOR_INCONSISTENT", "ROUTE_INSUFFICIENT", "OPERATION_CONTENT_EDIT",
    "OPERATION_ORDINARY_PROPAGATION", "InvariantEffectConfig", "InvariantEffectObservation",
    "InvariantNullSample", "InvariantEffectResult", "evaluate_invariant_effect",
]
