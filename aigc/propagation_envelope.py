"""Severity-stratified ordinary-propagation envelope audit.

PE-CEA is a dependency-light research contract.  It does not load an image
model and it does not decide whether an image is AI-generated.  It keeps the
paired local effect as a curve over a pre-registered propagation severity
path.  A frozen ordinary-propagation profile supplies one null envelope for
each severity level; a content-edit query must exceed that envelope on enough
levels to become a raw ``envelope_candidate``.

The contract is intentionally stricter than a single scalar threshold.  A
single clean-image spike, a missing severity level, a split leak, or a scope
mix is rejected or routed to review.  All values remain raw evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


VERSION = "propagation-envelope-audit-v1"
RESULT_SCHEMA = "propagation-envelope-result-v1"
STATISTIC_SCHEMA = "propagation-envelope-statistic-v1"

ORDINARY_PROPAGATION = "ordinary_propagation"
CONTENT_EDIT = "content_edit"

ROUTE_ENVELOPE_CANDIDATE = "envelope_candidate"
ROUTE_NULL_CONSISTENT = "null_consistent"
ROUTE_CURVE_INCONSISTENT = "curve_inconsistent"
ROUTE_INSUFFICIENT = "insufficient"


def _non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return normalized


def _signed_unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized) or not -1.0 <= normalized <= 1.0:
        raise ValueError(f"{name} must be finite and between -1 and 1")
    return normalized


def _positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _digest_hex(name: str, value: str) -> str:
    _non_empty(name, value)
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
    return value.lower()


def _severity(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _alpha(value: float) -> float:
    normalized = _unit("alpha", value)
    if normalized <= 0.0 or normalized >= 1.0:
        raise ValueError("alpha must be strictly between 0 and 1")
    return normalized


def _upper_order_statistic(values: Sequence[float], alpha: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    ordered = sorted(float(value) for value in values)
    rank = math.ceil((len(ordered) + 1) * (1.0 - alpha)) - 1
    rank = min(len(ordered) - 1, max(0, rank))
    return ordered[rank]


def _ties_inclusive_p(value: float, null_values: Sequence[float]) -> float:
    if not null_values:
        raise ValueError("null_values must not be empty")
    exceedances = sum(1 for item in null_values if item >= value)
    return (1.0 + exceedances) / (len(null_values) + 1.0)


@dataclass(frozen=True)
class EnvelopeObservation:
    """One paired local-effect observation at one propagation severity."""

    group_id: str
    asset_id: str
    severity_level: int
    transform_family: str
    operation_scope: str
    observed_delta_raw: float
    counterfactual_delta_raw: float
    quality_score: float
    source_match_score: float
    manifest_digest: str
    canonical_frame: str
    split: str
    split_digest: str
    detector_version: str = "source-residual-v1"
    score_schema: str = "source-residual-score-v1"
    edit_mask_digest: Optional[str] = None

    def __post_init__(self) -> None:
        _non_empty("group_id", self.group_id)
        _non_empty("asset_id", self.asset_id)
        _severity("severity_level", self.severity_level)
        _non_empty("transform_family", self.transform_family)
        if self.operation_scope not in {ORDINARY_PROPAGATION, CONTENT_EDIT}:
            raise ValueError("operation_scope must be ordinary_propagation or content_edit")
        _signed_unit("observed_delta_raw", self.observed_delta_raw)
        _signed_unit("counterfactual_delta_raw", self.counterfactual_delta_raw)
        _unit("quality_score", self.quality_score)
        _unit("source_match_score", self.source_match_score)
        _digest_hex("manifest_digest", self.manifest_digest)
        _non_empty("canonical_frame", self.canonical_frame)
        if self.split not in {"calibration", "evaluation", "external"}:
            raise ValueError("split must be calibration, evaluation, or external")
        _digest_hex("split_digest", self.split_digest)
        _non_empty("detector_version", self.detector_version)
        _non_empty("score_schema", self.score_schema)
        if self.edit_mask_digest is not None:
            _digest_hex("edit_mask_digest", self.edit_mask_digest)
        if self.operation_scope == CONTENT_EDIT and self.edit_mask_digest is None:
            raise ValueError("content_edit observations require edit_mask_digest")
        if self.operation_scope == ORDINARY_PROPAGATION and self.edit_mask_digest is not None:
            raise ValueError("ordinary_propagation observations cannot carry edit_mask_digest")

    @property
    def paired_delta_raw(self) -> float:
        return float(self.observed_delta_raw) - float(self.counterfactual_delta_raw)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "asset_id": self.asset_id,
            "severity_level": self.severity_level,
            "transform_family": self.transform_family,
            "operation_scope": self.operation_scope,
            "observed_delta_raw": self.observed_delta_raw,
            "counterfactual_delta_raw": self.counterfactual_delta_raw,
            "paired_delta_raw": self.paired_delta_raw,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "manifest_digest": self.manifest_digest,
            "canonical_frame": self.canonical_frame,
            "split": self.split,
            "split_digest": self.split_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "edit_mask_digest": self.edit_mask_digest,
        }


@dataclass(frozen=True)
class EnvelopeConfig:
    severity_levels: Tuple[int, ...] = (0, 1, 2)
    minimum_groups_per_level: int = 3
    alpha: float = 0.20
    minimum_positive_levels: int = 2
    minimum_positive_fraction: float = 0.60
    maximum_curve_discontinuity: float = 0.75
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60

    def __post_init__(self) -> None:
        if isinstance(self.severity_levels, (str, bytes)):
            raise ValueError("severity_levels must be a sequence")
        try:
            levels = tuple(_severity("severity_level", value) for value in self.severity_levels)
        except TypeError as exc:
            raise ValueError("severity_levels must be a sequence") from exc
        if len(levels) < 3 or tuple(sorted(set(levels))) != levels:
            raise ValueError("severity_levels must contain at least three sorted unique levels")
        object.__setattr__(self, "severity_levels", levels)
        object.__setattr__(self, "minimum_groups_per_level", _positive_int("minimum_groups_per_level", self.minimum_groups_per_level))
        object.__setattr__(self, "alpha", _alpha(self.alpha))
        object.__setattr__(self, "minimum_positive_levels", _positive_int("minimum_positive_levels", self.minimum_positive_levels))
        if self.minimum_positive_levels > len(levels):
            raise ValueError("minimum_positive_levels cannot exceed number of severity levels")
        object.__setattr__(self, "minimum_positive_fraction", _unit("minimum_positive_fraction", self.minimum_positive_fraction))
        if isinstance(self.maximum_curve_discontinuity, bool) or not isinstance(self.maximum_curve_discontinuity, (int, float)):
            raise ValueError("maximum_curve_discontinuity must be finite")
        discontinuity = float(self.maximum_curve_discontinuity)
        if not math.isfinite(discontinuity) or discontinuity < 0.0 or discontinuity > 2.0:
            raise ValueError("maximum_curve_discontinuity must be between 0 and 2")
        object.__setattr__(self, "maximum_curve_discontinuity", discontinuity)
        object.__setattr__(self, "minimum_quality", _unit("minimum_quality", self.minimum_quality))
        object.__setattr__(self, "minimum_source_match", _unit("minimum_source_match", self.minimum_source_match))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "severity_levels": list(self.severity_levels),
            "minimum_groups_per_level": self.minimum_groups_per_level,
            "alpha": self.alpha,
            "minimum_positive_levels": self.minimum_positive_levels,
            "minimum_positive_fraction": self.minimum_positive_fraction,
            "maximum_curve_discontinuity": self.maximum_curve_discontinuity,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class EnvelopeStratum:
    severity_level: int
    statistics: Tuple[float, ...]
    group_ids: Tuple[str, ...]
    upper_null_raw: float

    def __post_init__(self) -> None:
        _severity("severity_level", self.severity_level)
        if not self.statistics or len(self.statistics) != len(self.group_ids):
            raise ValueError("statistics and group_ids must be non-empty and equal length")
        stats = tuple(_signed_unit("statistic", item) for item in self.statistics)
        ids = tuple(_non_empty("group_id", item) for item in self.group_ids)
        if len(set(ids)) != len(ids):
            raise ValueError("group_ids must be unique within a stratum")
        ordered = tuple(sorted(zip(stats, ids), key=lambda item: (item[0], item[1])))
        object.__setattr__(self, "statistics", tuple(item[0] for item in ordered))
        object.__setattr__(self, "group_ids", tuple(item[1] for item in ordered))
        _signed_unit("upper_null_raw", self.upper_null_raw)

    @property
    def support(self) -> int:
        return len(self.statistics)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity_level": self.severity_level,
            "statistics": list(self.statistics),
            "group_ids": list(self.group_ids),
            "upper_null_raw": self.upper_null_raw,
            "support": self.support,
        }


@dataclass(frozen=True)
class EnvelopeProfile:
    transform_family: str
    manifest_digest: str
    canonical_frame: str
    detector_version: str
    score_schema: str
    calibration_split_digest: str
    calibration_asset_ids: Tuple[str, ...]
    strata: Tuple[EnvelopeStratum, ...]
    config_digest: str
    dataset_digest: str
    profile_digest: str
    version: str = VERSION

    def __post_init__(self) -> None:
        _non_empty("transform_family", self.transform_family)
        _digest_hex("manifest_digest", self.manifest_digest)
        _non_empty("canonical_frame", self.canonical_frame)
        _non_empty("detector_version", self.detector_version)
        _non_empty("score_schema", self.score_schema)
        _digest_hex("calibration_split_digest", self.calibration_split_digest)
        if not self.calibration_asset_ids or len(set(self.calibration_asset_ids)) != len(self.calibration_asset_ids):
            raise ValueError("calibration_asset_ids must be unique and non-empty")
        if not self.strata:
            raise ValueError("strata must not be empty")
        _digest_hex("config_digest", self.config_digest)
        _digest_hex("dataset_digest", self.dataset_digest)
        _digest_hex("profile_digest", self.profile_digest)

    @property
    def level_map(self) -> Mapping[int, EnvelopeStratum]:
        return {item.severity_level: item for item in self.strata}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "transform_family": self.transform_family,
            "manifest_digest": self.manifest_digest,
            "canonical_frame": self.canonical_frame,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "calibration_split_digest": self.calibration_split_digest,
            "calibration_asset_ids": list(self.calibration_asset_ids),
            "strata": [item.to_dict() for item in self.strata],
            "config_digest": self.config_digest,
            "dataset_digest": self.dataset_digest,
            "profile_digest": self.profile_digest,
        }


def _validate_profile_observations(observations: Sequence[EnvelopeObservation], config: EnvelopeConfig) -> None:
    if not observations:
        raise ValueError("observations must not be empty")
    first = observations[0]
    seen_pairs = set()
    group_assets: Dict[str, str] = {}
    for item in observations:
        if item.operation_scope != ORDINARY_PROPAGATION:
            raise ValueError("calibration profile accepts ordinary_propagation only")
        if item.split != "calibration":
            raise ValueError("calibration profile requires split=calibration")
        if item.transform_family != first.transform_family or item.manifest_digest != first.manifest_digest:
            raise ValueError("calibration observations must share transform and manifest binding")
        if item.canonical_frame != first.canonical_frame or item.detector_version != first.detector_version or item.score_schema != first.score_schema:
            raise ValueError("calibration observations must share frame/detector/schema")
        if item.split_digest != first.split_digest:
            raise ValueError("calibration observations must share split digest")
        if item.severity_level not in config.severity_levels:
            raise ValueError("observation severity level is not in config")
        key = (item.group_id, item.severity_level)
        if key in seen_pairs:
            raise ValueError("duplicate group/severity observation")
        seen_pairs.add(key)
        prior_asset = group_assets.setdefault(item.group_id, item.asset_id)
        if prior_asset != item.asset_id:
            raise ValueError("one group cannot contain multiple assets")
    if len(set(group_assets.values())) != len(group_assets):
        raise ValueError("calibration groups must use independent assets")


def fit_propagation_envelope_profile(
    observations: Iterable[EnvelopeObservation],
    config: EnvelopeConfig,
) -> EnvelopeProfile:
    items = tuple(observations)
    _validate_profile_observations(items, config)
    first = items[0]
    strata: List[EnvelopeStratum] = []
    for level in config.severity_levels:
        level_items = [item for item in items if item.severity_level == level]
        group_ids = tuple(sorted({item.group_id for item in level_items}))
        if len(group_ids) < config.minimum_groups_per_level:
            raise ValueError("minimum severity-level calibration support is missing")
        stats_by_group = {}
        for item in level_items:
            stats_by_group[item.group_id] = item.paired_delta_raw
        stats = tuple(stats_by_group[group_id] for group_id in group_ids)
        strata.append(
            EnvelopeStratum(
                severity_level=level,
                statistics=stats,
                group_ids=group_ids,
                upper_null_raw=_upper_order_statistic(stats, config.alpha),
            )
        )
    dataset_payload = {
        "observations": [item.to_dict() for item in sorted(items, key=lambda item: (item.group_id, item.severity_level))],
        "config": config.to_dict(),
    }
    dataset_digest = _digest(dataset_payload)
    profile_payload = {
        "transform_family": first.transform_family,
        "manifest_digest": first.manifest_digest,
        "canonical_frame": first.canonical_frame,
        "detector_version": first.detector_version,
        "score_schema": first.score_schema,
        "calibration_split_digest": first.split_digest,
        "calibration_asset_ids": sorted({item.asset_id for item in items}),
        "strata": [item.to_dict() for item in strata],
        "config_digest": config.digest,
        "dataset_digest": dataset_digest,
        "version": VERSION,
    }
    return EnvelopeProfile(
        transform_family=first.transform_family,
        manifest_digest=first.manifest_digest,
        canonical_frame=first.canonical_frame,
        detector_version=first.detector_version,
        score_schema=first.score_schema,
        calibration_split_digest=first.split_digest,
        calibration_asset_ids=tuple(sorted({item.asset_id for item in items})),
        strata=tuple(strata),
        config_digest=config.digest,
        dataset_digest=dataset_digest,
        profile_digest=_digest(profile_payload),
    )


@dataclass(frozen=True)
class EnvelopeResult:
    evaluated: bool
    abstained: bool
    route: str
    reason: str
    query_group_id: str
    asset_id: str
    transform_family: str
    severity_levels: Tuple[int, ...]
    paired_delta_by_level: Tuple[Tuple[int, float], ...]
    upper_null_by_level: Tuple[Tuple[int, float], ...]
    margin_by_level: Tuple[Tuple[int, float], ...]
    p_value_by_level: Tuple[Tuple[int, float], ...]
    auc_excess_raw: Optional[float]
    positive_level_fraction_raw: Optional[float]
    min_p_value_raw: Optional[float]
    max_curve_discontinuity_raw: Optional[float]
    profile_digest: Optional[str]
    config_digest: str
    manifest_digest: Optional[str]
    detector_version: Optional[str]
    score_schema: Optional[str]
    version: str = VERSION
    result_schema: str = RESULT_SCHEMA

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "result_schema": self.result_schema,
            "evaluated": self.evaluated,
            "abstained": self.abstained,
            "route": self.route,
            "reason": self.reason,
            "query_group_id": self.query_group_id,
            "asset_id": self.asset_id,
            "transform_family": self.transform_family,
            "severity_levels": list(self.severity_levels),
            "paired_delta_by_level": [[level, value] for level, value in self.paired_delta_by_level],
            "upper_null_by_level": [[level, value] for level, value in self.upper_null_by_level],
            "margin_by_level": [[level, value] for level, value in self.margin_by_level],
            "p_value_by_level": [[level, value] for level, value in self.p_value_by_level],
            "auc_excess_raw": self.auc_excess_raw,
            "positive_level_fraction_raw": self.positive_level_fraction_raw,
            "min_p_value_raw": self.min_p_value_raw,
            "max_curve_discontinuity_raw": self.max_curve_discontinuity_raw,
            "profile_digest": self.profile_digest,
            "config_digest": self.config_digest,
            "manifest_digest": self.manifest_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
        }


def _insufficient(config: EnvelopeConfig, reason: str, observations: Sequence[EnvelopeObservation], profile: Optional[EnvelopeProfile]) -> EnvelopeResult:
    first = observations[0] if observations else None
    return EnvelopeResult(
        evaluated=False,
        abstained=True,
        route=ROUTE_INSUFFICIENT,
        reason=reason,
        query_group_id=first.group_id if first else "unknown",
        asset_id=first.asset_id if first else "unknown",
        transform_family=first.transform_family if first else "unknown",
        severity_levels=tuple(item.severity_level for item in observations),
        paired_delta_by_level=(),
        upper_null_by_level=(),
        margin_by_level=(),
        p_value_by_level=(),
        auc_excess_raw=None,
        positive_level_fraction_raw=None,
        min_p_value_raw=None,
        max_curve_discontinuity_raw=None,
        profile_digest=profile.profile_digest if profile else None,
        config_digest=config.digest,
        manifest_digest=first.manifest_digest if first else None,
        detector_version=first.detector_version if first else None,
        score_schema=first.score_schema if first else None,
    )


def evaluate_propagation_envelope(
    observations: Iterable[EnvelopeObservation],
    profile: EnvelopeProfile,
    config: EnvelopeConfig,
) -> EnvelopeResult:
    items = tuple(observations)
    if not items:
        return _insufficient(config, "missing_observations", items, profile)
    first = items[0]
    common_fields = ("group_id", "asset_id", "transform_family", "manifest_digest", "canonical_frame", "detector_version", "score_schema", "split", "split_digest")
    for item in items[1:]:
        if any(getattr(item, field) != getattr(first, field) for field in common_fields):
            return _insufficient(config, "binding_mismatch", items, profile)
        if item.operation_scope != first.operation_scope:
            return _insufficient(config, "operation_scope_mismatch", items, profile)
        if item.edit_mask_digest != first.edit_mask_digest:
            return _insufficient(config, "edit_mask_mismatch", items, profile)
    if first.split == "calibration" or first.split_digest == profile.calibration_split_digest:
        return _insufficient(config, "evaluation_split_leakage", items, profile)
    if first.asset_id in profile.calibration_asset_ids:
        return _insufficient(config, "calibration_asset_reuse", items, profile)
    if first.manifest_digest != profile.manifest_digest or first.canonical_frame != profile.canonical_frame or first.transform_family != profile.transform_family:
        return _insufficient(config, "profile_binding_mismatch", items, profile)
    if first.detector_version != profile.detector_version or first.score_schema != profile.score_schema or profile.config_digest != config.digest:
        return _insufficient(config, "profile_schema_mismatch", items, profile)
    if any(item.quality_score < config.minimum_quality for item in items):
        return _insufficient(config, "quality_below_minimum", items, profile)
    if any(item.source_match_score < config.minimum_source_match for item in items):
        return _insufficient(config, "source_match_below_minimum", items, profile)
    by_level: Dict[int, EnvelopeObservation] = {}
    for item in items:
        if item.severity_level in by_level:
            return _insufficient(config, "duplicate_severity_level", items, profile)
        by_level[item.severity_level] = item
    missing = [level for level in config.severity_levels if level not in by_level]
    if missing:
        return _insufficient(config, "severity_level_missing", items, profile)
    if any(level not in profile.level_map for level in config.severity_levels):
        return _insufficient(config, "profile_severity_level_missing", items, profile)
    if first.operation_scope == CONTENT_EDIT and first.edit_mask_digest is None:
        return _insufficient(config, "edit_mask_missing", items, profile)
    if first.operation_scope == ORDINARY_PROPAGATION and any(item.edit_mask_digest is not None for item in items):
        return _insufficient(config, "ordinary_edit_label_forbidden", items, profile)

    paired = tuple((level, by_level[level].paired_delta_raw) for level in config.severity_levels)
    upper = tuple((level, profile.level_map[level].upper_null_raw) for level in config.severity_levels)
    margins = tuple((level, by_level[level].paired_delta_raw - profile.level_map[level].upper_null_raw) for level in config.severity_levels)
    p_values = tuple((level, _ties_inclusive_p(by_level[level].paired_delta_raw, profile.level_map[level].statistics)) for level in config.severity_levels)
    positive = tuple(value > 0.0 for _, value in margins)
    positive_fraction = sum(positive) / len(positive)
    weights = tuple(max(item.quality_score * item.source_match_score, 1e-12) for item in (by_level[level] for level in config.severity_levels))
    auc_excess = sum(weight * max(0.0, margin) for weight, (_, margin) in zip(weights, margins)) / sum(weights)
    deltas = [value for _, value in paired]
    discontinuity = max((abs(right - left) for left, right in zip(deltas, deltas[1:])), default=0.0)
    min_p = min(value for _, value in p_values)

    if first.operation_scope == ORDINARY_PROPAGATION:
        return EnvelopeResult(True, False, ROUTE_NULL_CONSISTENT, "ordinary_propagation_scope", first.group_id, first.asset_id, first.transform_family, config.severity_levels, paired, upper, margins, p_values, auc_excess, positive_fraction, min_p, discontinuity, profile.profile_digest, config.digest, first.manifest_digest, first.detector_version, first.score_schema)
    if positive_fraction == 0.0:
        route, abstained, reason = ROUTE_NULL_CONSISTENT, False, "within_ordinary_propagation_envelope"
    elif sum(positive) >= config.minimum_positive_levels and positive_fraction >= config.minimum_positive_fraction and discontinuity <= config.maximum_curve_discontinuity:
        route, abstained, reason = ROUTE_ENVELOPE_CANDIDATE, False, "severity_envelope_exceeded"
    else:
        route, abstained, reason = ROUTE_CURVE_INCONSISTENT, True, "insufficient_curve_persistence"
    return EnvelopeResult(True, abstained, route, reason, first.group_id, first.asset_id, first.transform_family, config.severity_levels, paired, upper, margins, p_values, auc_excess, positive_fraction, min_p, discontinuity, profile.profile_digest, config.digest, first.manifest_digest, first.detector_version, first.score_schema)
