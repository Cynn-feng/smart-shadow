"""Region-level paired counterfactual evidence.

``propagation_stability`` operates on one score per image version.  This
module keeps the same idea at the regional level: every observed region is
paired with a no-edit counterfactual region produced under the same
propagation family.  The signed raw delta is

``observed_score_raw - counterfactual_score_raw``.

Quality and source-match weights are applied only after both sides of a pair
pass their gates.  Missing pairs, transform mismatches, unstable deltas and
low coverage cause an explicit abstention.  The result is an auditable raw
observation and never an AIGC probability, authorship assertion or legal
conclusion.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


DETECTOR_VERSION = "regional-counterfactual-v1"
SCORE_SCHEMA = "regional-counterfactual-score-v1"
RESULT_VERSION = "regional-counterfactual-result-v1"


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
class RegionalObservation:
    """One regional detector score from an observed or counterfactual image.

    ``pair_id`` identifies one propagation operation.  A pair may contain
    several ``region_id`` values; therefore duplicate detection is scoped to
    ``(kind, pair_id, region_id)`` and a single image ``version_id`` may
    legitimately appear across multiple regions.
    """

    asset_id: str
    pair_id: str
    region_id: str
    version_id: str
    transform_family: str
    score_raw: float
    quality_score: float
    source_match_score: float
    kind: str = "observed"
    detector_version: str = "source-residual-v1"
    score_schema: str = "source-residual-score-v1"
    propagation_chain: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (
            ("asset_id", self.asset_id),
            ("pair_id", self.pair_id),
            ("region_id", self.region_id),
            ("version_id", self.version_id),
            ("transform_family", self.transform_family),
            ("detector_version", self.detector_version),
            ("score_schema", self.score_schema),
        ):
            _non_empty(name, value)
        _unit("score_raw", self.score_raw)
        _unit("quality_score", self.quality_score)
        _unit("source_match_score", self.source_match_score)
        if self.kind not in {"observed", "counterfactual"}:
            raise ValueError("kind must be observed or counterfactual")
        if not isinstance(self.propagation_chain, tuple) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.propagation_chain
        ):
            raise ValueError("propagation_chain must be a tuple of non-empty strings")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "region_id": self.region_id,
            "version_id": self.version_id,
            "transform_family": self.transform_family,
            "score_raw": self.score_raw,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "kind": self.kind,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "propagation_chain": list(self.propagation_chain),
        }


@dataclass(frozen=True)
class RegionalCounterfactualConfig:
    """Raw-evidence gates that must be tuned on a held-out manifest."""

    minimum_pairs: int = 2
    minimum_region_views: int = 2
    minimum_coverage: float = 0.75
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    max_delta_dispersion: float = 0.15
    max_pairwise_disagreement_rate: float = 0.50
    pairwise_delta: float = 0.25
    quality_power: float = 2.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.minimum_pairs, bool)
            or not isinstance(self.minimum_pairs, int)
            or self.minimum_pairs < 2
        ):
            raise ValueError("minimum_pairs must be an integer >= 2")
        if (
            isinstance(self.minimum_region_views, bool)
            or not isinstance(self.minimum_region_views, int)
            or self.minimum_region_views < 2
        ):
            raise ValueError("minimum_region_views must be an integer >= 2")
        for name in (
            "minimum_coverage",
            "minimum_quality",
            "minimum_source_match",
            "max_delta_dispersion",
            "max_pairwise_disagreement_rate",
            "pairwise_delta",
        ):
            _unit(name, getattr(self, name))
        _positive("quality_power", self.quality_power)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "minimum_pairs": self.minimum_pairs,
            "minimum_region_views": self.minimum_region_views,
            "minimum_coverage": self.minimum_coverage,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "max_delta_dispersion": self.max_delta_dispersion,
            "max_pairwise_disagreement_rate": self.max_pairwise_disagreement_rate,
            "pairwise_delta": self.pairwise_delta,
            "quality_power": self.quality_power,
        }

    @property
    def digest(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RegionalCounterfactualResult:
    """Auditable aggregate of paired regional raw deltas."""

    asset_id: Optional[str]
    has_score: bool
    abstained: bool
    reason: str
    weighted_delta_raw: Optional[float]
    positive_delta_raw: Optional[float]
    stability_adjusted_delta_raw: Optional[float]
    weighted_observed_score_raw: Optional[float]
    weighted_counterfactual_score_raw: Optional[float]
    coverage_raw: Optional[float]
    weighted_coverage_raw: Optional[float]
    paired_region_count: int
    observed_pair_count: int
    counterfactual_pair_count: int
    observed_region_count: int
    counterfactual_region_count: int
    region_view_coverage_raw: Optional[float]
    stable_region_count: int
    quality_score: Optional[float]
    source_match_score: Optional[float]
    delta_dispersion_raw: Optional[float]
    stability_score: Optional[float]
    pairwise_disagreement_rate: Optional[float]
    accepted_pair_keys: Tuple[str, ...]
    rejected_pair_keys: Tuple[str, ...]
    pair_audit: Tuple[Mapping[str, Any], ...]
    detector_version: Optional[str]
    score_schema: Optional[str]
    config_digest: str
    version: str = RESULT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "asset_id": self.asset_id,
            "has_score": self.has_score,
            "abstained": self.abstained,
            "reason": self.reason,
            "weighted_delta_raw": self.weighted_delta_raw,
            "positive_delta_raw": self.positive_delta_raw,
            "stability_adjusted_delta_raw": self.stability_adjusted_delta_raw,
            "weighted_observed_score_raw": self.weighted_observed_score_raw,
            "weighted_counterfactual_score_raw": self.weighted_counterfactual_score_raw,
            "coverage_raw": self.coverage_raw,
            "weighted_coverage_raw": self.weighted_coverage_raw,
            "paired_region_count": self.paired_region_count,
            "observed_pair_count": self.observed_pair_count,
            "counterfactual_pair_count": self.counterfactual_pair_count,
            "observed_region_count": self.observed_region_count,
            "counterfactual_region_count": self.counterfactual_region_count,
            "region_view_coverage_raw": self.region_view_coverage_raw,
            "stable_region_count": self.stable_region_count,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "delta_dispersion_raw": self.delta_dispersion_raw,
            "stability_score": self.stability_score,
            "pairwise_disagreement_rate": self.pairwise_disagreement_rate,
            "accepted_pair_keys": list(self.accepted_pair_keys),
            "rejected_pair_keys": list(self.rejected_pair_keys),
            "pair_audit": [dict(item) for item in self.pair_audit],
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "config_digest": self.config_digest,
        }


def _pair_key(pair_id: str, region_id: str) -> Tuple[str, str]:
    return pair_id, region_id


def _pair_key_text(key: Tuple[str, str]) -> str:
    return f"{key[0]}::{key[1]}"


def _weight(observation: RegionalObservation, config: RegionalCounterfactualConfig) -> float:
    return observation.quality_score ** config.quality_power * observation.source_match_score


def _weighted_mean(
    values: Sequence[float], weights: Sequence[float]
) -> Tuple[Optional[float], float]:
    if len(values) != len(weights) or not values:
        return None, 0.0
    total = sum(weights)
    if total <= 0.0:
        return None, 0.0
    return sum(value * weight for value, weight in zip(values, weights)) / total, total


def _empty_result(
    config: RegionalCounterfactualConfig,
    reason: str,
    asset_id: Optional[str] = None,
    *,
    detector_version: Optional[str] = None,
    score_schema: Optional[str] = None,
) -> RegionalCounterfactualResult:
    return RegionalCounterfactualResult(
        asset_id=asset_id,
        has_score=False,
        abstained=True,
        reason=reason,
        weighted_delta_raw=None,
        positive_delta_raw=None,
        stability_adjusted_delta_raw=None,
        weighted_observed_score_raw=None,
        weighted_counterfactual_score_raw=None,
        coverage_raw=None,
        weighted_coverage_raw=None,
        paired_region_count=0,
        observed_pair_count=0,
        counterfactual_pair_count=0,
        observed_region_count=0,
        counterfactual_region_count=0,
        region_view_coverage_raw=None,
        stable_region_count=0,
        quality_score=None,
        source_match_score=None,
        delta_dispersion_raw=None,
        stability_score=None,
        pairwise_disagreement_rate=None,
        accepted_pair_keys=(),
        rejected_pair_keys=(),
        pair_audit=(),
        detector_version=detector_version,
        score_schema=score_schema,
        config_digest=config.digest,
    )


def fuse_regional_counterfactual(
    observations: Iterable[RegionalObservation],
    *,
    asset_id: Optional[str] = None,
    config: Optional[RegionalCounterfactualConfig] = None,
) -> RegionalCounterfactualResult:
    """Aggregate paired regional deltas with coverage and stability gates.

    The denominator of ``coverage_raw`` is every observed region key, so a
    low-quality or missing counterfactual cannot disappear from the coverage
    calculation.  Accepted pair weights use the conservative minimum quality
    and source-match support from both sides of the pair.
    """

    cfg = config or RegionalCounterfactualConfig()
    if isinstance(observations, (str, bytes)):
        raise ValueError("observations must be an iterable of RegionalObservation")
    try:
        items = list(observations)
    except TypeError as exc:
        raise ValueError("observations must be an iterable of RegionalObservation") from exc
    if not items:
        return _empty_result(cfg, "no_observations", asset_id)
    if any(not isinstance(item, RegionalObservation) for item in items):
        raise ValueError("observations must contain RegionalObservation values")

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
    detector_version = next(iter(detector_versions))
    if len(schemas) != 1:
        return _empty_result(
            cfg,
            "score_schema_conflict",
            resolved_asset_id,
            detector_version=detector_version,
        )
    score_schema = next(iter(schemas))

    grouped: "OrderedDict[Tuple[str, str], Dict[str, RegionalObservation]]" = OrderedDict()
    duplicate_keys = set()
    for item in items:
        key = _pair_key(item.pair_id, item.region_id)
        group = grouped.setdefault(key, {})
        if item.kind in group:
            duplicate_keys.add(key)
        else:
            group[item.kind] = item
    if duplicate_keys:
        return _empty_result(
            cfg,
            "duplicate_region_observation",
            resolved_asset_id,
            detector_version=detector_version,
            score_schema=score_schema,
        )

    observed_keys = [key for key, group in grouped.items() if "observed" in group]
    counterfactual_keys = [
        key for key, group in grouped.items() if "counterfactual" in group
    ]
    observed_pair_count = len(observed_keys)
    counterfactual_pair_count = len(counterfactual_keys)
    observed_region_ids = tuple(dict.fromkeys(key[1] for key in observed_keys))
    counterfactual_region_ids = tuple(
        dict.fromkeys(key[1] for key in counterfactual_keys)
    )
    observed_region_count = len(observed_region_ids)
    counterfactual_region_count = len(counterfactual_region_ids)
    if observed_pair_count == 0:
        return _empty_result(
            cfg,
            "no_observed_regions",
            resolved_asset_id,
            detector_version=detector_version,
            score_schema=score_schema,
        )

    observed_weight_total = sum(
        _weight(grouped[key]["observed"], cfg) for key in observed_keys
    )
    audit: List[Dict[str, Any]] = []
    accepted: List[Tuple[Tuple[str, str], RegionalObservation, RegionalObservation, float, float]] = []
    rejected_keys: List[str] = []

    for key, group in grouped.items():
        observed = group.get("observed")
        counterfactual = group.get("counterfactual")
        key_text = _pair_key_text(key)
        entry: Dict[str, Any] = {
            "pair_id": key[0],
            "region_id": key[1],
            "pair_key": key_text,
            "observed_version_id": observed.version_id if observed else None,
            "counterfactual_version_id": counterfactual.version_id if counterfactual else None,
            "observed_transform_family": observed.transform_family if observed else None,
            "counterfactual_transform_family": (
                counterfactual.transform_family if counterfactual else None
            ),
            "observed_score_raw": observed.score_raw if observed else None,
            "counterfactual_score_raw": (
                counterfactual.score_raw if counterfactual else None
            ),
            "delta_raw": None,
            "quality_raw": None,
            "source_match_raw": None,
            "weight": 0.0,
            "accepted": False,
            "rejection_reason": None,
        }
        if observed is None:
            entry["rejection_reason"] = "counterfactual_without_observed"
            audit.append(entry)
            continue
        if counterfactual is None:
            entry["rejection_reason"] = "missing_counterfactual"
            rejected_keys.append(key_text)
            audit.append(entry)
            continue
        if observed.transform_family != counterfactual.transform_family:
            entry["rejection_reason"] = "transform_family_conflict"
            rejected_keys.append(key_text)
            audit.append(entry)
            continue

        delta = observed.score_raw - counterfactual.score_raw
        pair_quality = min(observed.quality_score, counterfactual.quality_score)
        pair_source_match = min(
            observed.source_match_score, counterfactual.source_match_score
        )
        pair_weight = pair_quality ** cfg.quality_power * pair_source_match
        entry.update(
            {
                "delta_raw": delta,
                "quality_raw": pair_quality,
                "source_match_raw": pair_source_match,
                "weight": pair_weight,
            }
        )
        if observed.quality_score < cfg.minimum_quality or counterfactual.quality_score < cfg.minimum_quality:
            entry["rejection_reason"] = "quality_below_threshold"
            rejected_keys.append(key_text)
            audit.append(entry)
            continue
        if observed.source_match_score < cfg.minimum_source_match or counterfactual.source_match_score < cfg.minimum_source_match:
            entry["rejection_reason"] = "source_match_below_threshold"
            rejected_keys.append(key_text)
            audit.append(entry)
            continue
        entry["accepted"] = True
        accepted.append((key, observed, counterfactual, delta, pair_weight))
        audit.append(entry)

    paired_count = len(accepted)
    coverage = paired_count / observed_pair_count
    accepted_weight = sum(item[4] for item in accepted)
    weighted_coverage = (
        accepted_weight / observed_weight_total if observed_weight_total > 0.0 else 0.0
    )

    if not accepted:
        reason = "no_usable_region_pairs"
        if coverage < cfg.minimum_coverage:
            reason = "coverage_below_threshold"
        return RegionalCounterfactualResult(
            asset_id=resolved_asset_id,
            has_score=False,
            abstained=True,
            reason=reason,
            weighted_delta_raw=None,
            positive_delta_raw=None,
            stability_adjusted_delta_raw=None,
            weighted_observed_score_raw=None,
            weighted_counterfactual_score_raw=None,
            coverage_raw=coverage,
            weighted_coverage_raw=weighted_coverage,
            paired_region_count=0,
            observed_pair_count=observed_pair_count,
            counterfactual_pair_count=counterfactual_pair_count,
            observed_region_count=observed_region_count,
            counterfactual_region_count=counterfactual_region_count,
            region_view_coverage_raw=0.0,
            stable_region_count=0,
            quality_score=None,
            source_match_score=None,
            delta_dispersion_raw=None,
            stability_score=None,
            pairwise_disagreement_rate=None,
            accepted_pair_keys=(),
            rejected_pair_keys=tuple(rejected_keys),
            pair_audit=tuple(audit),
            detector_version=detector_version,
            score_schema=score_schema,
            config_digest=cfg.digest,
        )

    deltas = [item[3] for item in accepted]
    weights = [item[4] for item in accepted]
    weighted_delta_from_pairs, total_weight = _weighted_mean(deltas, weights)
    weighted_observed, _ = _weighted_mean(
        [item[1].score_raw for item in accepted], weights
    )
    weighted_counterfactual, _ = _weighted_mean(
        [item[2].score_raw for item in accepted], weights
    )
    weighted_quality, _ = _weighted_mean(
        [min(item[1].quality_score, item[2].quality_score) for item in accepted],
        weights,
    )
    weighted_source_match, _ = _weighted_mean(
        [min(item[1].source_match_score, item[2].source_match_score) for item in accepted],
        weights,
    )
    assert weighted_delta_from_pairs is not None and weighted_observed is not None and weighted_counterfactual is not None and total_weight > 0.0
    # Derive the public delta from the same weighted aggregates so that the
    # audit identity ``observed - counterfactual == delta`` is exact up to the
    # caller's numeric representation.
    weighted_delta = weighted_observed - weighted_counterfactual
    # Stability is a propagation property.  Do not compare different spatial
    # regions against each other: an edited ROI and an unchanged ROI are
    # expected to have different deltas.  Compare views within each region,
    # then aggregate the within-region dispersion.
    region_groups: Dict[str, List[Tuple[float, float]]] = {}
    for item in accepted:
        region_groups.setdefault(item[0][1], []).append((item[3], item[4]))
    dispersion_numerator = 0.0
    for region_values in region_groups.values():
        region_mean, region_weight = _weighted_mean(
            [value for value, _ in region_values],
            [weight for _, weight in region_values],
        )
        if region_mean is None or region_weight <= 0.0:
            continue
        dispersion_numerator += sum(
            weight * abs(value - region_mean) for value, weight in region_values
        )
    dispersion = dispersion_numerator / total_weight
    if cfg.max_delta_dispersion == 0.0:
        stability = 1.0 if dispersion == 0.0 else 0.0
    else:
        stability = max(0.0, 1.0 - dispersion / cfg.max_delta_dispersion)

    pair_count = 0
    disagreement_count = 0
    for region_values in region_groups.values():
        for index, (left, _) in enumerate(region_values):
            for right, _ in region_values[index + 1:]:
                pair_count += 1
                if abs(left - right) > cfg.pairwise_delta:
                    disagreement_count += 1
    disagreement_rate = disagreement_count / pair_count if pair_count else 0.0

    positive_delta = max(0.0, weighted_delta)
    adjusted_delta = positive_delta * stability
    reason: Optional[str] = None
    if coverage < cfg.minimum_coverage:
        reason = "coverage_below_threshold"
    elif paired_count < cfg.minimum_pairs:
        reason = "insufficient_region_pairs"
    elif dispersion > cfg.max_delta_dispersion:
        reason = "delta_instability"
    elif disagreement_rate > cfg.max_pairwise_disagreement_rate:
        reason = "delta_pairwise_disagreement"

    return RegionalCounterfactualResult(
        asset_id=resolved_asset_id,
        has_score=reason is None,
        abstained=reason is not None,
        reason=reason or "stable_regional_counterfactual",
        weighted_delta_raw=weighted_delta,
        positive_delta_raw=positive_delta,
        stability_adjusted_delta_raw=adjusted_delta,
        weighted_observed_score_raw=weighted_observed,
        weighted_counterfactual_score_raw=weighted_counterfactual,
        coverage_raw=coverage,
        weighted_coverage_raw=weighted_coverage,
        paired_region_count=paired_count,
        observed_pair_count=observed_pair_count,
        counterfactual_pair_count=counterfactual_pair_count,
        observed_region_count=observed_region_count,
        counterfactual_region_count=counterfactual_region_count,
        region_view_coverage_raw=(
            len({item[0][1] for item in accepted}) / observed_region_count
            if observed_region_count > 0 else 0.0
        ),
        stable_region_count=len({item[0][1] for item in accepted}),
        quality_score=weighted_quality,
        source_match_score=weighted_source_match,
        delta_dispersion_raw=dispersion,
        stability_score=stability,
        pairwise_disagreement_rate=disagreement_rate,
        accepted_pair_keys=tuple(_pair_key_text(item[0]) for item in accepted),
        rejected_pair_keys=tuple(rejected_keys),
        pair_audit=tuple(audit),
        detector_version=detector_version,
        score_schema=score_schema,
        config_digest=cfg.digest,
    )


aggregate_regional_counterfactual = fuse_regional_counterfactual
evaluate_regional_counterfactual = fuse_regional_counterfactual


__all__ = [
    "DETECTOR_VERSION",
    "SCORE_SCHEMA",
    "RESULT_VERSION",
    "RegionalObservation",
    "RegionalCounterfactualConfig",
    "RegionalCounterfactualResult",
    "fuse_regional_counterfactual",
    "aggregate_regional_counterfactual",
    "evaluate_regional_counterfactual",
]
