"""Conservative conformal calibration for paired PC-SCFT region deltas.

This module calibrates *only* the null hypothesis that a paired regional delta
is compatible with ordinary propagation.  A calibration group contains all
regions observed under one propagation instance.  Its test statistic is the
maximum positive region delta, which protects the query against a single
localized spike being hidden by an average.

The profile is stratified by ``transform_family`` and a quality bucket.  A
query first uses the exact stratum, then an explicitly recorded family or
global fallback when the exact stratum has too little frozen null support.  A
one-sided finite-sample p-value is computed with ties included:

``(1 + count(null_statistic >= query_statistic)) / (n + 1)``.

``unknown=True`` means only that the query rejected the frozen ordinary
propagation null at ``alpha``.  The result is not an AIGC probability and does
not produce ``human_supported``, ``ai_generated_supported`` or a legal
conclusion.  A missing compatible stratum is represented as
``evaluated=False`` with ``unknown=False`` so lack of calibration support is
never mislabeled as a null rejection.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


CALIBRATION_VERSION = "paired-delta-conformal-v1"
STATISTIC_SCHEMA = "paired-delta-max-positive-v1"
UNKNOWN_REASON = "paired_delta_conformal_reject"


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


def _alpha(value: float) -> float:
    normalized = _unit("alpha", value)
    if normalized <= 0.0 or normalized >= 1.0:
        raise ValueError("alpha must be strictly between 0 and 1")
    return normalized


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


def _normalize_bins(values: Sequence[float]) -> Tuple[float, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("quality_bins must be a sequence")
    try:
        bins = tuple(float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise ValueError("quality_bins must contain finite numbers") from exc
    if any(not math.isfinite(value) or not 0.0 < value < 1.0 for value in bins):
        raise ValueError("quality_bins must be strictly between 0 and 1")
    if tuple(sorted(set(bins))) != bins:
        raise ValueError("quality_bins must be strictly increasing")
    return bins


def quality_bucket(quality_score: float, quality_bins: Sequence[float] = (0.35, 0.60, 0.80)) -> str:
    """Return the stable bucket used by both fitting and query evaluation."""

    quality = _unit("quality_score", quality_score)
    bins = _normalize_bins(quality_bins)
    return f"q{bisect_right(bins, quality)}"


@dataclass(frozen=True)
class PairedDeltaGroup:
    """One calibration or query group of region-level raw deltas."""

    group_id: str
    transform_family: str
    quality_score: float
    region_deltas: Tuple[float, ...]
    detector_version: str = "source-residual-v1"
    score_schema: str = "source-residual-score-v1"
    region_ids: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _non_empty("group_id", self.group_id)
        _non_empty("transform_family", self.transform_family)
        _non_empty("detector_version", self.detector_version)
        _non_empty("score_schema", self.score_schema)
        _unit("quality_score", self.quality_score)
        if isinstance(self.region_deltas, (str, bytes)):
            raise ValueError("region_deltas must be a non-empty sequence")
        try:
            deltas = tuple(_signed_unit("region_delta", value) for value in self.region_deltas)
        except TypeError as exc:
            raise ValueError("region_deltas must be a non-empty sequence") from exc
        if not deltas:
            raise ValueError("region_deltas must be a non-empty sequence")
        object.__setattr__(self, "region_deltas", deltas)
        if self.region_ids:
            if isinstance(self.region_ids, (str, bytes)):
                raise ValueError("region_ids must be a sequence")
            ids = tuple(_non_empty("region_id", value) for value in self.region_ids)
            if len(ids) != len(deltas):
                raise ValueError("region_ids and region_deltas must have equal length")
            if len(set(ids)) != len(ids):
                raise ValueError("region_ids must be unique within one group")
        else:
            ids = tuple(f"region-{index}" for index in range(len(deltas)))
        object.__setattr__(self, "region_ids", ids)

    @property
    def statistic_raw(self) -> float:
        """Maximum positive region delta used by the conformal test."""

        return max(0.0, max(self.region_deltas))

    def bucket(self, quality_bins: Sequence[float]) -> str:
        return quality_bucket(self.quality_score, quality_bins)

    def to_dict(self, *, quality_bins: Sequence[float] = (0.35, 0.60, 0.80)) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "transform_family": self.transform_family,
            "quality_score": self.quality_score,
            "quality_bucket": self.bucket(quality_bins),
            "region_deltas": list(self.region_deltas),
            "region_ids": list(self.region_ids),
            "statistic_raw": self.statistic_raw,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
        }


@dataclass(frozen=True)
class PairedDeltaCalibrationConfig:
    """Fitting and fallback policy for a frozen null profile."""

    quality_bins: Tuple[float, ...] = (0.35, 0.60, 0.80)
    minimum_stratum_count: int = 3
    alpha: float = 0.05
    allow_family_fallback: bool = True
    allow_global_fallback: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "quality_bins", _normalize_bins(self.quality_bins))
        if (
            isinstance(self.minimum_stratum_count, bool)
            or not isinstance(self.minimum_stratum_count, int)
            or self.minimum_stratum_count < 1
        ):
            raise ValueError("minimum_stratum_count must be a positive integer")
        object.__setattr__(self, "alpha", _alpha(self.alpha))
        if not isinstance(self.allow_family_fallback, bool):
            raise ValueError("allow_family_fallback must be a bool")
        if not isinstance(self.allow_global_fallback, bool):
            raise ValueError("allow_global_fallback must be a bool")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": CALIBRATION_VERSION,
            "quality_bins": list(self.quality_bins),
            "minimum_stratum_count": self.minimum_stratum_count,
            "alpha": self.alpha,
            "allow_family_fallback": self.allow_family_fallback,
            "allow_global_fallback": self.allow_global_fallback,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class PairedDeltaStratum:
    """Frozen sorted null statistics for one family/quality bucket."""

    key: str
    transform_family: str
    quality_bucket: str
    statistics: Tuple[float, ...]
    group_ids: Tuple[str, ...]

    def __post_init__(self) -> None:
        _non_empty("key", self.key)
        _non_empty("transform_family", self.transform_family)
        _non_empty("quality_bucket", self.quality_bucket)
        if len(self.statistics) != len(self.group_ids) or not self.statistics:
            raise ValueError("statistics and group_ids must be non-empty and equal length")
        stats = tuple(_unit("statistic", value) for value in self.statistics)
        ids = tuple(_non_empty("group_id", value) for value in self.group_ids)
        if len(set(ids)) != len(ids):
            raise ValueError("group_ids must be unique within a stratum")
        ordered = tuple(sorted(zip(stats, ids), key=lambda item: (item[0], item[1])))
        object.__setattr__(self, "statistics", tuple(item[0] for item in ordered))
        object.__setattr__(self, "group_ids", tuple(item[1] for item in ordered))

    @property
    def count(self) -> int:
        return len(self.statistics)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "transform_family": self.transform_family,
            "quality_bucket": self.quality_bucket,
            "statistics": list(self.statistics),
            "group_ids": list(self.group_ids),
            "count": self.count,
        }


@dataclass(frozen=True)
class PairedDeltaCalibrationResult:
    """One null-consistency observation for a query group."""

    evaluated: bool
    unknown: bool
    reason: str
    unknown_reason: Optional[str]
    query_group_id: str
    transform_family: str
    quality_score: float
    quality_bucket: str
    statistic_raw: float
    raw_p_value: Optional[float]
    alpha: float
    requested_stratum: str
    selected_stratum: Optional[str]
    fallback: str
    fallback_reason: Optional[str]
    null_count: int
    detector_version: str
    score_schema: str
    dataset_digest: str
    profile_digest: str
    config_digest: str
    statistic_schema: str = STATISTIC_SCHEMA
    version: str = CALIBRATION_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.evaluated, bool) or not isinstance(self.unknown, bool):
            raise ValueError("evaluated and unknown must be bools")
        if self.unknown and not self.evaluated:
            raise ValueError("an unevaluated query cannot reject the null")
        if self.unknown:
            if self.unknown_reason != UNKNOWN_REASON:
                raise ValueError(f"unknown results must use {UNKNOWN_REASON}")
        elif self.unknown_reason is not None:
            raise ValueError("unknown_reason is only valid when unknown is true")
        _non_empty("reason", self.reason)
        for name, value in (
            ("query_group_id", self.query_group_id),
            ("transform_family", self.transform_family),
            ("quality_bucket", self.quality_bucket),
            ("detector_version", self.detector_version),
            ("score_schema", self.score_schema),
            ("statistic_schema", self.statistic_schema),
            ("version", self.version),
        ):
            _non_empty(name, value)
        _unit("quality_score", self.quality_score)
        _unit("statistic_raw", self.statistic_raw)
        _alpha(self.alpha)
        if self.raw_p_value is not None:
            p_value = _unit("raw_p_value", self.raw_p_value)
            if p_value <= 0.0:
                raise ValueError("raw_p_value must be greater than zero")
            expected_unknown = p_value <= self.alpha
            if self.unknown != expected_unknown:
                raise ValueError("unknown must equal raw_p_value <= alpha")
        elif self.evaluated:
            raise ValueError("evaluated result requires raw_p_value")
        if not isinstance(self.null_count, int) or self.null_count < 0:
            raise ValueError("null_count must be a non-negative integer")
        for name, value in (
            ("dataset_digest", self.dataset_digest),
            ("profile_digest", self.profile_digest),
            ("config_digest", self.config_digest),
        ):
            _digest_hex(name, value)
        if not isinstance(self.fallback, str) or self.fallback not in {"none", "family", "global", "unavailable"}:
            raise ValueError("fallback must be none, family, global, or unavailable")
        if self.fallback == "unavailable" and self.evaluated:
            raise ValueError("unavailable fallback cannot be evaluated")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "statistic_schema": self.statistic_schema,
            "null_hypothesis": "ordinary_propagation_counterfactual",
            "evaluated": self.evaluated,
            "unknown": self.unknown,
            "reason": self.reason,
            "unknown_reason": self.unknown_reason,
            "query_group_id": self.query_group_id,
            "transform_family": self.transform_family,
            "quality_score": self.quality_score,
            "quality_bucket": self.quality_bucket,
            "statistic_raw": self.statistic_raw,
            "raw_p_value": self.raw_p_value,
            "alpha": self.alpha,
            "requested_stratum": self.requested_stratum,
            "selected_stratum": self.selected_stratum,
            "fallback": self.fallback,
            "fallback_reason": self.fallback_reason,
            "null_count": self.null_count,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "dataset_digest": self.dataset_digest,
            "profile_digest": self.profile_digest,
            "config_digest": self.config_digest,
        }


@dataclass(frozen=True)
class PairedDeltaCalibrationProfile:
    """Frozen stratified null profile and query evaluator."""

    detector_version: str
    score_schema: str
    dataset_digest: str
    config: PairedDeltaCalibrationConfig
    strata: Tuple[PairedDeltaStratum, ...]
    profile_version: str = CALIBRATION_VERSION

    def __post_init__(self) -> None:
        _non_empty("detector_version", self.detector_version)
        _non_empty("score_schema", self.score_schema)
        _digest_hex("dataset_digest", self.dataset_digest)
        if not isinstance(self.config, PairedDeltaCalibrationConfig):
            raise ValueError("config must be PairedDeltaCalibrationConfig")
        if not self.strata:
            raise ValueError("strata must be non-empty")
        keys = [item.key for item in self.strata]
        if len(set(keys)) != len(keys):
            raise ValueError("stratum keys must be unique")
        if not isinstance(self.profile_version, str) or not self.profile_version.strip():
            raise ValueError("profile_version is required")

    @property
    def config_digest(self) -> str:
        return self.config.digest

    @property
    def profile_digest(self) -> str:
        return _digest(
            {
                "version": self.profile_version,
                "detector_version": self.detector_version,
                "score_schema": self.score_schema,
                "dataset_digest": self.dataset_digest,
                "config": self.config.to_dict(),
                "strata": [item.to_dict() for item in self.strata],
            }
        )

    def quality_bucket(self, quality_score: float) -> str:
        return quality_bucket(quality_score, self.config.quality_bins)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.profile_version,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "statistic_schema": STATISTIC_SCHEMA,
            "dataset_digest": self.dataset_digest,
            "profile_digest": self.profile_digest,
            "config_digest": self.config_digest,
            "config": self.config.to_dict(),
            "strata": [item.to_dict() for item in self.strata],
        }

    def _stratum(self, key: str) -> Optional[PairedDeltaStratum]:
        return next((item for item in self.strata if item.key == key), None)

    def _family_statistics(self, transform_family: str) -> Tuple[float, ...]:
        values = [
            statistic
            for item in self.strata
            if item.transform_family == transform_family
            for statistic in item.statistics
        ]
        return tuple(sorted(values))

    def _global_statistics(self) -> Tuple[float, ...]:
        return tuple(sorted(statistic for item in self.strata for statistic in item.statistics))

    def evaluate(
        self,
        query: PairedDeltaGroup,
        *,
        detector_version: Optional[str] = None,
        score_schema: Optional[str] = None,
    ) -> PairedDeltaCalibrationResult:
        if not isinstance(query, PairedDeltaGroup):
            raise ValueError("query must be PairedDeltaGroup")
        expected_detector = detector_version or query.detector_version
        expected_schema = score_schema or query.score_schema
        if expected_detector != self.detector_version:
            raise ValueError("detector_version does not match paired-delta calibration")
        if expected_schema != self.score_schema:
            raise ValueError("score_schema does not match paired-delta calibration")
        bucket = self.quality_bucket(query.quality_score)
        requested = f"{query.transform_family}::{bucket}"
        exact = self._stratum(requested)
        selected: Optional[Tuple[float, ...]] = None
        selected_key: Optional[str] = None
        fallback = "none"
        fallback_reason: Optional[str] = None
        if exact is not None and exact.count >= self.config.minimum_stratum_count:
            selected = exact.statistics
            selected_key = exact.key
        else:
            fallback_reason = (
                "exact_stratum_missing" if exact is None else "exact_stratum_below_minimum"
            )
            if self.config.allow_family_fallback:
                family_values = self._family_statistics(query.transform_family)
                if len(family_values) >= self.config.minimum_stratum_count:
                    selected = family_values
                    selected_key = f"{query.transform_family}::*"
                    fallback = "family"
            if selected is None and self.config.allow_global_fallback:
                global_values = self._global_statistics()
                if len(global_values) >= self.config.minimum_stratum_count:
                    selected = global_values
                    selected_key = "*::*"
                    fallback = "global"
        statistic = query.statistic_raw
        if selected is None:
            return PairedDeltaCalibrationResult(
                evaluated=False,
                unknown=False,
                reason="no_compatible_null",
                unknown_reason=None,
                query_group_id=query.group_id,
                transform_family=query.transform_family,
                quality_score=query.quality_score,
                quality_bucket=bucket,
                statistic_raw=statistic,
                raw_p_value=None,
                alpha=self.config.alpha,
                requested_stratum=requested,
                selected_stratum=None,
                fallback="unavailable",
                fallback_reason=fallback_reason or "no_frozen_null_statistics",
                null_count=0,
                detector_version=self.detector_version,
                score_schema=self.score_schema,
                dataset_digest=self.dataset_digest,
                profile_digest=self.profile_digest,
                config_digest=self.config_digest,
            )
        exceedances = sum(value >= statistic for value in selected)
        p_value = (1.0 + exceedances) / (len(selected) + 1.0)
        unknown = p_value <= self.config.alpha
        return PairedDeltaCalibrationResult(
            evaluated=True,
            unknown=unknown,
            reason="paired_delta_conformal_reject" if unknown else "paired_delta_null_consistent",
            unknown_reason=UNKNOWN_REASON if unknown else None,
            query_group_id=query.group_id,
            transform_family=query.transform_family,
            quality_score=query.quality_score,
            quality_bucket=bucket,
            statistic_raw=statistic,
            raw_p_value=p_value,
            alpha=self.config.alpha,
            requested_stratum=requested,
            selected_stratum=selected_key,
            fallback=fallback,
            fallback_reason=fallback_reason if fallback != "none" else None,
            null_count=len(selected),
            detector_version=self.detector_version,
            score_schema=self.score_schema,
            dataset_digest=self.dataset_digest,
            profile_digest=self.profile_digest,
            config_digest=self.config_digest,
        )


def fit_paired_delta_profile(
    groups: Iterable[PairedDeltaGroup],
    *,
    detector_version: Optional[str] = None,
    score_schema: Optional[str] = None,
    config: Optional[PairedDeltaCalibrationConfig] = None,
    dataset_digest: Optional[str] = None,
) -> PairedDeltaCalibrationProfile:
    """Fit a frozen null profile from ordinary propagation groups only."""

    cfg = config or PairedDeltaCalibrationConfig()
    if isinstance(groups, (str, bytes)):
        raise ValueError("groups must be an iterable of PairedDeltaGroup")
    try:
        items = list(groups)
    except TypeError as exc:
        raise ValueError("groups must be an iterable of PairedDeltaGroup") from exc
    if not items or any(not isinstance(item, PairedDeltaGroup) for item in items):
        raise ValueError("groups must contain at least one PairedDeltaGroup")
    group_ids = [item.group_id for item in items]
    if len(set(group_ids)) != len(group_ids):
        raise ValueError("group_id values must be unique")
    resolved_detector = detector_version or items[0].detector_version
    resolved_schema = score_schema or items[0].score_schema
    _non_empty("detector_version", resolved_detector)
    _non_empty("score_schema", resolved_schema)
    if any(item.detector_version != resolved_detector for item in items):
        raise ValueError("all groups must use one detector_version")
    if any(item.score_schema != resolved_schema for item in items):
        raise ValueError("all groups must use one score_schema")
    canonical_groups = [
        item.to_dict(quality_bins=cfg.quality_bins)
        for item in sorted(items, key=lambda item: item.group_id)
    ]
    computed_dataset_digest = _digest(
        {
            "version": CALIBRATION_VERSION,
            "statistic_schema": STATISTIC_SCHEMA,
            "detector_version": resolved_detector,
            "score_schema": resolved_schema,
            "groups": canonical_groups,
        }
    )
    resolved_dataset_digest = computed_dataset_digest if dataset_digest is None else _digest_hex(
        "dataset_digest", dataset_digest
    )
    strata_map: Dict[str, Dict[str, Any]] = {}
    for item in items:
        bucket = item.bucket(cfg.quality_bins)
        key = f"{item.transform_family}::{bucket}"
        entry = strata_map.setdefault(
            key,
            {
                "transform_family": item.transform_family,
                "quality_bucket": bucket,
                "statistics": [],
                "group_ids": [],
            },
        )
        entry["statistics"].append(item.statistic_raw)
        entry["group_ids"].append(item.group_id)
    strata = tuple(
        PairedDeltaStratum(
            key=key,
            transform_family=entry["transform_family"],
            quality_bucket=entry["quality_bucket"],
            statistics=tuple(entry["statistics"]),
            group_ids=tuple(entry["group_ids"]),
        )
        for key, entry in sorted(strata_map.items())
    )
    return PairedDeltaCalibrationProfile(
        detector_version=resolved_detector,
        score_schema=resolved_schema,
        dataset_digest=resolved_dataset_digest,
        config=cfg,
        strata=strata,
    )


def evaluate_paired_delta(
    query: PairedDeltaGroup,
    profile: PairedDeltaCalibrationProfile,
    *,
    detector_version: Optional[str] = None,
    score_schema: Optional[str] = None,
) -> PairedDeltaCalibrationResult:
    """Functional wrapper for callers that keep profile and query separate."""

    if not isinstance(profile, PairedDeltaCalibrationProfile):
        raise ValueError("profile must be PairedDeltaCalibrationProfile")
    return profile.evaluate(
        query,
        detector_version=detector_version,
        score_schema=score_schema,
    )


__all__ = [
    "CALIBRATION_VERSION",
    "STATISTIC_SCHEMA",
    "UNKNOWN_REASON",
    "PairedDeltaGroup",
    "PairedDeltaCalibrationConfig",
    "PairedDeltaStratum",
    "PairedDeltaCalibrationResult",
    "PairedDeltaCalibrationProfile",
    "quality_bucket",
    "fit_paired_delta_profile",
    "evaluate_paired_delta",
]
