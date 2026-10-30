"""Selection-aware calibration for reference winners.

This module consumes scalar contrasts that have already passed the reference
specificity and invariant-effect contracts.  It calibrates the *selection
process* (choosing a winner from a fixed decoy pool) against independent
ordinary-propagation calibration groups.  It never runs a detector, image
operation, or retrieval step and never emits an AIGC probability.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Optional, Sequence, Tuple


VERSION = "selection-aware-calibration-v1"
SCHEMA = "selection-aware-calibration-result-v1"

ROUTE_SELECTION_SPECIFIC = "selection_specific_candidate"
ROUTE_SELECTION_AMBIGUOUS = "selection_ambiguous"
ROUTE_NULL_CONSISTENT = "null_consistent"
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
    normalized = _text(name, value).lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return normalized


def _finite(name: str, value: float, *, lower: float = -4.0, upper: float = 4.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < lower or normalized > upper:
        raise ValueError(f"{name} must be finite and between {lower} and {upper}")
    return normalized


def _unit(name: str, value: float) -> float:
    return _finite(name, value, lower=0.0, upper=1.0)


def _positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _upper_quantile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("quantile requires at least one value")
    ordered = sorted(float(value) for value in values)
    index = min(len(ordered) - 1, max(0, int(math.ceil(quantile * len(ordered))) - 1))
    return ordered[index]


@dataclass(frozen=True)
class SelectionAwareCalibrationConfig:
    """Frozen gates for winner-selection calibration."""

    minimum_decoy_count: int = 3
    minimum_calibration_groups: int = 20
    decoy_quantile: float = 0.75
    alpha: float = 0.05
    minimum_candidate_contrast_raw: float = 0.05
    minimum_specificity_gap_raw: float = 0.05
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    required_invariant_route: str = "invariant_candidate"
    profile_level: str = "exact"

    def __post_init__(self) -> None:
        _positive_int("minimum_decoy_count", self.minimum_decoy_count)
        _positive_int("minimum_calibration_groups", self.minimum_calibration_groups)
        if isinstance(self.decoy_quantile, bool) or not isinstance(self.decoy_quantile, (int, float)):
            raise ValueError("decoy_quantile must be finite")
        if not 0.0 < float(self.decoy_quantile) < 1.0:
            raise ValueError("decoy_quantile must be strictly between 0 and 1")
        alpha = _unit("alpha", self.alpha)
        if alpha <= 0.0 or alpha >= 1.0:
            raise ValueError("alpha must be strictly between 0 and 1")
        for name in ("minimum_candidate_contrast_raw", "minimum_specificity_gap_raw"):
            value = _finite(name, getattr(self, name), lower=-4.0, upper=4.0)
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative")
        _unit("minimum_quality", self.minimum_quality)
        _unit("minimum_source_match", self.minimum_source_match)
        object.__setattr__(self, "required_invariant_route", _text("required_invariant_route", self.required_invariant_route))
        object.__setattr__(self, "profile_level", _text("profile_level", self.profile_level))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "minimum_decoy_count": self.minimum_decoy_count,
            "minimum_calibration_groups": self.minimum_calibration_groups,
            "decoy_quantile": float(self.decoy_quantile),
            "alpha": float(self.alpha),
            "minimum_candidate_contrast_raw": float(self.minimum_candidate_contrast_raw),
            "minimum_specificity_gap_raw": float(self.minimum_specificity_gap_raw),
            "minimum_quality": float(self.minimum_quality),
            "minimum_source_match": float(self.minimum_source_match),
            "required_invariant_route": self.required_invariant_route,
            "profile_level": self.profile_level,
        }

    @property
    def config_digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class SelectionAwareBatch:
    """One query winner and its fixed blind-decoy pool."""

    query_digest: str
    query_group_id: str
    candidate_reference_digest: str
    candidate_contrast_raw: float
    decoy_reference_digests: Tuple[str, ...]
    decoy_contrasts_raw: Tuple[float, ...]
    candidate_quality_score: float
    candidate_source_match_raw: float
    invariant_route: str
    manifest_digest: str
    canonical_frame_digest: str
    transform_family: str
    quality_bucket: str
    source_match_bucket: str
    detector_version: str
    score_schema: str
    operator_set_digest: str
    selection_policy_digest: str
    selection_split_digest: str
    calibration_split_digest: str
    evaluation_split_digest: str
    calibration_dataset_digest: str
    profile_level: str
    null_profile_digest: str
    operation_scope: str = OPERATION_CONTENT_EDIT

    def __post_init__(self) -> None:
        for name in (
            "query_digest", "candidate_reference_digest", "manifest_digest", "canonical_frame_digest",
            "operator_set_digest", "selection_policy_digest", "selection_split_digest",
            "calibration_split_digest", "evaluation_split_digest", "calibration_dataset_digest",
            "null_profile_digest",
        ):
            object.__setattr__(self, name, _hex(name, getattr(self, name)))
        for name in (
            "query_group_id", "transform_family", "quality_bucket", "source_match_bucket",
            "detector_version", "score_schema", "profile_level", "invariant_route",
        ):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        object.__setattr__(self, "candidate_contrast_raw", _finite("candidate_contrast_raw", self.candidate_contrast_raw))
        object.__setattr__(self, "candidate_quality_score", _unit("candidate_quality_score", self.candidate_quality_score))
        object.__setattr__(self, "candidate_source_match_raw", _unit("candidate_source_match_raw", self.candidate_source_match_raw))
        if self.operation_scope not in {OPERATION_CONTENT_EDIT, OPERATION_ORDINARY_PROPAGATION}:
            raise ValueError("unsupported operation_scope")
        split_digests = (self.selection_split_digest, self.calibration_split_digest, self.evaluation_split_digest)
        if len(set(split_digests)) != 3:
            raise ValueError("selection, calibration and evaluation splits must be pairwise distinct")
        if isinstance(self.decoy_reference_digests, (str, bytes)) or isinstance(self.decoy_contrasts_raw, (str, bytes)):
            raise ValueError("decoy fields must be sequences")
        refs = tuple(_hex("decoy_reference_digest", item) for item in self.decoy_reference_digests)
        contrasts = tuple(_finite("decoy_contrast_raw", item) for item in self.decoy_contrasts_raw)
        if len(refs) != len(contrasts):
            raise ValueError("decoy digests and contrasts must have equal length")
        if len(set(refs)) != len(refs):
            raise ValueError("decoy reference digests must be unique")
        if self.candidate_reference_digest in set(refs):
            raise ValueError("candidate reference must differ from every decoy")
        object.__setattr__(self, "decoy_reference_digests", tuple(sorted(refs)))
        # Sorting contrasts by reference digest makes the evidence deterministic.
        pairs = sorted(zip(refs, contrasts), key=lambda item: item[0])
        object.__setattr__(self, "decoy_contrasts_raw", tuple(value for _, value in pairs))

    @property
    def decoy_count(self) -> int:
        return len(self.decoy_reference_digests)

    def binding_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "query_digest": self.query_digest,
            "query_group_id": self.query_group_id,
            "candidate_reference_digest": self.candidate_reference_digest,
            "manifest_digest": self.manifest_digest,
            "canonical_frame_digest": self.canonical_frame_digest,
            "transform_family": self.transform_family,
            "quality_bucket": self.quality_bucket,
            "source_match_bucket": self.source_match_bucket,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "operator_set_digest": self.operator_set_digest,
            "selection_policy_digest": self.selection_policy_digest,
            "selection_split_digest": self.selection_split_digest,
            "calibration_split_digest": self.calibration_split_digest,
            "evaluation_split_digest": self.evaluation_split_digest,
            "calibration_dataset_digest": self.calibration_dataset_digest,
            "profile_level": self.profile_level,
            "null_profile_digest": self.null_profile_digest,
            "operation_scope": self.operation_scope,
        }

    @property
    def binding_digest(self) -> str:
        return _digest(self.binding_dict())

    @property
    def decoy_pool_digest(self) -> str:
        return _digest(
            {
                "version": VERSION,
                "selection_split_digest": self.selection_split_digest,
                "references": list(self.decoy_reference_digests),
                "contrasts": list(self.decoy_contrasts_raw),
            }
        )


@dataclass(frozen=True)
class SelectionCalibrationGroup:
    """One independent ordinary-propagation winner statistic."""

    group_id: str
    max_statistic_raw: float
    decoy_count: int
    calibration_dataset_digest: str
    calibration_split_digest: str
    selection_policy_digest: str
    profile_level: str
    null_profile_digest: str
    manifest_digest: str
    detector_version: str
    score_schema: str
    operator_set_digest: str
    transform_family: str
    quality_bucket: str
    source_match_bucket: str
    operation_scope: str = OPERATION_ORDINARY_PROPAGATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_id", _text("group_id", self.group_id))
        for name in (
            "calibration_dataset_digest", "calibration_split_digest", "selection_policy_digest",
            "null_profile_digest", "manifest_digest", "operator_set_digest",
        ):
            object.__setattr__(self, name, _hex(name, getattr(self, name)))
        for name in (
            "profile_level", "detector_version", "score_schema", "transform_family",
            "quality_bucket", "source_match_bucket",
        ):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        object.__setattr__(self, "max_statistic_raw", _finite("max_statistic_raw", self.max_statistic_raw))
        object.__setattr__(self, "decoy_count", _positive_int("decoy_count", self.decoy_count))
        if self.operation_scope != OPERATION_ORDINARY_PROPAGATION:
            raise ValueError("calibration groups must use ordinary_propagation")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "group_id": self.group_id,
            "max_statistic_raw": self.max_statistic_raw,
            "decoy_count": self.decoy_count,
            "calibration_dataset_digest": self.calibration_dataset_digest,
            "calibration_split_digest": self.calibration_split_digest,
            "selection_policy_digest": self.selection_policy_digest,
            "profile_level": self.profile_level,
            "null_profile_digest": self.null_profile_digest,
            "manifest_digest": self.manifest_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "operator_set_digest": self.operator_set_digest,
            "transform_family": self.transform_family,
            "quality_bucket": self.quality_bucket,
            "source_match_bucket": self.source_match_bucket,
            "operation_scope": self.operation_scope,
        }


@dataclass(frozen=True)
class SelectionAwareResult:
    """Raw selection-calibration route; never a probability or legal finding."""

    route: str
    abstained: bool
    candidate_supported: bool
    reason: str
    candidate_contrast_raw: float
    decoy_count: int
    decoy_upper_quantile_raw: Optional[float]
    specificity_gap_raw: Optional[float]
    selection_p_value_raw: Optional[float]
    calibration_group_count: int
    calibration_max_statistics_raw: Tuple[float, ...]
    profile_level: str
    invariant_route: str
    binding_digest: str
    decoy_pool_digest: str
    profile_digest: Optional[str]
    config_digest: str
    evidence_digest: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "schema": SCHEMA,
            "route": self.route,
            "abstained": self.abstained,
            "candidate_supported": self.candidate_supported,
            "reason": self.reason,
            "candidate_contrast_raw": self.candidate_contrast_raw,
            "decoy_count": self.decoy_count,
            "decoy_upper_quantile_raw": self.decoy_upper_quantile_raw,
            "specificity_gap_raw": self.specificity_gap_raw,
            "selection_p_value_raw": self.selection_p_value_raw,
            "calibration_group_count": self.calibration_group_count,
            "calibration_max_statistics_raw": list(self.calibration_max_statistics_raw),
            "profile_level": self.profile_level,
            "invariant_route": self.invariant_route,
            "binding_digest": self.binding_digest,
            "decoy_pool_digest": self.decoy_pool_digest,
            "profile_digest": self.profile_digest,
            "config_digest": self.config_digest,
            "evidence_digest": self.evidence_digest,
        }


def _result(
    *,
    route: str,
    reason: str,
    batch: SelectionAwareBatch,
    config: SelectionAwareCalibrationConfig,
    decoy_upper_quantile_raw: Optional[float] = None,
    specificity_gap_raw: Optional[float] = None,
    selection_p_value_raw: Optional[float] = None,
    calibration_groups: Sequence[SelectionCalibrationGroup] = (),
    profile_digest: Optional[str] = None,
) -> SelectionAwareResult:
    max_statistics = tuple(group.max_statistic_raw for group in calibration_groups)
    base = {
        "route": route,
        "reason": reason,
        "candidate_contrast_raw": batch.candidate_contrast_raw,
        "decoy_count": batch.decoy_count,
        "decoy_upper_quantile_raw": decoy_upper_quantile_raw,
        "specificity_gap_raw": specificity_gap_raw,
        "selection_p_value_raw": selection_p_value_raw,
        "calibration_group_count": len(calibration_groups),
        "calibration_max_statistics_raw": list(max_statistics),
        "profile_level": batch.profile_level,
        "invariant_route": batch.invariant_route,
        "profile_digest": profile_digest,
    }
    return SelectionAwareResult(
        route=route,
        abstained=route in {ROUTE_SELECTION_AMBIGUOUS, ROUTE_INSUFFICIENT},
        candidate_supported=route == ROUTE_SELECTION_SPECIFIC,
        reason=reason,
        candidate_contrast_raw=batch.candidate_contrast_raw,
        decoy_count=batch.decoy_count,
        decoy_upper_quantile_raw=decoy_upper_quantile_raw,
        specificity_gap_raw=specificity_gap_raw,
        selection_p_value_raw=selection_p_value_raw,
        calibration_group_count=len(calibration_groups),
        calibration_max_statistics_raw=max_statistics,
        profile_level=batch.profile_level,
        invariant_route=batch.invariant_route,
        binding_digest=batch.binding_digest,
        decoy_pool_digest=batch.decoy_pool_digest,
        profile_digest=profile_digest,
        config_digest=config.config_digest,
        evidence_digest=_digest({"version": VERSION, **base, "binding_digest": batch.binding_digest, "decoy_pool_digest": batch.decoy_pool_digest, "config_digest": config.config_digest}),
    )


def evaluate_selection_aware_calibration(
    batch: SelectionAwareBatch,
    calibration_groups: Sequence[SelectionCalibrationGroup],
    *,
    config: Optional[SelectionAwareCalibrationConfig] = None,
) -> SelectionAwareResult:
    """Evaluate a winner against independent selection-aware null groups."""

    if not isinstance(batch, SelectionAwareBatch):
        raise ValueError("batch must be SelectionAwareBatch")
    if isinstance(calibration_groups, (str, bytes)):
        raise ValueError("calibration_groups must be a sequence")
    try:
        groups = tuple(calibration_groups)
    except TypeError as exc:
        raise ValueError("calibration_groups must be a sequence") from exc
    if any(not isinstance(group, SelectionCalibrationGroup) for group in groups):
        raise ValueError("calibration_groups must contain SelectionCalibrationGroup values")
    config = config or SelectionAwareCalibrationConfig()

    groups = tuple(sorted(groups, key=lambda group: group.group_id))
    ids = tuple(group.group_id for group in groups)
    if len(set(ids)) != len(ids):
        return _result(route=ROUTE_INSUFFICIENT, reason="duplicate_calibration_group_id", batch=batch, config=config)
    profile_digest = _digest({"version": VERSION, "groups": [group.to_dict() for group in sorted(groups, key=lambda item: item.group_id)]}) if groups else None

    if batch.profile_level != config.profile_level:
        return _result(route=ROUTE_INSUFFICIENT, reason="profile_level_mismatch", batch=batch, config=config, calibration_groups=groups, profile_digest=profile_digest)
    if batch.candidate_quality_score < config.minimum_quality:
        return _result(route=ROUTE_INSUFFICIENT, reason="candidate_quality_below_threshold", batch=batch, config=config, calibration_groups=groups, profile_digest=profile_digest)
    if batch.candidate_source_match_raw < config.minimum_source_match:
        return _result(route=ROUTE_INSUFFICIENT, reason="candidate_source_match_below_threshold", batch=batch, config=config, calibration_groups=groups, profile_digest=profile_digest)
    if batch.decoy_count < config.minimum_decoy_count:
        return _result(route=ROUTE_INSUFFICIENT, reason="decoy_sample_insufficient", batch=batch, config=config, calibration_groups=groups, profile_digest=profile_digest)
    if batch.operation_scope == OPERATION_ORDINARY_PROPAGATION:
        return _result(route=ROUTE_NULL_CONSISTENT, reason="ordinary_propagation_scope", batch=batch, config=config, calibration_groups=groups, profile_digest=profile_digest)
    if batch.invariant_route == "insufficient":
        return _result(route=ROUTE_INSUFFICIENT, reason="invariant_evidence_insufficient", batch=batch, config=config, calibration_groups=groups, profile_digest=profile_digest)
    if batch.invariant_route != config.required_invariant_route:
        return _result(route=ROUTE_SELECTION_AMBIGUOUS, reason="invariant_route_not_candidate", batch=batch, config=config, calibration_groups=groups, profile_digest=profile_digest)
    if batch.candidate_contrast_raw < config.minimum_candidate_contrast_raw:
        return _result(route=ROUTE_NULL_CONSISTENT, reason="candidate_contrast_below_threshold", batch=batch, config=config, calibration_groups=groups, profile_digest=profile_digest)
    if len(groups) < config.minimum_calibration_groups:
        return _result(route=ROUTE_INSUFFICIENT, reason="calibration_group_support_insufficient", batch=batch, config=config, calibration_groups=groups, profile_digest=profile_digest)
    if batch.query_group_id in set(ids):
        return _result(route=ROUTE_INSUFFICIENT, reason="query_group_leaks_into_calibration", batch=batch, config=config, calibration_groups=groups, profile_digest=profile_digest)

    for group in groups:
        checks = {
            "calibration_dataset_digest": group.calibration_dataset_digest == batch.calibration_dataset_digest,
            "calibration_split_digest": group.calibration_split_digest == batch.calibration_split_digest,
            "selection_policy_digest": group.selection_policy_digest == batch.selection_policy_digest,
            "profile_level": group.profile_level == batch.profile_level,
            "null_profile_digest": group.null_profile_digest == batch.null_profile_digest,
            "detector_version": group.detector_version == batch.detector_version,
            "score_schema": group.score_schema == batch.score_schema,
            "operator_set_digest": group.operator_set_digest == batch.operator_set_digest,
            "transform_family": group.transform_family == batch.transform_family,
            "quality_bucket": group.quality_bucket == batch.quality_bucket,
            "source_match_bucket": group.source_match_bucket == batch.source_match_bucket,
            "decoy_count": group.decoy_count == batch.decoy_count,
            "operation_scope": group.operation_scope == OPERATION_ORDINARY_PROPAGATION,
        }
        mismatch = next((name for name, ok in checks.items() if not ok), None)
        if mismatch is not None:
            return _result(route=ROUTE_INSUFFICIENT, reason=f"calibration_{mismatch}_mismatch", batch=batch, config=config, calibration_groups=groups, profile_digest=profile_digest)

    decoy_upper = _upper_quantile(batch.decoy_contrasts_raw, float(config.decoy_quantile))
    specificity_gap = batch.candidate_contrast_raw - decoy_upper
    exceedances = sum(group.max_statistic_raw >= batch.candidate_contrast_raw for group in groups)
    selection_p = (1.0 + float(exceedances)) / (1.0 + float(len(groups)))

    if specificity_gap < config.minimum_specificity_gap_raw:
        return _result(route=ROUTE_SELECTION_AMBIGUOUS, reason="decoy_gap_below_threshold", batch=batch, config=config, decoy_upper_quantile_raw=decoy_upper, specificity_gap_raw=specificity_gap, selection_p_value_raw=selection_p, calibration_groups=groups, profile_digest=profile_digest)
    if selection_p > config.alpha:
        return _result(route=ROUTE_SELECTION_AMBIGUOUS, reason="selection_p_value_not_supported", batch=batch, config=config, decoy_upper_quantile_raw=decoy_upper, specificity_gap_raw=specificity_gap, selection_p_value_raw=selection_p, calibration_groups=groups, profile_digest=profile_digest)
    return _result(route=ROUTE_SELECTION_SPECIFIC, reason="selection_aware_candidate_supported", batch=batch, config=config, decoy_upper_quantile_raw=decoy_upper, specificity_gap_raw=specificity_gap, selection_p_value_raw=selection_p, calibration_groups=groups, profile_digest=profile_digest)
