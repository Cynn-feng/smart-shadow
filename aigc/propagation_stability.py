"""Paired propagation consistency and abstention evidence.

The existing ``near_duplicate`` helper combines scores from versions of one
asset.  This module adds a different guard: a source-conditioned detector is
only allowed to expose a stable raw edit score when the score survives the
same propagation family *and* the paired no-edit counterfactual does not
activate the detector.  The counterfactual is an observation produced from
the registered source and query after the same nuisance transform (for
example, resize or JPEG re-encoding) with no local edit introduced.

This is deliberately a detector/evaluation primitive.  It does not read
images, estimate a probability, or produce an AIGC/legal conclusion.  The
caller must preserve the source/query construction and transform manifest so
that ``kind=counterfactual`` is auditable rather than a hidden label.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import hashlib
import json
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


DETECTOR_VERSION = "propagation-stability-v1"
SCORE_SCHEMA = "propagation-stability-score-v1"


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


def _positive(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive finite number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0.0:
        raise ValueError(f"{name} must be a positive finite number")
    return normalized


def _non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class PropagationObservation:
    """One score emitted for a propagation variant.

    ``kind=observed`` is the query image that may contain a local edit.
    ``kind=counterfactual`` is the paired no-edit nuisance transform.  A
    transform family (rather than an arbitrary free-text note) is retained so
    the evaluator can require family-level paired coverage.
    """

    asset_id: str
    version_id: str
    score_raw: float
    quality_score: float
    source_match_score: float
    transform_family: str
    detector_version: str = "source-residual-v1"
    score_schema: str = "source-residual-score-v1"
    kind: str = "observed"
    roi_fraction: Optional[float] = None
    propagation_chain: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _non_empty("asset_id", self.asset_id)
        _non_empty("version_id", self.version_id)
        _unit("score_raw", self.score_raw)
        _unit("quality_score", self.quality_score)
        _unit("source_match_score", self.source_match_score)
        _non_empty("transform_family", self.transform_family)
        _non_empty("detector_version", self.detector_version)
        _non_empty("score_schema", self.score_schema)
        if self.kind not in {"observed", "counterfactual"}:
            raise ValueError("kind must be observed or counterfactual")
        if self.roi_fraction is not None:
            _unit("roi_fraction", self.roi_fraction)
        if not isinstance(self.propagation_chain, tuple) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.propagation_chain
        ):
            raise ValueError("propagation_chain must be a tuple of non-empty strings")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "version_id": self.version_id,
            "score_raw": self.score_raw,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "transform_family": self.transform_family,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "kind": self.kind,
            "roi_fraction": self.roi_fraction,
            "propagation_chain": list(self.propagation_chain),
        }


@dataclass(frozen=True)
class StabilityConfig:
    """Raw-evidence gates; values require validation on held-out data."""

    minimum_views: int = 2
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    max_observed_dispersion: float = 0.15
    max_counterfactual_p95: float = 0.35
    max_pairwise_disagreement_rate: float = 0.50
    pairwise_delta: float = 0.25
    quality_power: float = 2.0
    require_counterfactual: bool = True
    require_paired_transform_families: bool = True

    def __post_init__(self) -> None:
        if (
            isinstance(self.minimum_views, bool)
            or not isinstance(self.minimum_views, int)
            or self.minimum_views < 2
        ):
            raise ValueError("minimum_views must be an integer >= 2")
        for name in (
            "minimum_quality",
            "minimum_source_match",
            "max_observed_dispersion",
            "max_counterfactual_p95",
            "max_pairwise_disagreement_rate",
            "pairwise_delta",
        ):
            _unit(name, getattr(self, name))
        _positive("quality_power", self.quality_power)
        if not isinstance(self.require_counterfactual, bool):
            raise ValueError("require_counterfactual must be a bool")
        if not isinstance(self.require_paired_transform_families, bool):
            raise ValueError("require_paired_transform_families must be a bool")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "minimum_views": self.minimum_views,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "max_observed_dispersion": self.max_observed_dispersion,
            "max_counterfactual_p95": self.max_counterfactual_p95,
            "max_pairwise_disagreement_rate": self.max_pairwise_disagreement_rate,
            "pairwise_delta": self.pairwise_delta,
            "quality_power": self.quality_power,
            "require_counterfactual": self.require_counterfactual,
            "require_paired_transform_families": self.require_paired_transform_families,
        }

    @property
    def digest(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PropagationStabilityResult:
    """Auditable paired-stability result.

    ``has_score`` means the gates passed and ``stability_adjusted_raw`` can
    be consumed by a later calibrated layer.  ``weighted_score_raw`` may be
    present even when ``abstained`` is true; that value is retained solely to
    explain why the gate rejected the sample.
    """

    asset_id: Optional[str]
    has_score: bool
    abstained: bool
    reason: str
    weighted_score_raw: Optional[float]
    counterfactual_p95_raw: Optional[float]
    adjusted_score_raw: Optional[float]
    stability_adjusted_raw: Optional[float]
    observed_dispersion_raw: Optional[float]
    consistency_score: Optional[float]
    pairwise_disagreement_rate: Optional[float]
    counterfactual_margin_raw: Optional[float]
    effective_quality: Optional[float]
    observed_version_ids: Tuple[str, ...]
    accepted_version_ids: Tuple[str, ...]
    rejected_version_ids: Tuple[str, ...]
    counterfactual_version_ids: Tuple[str, ...]
    version_audit: Tuple[Dict[str, Any], ...]
    detector_version: Optional[str]
    score_schema: Optional[str]
    config_digest: str
    version: str = "propagation-stability-result-v1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "asset_id": self.asset_id,
            "has_score": self.has_score,
            "abstained": self.abstained,
            "reason": self.reason,
            "weighted_score_raw": self.weighted_score_raw,
            "counterfactual_p95_raw": self.counterfactual_p95_raw,
            "adjusted_score_raw": self.adjusted_score_raw,
            "stability_adjusted_raw": self.stability_adjusted_raw,
            "observed_dispersion_raw": self.observed_dispersion_raw,
            "consistency_score": self.consistency_score,
            "pairwise_disagreement_rate": self.pairwise_disagreement_rate,
            "counterfactual_margin_raw": self.counterfactual_margin_raw,
            "effective_quality": self.effective_quality,
            "observed_version_ids": list(self.observed_version_ids),
            "accepted_version_ids": list(self.accepted_version_ids),
            "rejected_version_ids": list(self.rejected_version_ids),
            "counterfactual_version_ids": list(self.counterfactual_version_ids),
            "version_audit": [dict(item) for item in self.version_audit],
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "config_digest": self.config_digest,
        }


def _weight(observation: PropagationObservation, config: StabilityConfig) -> float:
    return observation.quality_score ** config.quality_power * observation.source_match_score


def _weighted_mean(
    observations: Sequence[PropagationObservation], config: StabilityConfig
) -> Tuple[Optional[float], float]:
    weights = [_weight(item, config) for item in observations]
    total = sum(weights)
    if total <= 0.0:
        return None, 0.0
    return sum(item.score_raw * weight for item, weight in zip(observations, weights)) / total, total


def _weighted_quantile(
    observations: Sequence[PropagationObservation],
    weights: Sequence[float],
    quantile: float,
) -> Optional[float]:
    if not observations or len(observations) != len(weights):
        return None
    pairs = sorted(zip(observations, weights), key=lambda pair: pair[0].score_raw)
    total = sum(weight for _, weight in pairs)
    if total <= 0.0:
        return None
    target = total * quantile
    cumulative = 0.0
    for observation, weight in pairs:
        cumulative += weight
        if cumulative >= target:
            return observation.score_raw
    return pairs[-1][0].score_raw


def _empty_result(config: StabilityConfig, reason: str, asset_id: Optional[str] = None, *,
                  detector_version: Optional[str] = None,
                  score_schema: Optional[str] = None) -> PropagationStabilityResult:
    return PropagationStabilityResult(
        asset_id=asset_id,
        has_score=False,
        abstained=True,
        reason=reason,
        weighted_score_raw=None,
        counterfactual_p95_raw=None,
        adjusted_score_raw=None,
        stability_adjusted_raw=None,
        observed_dispersion_raw=None,
        consistency_score=None,
        pairwise_disagreement_rate=None,
        counterfactual_margin_raw=None,
        effective_quality=None,
        observed_version_ids=(),
        accepted_version_ids=(),
        rejected_version_ids=(),
        counterfactual_version_ids=(),
        version_audit=(),
        detector_version=detector_version,
        score_schema=score_schema,
        config_digest=config.digest,
    )


def fuse_propagation_stability(
    observations: Iterable[PropagationObservation],
    *,
    asset_id: Optional[str] = None,
    config: Optional[StabilityConfig] = None,
) -> PropagationStabilityResult:
    """Fuse paired propagation observations and abstain on instability.

    Observed scores are quality/source-match weighted.  A weighted p95 of
    no-edit counterfactual scores is subtracted from the observed consensus,
    then multiplied by a consistency factor derived from observed dispersion.
    The result is accepted only when all configured gates pass.  This is a
    conservative raw evidence layer: no threshold here is a probability or
    an AIGC verdict.
    """

    cfg = config or StabilityConfig()
    if isinstance(observations, (str, bytes)):
        raise ValueError("observations must be an iterable of PropagationObservation")
    try:
        items = list(observations)
    except TypeError as exc:
        raise ValueError("observations must be an iterable of PropagationObservation") from exc
    if not items:
        return _empty_result(cfg, "no_observations", asset_id)
    if any(not isinstance(item, PropagationObservation) for item in items):
        raise ValueError("observations must contain PropagationObservation values")

    identities = {item.asset_id for item in items}
    if asset_id is not None:
        _non_empty("asset_id", asset_id)
        if identities != {asset_id}:
            return _empty_result(cfg, "asset_identity_conflict", asset_id)
    elif len(identities) != 1:
        return _empty_result(cfg, "asset_identity_conflict")
    resolved_asset_id = asset_id or next(iter(identities))

    detector_versions = {item.detector_version for item in items}
    schemas = {item.score_schema for item in items}
    if len(detector_versions) != 1:
        return _empty_result(cfg, "detector_version_conflict", resolved_asset_id)
    if len(schemas) != 1:
        return _empty_result(cfg, "score_schema_conflict", resolved_asset_id,
                             detector_version=next(iter(detector_versions)))
    detector_version = next(iter(detector_versions))
    score_schema = next(iter(schemas))

    version_ids = [item.version_id for item in items]
    if len(set(version_ids)) != len(version_ids):
        return _empty_result(cfg, "duplicate_version_id", resolved_asset_id,
                             detector_version=detector_version, score_schema=score_schema)

    observed = [item for item in items if item.kind == "observed"]
    counterfactual = [item for item in items if item.kind == "counterfactual"]
    observed_ids = tuple(item.version_id for item in observed)
    counterfactual_ids = tuple(item.version_id for item in counterfactual)

    accepted_observed: List[PropagationObservation] = []
    accepted_counterfactual: List[PropagationObservation] = []
    audit: List[Dict[str, Any]] = []
    accepted_ids = []
    rejected_ids = []

    def accept(item: PropagationObservation) -> bool:
        return (
            item.quality_score >= cfg.minimum_quality
            and item.source_match_score >= cfg.minimum_source_match
        )

    for item in items:
        accepted = accept(item)
        rejection_reason = None
        if not accepted:
            if item.quality_score < cfg.minimum_quality:
                rejection_reason = "quality_below_threshold"
            else:
                rejection_reason = "source_match_below_threshold"
        if accepted:
            if item.kind == "observed":
                accepted_observed.append(item)
                accepted_ids.append(item.version_id)
            else:
                accepted_counterfactual.append(item)
        elif item.kind == "observed":
            rejected_ids.append(item.version_id)
        audit.append({
            "version_id": item.version_id,
            "kind": item.kind,
            "transform_family": item.transform_family,
            "score_raw": item.score_raw,
            "quality_score": item.quality_score,
            "source_match_score": item.source_match_score,
            "accepted": accepted,
            "rejection_reason": rejection_reason,
            "propagation_chain": list(item.propagation_chain),
        })

    observed_mean, observed_weight = _weighted_mean(accepted_observed, cfg)
    if observed_mean is None or len(accepted_observed) < cfg.minimum_views:
        reason = "insufficient_stable_views" if accepted_observed else "no_usable_observed_views"
        return PropagationStabilityResult(
            asset_id=resolved_asset_id, has_score=False, abstained=True, reason=reason,
            weighted_score_raw=observed_mean, counterfactual_p95_raw=None,
            adjusted_score_raw=None, stability_adjusted_raw=None,
            observed_dispersion_raw=None, consistency_score=None,
            pairwise_disagreement_rate=None, counterfactual_margin_raw=None,
            effective_quality=None, observed_version_ids=observed_ids,
            accepted_version_ids=tuple(accepted_ids), rejected_version_ids=tuple(rejected_ids),
            counterfactual_version_ids=counterfactual_ids, version_audit=tuple(audit),
            detector_version=detector_version, score_schema=score_schema,
            config_digest=cfg.digest,
        )

    observed_weights = [_weight(item, cfg) for item in accepted_observed]
    total_observed_weight = sum(observed_weights)
    dispersion = sum(
        weight * abs(item.score_raw - observed_mean)
        for item, weight in zip(accepted_observed, observed_weights)
    ) / total_observed_weight
    if cfg.max_observed_dispersion == 0.0:
        consistency = 1.0 if dispersion == 0.0 else 0.0
    else:
        consistency = max(0.0, 1.0 - dispersion / cfg.max_observed_dispersion)

    pair_count = 0
    disagreement_count = 0
    for index, left in enumerate(accepted_observed):
        for right in accepted_observed[index + 1:]:
            pair_count += 1
            if abs(left.score_raw - right.score_raw) > cfg.pairwise_delta:
                disagreement_count += 1
    disagreement_rate = disagreement_count / pair_count if pair_count else 0.0

    cf_p95 = None
    if accepted_counterfactual:
        cf_weights = [_weight(item, cfg) for item in accepted_counterfactual]
        cf_p95 = _weighted_quantile(accepted_counterfactual, cf_weights, 0.95)
    margin = None if cf_p95 is None else observed_mean - cf_p95
    adjusted = None if cf_p95 is None else max(0.0, margin)
    stability_adjusted = None if adjusted is None else adjusted * consistency
    effective_quality = sum(
        item.quality_score * weight for item, weight in zip(accepted_observed, observed_weights)
    ) / total_observed_weight

    reason: Optional[str] = None
    if dispersion > cfg.max_observed_dispersion:
        reason = "propagation_score_instability"
    elif disagreement_rate > cfg.max_pairwise_disagreement_rate:
        reason = "propagation_pairwise_disagreement"
    elif cfg.require_counterfactual and not accepted_counterfactual:
        reason = "missing_counterfactual_baseline"
    elif accepted_counterfactual and cfg.require_paired_transform_families:
        observed_families = Counter(item.transform_family for item in accepted_observed)
        counterfactual_families = Counter(
            item.transform_family for item in accepted_counterfactual
        )
        # A family-level set match is insufficient when several observed
        # variants use the same family with different parameters.  Require at
        # least as many independent counterfactual observations per family so
        # the nuisance baseline cannot be silently under-covered.
        if any(
            counterfactual_families[family] < count
            for family, count in observed_families.items()
        ):
            reason = "counterfactual_coverage_gap"
    if reason is None and cf_p95 is not None and cf_p95 > cfg.max_counterfactual_p95:
        reason = "counterfactual_high_score"
    if reason is None and not cfg.require_counterfactual and cf_p95 is None:
        # A caller can explicitly opt out of the hard-negative gate, but the
        # result remains labelled as an unpaired raw observation.
        reason = "unpaired_stability_observation"

    return PropagationStabilityResult(
        asset_id=resolved_asset_id,
        has_score=reason is None and stability_adjusted is not None,
        abstained=reason is not None or stability_adjusted is None,
        reason=reason or "stable_with_counterfactual_baseline",
        weighted_score_raw=observed_mean,
        counterfactual_p95_raw=cf_p95,
        adjusted_score_raw=adjusted,
        stability_adjusted_raw=stability_adjusted,
        observed_dispersion_raw=dispersion,
        consistency_score=consistency,
        pairwise_disagreement_rate=disagreement_rate,
        counterfactual_margin_raw=margin,
        effective_quality=effective_quality,
        observed_version_ids=observed_ids,
        accepted_version_ids=tuple(accepted_ids),
        rejected_version_ids=tuple(rejected_ids),
        counterfactual_version_ids=counterfactual_ids,
        version_audit=tuple(audit),
        detector_version=detector_version,
        score_schema=score_schema,
        config_digest=cfg.digest,
    )


evaluate_propagation_stability = fuse_propagation_stability


__all__ = [
    "DETECTOR_VERSION",
    "SCORE_SCHEMA",
    "PropagationObservation",
    "StabilityConfig",
    "PropagationStabilityResult",
    "fuse_propagation_stability",
    "evaluate_propagation_stability",
]
