"""Matched Placebo Counterfactual Forensics (MPCF).

MPCF evaluates one source-conditioned regional delta against placebo/control
deltas that were produced under the same asset, pair, manifest, propagation
family, detector/schema and quality bucket.  It is deliberately a small,
auditable research contract:

* the one-sided finite-sample p-value includes ties;
* control median, contrast and range spread are retained as raw evidence; and
* identity, quality and support failures abstain instead of silently pooling
  incompatible controls.

The routes are evidence routes only.  They must not be mapped to the AIGC
four-state result, an authorship assertion, a probability, or a legal finding.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from statistics import median
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from .paired_delta_calibration import quality_bucket
from .regional_fdr import RegionalQueryDelta


VERSION = "mpcf-matched-placebo-v1"
SCHEMA = "mpcf-regional-control-v1"

ROUTE_CANDIDATE_EDIT = "candidate_edit"
ROUTE_CONTROL_CONSISTENT = "control_consistent"
ROUTE_INSUFFICIENT = "insufficient"


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _digest_hex(name: str, value: str) -> str:
    normalized = _text(name, value).lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return normalized


def _unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    return normalized


def _signed_unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number between -1 and 1")
    normalized = float(value)
    if not math.isfinite(normalized) or not -1.0 <= normalized <= 1.0:
        raise ValueError(f"{name} must be finite and between -1 and 1")
    return normalized


def _contrast(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number between -2 and 2")
    normalized = float(value)
    if not math.isfinite(normalized) or not -2.0 <= normalized <= 2.0:
        raise ValueError(f"{name} must be finite and between -2 and 2")
    return normalized


def _alpha(value: float) -> float:
    normalized = _unit("alpha", value)
    if normalized <= 0.0 or normalized >= 1.0:
        raise ValueError("alpha must be strictly between 0 and 1")
    return normalized


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _quality_bins(values: Sequence[float]) -> Tuple[float, ...]:
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


@dataclass(frozen=True)
class MPCFConfig:
    """Frozen gates for one matched-placebo evaluation."""

    quality_bins: Tuple[float, ...] = (0.35, 0.60, 0.80)
    minimum_control_count: int = 20
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    alpha: float = 0.05
    minimum_contrast_raw: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "quality_bins", _quality_bins(self.quality_bins))
        if (
            isinstance(self.minimum_control_count, bool)
            or not isinstance(self.minimum_control_count, int)
            or self.minimum_control_count < 1
        ):
            raise ValueError("minimum_control_count must be a positive integer")
        object.__setattr__(self, "minimum_quality", _unit("minimum_quality", self.minimum_quality))
        object.__setattr__(
            self,
            "minimum_source_match",
            _unit("minimum_source_match", self.minimum_source_match),
        )
        object.__setattr__(self, "alpha", _alpha(self.alpha))
        if (
            isinstance(self.minimum_contrast_raw, bool)
            or not isinstance(self.minimum_contrast_raw, (int, float))
            or not math.isfinite(float(self.minimum_contrast_raw))
            or not 0.0 <= float(self.minimum_contrast_raw) <= 2.0
        ):
            raise ValueError("minimum_contrast_raw must be finite and between 0 and 2")
        object.__setattr__(self, "minimum_contrast_raw", float(self.minimum_contrast_raw))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "quality_bins": list(self.quality_bins),
            "minimum_control_count": self.minimum_control_count,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "alpha": self.alpha,
            "minimum_contrast_raw": self.minimum_contrast_raw,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class MPCFTarget:
    """One SCTE/RegionalQueryDelta target with its source identity binding."""

    asset_id: str
    pair_id: str
    manifest_digest: str
    query_delta: RegionalQueryDelta
    coordinate_frame_digest: str
    transform_spec_digest: str
    source_evidence_digest: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_id", _text("asset_id", self.asset_id))
        object.__setattr__(self, "pair_id", _text("pair_id", self.pair_id))
        object.__setattr__(self, "manifest_digest", _digest_hex("manifest_digest", self.manifest_digest))
        object.__setattr__(self, "coordinate_frame_digest", _digest_hex("coordinate_frame_digest", self.coordinate_frame_digest))
        object.__setattr__(self, "transform_spec_digest", _digest_hex("transform_spec_digest", self.transform_spec_digest))
        if not isinstance(self.query_delta, RegionalQueryDelta):
            raise ValueError("query_delta must be RegionalQueryDelta")
        if self.source_evidence_digest is not None:
            object.__setattr__(
                self,
                "source_evidence_digest",
                _digest_hex("source_evidence_digest", self.source_evidence_digest),
            )

    def quality_bucket(self, quality_bins: Sequence[float] = (0.35, 0.60, 0.80)) -> str:
        return quality_bucket(self.query_delta.quality_score, quality_bins)

    def to_dict(self, *, quality_bins: Sequence[float] = (0.35, 0.60, 0.80)) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "manifest_digest": self.manifest_digest,
            "coordinate_frame_digest": self.coordinate_frame_digest,
            "transform_spec_digest": self.transform_spec_digest,
            "region_id": self.query_delta.region_id,
            "region_type": self.query_delta.region_type,
            "transform_family": self.query_delta.transform_family,
            "detector_version": self.query_delta.detector_version,
            "score_schema": self.query_delta.score_schema,
            "quality_bucket": self.quality_bucket(quality_bins),
            "query_delta": self.query_delta.to_dict(quality_bins=quality_bins),
            "source_evidence_digest": self.source_evidence_digest,
        }

    def binding_digest(self, *, quality_bins: Sequence[float] = (0.35, 0.60, 0.80)) -> str:
        return _digest(self.to_dict(quality_bins=quality_bins))


@dataclass(frozen=True)
class MPCFControlDelta:
    """One placebo delta eligible to be matched against an MPCF target."""

    control_id: str
    asset_id: str
    pair_id: str
    manifest_digest: str
    region_id: str
    region_type: str
    transform_family: str
    detector_version: str
    score_schema: str
    coordinate_frame_digest: str
    transform_spec_digest: str
    quality_score: float
    source_match_score: float
    delta_raw: float

    def __post_init__(self) -> None:
        for name in (
            "control_id",
            "asset_id",
            "pair_id",
            "region_id",
            "region_type",
            "transform_family",
            "detector_version",
            "score_schema",
            "coordinate_frame_digest",
            "transform_spec_digest",
        ):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        object.__setattr__(self, "manifest_digest", _digest_hex("manifest_digest", self.manifest_digest))
        object.__setattr__(self, "coordinate_frame_digest", _digest_hex("coordinate_frame_digest", self.coordinate_frame_digest))
        object.__setattr__(self, "transform_spec_digest", _digest_hex("transform_spec_digest", self.transform_spec_digest))
        object.__setattr__(self, "quality_score", _unit("quality_score", self.quality_score))
        object.__setattr__(self, "source_match_score", _unit("source_match_score", self.source_match_score))
        object.__setattr__(self, "delta_raw", _signed_unit("delta_raw", self.delta_raw))

    def quality_bucket(self, quality_bins: Sequence[float] = (0.35, 0.60, 0.80)) -> str:
        return quality_bucket(self.quality_score, quality_bins)

    def to_dict(self, *, quality_bins: Sequence[float] = (0.35, 0.60, 0.80)) -> Dict[str, Any]:
        return {
            "control_id": self.control_id,
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "manifest_digest": self.manifest_digest,
            "coordinate_frame_digest": self.coordinate_frame_digest,
            "transform_spec_digest": self.transform_spec_digest,
            "region_id": self.region_id,
            "region_type": self.region_type,
            "transform_family": self.transform_family,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "quality_score": self.quality_score,
            "quality_bucket": self.quality_bucket(quality_bins),
            "source_match_score": self.source_match_score,
            "delta_raw": self.delta_raw,
        }


@dataclass(frozen=True)
class MPCFResult:
    """Auditable MPCF route and raw placebo-control statistics."""

    route: str
    abstained: bool
    reason: str
    target_delta_raw: float
    target_quality_score: float
    target_source_match_score: float
    target_quality_bucket: str
    control_count: int
    minimum_control_count: int
    control_ids: Tuple[str, ...]
    control_deltas: Tuple[float, ...]
    control_median_raw: Optional[float]
    contrast_raw: Optional[float]
    control_spread_raw: Optional[float]
    p_value_raw: Optional[float]
    exceedance_count: Optional[int]
    alpha: float
    minimum_contrast_raw: float
    config_digest: str
    binding_digest: str
    controls_digest: str
    evidence_digest: str
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.route not in {
            ROUTE_CANDIDATE_EDIT,
            ROUTE_CONTROL_CONSISTENT,
            ROUTE_INSUFFICIENT,
        }:
            raise ValueError("invalid MPCF route")
        if self.abstained != (self.route == ROUTE_INSUFFICIENT):
            raise ValueError("abstained must match route")
        object.__setattr__(self, "reason", _text("reason", self.reason))
        _signed_unit("target_delta_raw", self.target_delta_raw)
        _unit("target_quality_score", self.target_quality_score)
        _unit("target_source_match_score", self.target_source_match_score)
        _text("target_quality_bucket", self.target_quality_bucket)
        if isinstance(self.control_count, bool) or not isinstance(self.control_count, int) or self.control_count < 0:
            raise ValueError("control_count must be a non-negative integer")
        if (
            isinstance(self.minimum_control_count, bool)
            or not isinstance(self.minimum_control_count, int)
            or self.minimum_control_count < 1
        ):
            raise ValueError("minimum_control_count must be a positive integer")
        if len(self.control_ids) != len(self.control_deltas):
            raise ValueError("control_ids and control_deltas must have equal length")
        ids = tuple(_text("control_id", item) for item in self.control_ids)
        if len(set(ids)) != len(ids):
            raise ValueError("control_ids must be unique")
        object.__setattr__(self, "control_ids", ids)
        deltas = tuple(_signed_unit("control_delta", item) for item in self.control_deltas)
        object.__setattr__(self, "control_deltas", deltas)
        object.__setattr__(self, "alpha", _alpha(self.alpha))
        _contrast("minimum_contrast_raw", self.minimum_contrast_raw)
        if self.minimum_contrast_raw < 0.0:
            raise ValueError("minimum_contrast_raw must be non-negative")
        object.__setattr__(self, "minimum_contrast_raw", float(self.minimum_contrast_raw))
        for name, value in (
            ("config_digest", self.config_digest),
            ("binding_digest", self.binding_digest),
            ("controls_digest", self.controls_digest),
            ("evidence_digest", self.evidence_digest),
        ):
            _digest_hex(name, value)
        if self.version != VERSION:
            raise ValueError("unsupported MPCF version")
        if self.route != ROUTE_INSUFFICIENT:
            if self.control_count < self.minimum_control_count:
                raise ValueError("accepted route requires minimum control count")
            if self.control_count != len(self.control_deltas):
                raise ValueError("accepted route control count mismatch")
            if self.control_median_raw is None or self.contrast_raw is None or self.control_spread_raw is None:
                raise ValueError("accepted route requires control statistics")
            if self.p_value_raw is None or self.exceedance_count is None:
                raise ValueError("accepted route requires finite-sample p-value")
            _signed_unit("control_median_raw", self.control_median_raw)
            _contrast("contrast_raw", self.contrast_raw)
            _contrast("control_spread_raw", self.control_spread_raw)
            if self.control_spread_raw < 0.0:
                raise ValueError("control_spread_raw must be non-negative")
            _unit("p_value_raw", self.p_value_raw)
            if self.p_value_raw <= 0.0:
                raise ValueError("p_value_raw must be greater than zero")
            if (
                isinstance(self.exceedance_count, bool)
                or not isinstance(self.exceedance_count, int)
                or not 0 <= self.exceedance_count <= self.control_count
            ):
                raise ValueError("exceedance_count is outside control range")
        elif any(
            value is not None
            for value in (self.control_median_raw, self.contrast_raw, self.control_spread_raw, self.p_value_raw, self.exceedance_count)
        ):
            raise ValueError("insufficient route cannot expose control statistics")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "schema": SCHEMA,
            "route": self.route,
            "abstained": self.abstained,
            "reason": self.reason,
            "target_delta_raw": self.target_delta_raw,
            "target_quality_score": self.target_quality_score,
            "target_source_match_score": self.target_source_match_score,
            "target_quality_bucket": self.target_quality_bucket,
            "control_count": self.control_count,
            "minimum_control_count": self.minimum_control_count,
            "control_ids": list(self.control_ids),
            "control_deltas": list(self.control_deltas),
            "control_median_raw": self.control_median_raw,
            "contrast_raw": self.contrast_raw,
            "control_spread_raw": self.control_spread_raw,
            "p_value_raw": self.p_value_raw,
            "exceedance_count": self.exceedance_count,
            "alpha": self.alpha,
            "minimum_contrast_raw": self.minimum_contrast_raw,
            "config_digest": self.config_digest,
            "binding_digest": self.binding_digest,
            "controls_digest": self.controls_digest,
            "evidence_digest": self.evidence_digest,
        }


def _controls_digest(controls: Sequence[MPCFControlDelta], cfg: MPCFConfig) -> str:
    payload = [item.to_dict(quality_bins=cfg.quality_bins) for item in controls]
    return _digest(sorted(payload, key=lambda item: json.dumps(item, sort_keys=True)))


def _empty_result(
    target: MPCFTarget,
    cfg: MPCFConfig,
    reason: str,
    *,
    controls: Sequence[MPCFControlDelta] = (),
) -> MPCFResult:
    ordered = tuple(sorted(controls, key=lambda item: item.control_id))
    binding_digest = target.binding_digest(quality_bins=cfg.quality_bins)
    controls_digest = _controls_digest(ordered, cfg)
    payload = {
        "version": VERSION,
        "route": ROUTE_INSUFFICIENT,
        "reason": reason,
        "binding_digest": binding_digest,
        "controls_digest": controls_digest,
        "control_count": len(ordered),
    }
    evidence_digest = _digest(payload)
    return MPCFResult(
        route=ROUTE_INSUFFICIENT,
        abstained=True,
        reason=reason,
        target_delta_raw=target.query_delta.delta_raw,
        target_quality_score=target.query_delta.quality_score,
        target_source_match_score=target.query_delta.source_match_score,
        target_quality_bucket=target.quality_bucket(cfg.quality_bins),
        control_count=len(ordered),
        minimum_control_count=cfg.minimum_control_count,
        control_ids=(),
        control_deltas=(),
        control_median_raw=None,
        contrast_raw=None,
        control_spread_raw=None,
        p_value_raw=None,
        exceedance_count=None,
        alpha=cfg.alpha,
        minimum_contrast_raw=cfg.minimum_contrast_raw,
        config_digest=cfg.digest,
        binding_digest=binding_digest,
        controls_digest=controls_digest,
        evidence_digest=evidence_digest,
    )


def evaluate_mpcf(
    target: MPCFTarget,
    controls: Iterable[MPCFControlDelta],
    *,
    config: Optional[MPCFConfig] = None,
) -> MPCFResult:
    """Evaluate one regional target against matched placebo controls.

    Every supplied control must match the target identity.  A mismatched row
    is not discarded because doing so could turn a heterogeneous control set
    into an apparently significant result; the complete evaluation abstains.
    """

    if not isinstance(target, MPCFTarget):
        raise ValueError("target must be MPCFTarget")
    cfg = config or MPCFConfig()
    if isinstance(controls, (str, bytes)):
        return _empty_result(target, cfg, "invalid_control_type")
    try:
        values = tuple(controls)
    except TypeError:
        return _empty_result(target, cfg, "invalid_control_type")
    if any(not isinstance(item, MPCFControlDelta) for item in values):
        valid = tuple(item for item in values if isinstance(item, MPCFControlDelta))
        return _empty_result(target, cfg, "invalid_control_type", controls=valid)

    ordered = tuple(sorted(values, key=lambda item: item.control_id))
    if len({item.control_id for item in ordered}) != len(ordered):
        return _empty_result(target, cfg, "duplicate_control_id", controls=ordered)

    query = target.query_delta
    if query.quality_score < cfg.minimum_quality:
        return _empty_result(target, cfg, "target_quality_below_threshold", controls=ordered)
    if query.source_match_score < cfg.minimum_source_match:
        return _empty_result(target, cfg, "target_source_match_below_threshold", controls=ordered)
    target_bucket = target.quality_bucket(cfg.quality_bins)

    for item in ordered:
        if (
            item.asset_id != target.asset_id
            or item.pair_id != target.pair_id
            or item.manifest_digest != target.manifest_digest
            or item.region_id != query.region_id
            or item.region_type != query.region_type
            or item.transform_family != query.transform_family
            or item.detector_version != query.detector_version
            or item.score_schema != query.score_schema
            or item.coordinate_frame_digest != target.coordinate_frame_digest
            or item.transform_spec_digest != target.transform_spec_digest
        ):
            return _empty_result(target, cfg, "control_identity_mismatch", controls=ordered)
        if item.quality_score < cfg.minimum_quality:
            return _empty_result(target, cfg, "control_quality_below_threshold", controls=ordered)
        if item.source_match_score < cfg.minimum_source_match:
            return _empty_result(target, cfg, "control_source_match_below_threshold", controls=ordered)
        if item.quality_bucket(cfg.quality_bins) != target_bucket:
            return _empty_result(target, cfg, "control_quality_bucket_mismatch", controls=ordered)

    if len(ordered) < cfg.minimum_control_count:
        return _empty_result(target, cfg, "control_sample_insufficient", controls=ordered)

    control_deltas = tuple(item.delta_raw for item in ordered)
    statistic = max(0.0, float(query.delta_raw))
    exceedances = sum(value >= statistic for value in control_deltas)
    p_value = (1.0 + exceedances) / (len(control_deltas) + 1.0)
    control_median = float(median(control_deltas))
    contrast = float(query.delta_raw) - control_median
    spread = float(max(control_deltas) - min(control_deltas))
    route = (
        ROUTE_CANDIDATE_EDIT
        if p_value <= cfg.alpha and contrast >= cfg.minimum_contrast_raw
        else ROUTE_CONTROL_CONSISTENT
    )
    reason = (
        "target_rejects_matched_placebo"
        if route == ROUTE_CANDIDATE_EDIT
        else "target_consistent_with_matched_placebo"
    )
    binding_digest = target.binding_digest(quality_bins=cfg.quality_bins)
    controls_digest = _controls_digest(ordered, cfg)
    payload = {
        "version": VERSION,
        "route": route,
        "reason": reason,
        "binding_digest": binding_digest,
        "controls_digest": controls_digest,
        "control_ids": [item.control_id for item in ordered],
        "control_deltas": list(control_deltas),
        "target_delta_raw": query.delta_raw,
        "control_median_raw": control_median,
        "contrast_raw": contrast,
        "control_spread_raw": spread,
        "p_value_raw": p_value,
        "exceedance_count": exceedances,
        "config_digest": cfg.digest,
    }
    return MPCFResult(
        route=route,
        abstained=False,
        reason=reason,
        target_delta_raw=query.delta_raw,
        target_quality_score=query.quality_score,
        target_source_match_score=query.source_match_score,
        target_quality_bucket=target_bucket,
        control_count=len(ordered),
        minimum_control_count=cfg.minimum_control_count,
        control_ids=tuple(item.control_id for item in ordered),
        control_deltas=control_deltas,
        control_median_raw=control_median,
        contrast_raw=contrast,
        control_spread_raw=spread,
        p_value_raw=p_value,
        exceedance_count=exceedances,
        alpha=cfg.alpha,
        minimum_contrast_raw=cfg.minimum_contrast_raw,
        config_digest=cfg.digest,
        binding_digest=binding_digest,
        controls_digest=controls_digest,
        evidence_digest=_digest(payload),
    )


def target_from_scte(binding: Any, result: Any, region_id: str) -> MPCFTarget:
    """Create an MPCF target from one accepted SCTE regional delta.

    The explicit binding/result check prevents a delta from one manifest or
    triadic evidence chain being silently evaluated under another binding.
    """

    from .scte import SCTEBinding, SCTEResult

    if not isinstance(binding, SCTEBinding) or not isinstance(result, SCTEResult):
        raise ValueError("binding and result must be SCTE objects")
    if not result.accepted or result.binding_digest != binding.binding_digest:
        raise ValueError("SCTE result is not accepted under the supplied binding")
    region_id = _text("region_id", region_id)
    matches = [item for item in result.query_deltas if item.region_id == region_id]
    if len(matches) != 1:
        raise ValueError("SCTE result must contain exactly one requested region")
    return MPCFTarget(
        asset_id=binding.asset_id,
        pair_id=binding.pair_id,
        manifest_digest=binding.manifest_digest,
        query_delta=matches[0],
        coordinate_frame_digest=binding.alignment_digest,
        transform_spec_digest=binding.transform_spec_digest,
        source_evidence_digest=result.evidence_digest,
    )


__all__ = [
    "VERSION",
    "SCHEMA",
    "ROUTE_CANDIDATE_EDIT",
    "ROUTE_CONTROL_CONSISTENT",
    "ROUTE_INSUFFICIENT",
    "MPCFConfig",
    "MPCFTarget",
    "MPCFControlDelta",
    "MPCFResult",
    "evaluate_mpcf",
    "target_from_scte",
]
