"""Quality-aware fusion for near-duplicate propagation evidence.

This module aggregates raw detector observations from multiple versions of the
same registered asset.  A clean original, a recompressed copy, a screenshot,
and other propagated versions may have different image quality and detector
scores.  The primitive gives higher-quality versions more influence and keeps
every version in an audit record.

The output is deliberately a raw score observation.  It does not produce an
AIGC or human-authorship state, and it does not replace calibration or the
four-state fusion policy in :mod:`aigc.fusion`.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import mean
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


NEAR_DUPLICATE_VERSION = "quality-aware-near-duplicate-v1"
NEAR_DUPLICATE_SCORE_SCHEMA = "near-duplicate-fusion-score-v1"


def _unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    return normalized


def _positive(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive finite number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0.0:
        raise ValueError(f"{name} must be a positive finite number")
    return normalized


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class NearDuplicateObservation:
    """One detector observation for one propagated asset version."""

    asset_id: str
    version_id: str
    detector_score: float
    quality_score: float
    detector_version: str = "unknown"
    score_schema: str = "raw"
    propagation_chain: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier("asset_id", self.asset_id)
        _identifier("version_id", self.version_id)
        _unit("detector_score", self.detector_score)
        _unit("quality_score", self.quality_score)
        _identifier("detector_version", self.detector_version)
        _identifier("score_schema", self.score_schema)
        if isinstance(self.propagation_chain, (str, bytes)):
            raise ValueError("propagation_chain must be a sequence of strings")
        try:
            chain = tuple(self.propagation_chain)
        except TypeError as exc:
            raise ValueError("propagation_chain must be a sequence of strings") from exc
        if any(not isinstance(item, str) or not item.strip() for item in chain):
            raise ValueError("propagation_chain entries must be non-empty strings")
        object.__setattr__(self, "asset_id", self.asset_id.strip())
        object.__setattr__(self, "version_id", self.version_id.strip())
        object.__setattr__(self, "detector_version", self.detector_version.strip())
        object.__setattr__(self, "score_schema", self.score_schema.strip())
        object.__setattr__(self, "detector_score", float(self.detector_score))
        object.__setattr__(self, "quality_score", float(self.quality_score))
        object.__setattr__(self, "propagation_chain", tuple(item.strip() for item in chain))


@dataclass(frozen=True)
class NearDuplicateAggregate:
    """Auditable raw score aggregate for one asset identity."""

    asset_id: Optional[str]
    weighted_score_raw: Optional[float]
    quality_mean: Optional[float]
    quality_min: Optional[float]
    effective_quality: Optional[float]
    score_spread_raw: Optional[float]
    quality_threshold: float
    quality_power: float
    detector_version: Optional[str]
    score_schema: Optional[str]
    accepted_version_ids: Tuple[str, ...]
    rejected_version_ids: Tuple[str, ...]
    version_audit: Tuple[Mapping[str, Any], ...]
    reason: Optional[str] = None
    schema: str = NEAR_DUPLICATE_VERSION

    def __post_init__(self) -> None:
        if self.asset_id is not None:
            _identifier("asset_id", self.asset_id)
        for name in ("weighted_score_raw", "quality_mean", "quality_min", "effective_quality", "score_spread_raw"):
            value = getattr(self, name)
            if value is not None:
                _unit(name, value)
        _unit("quality_threshold", self.quality_threshold)
        _positive("quality_power", self.quality_power)
        if self.detector_version is not None:
            _identifier("detector_version", self.detector_version)
        if self.score_schema is not None:
            _identifier("score_schema", self.score_schema)
        if not isinstance(self.accepted_version_ids, tuple) or not isinstance(self.rejected_version_ids, tuple):
            raise ValueError("version ID audit fields must be tuples")
        if any(not isinstance(item, str) or not item for item in self.accepted_version_ids + self.rejected_version_ids):
            raise ValueError("version ID audit fields must contain non-empty strings")
        if len(set(self.accepted_version_ids)) != len(self.accepted_version_ids):
            raise ValueError("accepted version IDs must be unique")
        if len(set(self.rejected_version_ids)) != len(self.rejected_version_ids):
            raise ValueError("rejected version IDs must be unique")
        if set(self.accepted_version_ids) & set(self.rejected_version_ids):
            raise ValueError("accepted and rejected version IDs must be disjoint")
        if not isinstance(self.version_audit, tuple):
            raise ValueError("version_audit must be a tuple")
        if self.reason is not None and (
            not isinstance(self.reason, str) or not self.reason.strip()
        ):
            raise ValueError("reason must be None or a non-empty string")
        if not isinstance(self.schema, str) or not self.schema.strip():
            raise ValueError("schema is required")

    @property
    def has_score(self) -> bool:
        return self.weighted_score_raw is not None

    @property
    def raw_score(self) -> Optional[float]:
        """Short alias for adapters that treat this as a raw detector score."""

        return self.weighted_score_raw

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "asset_id": self.asset_id,
            "weighted_score_raw": self.weighted_score_raw,
            "quality_mean": self.quality_mean,
            "quality_min": self.quality_min,
            "effective_quality": self.effective_quality,
            "score_spread_raw": self.score_spread_raw,
            "quality_threshold": self.quality_threshold,
            "quality_power": self.quality_power,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "accepted_version_ids": list(self.accepted_version_ids),
            "rejected_version_ids": list(self.rejected_version_ids),
            "version_audit": [dict(item) for item in self.version_audit],
            "reason": self.reason,
        }


def _empty_aggregate(
    *,
    asset_id: Optional[str],
    quality_threshold: float,
    quality_power: float,
    observations: Sequence[NearDuplicateObservation],
    reason: str,
    detector_version: Optional[str] = None,
    score_schema: Optional[str] = None,
) -> NearDuplicateAggregate:
    rejected_ids = tuple(dict.fromkeys(observation.version_id for observation in observations))
    audit = tuple(
        {
            "version_id": observation.version_id,
            "asset_id": observation.asset_id,
            "detector_score_raw": observation.detector_score,
            "quality_score": observation.quality_score,
            "weight": 0.0,
            "accepted": False,
            "rejection_reason": reason,
            "detector_version": observation.detector_version,
            "score_schema": observation.score_schema,
            "propagation_chain": list(observation.propagation_chain),
        }
        for observation in observations
    )
    return NearDuplicateAggregate(
        asset_id=asset_id,
        weighted_score_raw=None,
        quality_mean=None,
        quality_min=None,
        effective_quality=None,
        score_spread_raw=None,
        quality_threshold=quality_threshold,
        quality_power=quality_power,
        detector_version=detector_version,
        score_schema=score_schema,
        accepted_version_ids=(),
        rejected_version_ids=rejected_ids,
        version_audit=audit,
        reason=reason,
    )


def fuse_near_duplicate_scores(
    observations: Sequence[NearDuplicateObservation],
    *,
    asset_id: Optional[str] = None,
    minimum_quality: float = 0.35,
    quality_power: float = 2.0,
    detector_version: Optional[str] = None,
    score_schema: Optional[str] = None,
) -> NearDuplicateAggregate:
    """Fuse same-asset version scores with quality-derived weights.

    Versions below ``minimum_quality`` are retained in the audit but receive
    no weight.  All observations must share one asset identity and one
    detector/schema identity; mixing them returns an empty aggregate with a
    reason rather than silently averaging incomparable scores.
    """

    minimum_quality = _unit("minimum_quality", minimum_quality)
    quality_power = _positive("quality_power", quality_power)
    if asset_id is not None:
        asset_id = _identifier("asset_id", asset_id)
    if detector_version is not None:
        detector_version = _identifier("detector_version", detector_version)
    if score_schema is not None:
        score_schema = _identifier("score_schema", score_schema)
    if isinstance(observations, (str, bytes)):
        raise ValueError("observations must be a sequence")
    try:
        observations = tuple(observations)
    except TypeError as exc:
        raise ValueError("observations must be a sequence") from exc
    if any(not isinstance(item, NearDuplicateObservation) for item in observations):
        raise ValueError("observations must contain NearDuplicateObservation values")
    if not observations:
        return _empty_aggregate(
            asset_id=asset_id,
            quality_threshold=minimum_quality,
            quality_power=quality_power,
            observations=(),
            reason="no_versions",
            detector_version=detector_version,
            score_schema=score_schema,
        )

    observed_assets = {item.asset_id for item in observations}
    resolved_asset = asset_id or (next(iter(observed_assets)) if len(observed_assets) == 1 else None)
    if len(observed_assets) != 1 or (asset_id is not None and observed_assets != {asset_id}):
        return _empty_aggregate(
            asset_id=resolved_asset,
            quality_threshold=minimum_quality,
            quality_power=quality_power,
            observations=observations,
            reason="asset_identity_conflict",
            detector_version=detector_version,
            score_schema=score_schema,
        )

    version_ids = [item.version_id for item in observations]
    if len(set(version_ids)) != len(version_ids):
        return _empty_aggregate(
            asset_id=resolved_asset,
            quality_threshold=minimum_quality,
            quality_power=quality_power,
            observations=observations,
            reason="duplicate_version_id",
            detector_version=detector_version,
            score_schema=score_schema,
        )

    observed_detectors = {item.detector_version for item in observations}
    resolved_detector = detector_version or (next(iter(observed_detectors)) if len(observed_detectors) == 1 else None)
    if len(observed_detectors) != 1 or (detector_version is not None and observed_detectors != {detector_version}):
        return _empty_aggregate(
            asset_id=resolved_asset,
            quality_threshold=minimum_quality,
            quality_power=quality_power,
            observations=observations,
            reason="detector_version_conflict",
            detector_version=resolved_detector,
            score_schema=score_schema,
        )

    observed_schemas = {item.score_schema for item in observations}
    resolved_schema = score_schema or (next(iter(observed_schemas)) if len(observed_schemas) == 1 else None)
    if len(observed_schemas) != 1 or (score_schema is not None and observed_schemas != {score_schema}):
        return _empty_aggregate(
            asset_id=resolved_asset,
            quality_threshold=minimum_quality,
            quality_power=quality_power,
            observations=observations,
            reason="score_schema_conflict",
            detector_version=resolved_detector,
            score_schema=resolved_schema,
        )

    accepted = [item for item in observations if item.quality_score >= minimum_quality]
    rejected = [item for item in observations if item.quality_score < minimum_quality]
    if not accepted:
        return _empty_aggregate(
            asset_id=resolved_asset,
            quality_threshold=minimum_quality,
            quality_power=quality_power,
            observations=observations,
            reason="all_versions_below_quality_threshold",
            detector_version=resolved_detector,
            score_schema=resolved_schema,
        )

    weights = {item.version_id: item.quality_score**quality_power for item in accepted}
    total_weight = sum(weights.values())
    if total_weight <= 0.0:
        return _empty_aggregate(
            asset_id=resolved_asset,
            quality_threshold=minimum_quality,
            quality_power=quality_power,
            observations=observations,
            reason="zero_quality_weight",
            detector_version=resolved_detector,
            score_schema=resolved_schema,
        )
    weighted_score = sum(item.detector_score * weights[item.version_id] for item in accepted) / total_weight
    accepted_scores = [item.detector_score for item in accepted]
    accepted_quality = [item.quality_score for item in accepted]
    effective_quality = sum(item.quality_score * weights[item.version_id] for item in accepted) / total_weight
    audit = []
    for item in observations:
        accepted_item = item in accepted
        audit.append(
            {
                "version_id": item.version_id,
                "asset_id": item.asset_id,
                "detector_score_raw": item.detector_score,
                "quality_score": item.quality_score,
                "weight": weights.get(item.version_id, 0.0),
                "accepted": accepted_item,
                "rejection_reason": None if accepted_item else "quality_below_threshold",
                "detector_version": item.detector_version,
                "score_schema": item.score_schema,
                "propagation_chain": list(item.propagation_chain),
            }
        )
    return NearDuplicateAggregate(
        asset_id=resolved_asset,
        weighted_score_raw=weighted_score,
        quality_mean=mean(accepted_quality),
        quality_min=min(accepted_quality),
        effective_quality=effective_quality,
        score_spread_raw=max(accepted_scores) - min(accepted_scores),
        quality_threshold=minimum_quality,
        quality_power=quality_power,
        detector_version=resolved_detector,
        score_schema=resolved_schema,
        accepted_version_ids=tuple(item.version_id for item in accepted),
        rejected_version_ids=tuple(item.version_id for item in rejected),
        version_audit=tuple(audit),
        reason=None,
    )


# Descriptive aliases make the primitive discoverable without duplicating the
# implementation or creating a second score schema.
aggregate_near_duplicates = fuse_near_duplicate_scores
QualityAwareNearDuplicateAggregate = NearDuplicateAggregate
