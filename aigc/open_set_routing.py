"""Open-set generator-family routing with a real-only calibration guard.

This module is an adapter boundary, not an AIGC detector.  A future model
adapter may supply a generator-aware embedding (for example, a GAPL-like
prototype feature or an LTD-like transition feature) and an independently
calibrated real-only p-value.  The router keeps those streams separate,
rejects unknown or ambiguous families, and exposes conflicts for review.

No route in this module proves AI generation, human authorship, provenance,
or a legal conclusion.  The profile is immutable and digest-bound so a new
generator family cannot silently rewrite an earlier calibration.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


VERSION = "generator-family-open-set-v1"
PROFILE_SCHEMA = "generator-family-profile-v1"
RESULT_SCHEMA = "generator-family-route-result-v1"
FEATURE_SCHEMA = "generator-family-feature-v1"

ROUTE_KNOWN_FAMILY = "known_family_supported"
ROUTE_REAL_CONSISTENT = "real_consistent"
ROUTE_OPEN_SET_UNKNOWN = "open_set_unknown"
ROUTE_CONFLICT_REVIEW = "conflict_review"
ROUTE_INSUFFICIENT = "insufficient"


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _finite(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _unit(name: str, value: float) -> float:
    result = _finite(name, value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return result


def _positive(name: str, value: float) -> float:
    result = _finite(name, value)
    if result <= 0.0:
        raise ValueError(f"{name} must be positive")
    return result


def _vector(name: str, values: Sequence[float]) -> Tuple[float, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be a non-empty finite vector")
    result = tuple(_finite(f"{name}[{index}]", value) for index, value in enumerate(values))
    if not result:
        raise ValueError(f"{name} must not be empty")
    return result


def _sha256(value: Any) -> str:
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


def _distance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("feature dimensions must match")
    return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(left, right)) / len(left))


def _quantile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("quantile requires values")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


@dataclass(frozen=True)
class OpenSetRoutingConfig:
    minimum_family_support: int = 5
    minimum_query_quality: float = 0.35
    maximum_family_distance: float = 0.25
    minimum_family_margin: float = 0.02
    real_alpha: float = 0.05
    radius_floor: float = 1e-3
    minimum_family_group_support: int = 2
    minimum_real_calibration_support: int = 8
    require_real_calibration: bool = True

    def __post_init__(self) -> None:
        if (
            isinstance(self.minimum_family_support, bool)
            or not isinstance(self.minimum_family_support, int)
            or self.minimum_family_support < 2
        ):
            raise ValueError("minimum_family_support must be an integer >= 2")
        _unit("minimum_query_quality", self.minimum_query_quality)
        _positive("maximum_family_distance", self.maximum_family_distance)
        _positive("minimum_family_margin", self.minimum_family_margin)
        alpha = _unit("real_alpha", self.real_alpha)
        if alpha <= 0.0 or alpha >= 1.0:
            raise ValueError("real_alpha must be strictly between 0 and 1")
        _positive("radius_floor", self.radius_floor)
        for name, value in (
            ("minimum_family_group_support", self.minimum_family_group_support),
            ("minimum_real_calibration_support", self.minimum_real_calibration_support),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(self.require_real_calibration, bool):
            raise ValueError("require_real_calibration must be a bool")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "minimum_family_support": self.minimum_family_support,
            "minimum_query_quality": float(self.minimum_query_quality),
            "maximum_family_distance": float(self.maximum_family_distance),
            "minimum_family_margin": float(self.minimum_family_margin),
            "real_alpha": float(self.real_alpha),
            "radius_floor": float(self.radius_floor),
            "minimum_family_group_support": self.minimum_family_group_support,
            "minimum_real_calibration_support": self.minimum_real_calibration_support,
            "require_real_calibration": self.require_real_calibration,
        }

    @property
    def digest(self) -> str:
        return _sha256(self.to_dict())


@dataclass(frozen=True)
class GeneratorFamilyExample:
    sample_id: str
    group_id: str
    family_id: str
    feature: Tuple[float, ...]
    feature_schema: str = FEATURE_SCHEMA
    detector_version: str = "adapter-unbound"
    quality_score: float = 1.0
    authorized_for_research: bool = True
    split: str = "calibration"

    def __post_init__(self) -> None:
        _text("sample_id", self.sample_id)
        _text("group_id", self.group_id)
        _text("family_id", self.family_id)
        _text("feature_schema", self.feature_schema)
        _text("detector_version", self.detector_version)
        _unit("quality_score", self.quality_score)
        if self.authorized_for_research is not True:
            raise ValueError("generator-family examples must be authorised")
        if self.split != "calibration":
            raise ValueError("generator-family examples must use split=calibration")
        object.__setattr__(self, "feature", _vector("feature", self.feature))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "group_id": self.group_id,
            "family_id": self.family_id,
            "feature": list(self.feature),
            "feature_schema": self.feature_schema,
            "detector_version": self.detector_version,
            "quality_score": float(self.quality_score),
            "authorized_for_research": self.authorized_for_research,
            "split": self.split,
        }


@dataclass(frozen=True)
class GeneratorPrototype:
    family_id: str
    centroid: Tuple[float, ...]
    radius_raw: float
    support_count: int
    group_count: int

    def __post_init__(self) -> None:
        _text("family_id", self.family_id)
        object.__setattr__(self, "centroid", _vector("centroid", self.centroid))
        _positive("radius_raw", self.radius_raw)
        if not isinstance(self.support_count, int) or self.support_count < 1:
            raise ValueError("support_count must be positive")
        if not isinstance(self.group_count, int) or self.group_count < 1:
            raise ValueError("group_count must be positive")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "family_id": self.family_id,
            "centroid": list(self.centroid),
            "radius_raw": float(self.radius_raw),
            "support_count": self.support_count,
            "group_count": self.group_count,
        }


@dataclass(frozen=True)
class GeneratorFamilyProfile:
    feature_schema: str
    detector_version: str
    dimension: int
    prototypes: Tuple[GeneratorPrototype, ...]
    dataset_digest: str
    config_digest: str
    profile_digest: str
    real_profile_digest: Optional[str] = None
    real_calibration_dataset_digest: Optional[str] = None
    real_calibration_support_count: Optional[int] = None
    profile_version: str = "generator-family-profile-v1"
    schema: str = PROFILE_SCHEMA

    def __post_init__(self) -> None:
        _text("feature_schema", self.feature_schema)
        _text("detector_version", self.detector_version)
        _text("profile_version", self.profile_version)
        if self.schema != PROFILE_SCHEMA:
            raise ValueError(f"unsupported profile schema: {self.schema!r}")
        if not isinstance(self.dimension, int) or self.dimension < 1:
            raise ValueError("dimension must be positive")
        if not self.prototypes:
            raise ValueError("at least one generator prototype is required")
        family_ids = [prototype.family_id for prototype in self.prototypes]
        if len(set(family_ids)) != len(family_ids):
            raise ValueError("prototype family IDs must be unique")
        if any(len(prototype.centroid) != self.dimension for prototype in self.prototypes):
            raise ValueError("prototype dimensions must match profile dimension")
        _digest_hex("dataset_digest", self.dataset_digest)
        _digest_hex("config_digest", self.config_digest)
        _digest_hex("profile_digest", self.profile_digest)
        if self.real_profile_digest is not None:
            _digest_hex("real_profile_digest", self.real_profile_digest)
        if self.real_calibration_dataset_digest is not None:
            _digest_hex("real_calibration_dataset_digest", self.real_calibration_dataset_digest)
        if self.real_calibration_support_count is not None:
            if (
                isinstance(self.real_calibration_support_count, bool)
                or not isinstance(self.real_calibration_support_count, int)
                or self.real_calibration_support_count < 1
            ):
                raise ValueError("real_calibration_support_count must be a positive integer")
        if (self.real_calibration_dataset_digest is None) != (
            self.real_calibration_support_count is None
        ):
            raise ValueError("real calibration dataset and support count must be provided together")

    def digest_payload(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "profile_version": self.profile_version,
            "feature_schema": self.feature_schema,
            "detector_version": self.detector_version,
            "dimension": self.dimension,
            "prototypes": [prototype.to_dict() for prototype in self.prototypes],
            "dataset_digest": self.dataset_digest,
            "config_digest": self.config_digest,
            "real_profile_digest": self.real_profile_digest,
            "real_calibration_dataset_digest": self.real_calibration_dataset_digest,
            "real_calibration_support_count": self.real_calibration_support_count,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {**self.digest_payload(), "profile_digest": self.profile_digest}


@dataclass(frozen=True)
class OpenSetQuery:
    sample_id: str
    feature: Tuple[float, ...]
    feature_schema: str
    detector_version: str
    input_digest: Optional[str] = None
    quality_score: float = 1.0
    real_p_value_raw: Optional[float] = None
    real_profile_digest: Optional[str] = None

    def __post_init__(self) -> None:
        _text("sample_id", self.sample_id)
        _text("feature_schema", self.feature_schema)
        _text("detector_version", self.detector_version)
        _unit("quality_score", self.quality_score)
        object.__setattr__(self, "feature", _vector("feature", self.feature))
        if self.real_p_value_raw is None:
            if self.real_profile_digest is not None:
                raise ValueError("real_profile_digest requires real_p_value_raw")
        else:
            p_value = _unit("real_p_value_raw", self.real_p_value_raw)
            if p_value <= 0.0:
                raise ValueError("real_p_value_raw must be greater than zero")
            if self.real_profile_digest is None:
                raise ValueError("real_p_value_raw requires real_profile_digest")
            _digest_hex("real_profile_digest", self.real_profile_digest)
            if self.input_digest is None:
                raise ValueError("real_p_value_raw requires input_digest")
        if self.input_digest is not None:
            _digest_hex("input_digest", self.input_digest)


@dataclass(frozen=True)
class OpenSetRouteResult:
    route: str
    reason: str
    sample_id: str
    input_digest: Optional[str]
    family_id: Optional[str]
    nearest_distance_raw: Optional[float]
    family_margin_raw: Optional[float]
    family_support_count: int
    real_p_value_raw: Optional[float]
    real_consistent: Optional[bool]
    profile_digest: str
    config_digest: str
    evidence_digest: str
    schema: str = RESULT_SCHEMA
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.route not in {
            ROUTE_KNOWN_FAMILY,
            ROUTE_REAL_CONSISTENT,
            ROUTE_OPEN_SET_UNKNOWN,
            ROUTE_CONFLICT_REVIEW,
            ROUTE_INSUFFICIENT,
        }:
            raise ValueError("unsupported route")
        _text("reason", self.reason)
        _text("sample_id", self.sample_id)
        if self.input_digest is not None:
            _digest_hex("input_digest", self.input_digest)
        if self.family_id is not None:
            _text("family_id", self.family_id)
        if self.nearest_distance_raw is not None:
            _finite("nearest_distance_raw", self.nearest_distance_raw)
        if self.family_margin_raw is not None:
            _finite("family_margin_raw", self.family_margin_raw)
        if not isinstance(self.family_support_count, int) or self.family_support_count < 0:
            raise ValueError("family_support_count must be a non-negative integer")
        if self.real_p_value_raw is not None:
            p_value = _unit("real_p_value_raw", self.real_p_value_raw)
            if p_value <= 0.0:
                raise ValueError("real_p_value_raw must be greater than zero")
        if self.real_consistent is not None and not isinstance(self.real_consistent, bool):
            raise ValueError("real_consistent must be a bool or null")
        _digest_hex("profile_digest", self.profile_digest)
        _digest_hex("config_digest", self.config_digest)
        _digest_hex("evidence_digest", self.evidence_digest)

    @property
    def abstained(self) -> bool:
        return self.route in {ROUTE_CONFLICT_REVIEW, ROUTE_OPEN_SET_UNKNOWN, ROUTE_INSUFFICIENT}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "route": self.route,
            "reason": self.reason,
            "sample_id": self.sample_id,
            "input_digest": self.input_digest,
            "family_id": self.family_id,
            "nearest_distance_raw": self.nearest_distance_raw,
            "family_margin_raw": self.family_margin_raw,
            "family_support_count": self.family_support_count,
            "real_p_value_raw": self.real_p_value_raw,
            "real_consistent": self.real_consistent,
            "profile_digest": self.profile_digest,
            "config_digest": self.config_digest,
            "evidence_digest": self.evidence_digest,
            "abstained": self.abstained,
        }


def fit_generator_family_profile(
    examples: Iterable[GeneratorFamilyExample],
    config: Optional[OpenSetRoutingConfig] = None,
    *,
    profile_version: str = "generator-family-profile-v1",
    real_profile_digest: Optional[str] = None,
    real_calibration_dataset_digest: Optional[str] = None,
    real_calibration_support_count: Optional[int] = None,
) -> GeneratorFamilyProfile:
    """Fit immutable family centroids from a calibration-only stream."""

    config = config or OpenSetRoutingConfig()
    if real_profile_digest is not None:
        real_profile_digest = _digest_hex("real_profile_digest", real_profile_digest)
    if config.require_real_calibration:
        if real_profile_digest is None:
            raise ValueError("real_profile_digest is required when real calibration is required")
        if real_calibration_dataset_digest is None or real_calibration_support_count is None:
            raise ValueError(
                "real calibration dataset digest and support count are required when real calibration is required"
            )
    if real_calibration_dataset_digest is not None:
        real_calibration_dataset_digest = _digest_hex(
            "real_calibration_dataset_digest", real_calibration_dataset_digest
        )
    if real_calibration_support_count is not None:
        if (
            isinstance(real_calibration_support_count, bool)
            or not isinstance(real_calibration_support_count, int)
            or real_calibration_support_count < config.minimum_real_calibration_support
        ):
            raise ValueError(
                "real_calibration_support_count is below the configured independent support gate"
            )
    rows = list(examples)
    if not rows:
        raise ValueError("at least one calibration example is required")
    sample_ids = [row.sample_id for row in rows]
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError("sample_id values must be unique")
    group_to_family: Dict[str, str] = {}
    for row in rows:
        previous = group_to_family.setdefault(row.group_id, row.family_id)
        if previous != row.family_id:
            raise ValueError("a calibration group cannot span generator families")
    feature_schema = rows[0].feature_schema
    detector_version = rows[0].detector_version
    dimension = len(rows[0].feature)
    if any(
        row.feature_schema != feature_schema
        or row.detector_version != detector_version
        or len(row.feature) != dimension
        for row in rows
    ):
        raise ValueError("calibration examples must share feature schema, detector and dimension")
    usable = [row for row in rows if row.quality_score >= config.minimum_query_quality]
    if not usable:
        raise ValueError("no calibration examples pass the quality gate")
    by_family: Dict[str, List[GeneratorFamilyExample]] = {}
    for row in usable:
        by_family.setdefault(row.family_id, []).append(row)
    prototypes: List[GeneratorPrototype] = []
    for family_id in sorted(by_family):
        family_rows = sorted(by_family[family_id], key=lambda item: item.sample_id)
        centroid = tuple(
            math.fsum(row.feature[index] for row in family_rows) / len(family_rows)
            for index in range(dimension)
        )
        distances = [_distance(row.feature, centroid) for row in family_rows]
        radius = max(config.radius_floor, _quantile(distances, 0.90))
        prototypes.append(
            GeneratorPrototype(
                family_id=family_id,
                centroid=centroid,
                radius_raw=radius,
                support_count=len(family_rows),
                group_count=len({row.group_id for row in family_rows}),
            )
        )
    dataset_digest = _sha256([row.to_dict() for row in sorted(usable, key=lambda item: item.sample_id)])
    payload = {
        "schema": PROFILE_SCHEMA,
        "profile_version": _text("profile_version", profile_version),
        "feature_schema": feature_schema,
        "detector_version": detector_version,
        "dimension": dimension,
        "prototypes": [prototype.to_dict() for prototype in prototypes],
        "dataset_digest": dataset_digest,
        "config_digest": config.digest,
        "real_profile_digest": real_profile_digest,
        "real_calibration_dataset_digest": real_calibration_dataset_digest,
        "real_calibration_support_count": real_calibration_support_count,
    }
    profile_digest = _sha256(payload)
    return GeneratorFamilyProfile(
        feature_schema=feature_schema,
        detector_version=detector_version,
        dimension=dimension,
        prototypes=tuple(prototypes),
        dataset_digest=dataset_digest,
        config_digest=config.digest,
        profile_digest=profile_digest,
        real_profile_digest=real_profile_digest,
        real_calibration_dataset_digest=real_calibration_dataset_digest,
        real_calibration_support_count=real_calibration_support_count,
        profile_version=profile_version,
    )


def evaluate_open_set_route(
    query: OpenSetQuery,
    profile: GeneratorFamilyProfile,
    config: Optional[OpenSetRoutingConfig] = None,
) -> OpenSetRouteResult:
    """Route a query while preserving unknown and cross-stream conflicts."""

    config = config or OpenSetRoutingConfig()
    base = {
        "sample_id": query.sample_id,
        "input_digest": query.input_digest,
        "profile_digest": profile.profile_digest,
        "config_digest": config.digest,
    }
    if profile.config_digest != config.digest:
        return _result(base, ROUTE_INSUFFICIENT, "config_binding_mismatch")
    if _sha256(profile.digest_payload()) != profile.profile_digest:
        return _result(base, ROUTE_INSUFFICIENT, "profile_integrity_mismatch")
    if query.feature_schema != profile.feature_schema:
        return _result(base, ROUTE_INSUFFICIENT, "feature_schema_mismatch")
    if query.detector_version != profile.detector_version:
        return _result(base, ROUTE_INSUFFICIENT, "detector_version_mismatch")
    if len(query.feature) != profile.dimension:
        return _result(base, ROUTE_INSUFFICIENT, "feature_dimension_mismatch")
    if query.quality_score < config.minimum_query_quality:
        return _result(base, ROUTE_INSUFFICIENT, "quality_below_gate")
    if config.require_real_calibration and query.real_p_value_raw is None:
        return _result(base, ROUTE_INSUFFICIENT, "real_calibration_missing")
    if config.require_real_calibration and (
        profile.real_calibration_dataset_digest is None
        or profile.real_calibration_support_count is None
        or profile.real_calibration_support_count < config.minimum_real_calibration_support
    ):
        return _result(base, ROUTE_INSUFFICIENT, "real_calibration_support_insufficient")
    if query.real_p_value_raw is not None and query.real_profile_digest != profile.real_profile_digest:
        return _result(base, ROUTE_INSUFFICIENT, "real_profile_binding_mismatch")

    ranked = sorted(
        ((_distance(query.feature, prototype.centroid), prototype) for prototype in profile.prototypes),
        key=lambda item: (item[0], item[1].family_id),
    )
    nearest_distance, nearest = ranked[0]
    second_distance = ranked[1][0] if len(ranked) > 1 else None
    margin = None if second_distance is None else second_distance - nearest_distance
    real_consistent = None
    if query.real_p_value_raw is not None:
        real_consistent = query.real_p_value_raw > config.real_alpha
    family_supported = (
        nearest.support_count >= config.minimum_family_support
        and nearest.group_count >= config.minimum_family_group_support
        and nearest_distance <= config.maximum_family_distance
        and nearest_distance <= max(nearest.radius_raw, config.radius_floor)
    )
    second_supported = False
    if len(ranked) > 1:
        second = ranked[1][1]
        second_supported = (
            second.support_count >= config.minimum_family_support
            and second.group_count >= config.minimum_family_group_support
            and second_distance is not None
            and second_distance <= config.maximum_family_distance
            and second_distance <= max(second.radius_raw, config.radius_floor)
        )
    family_ambiguous = bool(
        family_supported
        and second_supported
        and margin is not None
        and margin < config.minimum_family_margin
    )
    if family_ambiguous:
        route, reason = ROUTE_CONFLICT_REVIEW, "family_margin_below_gate"
    elif family_supported and real_consistent is False:
        route, reason = ROUTE_KNOWN_FAMILY, "family_prototype_and_real_rejection_agree"
    elif family_supported and real_consistent is True:
        route, reason = ROUTE_CONFLICT_REVIEW, "family_and_real_only_stream_conflict"
    elif not family_supported and real_consistent is True:
        route, reason = ROUTE_REAL_CONSISTENT, "query_consistent_with_real_profile_only"
    elif not family_supported and real_consistent is False:
        route, reason = ROUTE_OPEN_SET_UNKNOWN, "real_rejected_but_no_supported_family"
    else:
        route, reason = ROUTE_INSUFFICIENT, "real_calibration_missing"
    selected_family_id = nearest.family_id if family_supported and not family_ambiguous else None
    return _result(
        {
            **base,
            "family_id": selected_family_id,
            "nearest_distance_raw": nearest_distance,
            "family_margin_raw": margin,
            "family_support_count": nearest.support_count,
            "real_p_value_raw": query.real_p_value_raw,
            "real_consistent": real_consistent,
        },
        route,
        reason,
    )


def _result(fields: Mapping[str, Any], route: str, reason: str) -> OpenSetRouteResult:
    evidence_payload = {
        "route": route,
        "reason": reason,
        "sample_id": fields["sample_id"],
        "input_digest": fields.get("input_digest"),
        "family_id": fields.get("family_id"),
        "nearest_distance_raw": fields.get("nearest_distance_raw"),
        "family_margin_raw": fields.get("family_margin_raw"),
        "family_support_count": fields.get("family_support_count", 0),
        "real_p_value_raw": fields.get("real_p_value_raw"),
        "real_consistent": fields.get("real_consistent"),
        "profile_digest": fields["profile_digest"],
        "config_digest": fields["config_digest"],
    }
    return OpenSetRouteResult(
        route=route,
        reason=reason,
        sample_id=fields["sample_id"],
        input_digest=fields.get("input_digest"),
        family_id=fields.get("family_id"),
        nearest_distance_raw=fields.get("nearest_distance_raw"),
        family_margin_raw=fields.get("family_margin_raw"),
        family_support_count=fields.get("family_support_count", 0),
        real_p_value_raw=fields.get("real_p_value_raw"),
        real_consistent=fields.get("real_consistent"),
        profile_digest=fields["profile_digest"],
        config_digest=fields["config_digest"],
        evidence_digest=_sha256(evidence_payload),
    )


__all__ = [
    "VERSION",
    "PROFILE_SCHEMA",
    "RESULT_SCHEMA",
    "FEATURE_SCHEMA",
    "ROUTE_KNOWN_FAMILY",
    "ROUTE_REAL_CONSISTENT",
    "ROUTE_OPEN_SET_UNKNOWN",
    "ROUTE_CONFLICT_REVIEW",
    "ROUTE_INSUFFICIENT",
    "OpenSetRoutingConfig",
    "GeneratorFamilyExample",
    "GeneratorPrototype",
    "GeneratorFamilyProfile",
    "OpenSetQuery",
    "OpenSetRouteResult",
    "fit_generator_family_profile",
    "evaluate_open_set_route",
]
