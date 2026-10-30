"""Patch contribution and forensic-distraction audit.

The PC-SCFT patch-coverage layer deliberately aggregates regional evidence.  A
high aggregate can still be caused by one conspicuous patch (a logo, a sky
edge, or a compression artifact).  This module adds a deterministic mask-out
audit: each positive patch is removed in turn and the top ``k`` contributors
are removed as a group.  The audit keeps the original patch coverage result
and reports how much positive mass, coverage, and route survive.

The output is raw evidence and a review route only.  It is not an AIGC
probability, a causal attribution, a provenance claim, or a legal finding.
Thresholds are protocol defaults and must be learned on a frozen independent
manifest before use with real data.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .patch_coverage import (
    PatchCoverageConfig,
    PatchCoverageResult,
    PatchDelta,
    STATUS_ABSTAINED,
    STATUS_AMBIGUOUS,
    STATUS_GLOBAL,
    STATUS_LOCAL,
    summarize_patch_coverage,
)


VERSION = "patch-contribution-audit-v1"
STATUS_STABLE = "stable"
STATUS_DISTRACTION_SENSITIVE = "distraction_sensitive"
STATUS_INSUFFICIENT = "insufficient"
STATUS_AMBIGUOUS_AUDIT = "ambiguous"


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return value


def _signed_unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or not -1.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and between -1 and 1")
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hex(name: str, value: str) -> str:
    _text(name, value)
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
    return value.lower()


@dataclass(frozen=True)
class PatchContributionConfig:
    """Mask-out gates for the contribution audit."""

    top_k: int = 1
    maximum_global_dominance: float = 0.70
    minimum_retained_mass: float = 0.50
    minimum_accepted_patches: int = 2

    def __post_init__(self) -> None:
        if isinstance(self.top_k, bool) or not isinstance(self.top_k, int) or self.top_k < 1:
            raise ValueError("top_k must be a positive integer")
        _unit("maximum_global_dominance", self.maximum_global_dominance)
        _unit("minimum_retained_mass", self.minimum_retained_mass)
        if (
            isinstance(self.minimum_accepted_patches, bool)
            or not isinstance(self.minimum_accepted_patches, int)
            or self.minimum_accepted_patches < 2
        ):
            raise ValueError("minimum_accepted_patches must be an integer >= 2")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "top_k": self.top_k,
            "maximum_global_dominance": self.maximum_global_dominance,
            "minimum_retained_mass": self.minimum_retained_mass,
            "minimum_accepted_patches": self.minimum_accepted_patches,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class PatchContributionEntry:
    """Leave-one-out evidence for one accepted positive patch."""

    region_id: str
    positive_raw: float
    weight_share_raw: float
    contribution_share_raw: float
    leave_one_out_positive_mass_raw: Optional[float]
    leave_one_out_coverage_raw: Optional[float]
    leave_one_out_route: str
    route_flip_without: bool
    mask_out_available: bool

    def __post_init__(self) -> None:
        _text("region_id", self.region_id)
        _unit("positive_raw", self.positive_raw)
        _unit("weight_share_raw", self.weight_share_raw)
        _unit("contribution_share_raw", self.contribution_share_raw)
        if self.leave_one_out_positive_mass_raw is not None:
            _unit("leave_one_out_positive_mass_raw", self.leave_one_out_positive_mass_raw)
        if self.leave_one_out_coverage_raw is not None:
            _unit("leave_one_out_coverage_raw", self.leave_one_out_coverage_raw)
        _text("leave_one_out_route", self.leave_one_out_route)
        if not isinstance(self.route_flip_without, bool):
            raise ValueError("route_flip_without must be bool")
        if not isinstance(self.mask_out_available, bool):
            raise ValueError("mask_out_available must be bool")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region_id": self.region_id,
            "positive_raw": self.positive_raw,
            "weight_share_raw": self.weight_share_raw,
            "contribution_share_raw": self.contribution_share_raw,
            "leave_one_out_positive_mass_raw": self.leave_one_out_positive_mass_raw,
            "leave_one_out_coverage_raw": self.leave_one_out_coverage_raw,
            "leave_one_out_route": self.leave_one_out_route,
            "route_flip_without": self.route_flip_without,
            "mask_out_available": self.mask_out_available,
        }


@dataclass(frozen=True)
class PatchContributionResult:
    """Auditable mask-out summary and conservative review route."""

    status: str
    abstained: bool
    reason: str
    baseline_status: str
    baseline_route: str
    accepted_patch_count: int
    positive_patch_count: int
    baseline_positive_mass_raw: Optional[float]
    max_contribution_raw: Optional[float]
    retained_mass_after_top_k_raw: Optional[float]
    top_k_removed_region_ids: Tuple[str, ...]
    top_k_route: str
    route_flip_after_top_k: bool
    entries: Tuple[PatchContributionEntry, ...]
    detector_version: Optional[str]
    score_schema: Optional[str]
    config_digest: str
    evidence_digest: str
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.status not in {
            STATUS_STABLE,
            STATUS_DISTRACTION_SENSITIVE,
            STATUS_INSUFFICIENT,
            STATUS_AMBIGUOUS_AUDIT,
        }:
            raise ValueError("invalid patch contribution status")
        if not isinstance(self.abstained, bool):
            raise ValueError("abstained must be bool")
        if self.status in {STATUS_DISTRACTION_SENSITIVE, STATUS_INSUFFICIENT, STATUS_AMBIGUOUS_AUDIT} and not self.abstained:
            raise ValueError("conservative statuses must abstain")
        _text("reason", self.reason)
        _text("baseline_status", self.baseline_status)
        _text("baseline_route", self.baseline_route)
        if not isinstance(self.accepted_patch_count, int) or self.accepted_patch_count < 0:
            raise ValueError("accepted_patch_count must be non-negative")
        if not isinstance(self.positive_patch_count, int) or self.positive_patch_count < 0:
            raise ValueError("positive_patch_count must be non-negative")
        if self.positive_patch_count > self.accepted_patch_count:
            raise ValueError("positive_patch_count cannot exceed accepted_patch_count")
        for name, value in (
            ("baseline_positive_mass_raw", self.baseline_positive_mass_raw),
            ("max_contribution_raw", self.max_contribution_raw),
            ("retained_mass_after_top_k_raw", self.retained_mass_after_top_k_raw),
        ):
            if value is not None:
                _unit(name, value)
        if not isinstance(self.top_k_removed_region_ids, tuple):
            raise ValueError("top_k_removed_region_ids must be a tuple")
        _text("top_k_route", self.top_k_route)
        if not isinstance(self.route_flip_after_top_k, bool):
            raise ValueError("route_flip_after_top_k must be bool")
        if not isinstance(self.entries, tuple) or any(not isinstance(item, PatchContributionEntry) for item in self.entries):
            raise ValueError("entries must be a tuple of PatchContributionEntry")
        for name, value in (("config_digest", self.config_digest), ("evidence_digest", self.evidence_digest)):
            _hex(name, value)
        if self.detector_version is not None:
            _text("detector_version", self.detector_version)
        if self.score_schema is not None:
            _text("score_schema", self.score_schema)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "abstained": self.abstained,
            "reason": self.reason,
            "baseline_status": self.baseline_status,
            "baseline_route": self.baseline_route,
            "accepted_patch_count": self.accepted_patch_count,
            "positive_patch_count": self.positive_patch_count,
            "baseline_positive_mass_raw": self.baseline_positive_mass_raw,
            "max_contribution_raw": self.max_contribution_raw,
            "retained_mass_after_top_k_raw": self.retained_mass_after_top_k_raw,
            "top_k_removed_region_ids": list(self.top_k_removed_region_ids),
            "top_k_route": self.top_k_route,
            "route_flip_after_top_k": self.route_flip_after_top_k,
            "entries": [item.to_dict() for item in self.entries],
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "config_digest": self.config_digest,
            "evidence_digest": self.evidence_digest,
        }


def _empty(
    *,
    cfg: PatchContributionConfig,
    baseline: PatchCoverageResult,
    reason: str,
    accepted: int = 0,
    positive: int = 0,
    detector_version: Optional[str] = None,
    score_schema: Optional[str] = None,
    evidence_digest: Optional[str] = None,
) -> PatchContributionResult:
    return PatchContributionResult(
        status=STATUS_INSUFFICIENT,
        abstained=True,
        reason=reason,
        baseline_status=baseline.status,
        baseline_route=baseline.route,
        accepted_patch_count=accepted,
        positive_patch_count=positive,
        baseline_positive_mass_raw=None,
        max_contribution_raw=None,
        retained_mass_after_top_k_raw=None,
        top_k_removed_region_ids=(),
        top_k_route="unavailable",
        route_flip_after_top_k=False,
        entries=(),
        detector_version=detector_version,
        score_schema=score_schema,
        config_digest=cfg.digest,
        evidence_digest=evidence_digest or _digest({"version": VERSION, "reason": reason}),
    )


def audit_patch_contributions(
    patches: Iterable[PatchDelta],
    *,
    coverage_config: Optional[PatchCoverageConfig] = None,
    config: Optional[PatchContributionConfig] = None,
) -> PatchContributionResult:
    """Run deterministic leave-one-out and top-k mask-out auditing.

    ``summarize_patch_coverage`` remains the source of the baseline route.  A
    global-like baseline with a dominant patch or a severe top-k collapse is
    conservatively marked ``distraction_sensitive``.  A localized baseline is
    allowed to remain stable because concentration is expected for a local
    edit candidate; the result still records the mask-out collapse for human
    review.
    """

    cfg = config or PatchContributionConfig()
    cov_cfg = coverage_config or PatchCoverageConfig()
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
    ordered = sorted(items, key=lambda item: item.region_id)
    evidence_digest = _digest(
        {
            "version": VERSION,
            "coverage_config": cov_cfg.to_dict(),
            "patches": [item.to_dict() for item in ordered],
        }
    )
    baseline = summarize_patch_coverage(ordered, config=cov_cfg)
    accepted = [
        item
        for item in ordered
        if item.quality_score >= cov_cfg.minimum_quality
        and item.source_match_score >= cov_cfg.minimum_source_match
    ]
    if len(accepted) < cfg.minimum_accepted_patches:
        return _empty(
            cfg=cfg,
            baseline=baseline,
            reason="insufficient_accepted_patches",
            accepted=len(accepted),
            positive=0,
            detector_version=detector_version,
            score_schema=score_schema,
            evidence_digest=evidence_digest,
        )
    weights = [
        item.quality_score ** cov_cfg.quality_power * item.source_match_score * item.area_fraction
        for item in accepted
    ]
    total_weight = sum(weights)
    if total_weight <= 0.0:
        return _empty(
            cfg=cfg,
            baseline=baseline,
            reason="zero_evidence_weight",
            accepted=len(accepted),
            detector_version=detector_version,
            score_schema=score_schema,
            evidence_digest=evidence_digest,
        )
    values = [max(0.0, float(item.delta_raw)) for item in accepted]
    positive_indices = [index for index, value in enumerate(values) if value >= cov_cfg.delta_threshold]
    if not positive_indices:
        return _empty(
            cfg=cfg,
            baseline=baseline,
            reason="no_positive_delta",
            accepted=len(accepted),
            detector_version=detector_version,
            score_schema=score_schema,
            evidence_digest=evidence_digest,
        )
    positive_mass = sum(weight * value for weight, value in zip(weights, values)) / total_weight
    shares_total = sum(weights[index] * values[index] for index in positive_indices)
    if shares_total <= 0.0:
        return _empty(
            cfg=cfg,
            baseline=baseline,
            reason="zero_positive_mass",
            accepted=len(accepted),
            positive=len(positive_indices),
            detector_version=detector_version,
            score_schema=score_schema,
            evidence_digest=evidence_digest,
        )
    ranked = sorted(
        positive_indices,
        key=lambda index: (-weights[index] * values[index], accepted[index].region_id),
    )
    top_indices = ranked[: cfg.top_k]
    top_ids = tuple(accepted[index].region_id for index in top_indices)
    top_share = sum(weights[index] * values[index] for index in top_indices) / shares_total
    retained = max(0.0, min(1.0, 1.0 - top_share))

    def _route_after_removed(removed: Sequence[str]) -> Tuple[str, Optional[PatchCoverageResult]]:
        remaining = [item for item in ordered if item.region_id not in set(removed)]
        if len(remaining) < cov_cfg.minimum_patches:
            return "unavailable_insufficient_patches", None
        reduced = summarize_patch_coverage(remaining, config=cov_cfg)
        return reduced.route, reduced

    top_route, top_result = _route_after_removed(top_ids)
    route_flip = top_result is not None and top_result.route != baseline.route
    entries: List[PatchContributionEntry] = []
    for index in ranked:
        item = accepted[index]
        removed_route, removed_result = _route_after_removed((item.region_id,))
        remaining_indices = [j for j in range(len(accepted)) if j != index]
        remaining_weight = sum(weights[j] for j in remaining_indices)
        if remaining_weight > 0.0:
            loo_mass = sum(weights[j] * values[j] for j in remaining_indices) / remaining_weight
            loo_coverage = sum(
                weights[j]
                for j in remaining_indices
                if values[j] >= cov_cfg.delta_threshold
            ) / remaining_weight
            available = True
        else:
            loo_mass = None
            loo_coverage = None
            available = False
        entries.append(
            PatchContributionEntry(
                region_id=item.region_id,
                positive_raw=values[index],
                weight_share_raw=weights[index] / total_weight,
                contribution_share_raw=(weights[index] * values[index]) / shares_total,
                leave_one_out_positive_mass_raw=loo_mass,
                leave_one_out_coverage_raw=loo_coverage,
                leave_one_out_route=removed_route,
                route_flip_without=removed_result is not None and removed_result.route != baseline.route,
                mask_out_available=available,
            )
        )
    entries.sort(key=lambda item: item.region_id)

    if baseline.status == STATUS_ABSTAINED:
        status, abstained, reason = STATUS_INSUFFICIENT, True, f"baseline_{baseline.reason}"
    elif baseline.status == STATUS_AMBIGUOUS:
        status, abstained, reason = STATUS_AMBIGUOUS_AUDIT, True, "baseline_ambiguous_patch_shape"
    elif baseline.status == STATUS_GLOBAL and (
        top_share > cfg.maximum_global_dominance
        or retained < cfg.minimum_retained_mass
        or route_flip
    ):
        status, abstained, reason = STATUS_DISTRACTION_SENSITIVE, True, "global_evidence_dominated_or_unstable"
    else:
        status, abstained, reason = STATUS_STABLE, False, "mask_out_stable_for_baseline_route"
    return PatchContributionResult(
        status=status,
        abstained=abstained,
        reason=reason,
        baseline_status=baseline.status,
        baseline_route=baseline.route,
        accepted_patch_count=len(accepted),
        positive_patch_count=len(positive_indices),
        baseline_positive_mass_raw=max(0.0, min(1.0, positive_mass)),
        max_contribution_raw=max(0.0, min(1.0, top_share)),
        retained_mass_after_top_k_raw=retained,
        top_k_removed_region_ids=top_ids,
        top_k_route=top_route,
        route_flip_after_top_k=route_flip,
        entries=tuple(entries),
        detector_version=detector_version,
        score_schema=score_schema,
        config_digest=cfg.digest,
        evidence_digest=evidence_digest,
    )


__all__ = [
    "VERSION",
    "STATUS_STABLE",
    "STATUS_DISTRACTION_SENSITIVE",
    "STATUS_INSUFFICIENT",
    "STATUS_AMBIGUOUS_AUDIT",
    "PatchContributionConfig",
    "PatchContributionEntry",
    "PatchContributionResult",
    "audit_patch_contributions",
]
