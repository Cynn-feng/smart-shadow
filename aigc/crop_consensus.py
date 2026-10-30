"""Source-conditioned crop-consensus evidence.

The paired PC-SCFT protocol evaluates one observed/counterfactual view.  This
module evaluates several crop views of that *same* pair in a shared canonical
coordinate frame.  It records whether a regional delta survives view changes
and compares a conservative consensus statistic with matched
ordinary-propagation crop-null samples.

The implementation is a raw-evidence contract.  It does not infer an AIGC
probability, authorship, provenance, or a legal conclusion.  Missing views,
incompatible bindings, weak quality/source match, and insufficient null
support fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from bisect import bisect_right
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


VERSION = "source-conditioned-crop-consensus-v1"
SCHEMA = "crop-consensus-evidence-v1"

ROUTE_CONSENSUS_CANDIDATE = "consensus_candidate"
ROUTE_NULL_CONSISTENT = "null_consistent"
ROUTE_VIEW_INCONSISTENT = "view_inconsistent"
ROUTE_INSUFFICIENT = "insufficient"


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _digest_hex(name: str, value: str) -> str:
    value = _text(name, value).lower()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return value


def _finite(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _unit(name: str, value: float) -> float:
    value = _finite(name, value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


def _signed_unit(name: str, value: float) -> float:
    value = _finite(name, value)
    if not -1.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between -1 and 1")
    return value


def _positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _bins(name: str, values: Sequence[float]) -> Tuple[float, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    try:
        result = tuple(float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain finite numbers") from exc
    if any(not math.isfinite(value) or not 0.0 < value < 1.0 for value in result):
        raise ValueError(f"{name} must be strictly between 0 and 1")
    if tuple(sorted(set(result))) != result:
        raise ValueError(f"{name} must be strictly increasing")
    return result


def _quality_bucket(score: float, bins: Sequence[float]) -> str:
    return f"q{bisect_right(bins, score)}"


@dataclass(frozen=True)
class CropConsensusConfig:
    minimum_view_count: int = 3
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    positive_delta_threshold: float = 0.20
    minimum_positive_view_fraction: float = 0.67
    minimum_region_availability: float = 0.67
    minimum_view_set_overlap: float = 0.50
    minimum_null_count: int = 20
    alpha: float = 0.05
    quality_bins: Tuple[float, ...] = (0.35, 0.60, 0.80)

    def __post_init__(self) -> None:
        _positive_int("minimum_view_count", self.minimum_view_count)
        object.__setattr__(self, "minimum_quality", _unit("minimum_quality", self.minimum_quality))
        object.__setattr__(self, "minimum_source_match", _unit("minimum_source_match", self.minimum_source_match))
        object.__setattr__(self, "positive_delta_threshold", _unit("positive_delta_threshold", self.positive_delta_threshold))
        object.__setattr__(self, "minimum_positive_view_fraction", _unit("minimum_positive_view_fraction", self.minimum_positive_view_fraction))
        object.__setattr__(self, "minimum_region_availability", _unit("minimum_region_availability", self.minimum_region_availability))
        object.__setattr__(self, "minimum_view_set_overlap", _unit("minimum_view_set_overlap", self.minimum_view_set_overlap))
        _positive_int("minimum_null_count", self.minimum_null_count)
        object.__setattr__(self, "quality_bins", _bins("quality_bins", self.quality_bins))
        alpha = _unit("alpha", self.alpha)
        if alpha <= 0.0 or alpha >= 1.0:
            raise ValueError("alpha must be strictly between 0 and 1")
        object.__setattr__(self, "alpha", alpha)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "minimum_view_count": self.minimum_view_count,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "positive_delta_threshold": self.positive_delta_threshold,
            "minimum_positive_view_fraction": self.minimum_positive_view_fraction,
            "minimum_region_availability": self.minimum_region_availability,
            "minimum_view_set_overlap": self.minimum_view_set_overlap,
            "minimum_null_count": self.minimum_null_count,
            "alpha": self.alpha,
            "quality_bins": list(self.quality_bins),
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class CropView:
    """One paired observed/counterfactual crop in canonical coordinates."""

    view_id: str
    consensus_id: str
    asset_id: str
    pair_id: str
    manifest_digest: str
    canonical_frame_digest: str
    crop_spec_digest: str
    transform_family: str
    detector_version: str
    score_schema: str
    quality_score: float
    source_match_score: float
    delta_by_region: Mapping[str, float]

    def __post_init__(self) -> None:
        for name in (
            "view_id", "consensus_id", "asset_id", "pair_id", "transform_family",
            "detector_version", "score_schema",
        ):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        for name in ("manifest_digest", "canonical_frame_digest", "crop_spec_digest"):
            object.__setattr__(self, name, _digest_hex(name, getattr(self, name)))
        object.__setattr__(self, "quality_score", _unit("quality_score", self.quality_score))
        object.__setattr__(self, "source_match_score", _unit("source_match_score", self.source_match_score))
        if not isinstance(self.delta_by_region, Mapping) or not self.delta_by_region:
            raise ValueError("delta_by_region must be a non-empty mapping")
        normalized: Dict[str, float] = {}
        for region_id, value in self.delta_by_region.items():
            key = _text("region_id", region_id)
            normalized[key] = _signed_unit(f"delta_by_region[{key}]", value)
        if len(normalized) != len(self.delta_by_region):
            raise ValueError("delta_by_region contains duplicate normalized region IDs")
        object.__setattr__(self, "delta_by_region", dict(sorted(normalized.items())))

    @property
    def weight(self) -> float:
        # Both factors are retained and this deterministic product is auditable;
        # it is not a calibrated confidence or probability.
        return self.quality_score * self.source_match_score

    def positive_regions_at(self, threshold: float) -> Tuple[str, ...]:
        return tuple(sorted(region for region, value in self.delta_by_region.items() if value >= threshold))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "view_id": self.view_id,
            "consensus_id": self.consensus_id,
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "manifest_digest": self.manifest_digest,
            "canonical_frame_digest": self.canonical_frame_digest,
            "crop_spec_digest": self.crop_spec_digest,
            "transform_family": self.transform_family,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "delta_by_region": dict(self.delta_by_region),
        }


@dataclass(frozen=True)
class CropNullSample:
    """One ordinary-propagation crop-group statistic used for calibration."""

    sample_id: str
    consensus_id: str
    asset_id: str
    pair_id: str
    manifest_digest: str
    canonical_frame_digest: str
    transform_family: str
    detector_version: str
    score_schema: str
    quality_score: float
    source_match_score: float
    positive_view_fraction_raw: float
    view_set_overlap_raw: float
    consensus_raw: float

    def __post_init__(self) -> None:
        for name in (
            "sample_id", "consensus_id", "asset_id", "pair_id", "transform_family",
            "detector_version", "score_schema",
        ):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        for name in ("manifest_digest", "canonical_frame_digest"):
            object.__setattr__(self, name, _digest_hex(name, getattr(self, name)))
        for name in ("quality_score", "source_match_score", "positive_view_fraction_raw", "view_set_overlap_raw", "consensus_raw"):
            object.__setattr__(self, name, _unit(name, getattr(self, name)))
        expected = self.positive_view_fraction_raw * self.view_set_overlap_raw
        if not math.isclose(expected, self.consensus_raw, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("consensus_raw must equal positive_view_fraction_raw * view_set_overlap_raw")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "consensus_id": self.consensus_id,
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "manifest_digest": self.manifest_digest,
            "canonical_frame_digest": self.canonical_frame_digest,
            "transform_family": self.transform_family,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "positive_view_fraction_raw": self.positive_view_fraction_raw,
            "view_set_overlap_raw": self.view_set_overlap_raw,
            "consensus_raw": self.consensus_raw,
        }


@dataclass(frozen=True)
class CropConsensusSummary:
    weighted_positive_view_fraction: float
    view_set_overlap_raw: float
    candidate_regions: Tuple[str, ...]
    region_positive_fraction: Tuple[Tuple[str, float], ...]
    region_availability: Tuple[Tuple[str, float], ...]
    consensus_raw: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "weighted_positive_view_fraction": self.weighted_positive_view_fraction,
            "view_set_overlap_raw": self.view_set_overlap_raw,
            "candidate_regions": list(self.candidate_regions),
            "region_positive_fraction": [list(item) for item in self.region_positive_fraction],
            "region_availability": [list(item) for item in self.region_availability],
            "consensus_raw": self.consensus_raw,
        }


@dataclass(frozen=True)
class CropConsensusResult:
    route: str
    abstained: bool
    reason: str
    consensus_id: str
    asset_id: str
    view_count: int
    summary: Optional[CropConsensusSummary]
    null_count: int
    exceedance_count: Optional[int]
    p_value_raw: Optional[float]
    null_statistics_raw: Tuple[float, ...]
    observation_digest: str
    null_digest: str
    binding_digest: str
    policy_digest: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "schema": SCHEMA,
            "route": self.route,
            "abstained": self.abstained,
            "reason": self.reason,
            "consensus_id": self.consensus_id,
            "asset_id": self.asset_id,
            "view_count": self.view_count,
            "summary": None if self.summary is None else self.summary.to_dict(),
            "null_count": self.null_count,
            "exceedance_count": self.exceedance_count,
            "p_value_raw": self.p_value_raw,
            "null_statistics_raw": list(self.null_statistics_raw),
            "observation_digest": self.observation_digest,
            "null_digest": self.null_digest,
            "binding_digest": self.binding_digest,
            "policy_digest": self.policy_digest,
        }


def _binding_key(item: CropView) -> Tuple[str, ...]:
    return (
        item.consensus_id,
        item.asset_id,
        item.pair_id,
        item.manifest_digest,
        item.canonical_frame_digest,
        item.transform_family,
        item.detector_version,
        item.score_schema,
    )


def _null_binding_key(item: CropNullSample) -> Tuple[str, ...]:
    return (
        item.consensus_id,
        item.asset_id,
        item.pair_id,
        item.manifest_digest,
        item.canonical_frame_digest,
        item.transform_family,
        item.detector_version,
        item.score_schema,
    )


def _summary(views: Sequence[CropView], config: CropConsensusConfig) -> CropConsensusSummary:
    total_weight = sum(item.weight for item in views)
    if total_weight <= 0.0:
        raise ValueError("view weights must have positive total")
    positive_sets = [set(item.positive_regions_at(config.positive_delta_threshold)) for item in views]
    positive_view_weight = sum(item.weight for item, regions in zip(views, positive_sets) if regions)
    weighted_fraction = positive_view_weight / total_weight
    overlaps = []
    for left_index in range(len(positive_sets)):
        for right_index in range(left_index + 1, len(positive_sets)):
            # A crop that does not contain a canonical region must not count as
            # negative evidence for that region.  Compare only the canonical
            # regions visible in both views; pairs with no shared region are
            # excluded from the overlap denominator and remain auditable via
            # region_availability below.
            common_visible = set(views[left_index].delta_by_region) & set(views[right_index].delta_by_region)
            if not common_visible:
                continue
            left = positive_sets[left_index] & common_visible
            right = positive_sets[right_index] & common_visible
            union = left | right
            overlaps.append(len(left & right) / len(union) if union else 1.0)
    view_overlap = sum(overlaps) / len(overlaps) if overlaps else 0.0
    all_regions = sorted({region for item in views for region in item.delta_by_region})
    positive_fraction = []
    availability = []
    candidates = []
    for region in all_regions:
        available_weight = sum(item.weight for item in views if region in item.delta_by_region)
        positive_weight = sum(item.weight for item in views if region in item.delta_by_region and item.delta_by_region[region] >= config.positive_delta_threshold)
        available_fraction = available_weight / total_weight
        fraction = positive_weight / available_weight if available_weight else 0.0
        availability.append((region, available_fraction))
        positive_fraction.append((region, fraction))
        if available_fraction >= config.minimum_region_availability and fraction >= config.minimum_positive_view_fraction:
            candidates.append(region)
    consensus_raw = weighted_fraction * view_overlap
    return CropConsensusSummary(
        weighted_positive_view_fraction=weighted_fraction,
        view_set_overlap_raw=view_overlap,
        candidate_regions=tuple(candidates),
        region_positive_fraction=tuple(positive_fraction),
        region_availability=tuple(availability),
        consensus_raw=consensus_raw,
    )


def _finite_sample_p(target: float, nulls: Sequence[float]) -> Tuple[int, float]:
    exceedance = sum(value >= target for value in nulls)
    return exceedance, (1.0 + exceedance) / (len(nulls) + 1.0)


def _empty_result(
    *,
    route: str,
    reason: str,
    views: Sequence[CropView],
    nulls: Sequence[CropNullSample],
    config: CropConsensusConfig,
    consensus_id: str = "unknown",
    asset_id: str = "unknown",
) -> CropConsensusResult:
    binding = {
        "view_keys": sorted(_binding_key(item) for item in views),
        "null_keys": sorted(_null_binding_key(item) for item in nulls),
    }
    return CropConsensusResult(
        route=route,
        abstained=route == ROUTE_INSUFFICIENT,
        reason=reason,
        consensus_id=consensus_id,
        asset_id=asset_id,
        view_count=len(views),
        summary=None,
        null_count=len(nulls),
        exceedance_count=None,
        p_value_raw=None,
        null_statistics_raw=tuple(item.consensus_raw for item in nulls),
        observation_digest=_digest([item.to_dict() for item in views]),
        null_digest=_digest([item.to_dict() for item in nulls]),
        binding_digest=_digest(binding),
        policy_digest=config.digest,
    )


def evaluate_crop_consensus(
    views: Iterable[CropView],
    null_samples: Iterable[CropNullSample],
    *,
    config: CropConsensusConfig = CropConsensusConfig(),
) -> CropConsensusResult:
    """Evaluate source-conditioned consensus across crop views."""

    if not isinstance(config, CropConsensusConfig):
        raise ValueError("config must be CropConsensusConfig")
    try:
        view_items = tuple(views)
        null_items = tuple(null_samples)
    except TypeError as exc:
        raise ValueError("views and null_samples must be iterable") from exc
    if not all(isinstance(item, CropView) for item in view_items):
        raise ValueError("views must contain CropView values")
    if not all(isinstance(item, CropNullSample) for item in null_items):
        raise ValueError("null_samples must contain CropNullSample values")
    null_items = tuple(sorted(null_items, key=lambda item: item.sample_id))
    if not view_items:
        return _empty_result(route=ROUTE_INSUFFICIENT, reason="view_empty", views=view_items, nulls=null_items, config=config)
    ordered = tuple(sorted(view_items, key=lambda item: item.view_id))
    first = ordered[0]
    if len({item.view_id for item in ordered}) != len(ordered):
        return _empty_result(route=ROUTE_INSUFFICIENT, reason="duplicate_view_id", views=ordered, nulls=null_items, config=config, consensus_id=first.consensus_id, asset_id=first.asset_id)
    if any(_binding_key(item) != _binding_key(first) for item in ordered):
        return _empty_result(route=ROUTE_INSUFFICIENT, reason="view_identity_mismatch", views=ordered, nulls=null_items, config=config, consensus_id=first.consensus_id, asset_id=first.asset_id)
    if len(ordered) < config.minimum_view_count:
        return _empty_result(route=ROUTE_INSUFFICIENT, reason="view_count_insufficient", views=ordered, nulls=null_items, config=config, consensus_id=first.consensus_id, asset_id=first.asset_id)
    if any(item.quality_score < config.minimum_quality for item in ordered):
        return _empty_result(route=ROUTE_INSUFFICIENT, reason="view_quality_below_threshold", views=ordered, nulls=null_items, config=config, consensus_id=first.consensus_id, asset_id=first.asset_id)
    if any(item.source_match_score < config.minimum_source_match for item in ordered):
        return _empty_result(route=ROUTE_INSUFFICIENT, reason="view_source_match_below_threshold", views=ordered, nulls=null_items, config=config, consensus_id=first.consensus_id, asset_id=first.asset_id)
    target_quality_buckets = {_quality_bucket(item.quality_score, config.quality_bins) for item in ordered}
    if len(target_quality_buckets) != 1:
        return _empty_result(route=ROUTE_INSUFFICIENT, reason="view_quality_bucket_mismatch", views=ordered, nulls=null_items, config=config, consensus_id=first.consensus_id, asset_id=first.asset_id)
    if len({item.sample_id for item in null_items}) != len(null_items):
        return _empty_result(route=ROUTE_INSUFFICIENT, reason="duplicate_null_id", views=ordered, nulls=null_items, config=config, consensus_id=first.consensus_id, asset_id=first.asset_id)
    if any(_null_binding_key(item) != _binding_key(first) for item in null_items):
        return _empty_result(route=ROUTE_INSUFFICIENT, reason="null_identity_mismatch", views=ordered, nulls=null_items, config=config, consensus_id=first.consensus_id, asset_id=first.asset_id)
    if len(null_items) < config.minimum_null_count:
        return _empty_result(route=ROUTE_INSUFFICIENT, reason="null_sample_insufficient", views=ordered, nulls=null_items, config=config, consensus_id=first.consensus_id, asset_id=first.asset_id)
    if any(item.quality_score < config.minimum_quality for item in null_items):
        return _empty_result(route=ROUTE_INSUFFICIENT, reason="null_quality_below_threshold", views=ordered, nulls=null_items, config=config, consensus_id=first.consensus_id, asset_id=first.asset_id)
    target_quality_bucket = next(iter(target_quality_buckets))
    if any(_quality_bucket(item.quality_score, config.quality_bins) != target_quality_bucket for item in null_items):
        return _empty_result(route=ROUTE_INSUFFICIENT, reason="null_quality_bucket_mismatch", views=ordered, nulls=null_items, config=config, consensus_id=first.consensus_id, asset_id=first.asset_id)
    if any(item.source_match_score < config.minimum_source_match for item in null_items):
        return _empty_result(route=ROUTE_INSUFFICIENT, reason="null_source_match_below_threshold", views=ordered, nulls=null_items, config=config, consensus_id=first.consensus_id, asset_id=first.asset_id)

    summary = _summary(ordered, config)
    null_statistics = tuple(sorted(item.consensus_raw for item in null_items))
    exceedance, p_value = _finite_sample_p(summary.consensus_raw, null_statistics)
    if not summary.candidate_regions or summary.weighted_positive_view_fraction < config.minimum_positive_view_fraction:
        route, reason = ROUTE_VIEW_INCONSISTENT, "positive_view_consensus_insufficient"
    elif summary.view_set_overlap_raw < config.minimum_view_set_overlap:
        route, reason = ROUTE_VIEW_INCONSISTENT, "positive_region_set_overlap_insufficient"
    elif p_value <= config.alpha:
        route, reason = ROUTE_CONSENSUS_CANDIDATE, "crop_consensus_exceeds_ordinary_propagation_null"
    else:
        route, reason = ROUTE_NULL_CONSISTENT, "crop_consensus_consistent_with_ordinary_propagation_null"
    binding = {
        "view_key": _binding_key(first),
        "view_ids": [item.view_id for item in ordered],
        "crop_spec_digests": [item.crop_spec_digest for item in ordered],
        "null_sample_ids": [item.sample_id for item in null_items],
    }
    return CropConsensusResult(
        route=route,
        abstained=False,
        reason=reason,
        consensus_id=first.consensus_id,
        asset_id=first.asset_id,
        view_count=len(ordered),
        summary=summary,
        null_count=len(null_items),
        exceedance_count=exceedance,
        p_value_raw=p_value,
        null_statistics_raw=null_statistics,
        observation_digest=_digest([item.to_dict() for item in ordered]),
        null_digest=_digest([item.to_dict() for item in null_items]),
        binding_digest=_digest(binding),
        policy_digest=config.digest,
    )
