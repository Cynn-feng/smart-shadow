"""Group-matched conformal regional selection for source-conditioned evidence.

The existing paired-delta calibration protects a query with one maximum
positive regional delta.  That is useful for a conservative image-level gate,
but it does not say which regions remain credible when several regions are
tested at once.  This module keeps the regions separate:

1. fit a frozen ordinary-propagation null for each region/family/quality
   stratum;
2. compute ties-inclusive finite-sample one-sided p-values for a query; and
3. apply Benjamini-Hochberg selection at a configured q-value.

The output is an empirical regional-selection route.  It is not an AIGC
probability, a legal finding, or a formal FDR guarantee.  The latter requires
independent, group-matched calibration and dependence/selection validation on
real authorized data.  Missing strata, detector/schema mismatches and quality
failures are fail-closed.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


VERSION = "regional-fdr-v1"
STATISTIC_SCHEMA = "regional-positive-delta-v1"
ROUTE_CANDIDATE = "candidate_regions"
ROUTE_NULL_CONSISTENT = "null_consistent"
ROUTE_REVIEW = "review"
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


def _alpha(name: str, value: float) -> float:
    normalized = _unit(name, value)
    if normalized <= 0.0 or normalized >= 1.0:
        raise ValueError(f"{name} must be strictly between 0 and 1")
    return normalized


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _digest_hex(name: str, value: str) -> str:
    _non_empty(name, value)
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
    return value.lower()


def _quality_bucket(quality_score: float, bins: Sequence[float]) -> str:
    quality = _unit("quality_score", quality_score)
    normalized = tuple(float(value) for value in bins)
    if tuple(sorted(set(normalized))) != normalized:
        raise ValueError("quality_bins must be strictly increasing")
    if any(not math.isfinite(value) or not 0.0 < value < 1.0 for value in normalized):
        raise ValueError("quality_bins must contain finite values between 0 and 1")
    return f"q{bisect_right(normalized, quality)}"


@dataclass(frozen=True)
class RegionalFDRConfig:
    """Configuration for the frozen profile and regional selection policy."""

    quality_bins: Tuple[float, ...] = (0.35, 0.60, 0.80)
    minimum_null_count: int = 10
    q_value: float = 0.10
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    minimum_selected_regions: int = 1

    def __post_init__(self) -> None:
        bins = tuple(float(value) for value in self.quality_bins)
        if tuple(sorted(set(bins))) != bins:
            raise ValueError("quality_bins must be strictly increasing")
        if any(not math.isfinite(value) or not 0.0 < value < 1.0 for value in bins):
            raise ValueError("quality_bins must contain finite values between 0 and 1")
        object.__setattr__(self, "quality_bins", bins)
        if (
            isinstance(self.minimum_null_count, bool)
            or not isinstance(self.minimum_null_count, int)
            or self.minimum_null_count < 1
        ):
            raise ValueError("minimum_null_count must be a positive integer")
        object.__setattr__(self, "q_value", _alpha("q_value", self.q_value))
        _unit("minimum_quality", self.minimum_quality)
        _unit("minimum_source_match", self.minimum_source_match)
        if (
            isinstance(self.minimum_selected_regions, bool)
            or not isinstance(self.minimum_selected_regions, int)
            or self.minimum_selected_regions < 1
        ):
            raise ValueError("minimum_selected_regions must be a positive integer")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "quality_bins": list(self.quality_bins),
            "minimum_null_count": self.minimum_null_count,
            "q_value": self.q_value,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "minimum_selected_regions": self.minimum_selected_regions,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class RegionNullDelta:
    """One ordinary-propagation null observation for one region."""

    group_id: str
    transform_family: str
    quality_score: float
    region_id: str
    delta_raw: float
    region_type: str = "unknown"
    detector_version: str = "source-residual-v1"
    score_schema: str = "source-residual-score-v1"

    def __post_init__(self) -> None:
        for name, value in (
            ("group_id", self.group_id),
            ("transform_family", self.transform_family),
            ("region_id", self.region_id),
            ("region_type", self.region_type),
            ("detector_version", self.detector_version),
            ("score_schema", self.score_schema),
        ):
            _non_empty(name, value)
        _unit("quality_score", self.quality_score)
        _signed_unit("delta_raw", self.delta_raw)

    def to_dict(self, *, quality_bins: Sequence[float] = (0.35, 0.60, 0.80)) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "transform_family": self.transform_family,
            "quality_score": float(self.quality_score),
            "quality_bucket": _quality_bucket(self.quality_score, quality_bins),
            "region_id": self.region_id,
            "region_type": self.region_type,
            "delta_raw": float(self.delta_raw),
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
        }


@dataclass(frozen=True)
class RegionalQueryDelta:
    """One observed paired delta that is eligible for regional selection."""

    region_id: str
    delta_raw: float
    quality_score: float
    source_match_score: float
    transform_family: str
    region_type: str = "unknown"
    detector_version: str = "source-residual-v1"
    score_schema: str = "source-residual-score-v1"

    def __post_init__(self) -> None:
        for name, value in (
            ("region_id", self.region_id),
            ("transform_family", self.transform_family),
            ("region_type", self.region_type),
            ("detector_version", self.detector_version),
            ("score_schema", self.score_schema),
        ):
            _non_empty(name, value)
        _signed_unit("delta_raw", self.delta_raw)
        _unit("quality_score", self.quality_score)
        _unit("source_match_score", self.source_match_score)

    def to_dict(self, *, quality_bins: Sequence[float] = (0.35, 0.60, 0.80)) -> Dict[str, Any]:
        return {
            "region_id": self.region_id,
            "delta_raw": float(self.delta_raw),
            "quality_score": float(self.quality_score),
            "quality_bucket": _quality_bucket(self.quality_score, quality_bins),
            "source_match_score": float(self.source_match_score),
            "transform_family": self.transform_family,
            "region_type": self.region_type,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
        }


@dataclass(frozen=True)
class RegionalFDRStratum:
    """Sorted null deltas for one region/family/quality/type key."""

    key: str
    transform_family: str
    quality_bucket: str
    region_id: str
    region_type: str
    deltas: Tuple[float, ...]
    group_ids: Tuple[str, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("key", self.key),
            ("transform_family", self.transform_family),
            ("quality_bucket", self.quality_bucket),
            ("region_id", self.region_id),
            ("region_type", self.region_type),
        ):
            _non_empty(name, value)
        if len(self.deltas) != len(self.group_ids) or not self.deltas:
            raise ValueError("deltas and group_ids must be non-empty and equal length")
        normalized = tuple(_signed_unit("delta_raw", value) for value in self.deltas)
        ids = tuple(_non_empty("group_id", value) for value in self.group_ids)
        if len(set(ids)) != len(ids):
            raise ValueError("group_ids must be unique within a stratum")
        ordered = tuple(sorted(zip(normalized, ids), key=lambda item: (item[0], item[1])))
        object.__setattr__(self, "deltas", tuple(item[0] for item in ordered))
        object.__setattr__(self, "group_ids", tuple(item[1] for item in ordered))

    @property
    def count(self) -> int:
        return len(self.deltas)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "transform_family": self.transform_family,
            "quality_bucket": self.quality_bucket,
            "region_id": self.region_id,
            "region_type": self.region_type,
            "deltas": list(self.deltas),
            "group_ids": list(self.group_ids),
            "count": self.count,
        }


@dataclass(frozen=True)
class RegionalFDRProfile:
    """Frozen ordinary-propagation profile used by query evaluation."""

    detector_version: str
    score_schema: str
    config_digest: str
    dataset_digest: str
    profile_digest: str
    strata: Tuple[RegionalFDRStratum, ...]
    version: str = VERSION

    def __post_init__(self) -> None:
        _non_empty("detector_version", self.detector_version)
        _non_empty("score_schema", self.score_schema)
        for name, value in (
            ("config_digest", self.config_digest),
            ("dataset_digest", self.dataset_digest),
            ("profile_digest", self.profile_digest),
        ):
            _digest_hex(name, value)
        if self.version != VERSION or not self.strata:
            raise ValueError("profile version and strata are required")
        keys = [stratum.key for stratum in self.strata]
        if len(set(keys)) != len(keys):
            raise ValueError("profile strata keys must be unique")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "config_digest": self.config_digest,
            "dataset_digest": self.dataset_digest,
            "profile_digest": self.profile_digest,
            "strata": [stratum.to_dict() for stratum in self.strata],
        }


@dataclass(frozen=True)
class RegionalSelection:
    """Per-region p/q values retained in the final evidence sidecar."""

    region_id: str
    region_type: str
    delta_raw: float
    p_value_raw: float
    q_value_raw: float
    null_count: int
    selected: bool
    stratum_key: str

    def __post_init__(self) -> None:
        _non_empty("region_id", self.region_id)
        _non_empty("region_type", self.region_type)
        _signed_unit("delta_raw", self.delta_raw)
        _unit("p_value_raw", self.p_value_raw)
        _unit("q_value_raw", self.q_value_raw)
        if self.p_value_raw <= 0.0 or self.q_value_raw <= 0.0:
            raise ValueError("p_value_raw and q_value_raw must be greater than zero")
        if not isinstance(self.null_count, int) or self.null_count < 1:
            raise ValueError("null_count must be a positive integer")
        _non_empty("stratum_key", self.stratum_key)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region_id": self.region_id,
            "region_type": self.region_type,
            "delta_raw": self.delta_raw,
            "p_value_raw": self.p_value_raw,
            "q_value_raw": self.q_value_raw,
            "null_count": self.null_count,
            "selected": self.selected,
            "stratum_key": self.stratum_key,
        }


@dataclass(frozen=True)
class RegionalFDRResult:
    """Auditable route produced by the regional selection policy."""

    route: str
    abstained: bool
    candidate_supported: bool
    reason: str
    selected_region_ids: Tuple[str, ...]
    selections: Tuple[RegionalSelection, ...]
    unsupported_region_ids: Tuple[str, ...]
    quality_score: float
    source_match_score: float
    q_value: float
    evaluated_region_count: int
    config_digest: str
    profile_digest: str
    evidence_digest: str
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.route not in {ROUTE_CANDIDATE, ROUTE_NULL_CONSISTENT, ROUTE_REVIEW, ROUTE_INSUFFICIENT}:
            raise ValueError("invalid regional selection route")
        if self.route == ROUTE_CANDIDATE and (self.abstained or not self.candidate_supported):
            raise ValueError("candidate route requires candidate support and no abstention")
        if self.route != ROUTE_CANDIDATE and self.candidate_supported:
            raise ValueError("only candidate route may support candidate regions")
        if self.route in {ROUTE_REVIEW, ROUTE_INSUFFICIENT} and not self.abstained:
            raise ValueError("review and insufficient routes must abstain")
        _non_empty("reason", self.reason)
        _unit("quality_score", self.quality_score)
        _unit("source_match_score", self.source_match_score)
        _alpha("q_value", self.q_value)
        if self.evaluated_region_count < 0:
            raise ValueError("evaluated_region_count must be non-negative")
        if self.version != VERSION:
            raise ValueError("unsupported regional selection version")
        for name, value in (
            ("config_digest", self.config_digest),
            ("profile_digest", self.profile_digest),
            ("evidence_digest", self.evidence_digest),
        ):
            _digest_hex(name, value)
        ids = tuple(selection.region_id for selection in self.selections)
        if len(set(ids)) != len(ids):
            raise ValueError("selection region IDs must be unique")
        if tuple(self.selected_region_ids) != tuple(selection.region_id for selection in self.selections if selection.selected):
            raise ValueError("selected_region_ids must match selections")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "route": self.route,
            "abstained": self.abstained,
            "candidate_supported": self.candidate_supported,
            "reason": self.reason,
            "selected_region_ids": list(self.selected_region_ids),
            "selections": [selection.to_dict() for selection in self.selections],
            "unsupported_region_ids": list(self.unsupported_region_ids),
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "q_value": self.q_value,
            "evaluated_region_count": self.evaluated_region_count,
            "config_digest": self.config_digest,
            "profile_digest": self.profile_digest,
            "evidence_digest": self.evidence_digest,
        }


def _stratum_key(
    transform_family: str,
    quality_bucket: str,
    region_id: str,
    region_type: str,
) -> str:
    return "|".join((transform_family, quality_bucket, region_id, region_type))


def fit_regional_fdr_profile(
    null_deltas: Iterable[RegionNullDelta],
    *,
    config: Optional[RegionalFDRConfig] = None,
) -> RegionalFDRProfile:
    """Fit a region-specific ordinary-propagation null profile."""

    cfg = config or RegionalFDRConfig()
    values = tuple(null_deltas)
    if not values:
        raise ValueError("null_deltas must not be empty")
    detector_versions = {value.detector_version for value in values}
    score_schemas = {value.score_schema for value in values}
    if len(detector_versions) != 1 or len(score_schemas) != 1:
        raise ValueError("null profile requires one detector version and score schema")
    seen = set()
    for value in values:
        identity = (value.group_id, value.region_id)
        if identity in seen:
            raise ValueError("duplicate group/region null observation")
        seen.add(identity)
    dataset_payload = [value.to_dict(quality_bins=cfg.quality_bins) for value in values]
    dataset_digest = _digest(sorted(dataset_payload, key=lambda item: json.dumps(item, sort_keys=True)))
    grouped: Dict[str, List[RegionNullDelta]] = {}
    for value in values:
        bucket = _quality_bucket(value.quality_score, cfg.quality_bins)
        key = _stratum_key(value.transform_family, bucket, value.region_id, value.region_type)
        grouped.setdefault(key, []).append(value)
    strata = []
    for key in sorted(grouped):
        members = grouped[key]
        first = members[0]
        bucket = _quality_bucket(first.quality_score, cfg.quality_bins)
        ordered = sorted(members, key=lambda item: (float(item.delta_raw), item.group_id))
        strata.append(
            RegionalFDRStratum(
                key=key,
                transform_family=first.transform_family,
                quality_bucket=bucket,
                region_id=first.region_id,
                region_type=first.region_type,
                deltas=tuple(item.delta_raw for item in ordered),
                group_ids=tuple(item.group_id for item in ordered),
            )
        )
    config_digest = cfg.digest
    profile_payload = {
        "version": VERSION,
        "detector_version": next(iter(detector_versions)),
        "score_schema": next(iter(score_schemas)),
        "config_digest": config_digest,
        "dataset_digest": dataset_digest,
        "strata": [stratum.to_dict() for stratum in strata],
    }
    profile_digest = _digest(profile_payload)
    return RegionalFDRProfile(
        detector_version=next(iter(detector_versions)),
        score_schema=next(iter(score_schemas)),
        config_digest=config_digest,
        dataset_digest=dataset_digest,
        profile_digest=profile_digest,
        strata=tuple(strata),
    )


def _bh_q_values(p_values: Mapping[str, float]) -> Dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    count = len(ordered)
    adjusted: Dict[str, float] = {}
    running = 1.0
    for rank in range(count, 0, -1):
        region_id, p_value = ordered[rank - 1]
        running = min(running, float(p_value) * count / rank)
        adjusted[region_id] = min(1.0, running)
    return adjusted


def evaluate_regional_fdr(
    profile: RegionalFDRProfile,
    query_deltas: Sequence[RegionalQueryDelta],
    *,
    config: Optional[RegionalFDRConfig] = None,
) -> RegionalFDRResult:
    """Evaluate query regions using profile p-values and BH selection."""

    if not isinstance(profile, RegionalFDRProfile):
        raise ValueError("profile must be RegionalFDRProfile")
    cfg = config or RegionalFDRConfig()
    if profile.config_digest != cfg.digest:
        raise ValueError("profile/config digest mismatch")
    # Canonicalize query order so evidence digests and selection sidecars do
    # not change when an adapter returns the same regions in a different order.
    values = tuple(sorted(query_deltas, key=lambda item: item.region_id))
    if not values:
        raise ValueError("query_deltas must not be empty")
    ids = [value.region_id for value in values]
    if len(set(ids)) != len(ids):
        raise ValueError("query region IDs must be unique")
    if any(value.detector_version != profile.detector_version for value in values):
        raise ValueError("query detector version mismatch")
    if any(value.score_schema != profile.score_schema for value in values):
        raise ValueError("query score schema mismatch")

    stratum_by_key = {stratum.key: stratum for stratum in profile.strata}
    unsupported = []
    p_values: Dict[str, float] = {}
    selected_inputs: Dict[str, Tuple[RegionalQueryDelta, RegionalFDRStratum, float]] = {}
    for value in values:
        if value.quality_score < cfg.minimum_quality:
            unsupported.append(value.region_id)
            continue
        if value.source_match_score < cfg.minimum_source_match:
            unsupported.append(value.region_id)
            continue
        bucket = _quality_bucket(value.quality_score, cfg.quality_bins)
        key = _stratum_key(value.transform_family, bucket, value.region_id, value.region_type)
        stratum = stratum_by_key.get(key)
        if stratum is None or stratum.count < cfg.minimum_null_count:
            unsupported.append(value.region_id)
            continue
        statistic = max(0.0, float(value.delta_raw))
        # Ties are included in the upper tail; this is conservative for finite
        # null streams and agrees with the existing paired-delta calibration.
        exceedances = sum(null_delta >= statistic for null_delta in stratum.deltas)
        p_value = (1.0 + exceedances) / (stratum.count + 1.0)
        p_values[value.region_id] = p_value
        selected_inputs[value.region_id] = (value, stratum, p_value)

    quality_score = min(value.quality_score for value in values)
    source_match_score = min(value.source_match_score for value in values)
    if unsupported:
        digest = _digest(
            {
                "version": VERSION,
                "profile_digest": profile.profile_digest,
                "query": [value.to_dict(quality_bins=cfg.quality_bins) for value in values],
                "unsupported": sorted(unsupported),
                "reason": "unsupported_region",
            }
        )
        return RegionalFDRResult(
            route=ROUTE_INSUFFICIENT,
            abstained=True,
            candidate_supported=False,
            reason="unsupported_or_unavailable_region_null",
            selected_region_ids=(),
            selections=(),
            unsupported_region_ids=tuple(sorted(unsupported)),
            quality_score=quality_score,
            source_match_score=source_match_score,
            q_value=cfg.q_value,
            evaluated_region_count=len(p_values),
            config_digest=cfg.digest,
            profile_digest=profile.profile_digest,
            evidence_digest=digest,
        )

    q_values = _bh_q_values(p_values)
    selections = []
    for region_id in ids:
        value, stratum, p_value = selected_inputs[region_id]
        selections.append(
            RegionalSelection(
                region_id=region_id,
                region_type=value.region_type,
                delta_raw=value.delta_raw,
                p_value_raw=p_value,
                q_value_raw=q_values[region_id],
                null_count=stratum.count,
                selected=q_values[region_id] <= cfg.q_value,
                stratum_key=stratum.key,
            )
        )
    selections_tuple = tuple(selections)
    selected_ids = tuple(item.region_id for item in selections_tuple if item.selected)
    if selected_ids and len(selected_ids) < cfg.minimum_selected_regions:
        route = ROUTE_REVIEW
        abstained = True
        candidate_supported = False
        reason = "selected_region_support_below_minimum"
    elif selected_ids:
        route = ROUTE_CANDIDATE
        abstained = False
        candidate_supported = True
        reason = "bh_selected_regions"
    else:
        route = ROUTE_NULL_CONSISTENT
        abstained = False
        candidate_supported = False
        reason = "no_region_rejected_ordinary_propagation"
    evidence_digest = _digest(
        {
            "version": VERSION,
            "profile_digest": profile.profile_digest,
            "query": [value.to_dict(quality_bins=cfg.quality_bins) for value in values],
            "selections": [item.to_dict() for item in selections_tuple],
            "route": route,
            "reason": reason,
        }
    )
    return RegionalFDRResult(
        route=route,
        abstained=abstained,
        candidate_supported=candidate_supported,
        reason=reason,
        selected_region_ids=selected_ids,
        selections=selections_tuple,
        unsupported_region_ids=(),
        quality_score=quality_score,
        source_match_score=source_match_score,
        q_value=cfg.q_value,
        evaluated_region_count=len(selections_tuple),
        config_digest=cfg.digest,
        profile_digest=profile.profile_digest,
        evidence_digest=evidence_digest,
    )
