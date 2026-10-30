"""Patch-coverage shape evidence for source-conditioned AIGC forensics.

This module turns regional counterfactual deltas into a conservative *shape*
observation.  It is motivated by recent work showing that detectors can rely
on a few patches, while distributed patch evidence is more stable for full
synthetic images.  In Smart Shadow the observation is used only to route a
query or describe an ROI:

* ``global_like``: positive delta is distributed across enough accepted
  regions;
* ``localized_like``: positive delta is concentrated in a small region set;
* ``ambiguous``: the evidence shape is between the two policies; and
* ``abstained``: quality, source match, metadata, or positive support is not
  sufficient.

The result is raw evidence, not an AIGC probability and not one of the
four-state AIGC conclusions.  Thresholds are protocol defaults only and must
be learned or reviewed on a frozen, independent manifest before use.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


VERSION = "patch-coverage-v2"
STATUS_GLOBAL = "global_like"
STATUS_LOCAL = "localized_like"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_ABSTAINED = "abstained"
REGION_TYPE_UNKNOWN = "unknown"


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


def _positive(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive finite number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0.0:
        raise ValueError(f"{name} must be a positive finite number")
    return normalized


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PatchDelta:
    """One aligned regional observed-minus-counterfactual raw delta."""

    region_id: str
    delta_raw: float
    quality_score: float
    source_match_score: float
    area_fraction: float = 1.0
    detector_version: str = "source-residual-v1"
    score_schema: str = "source-residual-score-v1"
    region_type: str = REGION_TYPE_UNKNOWN

    def __post_init__(self) -> None:
        _non_empty("region_id", self.region_id)
        if isinstance(self.delta_raw, bool) or not isinstance(self.delta_raw, (int, float)):
            raise ValueError("delta_raw must be a finite number")
        delta = float(self.delta_raw)
        if not math.isfinite(delta) or not -1.0 <= delta <= 1.0:
            raise ValueError("delta_raw must be finite and between -1 and 1")
        _unit("quality_score", self.quality_score)
        _unit("source_match_score", self.source_match_score)
        area = _unit("area_fraction", self.area_fraction)
        if area <= 0.0:
            raise ValueError("area_fraction must be greater than zero")
        _non_empty("detector_version", self.detector_version)
        _non_empty("score_schema", self.score_schema)
        _non_empty("region_type", self.region_type)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region_id": self.region_id,
            "delta_raw": float(self.delta_raw),
            "quality_score": float(self.quality_score),
            "source_match_score": float(self.source_match_score),
            "area_fraction": float(self.area_fraction),
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "region_type": self.region_type,
        }


@dataclass(frozen=True)
class PatchCoverageConfig:
    """Auditable gates for the evidence-shape policy."""

    delta_threshold: float = 0.15
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    minimum_patches: int = 2
    minimum_global_coverage: float = 0.60
    maximum_local_coverage: float = 0.40
    minimum_effective_patch_ratio: float = 0.50
    quality_power: float = 2.0
    require_region_type_diversity: bool = False
    minimum_global_region_types: int = 2

    def __post_init__(self) -> None:
        for name in (
            "delta_threshold",
            "minimum_quality",
            "minimum_source_match",
            "minimum_global_coverage",
            "maximum_local_coverage",
            "minimum_effective_patch_ratio",
        ):
            _unit(name, getattr(self, name))
        if self.maximum_local_coverage >= self.minimum_global_coverage:
            raise ValueError("maximum_local_coverage must be below minimum_global_coverage")
        if (
            isinstance(self.minimum_patches, bool)
            or not isinstance(self.minimum_patches, int)
            or self.minimum_patches < 2
        ):
            raise ValueError("minimum_patches must be an integer >= 2")
        _positive("quality_power", self.quality_power)
        if not isinstance(self.require_region_type_diversity, bool):
            raise ValueError("require_region_type_diversity must be a bool")
        if (
            isinstance(self.minimum_global_region_types, bool)
            or not isinstance(self.minimum_global_region_types, int)
            or self.minimum_global_region_types < 1
        ):
            raise ValueError("minimum_global_region_types must be an integer >= 1")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "delta_threshold": self.delta_threshold,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "minimum_patches": self.minimum_patches,
            "minimum_global_coverage": self.minimum_global_coverage,
            "maximum_local_coverage": self.maximum_local_coverage,
            "minimum_effective_patch_ratio": self.minimum_effective_patch_ratio,
            "quality_power": self.quality_power,
            "require_region_type_diversity": self.require_region_type_diversity,
            "minimum_global_region_types": self.minimum_global_region_types,
        }

    @property
    def digest(self) -> str:
        return _digest({"version": VERSION, "config": self.to_dict()})


@dataclass(frozen=True)
class PatchCoverageResult:
    """Auditable shape evidence and routing hint."""

    status: str
    abstained: bool
    reason: str
    positive_region_ids: Tuple[str, ...]
    rejected_region_ids: Tuple[str, ...]
    accepted_patch_count: int
    positive_patch_count: int
    coverage_raw: Optional[float]
    effective_patch_ratio_raw: Optional[float]
    concentration_raw: Optional[float]
    positive_mass_raw: Optional[float]
    weighted_quality_raw: Optional[float]
    route: str
    detector_version: Optional[str]
    score_schema: Optional[str]
    config_digest: str
    evidence_digest: str
    version: str = VERSION
    positive_region_types: Tuple[str, ...] = ()
    coverage_by_region_type: Tuple[Tuple[str, float], ...] = ()
    balanced_coverage_raw: Optional[float] = None
    active_region_type_count: int = 0
    region_type_count: int = 0

    def __post_init__(self) -> None:
        if self.status not in {STATUS_GLOBAL, STATUS_LOCAL, STATUS_AMBIGUOUS, STATUS_ABSTAINED}:
            raise ValueError("invalid patch coverage status")
        if not isinstance(self.abstained, bool):
            raise ValueError("abstained must be a bool")
        if self.status == STATUS_ABSTAINED and not self.abstained:
            raise ValueError("abstained status must set abstained=true")
        if self.status != STATUS_ABSTAINED and self.abstained and self.status != STATUS_AMBIGUOUS:
            raise ValueError("global/local status cannot be abstained")
        _non_empty("reason", self.reason)
        if self.accepted_patch_count < 0 or self.positive_patch_count < 0:
            raise ValueError("patch counts must be non-negative")
        if self.positive_patch_count > self.accepted_patch_count:
            raise ValueError("positive patch count cannot exceed accepted count")
        if self.active_region_type_count < 0 or self.region_type_count < 0:
            raise ValueError("region type counts must be non-negative")
        if self.active_region_type_count > self.region_type_count:
            raise ValueError("active region type count cannot exceed region type count")
        for name, value in (
            ("coverage_raw", self.coverage_raw),
            ("effective_patch_ratio_raw", self.effective_patch_ratio_raw),
            ("concentration_raw", self.concentration_raw),
            ("positive_mass_raw", self.positive_mass_raw),
            ("weighted_quality_raw", self.weighted_quality_raw),
        ):
            if value is not None:
                _unit(name, value)
        for region_type, coverage in self.coverage_by_region_type:
            _non_empty("region_type", region_type)
            _unit("coverage_by_region_type", coverage)
        if self.balanced_coverage_raw is not None:
            _unit("balanced_coverage_raw", self.balanced_coverage_raw)
        _non_empty("route", self.route)
        _digest_hex("config_digest", self.config_digest)
        _digest_hex("evidence_digest", self.evidence_digest)
        if self.detector_version is not None:
            _non_empty("detector_version", self.detector_version)
        if self.score_schema is not None:
            _non_empty("score_schema", self.score_schema)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "abstained": self.abstained,
            "reason": self.reason,
            "positive_region_ids": list(self.positive_region_ids),
            "rejected_region_ids": list(self.rejected_region_ids),
            "accepted_patch_count": self.accepted_patch_count,
            "positive_patch_count": self.positive_patch_count,
            "coverage_raw": self.coverage_raw,
            "effective_patch_ratio_raw": self.effective_patch_ratio_raw,
            "concentration_raw": self.concentration_raw,
            "positive_mass_raw": self.positive_mass_raw,
            "weighted_quality_raw": self.weighted_quality_raw,
            "route": self.route,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "config_digest": self.config_digest,
            "evidence_digest": self.evidence_digest,
            "positive_region_types": list(self.positive_region_types),
            "coverage_by_region_type": {
                region_type: coverage for region_type, coverage in self.coverage_by_region_type
            },
            "balanced_coverage_raw": self.balanced_coverage_raw,
            "active_region_type_count": self.active_region_type_count,
            "region_type_count": self.region_type_count,
        }


def _digest_hex(name: str, value: str) -> str:
    _non_empty(name, value)
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
    return value.lower()


def _empty_result(
    config: PatchCoverageConfig,
    *,
    reason: str,
    rejected: Sequence[str] = (),
    detector_version: Optional[str] = None,
    score_schema: Optional[str] = None,
    evidence_digest: Optional[str] = None,
) -> PatchCoverageResult:
    return PatchCoverageResult(
        status=STATUS_ABSTAINED,
        abstained=True,
        reason=reason,
        positive_region_ids=(),
        rejected_region_ids=tuple(rejected),
        accepted_patch_count=0,
        positive_patch_count=0,
        coverage_raw=None,
        effective_patch_ratio_raw=None,
        concentration_raw=None,
        positive_mass_raw=None,
        weighted_quality_raw=None,
        route="manual_review",
        detector_version=detector_version,
        score_schema=score_schema,
        config_digest=config.digest,
        evidence_digest=evidence_digest or _digest({"version": VERSION, "reason": reason}),
    )


def summarize_patch_coverage(
    patches: Iterable[PatchDelta],
    *,
    config: Optional[PatchCoverageConfig] = None,
) -> PatchCoverageResult:
    """Summarize patch evidence without producing a semantic AIGC label."""

    cfg = config or PatchCoverageConfig()
    if isinstance(patches, (str, bytes)):
        raise ValueError("patches must be an iterable of PatchDelta")
    try:
        items = list(patches)
    except TypeError as exc:
        raise ValueError("patches must be an iterable of PatchDelta") from exc
    if not items or any(not isinstance(item, PatchDelta) for item in items):
        raise ValueError("patches must contain at least one PatchDelta")
    if len({item.region_id for item in items}) != len(items):
        raise ValueError("region_id values must be unique")
    detectors = {item.detector_version for item in items}
    schemas = {item.score_schema for item in items}
    if len(detectors) != 1 or len(schemas) != 1:
        raise ValueError("all patches must use one detector_version and score_schema")
    detector_version = next(iter(detectors))
    score_schema = next(iter(schemas))
    evidence_digest = _digest(
        {"version": VERSION, "patches": [item.to_dict() for item in sorted(items, key=lambda x: x.region_id)]}
    )
    accepted: List[PatchDelta] = []
    rejected: List[str] = []
    rejection_reasons: List[str] = []
    for item in items:
        if item.quality_score < cfg.minimum_quality:
            rejected.append(item.region_id)
            rejection_reasons.append("quality_below_threshold")
        elif item.source_match_score < cfg.minimum_source_match:
            rejected.append(item.region_id)
            rejection_reasons.append("source_match_below_threshold")
        else:
            accepted.append(item)
    accepted.sort(key=lambda item: item.region_id)
    rejected.sort()
    if len(accepted) < cfg.minimum_patches:
        reason = "insufficient_accepted_patches"
        if rejection_reasons and len(set(rejection_reasons)) == 1:
            reason = rejection_reasons[0]
        return _empty_result(
            cfg,
            reason=reason,
            rejected=rejected,
            detector_version=detector_version,
            score_schema=score_schema,
            evidence_digest=evidence_digest,
        )
    weights = [item.quality_score ** cfg.quality_power * item.source_match_score * item.area_fraction for item in accepted]
    total_weight = sum(weights)
    if total_weight <= 0.0:
        return _empty_result(
            cfg,
            reason="zero_evidence_weight",
            rejected=rejected,
            detector_version=detector_version,
            score_schema=score_schema,
            evidence_digest=evidence_digest,
        )
    positive = [max(0.0, float(item.delta_raw)) for item in accepted]
    active = [value >= cfg.delta_threshold for value in positive]
    active_weight = sum(weight for weight, is_active in zip(weights, active) if is_active)
    coverage = active_weight / total_weight
    type_total_weight: Dict[str, float] = {}
    type_active_weight: Dict[str, float] = {}
    for item, weight, is_active in zip(accepted, weights, active):
        type_total_weight[item.region_type] = type_total_weight.get(item.region_type, 0.0) + weight
        if is_active:
            type_active_weight[item.region_type] = type_active_weight.get(item.region_type, 0.0) + weight
    coverage_by_type = tuple(
        (region_type, type_active_weight.get(region_type, 0.0) / type_total_weight[region_type])
        for region_type in sorted(type_total_weight)
    )
    balanced_coverage = sum(value for _, value in coverage_by_type) / len(coverage_by_type)
    active_region_types = tuple(sorted(type_active_weight))
    mass = [weight * max(0.0, value - cfg.delta_threshold) for weight, value in zip(weights, positive)]
    positive_mass = sum(weight * value for weight, value in zip(weights, positive)) / total_weight
    mass_total = sum(mass)
    if mass_total > 0.0:
        probabilities = [value / mass_total for value in mass if value > 0.0]
        entropy = -sum(value * math.log(value) for value in probabilities)
        effective_ratio = math.exp(entropy) / len(accepted)
        concentration = max(probabilities)
    else:
        effective_ratio = 0.0
        concentration = 0.0
    weighted_quality = sum(weight * item.quality_score for weight, item in zip(weights, accepted)) / total_weight
    positive_ids = tuple(item.region_id for item, is_active in zip(accepted, active) if is_active)
    if not positive_ids:
        status, abstained, reason, route = STATUS_ABSTAINED, True, "no_positive_delta", "manual_review"
    elif coverage >= cfg.minimum_global_coverage and effective_ratio >= cfg.minimum_effective_patch_ratio:
        if cfg.require_region_type_diversity and (
            REGION_TYPE_UNKNOWN in type_total_weight
            or len(active_region_types) < cfg.minimum_global_region_types
        ):
            status, abstained, reason, route = (
                STATUS_AMBIGUOUS,
                True,
                "insufficient_region_type_support",
                "manual_review",
            )
        else:
            status, abstained, reason, route = STATUS_GLOBAL, False, "distributed_positive_delta", "global_forensic_review"
    elif coverage <= cfg.maximum_local_coverage:
        status, abstained, reason, route = STATUS_LOCAL, False, "concentrated_positive_delta", "local_roi_review"
    else:
        status, abstained, reason, route = STATUS_AMBIGUOUS, True, "mixed_patch_coverage", "manual_review"
    return PatchCoverageResult(
        status=status,
        abstained=abstained,
        reason=reason,
        positive_region_ids=positive_ids,
        rejected_region_ids=tuple(rejected),
        accepted_patch_count=len(accepted),
        positive_patch_count=len(positive_ids),
        coverage_raw=coverage,
        effective_patch_ratio_raw=effective_ratio,
        concentration_raw=concentration,
        positive_mass_raw=positive_mass,
        weighted_quality_raw=weighted_quality,
        route=route,
        detector_version=detector_version,
        score_schema=score_schema,
        config_digest=cfg.digest,
        evidence_digest=evidence_digest,
        positive_region_types=active_region_types,
        coverage_by_region_type=coverage_by_type,
        balanced_coverage_raw=balanced_coverage,
        active_region_type_count=len(active_region_types),
        region_type_count=len(type_total_weight),
    )


__all__ = [
    "VERSION",
    "STATUS_GLOBAL",
    "STATUS_LOCAL",
    "STATUS_AMBIGUOUS",
    "STATUS_ABSTAINED",
    "REGION_TYPE_UNKNOWN",
    "PatchDelta",
    "PatchCoverageConfig",
    "PatchCoverageResult",
    "summarize_patch_coverage",
]
