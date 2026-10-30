"""Versioned real-only natural-manifold evidence for the ONMA research path.

This module is deliberately model-agnostic.  A caller supplies a fixed
feature vector from an audited adapter; the module fits a robust median/MAD
profile on explicitly authorised real samples and measures how far a query is
from that profile.  The result is raw open-world evidence, never an AIGC or
human-authorship decision.

The profile is immutable and digest-bound.  Adaptation takes a complete
replay buffer plus the parent digest and produces a new version, so a new
generator or domain cannot silently rewrite an old calibration profile.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PROFILE_SCHEMA = "natural-manifold-profile-v1"
RESULT_SCHEMA = "natural-manifold-result-v1"
FEATURE_SCHEMA = "natural-manifold-feature-v1"
VERSION = "onma-natural-profile-v1"

ROUTE_IN_DISTRIBUTION = "in_distribution"
ROUTE_OUT_OF_MANIFOLD = "out_of_manifold"
ROUTE_INSUFFICIENT = "insufficient"
ROUTE_PROFILE_MISMATCH = "profile_mismatch"


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return result


def _positive(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive finite number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be a positive finite number")
    return result


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _digest_hex(name: str, value: str) -> str:
    _text(name, value)
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
    return value.lower()


def _vector(name: str, values: Sequence[float]) -> Tuple[float, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be a non-empty finite vector")
    result = []
    for index, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name}[{index}] must be a finite number")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{name}[{index}] must be a finite number")
        result.append(number)
    if not result:
        raise ValueError(f"{name} must not be empty")
    return tuple(result)


def _median(values: Sequence[float]) -> float:
    ordered = sorted(float(value) for value in values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _quantile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("quantile requires at least one value")
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile must be between 0 and 1")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


@dataclass(frozen=True)
class NaturalManifoldConfig:
    """Frozen fitting and query parameters.

    Defaults are research-safe gates, not production thresholds.
    """

    minimum_support: int = 20
    minimum_quality: float = 0.35
    alpha: float = 0.05
    energy_scale: float = 1.0
    scale_floor: float = 1e-3

    def __post_init__(self) -> None:
        if (
            isinstance(self.minimum_support, bool)
            or not isinstance(self.minimum_support, int)
            or self.minimum_support < 2
        ):
            raise ValueError("minimum_support must be an integer >= 2")
        _unit("minimum_quality", self.minimum_quality)
        alpha = _unit("alpha", self.alpha)
        if alpha <= 0.0 or alpha >= 1.0:
            raise ValueError("alpha must be strictly between 0 and 1")
        _positive("energy_scale", self.energy_scale)
        _positive("scale_floor", self.scale_floor)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "minimum_support": self.minimum_support,
            "minimum_quality": float(self.minimum_quality),
            "alpha": float(self.alpha),
            "energy_scale": float(self.energy_scale),
            "scale_floor": float(self.scale_floor),
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class ManifoldObservation:
    """One feature vector eligible for real-only calibration."""

    sample_id: str
    group_id: str
    feature: Tuple[float, ...]
    feature_schema: str = FEATURE_SCHEMA
    detector_version: str = "adapter-unbound"
    origin: str = "real_authorized"
    authorized_for_research: bool = True
    quality_score: float = 1.0
    split: str = "calibration"

    def __post_init__(self) -> None:
        _text("sample_id", self.sample_id)
        _text("group_id", self.group_id)
        _text("feature_schema", self.feature_schema)
        _text("detector_version", self.detector_version)
        if self.origin != "real_authorized":
            raise ValueError("origin must be real_authorized")
        if self.authorized_for_research is not True:
            raise ValueError("authorized_for_research must be true")
        if self.split != "calibration":
            raise ValueError("real-only profile observations must use split=calibration")
        _unit("quality_score", self.quality_score)
        object.__setattr__(self, "feature", _vector("feature", self.feature))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "group_id": self.group_id,
            "feature": list(self.feature),
            "feature_schema": self.feature_schema,
            "detector_version": self.detector_version,
            "origin": self.origin,
            "authorized_for_research": self.authorized_for_research,
            "quality_score": float(self.quality_score),
            "split": self.split,
        }


@dataclass(frozen=True)
class NaturalManifoldProfile:
    feature_schema: str
    detector_version: str
    dimension: int
    feature_median: Tuple[float, ...]
    robust_scale: Tuple[float, ...]
    energy_threshold: float
    energy_scale: float
    support_count: int
    group_count: int
    minimum_support: int
    minimum_quality: float
    alpha: float
    dataset_digest: str
    profile_digest: str
    config_digest: str
    parent_profile_digest: Optional[str] = None
    prototype_version: str = "real-only-v1"
    version_index: int = 1
    schema: str = PROFILE_SCHEMA

    def __post_init__(self) -> None:
        _text("feature_schema", self.feature_schema)
        _text("detector_version", self.detector_version)
        _text("prototype_version", self.prototype_version)
        if self.schema != PROFILE_SCHEMA:
            raise ValueError(f"unsupported profile schema: {self.schema!r}")
        if isinstance(self.dimension, bool) or not isinstance(self.dimension, int) or self.dimension < 1:
            raise ValueError("dimension must be a positive integer")
        if len(self.feature_median) != self.dimension or len(self.robust_scale) != self.dimension:
            raise ValueError("profile vectors must match dimension")
        _vector("feature_median", self.feature_median)
        scales = _vector("robust_scale", self.robust_scale)
        if any(value <= 0.0 for value in scales):
            raise ValueError("robust_scale values must be positive")
        _unit("energy_threshold", self.energy_threshold)
        _positive("energy_scale", self.energy_scale)
        if self.support_count < 1 or self.group_count < 1:
            raise ValueError("profile support counts must be positive")
        if self.minimum_support < 2 or self.version_index < 1:
            raise ValueError("profile version/support bounds are invalid")
        _unit("minimum_quality", self.minimum_quality)
        alpha = _unit("alpha", self.alpha)
        if alpha <= 0.0 or alpha >= 1.0:
            raise ValueError("alpha must be strictly between 0 and 1")
        _digest_hex("dataset_digest", self.dataset_digest)
        _digest_hex("profile_digest", self.profile_digest)
        _digest_hex("config_digest", self.config_digest)
        if self.parent_profile_digest is not None:
            _digest_hex("parent_profile_digest", self.parent_profile_digest)

    @property
    def support_sufficient(self) -> bool:
        return self.support_count >= self.minimum_support

    def digest_payload(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "feature_schema": self.feature_schema,
            "detector_version": self.detector_version,
            "dimension": self.dimension,
            "feature_median": list(self.feature_median),
            "robust_scale": list(self.robust_scale),
            "energy_threshold": self.energy_threshold,
            "energy_scale": self.energy_scale,
            "support_count": self.support_count,
            "group_count": self.group_count,
            "minimum_support": self.minimum_support,
            "minimum_quality": self.minimum_quality,
            "alpha": self.alpha,
            "dataset_digest": self.dataset_digest,
            "config_digest": self.config_digest,
            "parent_profile_digest": self.parent_profile_digest,
            "prototype_version": self.prototype_version,
            "version_index": self.version_index,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {**self.digest_payload(), "profile_digest": self.profile_digest}


@dataclass(frozen=True)
class ManifoldQuery:
    sample_id: str
    feature: Tuple[float, ...]
    feature_schema: str
    detector_version: str
    quality_score: float = 1.0

    def __post_init__(self) -> None:
        _text("sample_id", self.sample_id)
        _text("feature_schema", self.feature_schema)
        _text("detector_version", self.detector_version)
        _unit("quality_score", self.quality_score)
        object.__setattr__(self, "feature", _vector("feature", self.feature))


@dataclass(frozen=True)
class NaturalManifoldResult:
    route: str
    reason: str
    sample_id: str
    energy_raw: Optional[float]
    threshold: Optional[float]
    profile_digest: str
    dataset_digest: str
    feature_schema: str
    detector_version: str
    support_sufficient: bool
    schema: str = RESULT_SCHEMA

    def __post_init__(self) -> None:
        if self.route not in {
            ROUTE_IN_DISTRIBUTION,
            ROUTE_OUT_OF_MANIFOLD,
            ROUTE_INSUFFICIENT,
            ROUTE_PROFILE_MISMATCH,
        }:
            raise ValueError(f"unsupported manifold route: {self.route!r}")
        _text("reason", self.reason)
        _text("sample_id", self.sample_id)
        _digest_hex("profile_digest", self.profile_digest)
        _digest_hex("dataset_digest", self.dataset_digest)
        _text("feature_schema", self.feature_schema)
        _text("detector_version", self.detector_version)
        if self.energy_raw is not None:
            _unit("energy_raw", self.energy_raw)
        if self.threshold is not None:
            _unit("threshold", self.threshold)
        if self.route in {ROUTE_IN_DISTRIBUTION, ROUTE_OUT_OF_MANIFOLD}:
            if self.energy_raw is None or self.threshold is None:
                raise ValueError("evaluated routes require energy and threshold")

    @property
    def evaluated(self) -> bool:
        return self.route in {ROUTE_IN_DISTRIBUTION, ROUTE_OUT_OF_MANIFOLD}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "route": self.route,
            "reason": self.reason,
            "sample_id": self.sample_id,
            "energy_raw": self.energy_raw,
            "threshold": self.threshold,
            "profile_digest": self.profile_digest,
            "dataset_digest": self.dataset_digest,
            "feature_schema": self.feature_schema,
            "detector_version": self.detector_version,
            "support_sufficient": self.support_sufficient,
            "evaluated": self.evaluated,
            "interpretation": (
                "raw natural-manifold evidence only; routes do not prove human or AI origin"
            ),
        }


def _validate_observations(
    observations: Iterable[ManifoldObservation],
    config: NaturalManifoldConfig,
) -> List[ManifoldObservation]:
    values = list(observations)
    if not values:
        raise ValueError("at least one real-authorized observation is required")
    if any(not isinstance(item, ManifoldObservation) for item in values):
        raise ValueError("observations must be ManifoldObservation instances")
    sample_ids = [item.sample_id for item in values]
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError("sample_id values must be unique")
    group_ids = [item.group_id for item in values]
    if len(set(group_ids)) != len(group_ids):
        raise ValueError("group_id values must be unique for calibration independence")
    feature_schema = values[0].feature_schema
    detector_version = values[0].detector_version
    dimension = len(values[0].feature)
    for item in values:
        if item.feature_schema != feature_schema or item.detector_version != detector_version:
            raise ValueError("feature_schema and detector_version must be homogeneous")
        if len(item.feature) != dimension:
            raise ValueError("feature dimensions must be homogeneous")
        if item.quality_score < config.minimum_quality:
            raise ValueError("low-quality observations cannot enter the real-only profile")
    return values


def _dataset_digest(observations: Sequence[ManifoldObservation]) -> str:
    payload = [item.to_dict() for item in sorted(observations, key=lambda item: item.sample_id)]
    return _digest(payload)


def _energy(
    feature: Sequence[float],
    medians: Sequence[float],
    scales: Sequence[float],
    energy_scale: float,
) -> float:
    z_mean = sum(abs(float(value) - median) / scale for value, median, scale in zip(feature, medians, scales)) / len(medians)
    raw = 1.0 - math.exp(-z_mean / energy_scale)
    return min(1.0, max(0.0, raw))


def _profile_from_observations(
    observations: Sequence[ManifoldObservation],
    config: NaturalManifoldConfig,
    *,
    parent_profile_digest: Optional[str],
    prototype_version: str,
    version_index: int,
) -> NaturalManifoldProfile:
    dimension = len(observations[0].feature)
    medians = tuple(_median([item.feature[index] for item in observations]) for index in range(dimension))
    scales = []
    for index, median in enumerate(medians):
        mad = _median([abs(item.feature[index] - median) for item in observations])
        scales.append(max(1.4826 * mad, config.scale_floor))
    scales_tuple = tuple(scales)
    energies = [
        _energy(item.feature, medians, scales_tuple, config.energy_scale)
        for item in observations
    ]
    threshold = _quantile(energies, 1.0 - config.alpha)
    dataset_digest = _dataset_digest(observations)
    provisional = {
        "schema": PROFILE_SCHEMA,
        "feature_schema": observations[0].feature_schema,
        "detector_version": observations[0].detector_version,
        "dimension": dimension,
        "feature_median": list(medians),
        "robust_scale": list(scales_tuple),
        "energy_threshold": threshold,
        "energy_scale": config.energy_scale,
        "support_count": len(observations),
        "group_count": len({item.group_id for item in observations}),
        "minimum_support": config.minimum_support,
        "minimum_quality": config.minimum_quality,
        "alpha": config.alpha,
        "dataset_digest": dataset_digest,
        "config_digest": config.digest,
        "parent_profile_digest": parent_profile_digest,
        "prototype_version": prototype_version,
        "version_index": version_index,
    }
    profile_digest = _digest(provisional)
    return NaturalManifoldProfile(
        feature_schema=observations[0].feature_schema,
        detector_version=observations[0].detector_version,
        dimension=dimension,
        feature_median=medians,
        robust_scale=scales_tuple,
        energy_threshold=threshold,
        energy_scale=config.energy_scale,
        support_count=len(observations),
        group_count=len({item.group_id for item in observations}),
        minimum_support=config.minimum_support,
        minimum_quality=config.minimum_quality,
        alpha=config.alpha,
        dataset_digest=dataset_digest,
        profile_digest=profile_digest,
        config_digest=config.digest,
        parent_profile_digest=parent_profile_digest,
        prototype_version=prototype_version,
        version_index=version_index,
    )


def fit_real_manifold_profile(
    observations: Iterable[ManifoldObservation],
    *,
    config: NaturalManifoldConfig = NaturalManifoldConfig(),
    prototype_version: str = "real-only-v1",
) -> NaturalManifoldProfile:
    """Fit an immutable real-only profile from an authorised calibration flow."""

    _text("prototype_version", prototype_version)
    values = _validate_observations(observations, config)
    return _profile_from_observations(
        values,
        config,
        parent_profile_digest=None,
        prototype_version=prototype_version,
        version_index=1,
    )


def adapt_real_manifold_profile(
    parent: NaturalManifoldProfile,
    replay_observations: Iterable[ManifoldObservation],
    *,
    parent_profile_digest: str,
    config: Optional[NaturalManifoldConfig] = None,
    prototype_version: str,
) -> NaturalManifoldProfile:
    """Create a new profile from a complete replay buffer.

    The caller must explicitly bind the replay buffer to the parent digest and
    provide more support than the parent profile.  The parent object remains
    unchanged and is the rollback target.
    """

    if not isinstance(parent, NaturalManifoldProfile):
        raise ValueError("parent must be a NaturalManifoldProfile")
    _digest_hex("parent_profile_digest", parent_profile_digest)
    if parent_profile_digest != parent.profile_digest:
        raise ValueError("parent_profile_digest does not match parent profile")
    _text("prototype_version", prototype_version)
    if config is None:
        config = NaturalManifoldConfig(
            minimum_support=parent.minimum_support,
            minimum_quality=parent.minimum_quality,
            alpha=parent.alpha,
            energy_scale=parent.energy_scale,
            scale_floor=min(parent.robust_scale),
        )
    values = _validate_observations(replay_observations, config)
    if len(values) <= parent.support_count:
        raise ValueError("replay buffer must contain new support beyond parent profile")
    if values[0].feature_schema != parent.feature_schema or values[0].detector_version != parent.detector_version:
        raise ValueError("replay buffer schema does not match parent profile")
    return _profile_from_observations(
        values,
        config,
        parent_profile_digest=parent.profile_digest,
        prototype_version=prototype_version,
        version_index=parent.version_index + 1,
    )


def _mismatch_result(
    query: ManifoldQuery,
    profile: NaturalManifoldProfile,
    reason: str,
) -> NaturalManifoldResult:
    return NaturalManifoldResult(
        route=ROUTE_PROFILE_MISMATCH,
        reason=reason,
        sample_id=query.sample_id,
        energy_raw=None,
        threshold=None,
        profile_digest=profile.profile_digest,
        dataset_digest=profile.dataset_digest,
        feature_schema=profile.feature_schema,
        detector_version=profile.detector_version,
        support_sufficient=profile.support_sufficient,
    )


def evaluate_real_manifold(
    query: ManifoldQuery,
    profile: NaturalManifoldProfile,
) -> NaturalManifoldResult:
    """Evaluate one query against a profile without producing an AIGC label."""

    if not isinstance(query, ManifoldQuery) or not isinstance(profile, NaturalManifoldProfile):
        raise ValueError("query and profile types are required")
    if query.feature_schema != profile.feature_schema:
        return _mismatch_result(query, profile, "feature_schema_mismatch")
    if query.detector_version != profile.detector_version:
        return _mismatch_result(query, profile, "detector_version_mismatch")
    if len(query.feature) != profile.dimension:
        return _mismatch_result(query, profile, "feature_dimension_mismatch")
    if query.quality_score < profile.minimum_quality:
        return NaturalManifoldResult(
            route=ROUTE_INSUFFICIENT,
            reason="quality_below_threshold",
            sample_id=query.sample_id,
            energy_raw=None,
            threshold=profile.energy_threshold,
            profile_digest=profile.profile_digest,
            dataset_digest=profile.dataset_digest,
            feature_schema=profile.feature_schema,
            detector_version=profile.detector_version,
            support_sufficient=profile.support_sufficient,
        )
    if not profile.support_sufficient:
        return NaturalManifoldResult(
            route=ROUTE_INSUFFICIENT,
            reason="insufficient_profile_support",
            sample_id=query.sample_id,
            energy_raw=None,
            threshold=profile.energy_threshold,
            profile_digest=profile.profile_digest,
            dataset_digest=profile.dataset_digest,
            feature_schema=profile.feature_schema,
            detector_version=profile.detector_version,
            support_sufficient=False,
        )
    energy = _energy(query.feature, profile.feature_median, profile.robust_scale, profile.energy_scale)
    route = ROUTE_OUT_OF_MANIFOLD if energy > profile.energy_threshold else ROUTE_IN_DISTRIBUTION
    return NaturalManifoldResult(
        route=route,
        reason="energy_above_profile_threshold" if route == ROUTE_OUT_OF_MANIFOLD else "within_profile_threshold",
        sample_id=query.sample_id,
        energy_raw=energy,
        threshold=profile.energy_threshold,
        profile_digest=profile.profile_digest,
        dataset_digest=profile.dataset_digest,
        feature_schema=profile.feature_schema,
        detector_version=profile.detector_version,
        support_sufficient=True,
    )
