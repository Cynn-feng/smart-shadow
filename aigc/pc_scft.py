"""Integrated PC-SCFT evidence decision protocol.

The existing regional counterfactual, paired-delta calibration and patch
coverage modules deliberately expose independent raw observations.  This
module joins them at the *evidence-routing* boundary:

``regional gate -> frozen propagation null -> patch-shape gate -> route``

It never emits an AIGC label, probability, authorship claim or legal finding.
``candidate_edit`` means that the ordinary-propagation null was rejected and
the evidence shape is usable for a human edit review.  ``null_consistent``
means that the query was compatible with the frozen ordinary-propagation null;
it does not prove human creation.  Missing coverage, quality, calibration or
shape support is represented explicitly as ``review`` or ``insufficient``.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Optional

from .paired_delta_calibration import PairedDeltaCalibrationResult
from .patch_coverage import (
    STATUS_ABSTAINED,
    STATUS_AMBIGUOUS,
    STATUS_GLOBAL,
    STATUS_LOCAL,
    PatchCoverageResult,
)
from .regional_counterfactual import RegionalCounterfactualResult


VERSION = "pc-scft-decision-v1"
STATUS_CANDIDATE = "candidate_edit"
STATUS_NULL_CONSISTENT = "null_consistent"
STATUS_REVIEW = "review"
STATUS_INSUFFICIENT = "insufficient"


def _unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return normalized


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PCSCFTConfig:
    """Conservative gates for the integrated evidence protocol."""

    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    minimum_coverage: float = 0.75
    minimum_null_count: int = 3
    allow_calibration_fallback: bool = False
    require_patch_shape: bool = True

    def __post_init__(self) -> None:
        for name in ("minimum_quality", "minimum_source_match", "minimum_coverage"):
            _unit(name, getattr(self, name))
        if (
            isinstance(self.minimum_null_count, bool)
            or not isinstance(self.minimum_null_count, int)
            or self.minimum_null_count < 1
        ):
            raise ValueError("minimum_null_count must be a positive integer")
        if not isinstance(self.allow_calibration_fallback, bool):
            raise ValueError("allow_calibration_fallback must be a bool")
        if not isinstance(self.require_patch_shape, bool):
            raise ValueError("require_patch_shape must be a bool")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "minimum_coverage": self.minimum_coverage,
            "minimum_null_count": self.minimum_null_count,
            "allow_calibration_fallback": self.allow_calibration_fallback,
            "require_patch_shape": self.require_patch_shape,
        }

    @property
    def digest(self) -> str:
        return _digest({"version": VERSION, "config": self.to_dict()})


@dataclass(frozen=True)
class PCSCFTResult:
    """Auditable decision at the boundary between evidence and routing."""

    status: str
    abstained: bool
    candidate_supported: bool
    reason: str
    route: str
    asset_id: Optional[str]
    detector_version: Optional[str]
    score_schema: Optional[str]
    null_evaluated: bool
    null_rejected: bool
    null_p_value: Optional[float]
    null_fallback: str
    null_count: int
    delta_raw: Optional[float]
    stability_adjusted_delta_raw: Optional[float]
    regional_coverage_raw: Optional[float]
    patch_status: Optional[str]
    patch_coverage_raw: Optional[float]
    patch_balanced_coverage_raw: Optional[float]
    quality_score: Optional[float]
    source_match_score: Optional[float]
    config_digest: str
    evidence_digest: str
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.status not in {
            STATUS_CANDIDATE,
            STATUS_NULL_CONSISTENT,
            STATUS_REVIEW,
            STATUS_INSUFFICIENT,
        }:
            raise ValueError("invalid PC-SCFT status")
        if not isinstance(self.abstained, bool) or not isinstance(self.candidate_supported, bool):
            raise ValueError("abstained and candidate_supported must be bools")
        if self.status == STATUS_CANDIDATE and (
            self.abstained or not self.candidate_supported
        ):
            raise ValueError("candidate status requires candidate_supported and no abstention")
        if self.status != STATUS_CANDIDATE and self.candidate_supported:
            raise ValueError("only candidate status may support an edit candidate")
        if self.status in {STATUS_REVIEW, STATUS_INSUFFICIENT} and not self.abstained:
            raise ValueError("review and insufficient statuses must abstain")
        if not self.reason or not self.route:
            raise ValueError("reason and route are required")
        if self.null_p_value is not None:
            _unit("null_p_value", self.null_p_value)
            if self.null_p_value <= 0.0:
                raise ValueError("null_p_value must be greater than zero")
        if self.null_count < 0:
            raise ValueError("null_count must be non-negative")
        for name, value in (
            ("delta_raw", self.delta_raw),
            ("stability_adjusted_delta_raw", self.stability_adjusted_delta_raw),
            ("regional_coverage_raw", self.regional_coverage_raw),
            ("patch_coverage_raw", self.patch_coverage_raw),
            ("patch_balanced_coverage_raw", self.patch_balanced_coverage_raw),
            ("quality_score", self.quality_score),
            ("source_match_score", self.source_match_score),
        ):
            if value is not None:
                _unit(name, value)
        if len(self.config_digest) != 64 or len(self.evidence_digest) != 64:
            raise ValueError("digests must be SHA-256 hex strings")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "abstained": self.abstained,
            "candidate_supported": self.candidate_supported,
            "reason": self.reason,
            "route": self.route,
            "asset_id": self.asset_id,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "null_evaluated": self.null_evaluated,
            "null_rejected": self.null_rejected,
            "null_p_value": self.null_p_value,
            "null_fallback": self.null_fallback,
            "null_count": self.null_count,
            "delta_raw": self.delta_raw,
            "stability_adjusted_delta_raw": self.stability_adjusted_delta_raw,
            "regional_coverage_raw": self.regional_coverage_raw,
            "patch_status": self.patch_status,
            "patch_coverage_raw": self.patch_coverage_raw,
            "patch_balanced_coverage_raw": self.patch_balanced_coverage_raw,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "config_digest": self.config_digest,
            "evidence_digest": self.evidence_digest,
        }


def _result(
    *,
    status: str,
    abstained: bool,
    candidate_supported: bool,
    reason: str,
    route: str,
    regional: RegionalCounterfactualResult,
    calibration: PairedDeltaCalibrationResult,
    coverage: PatchCoverageResult,
    config: PCSCFTConfig,
) -> PCSCFTResult:
    evidence_digest = _digest(
        {
            "version": VERSION,
            "regional": regional.to_dict(),
            "calibration": calibration.to_dict(),
            "coverage": coverage.to_dict(),
            "config": config.to_dict(),
            "decision": {"status": status, "reason": reason, "route": route},
        }
    )
    return PCSCFTResult(
        status=status,
        abstained=abstained,
        candidate_supported=candidate_supported,
        reason=reason,
        route=route,
        asset_id=regional.asset_id,
        detector_version=regional.detector_version or calibration.detector_version,
        score_schema=regional.score_schema or calibration.score_schema,
        null_evaluated=calibration.evaluated,
        null_rejected=calibration.unknown,
        null_p_value=calibration.raw_p_value,
        null_fallback=calibration.fallback,
        null_count=calibration.null_count,
        delta_raw=regional.positive_delta_raw,
        stability_adjusted_delta_raw=regional.stability_adjusted_delta_raw,
        regional_coverage_raw=regional.coverage_raw,
        patch_status=coverage.status,
        patch_coverage_raw=coverage.coverage_raw,
        patch_balanced_coverage_raw=coverage.balanced_coverage_raw,
        quality_score=regional.quality_score,
        source_match_score=regional.source_match_score,
        config_digest=config.digest,
        evidence_digest=evidence_digest,
    )


def decide_pc_scft(
    regional: RegionalCounterfactualResult,
    calibration: PairedDeltaCalibrationResult,
    coverage: PatchCoverageResult,
    *,
    config: Optional[PCSCFTConfig] = None,
) -> PCSCFTResult:
    """Join three raw observations into one conservative routing decision."""

    if not isinstance(regional, RegionalCounterfactualResult):
        raise ValueError("regional must be RegionalCounterfactualResult")
    if not isinstance(calibration, PairedDeltaCalibrationResult):
        raise ValueError("calibration must be PairedDeltaCalibrationResult")
    if not isinstance(coverage, PatchCoverageResult):
        raise ValueError("coverage must be PatchCoverageResult")
    cfg = config or PCSCFTConfig()

    identities = {
        value
        for value in (regional.detector_version, calibration.detector_version, coverage.detector_version)
        if value is not None
    }
    schemas = {
        value
        for value in (regional.score_schema, calibration.score_schema, coverage.score_schema)
        if value is not None
    }
    if len(identities) != 1 or len(schemas) != 1:
        raise ValueError("detector_version and score_schema must agree across evidence")

    if regional.abstained or not regional.has_score:
        return _result(
            status=STATUS_INSUFFICIENT,
            abstained=True,
            candidate_supported=False,
            reason=f"regional_gate:{regional.reason}",
            route="manual_review",
            regional=regional,
            calibration=calibration,
            coverage=coverage,
            config=cfg,
        )
    if regional.quality_score is None or regional.quality_score < cfg.minimum_quality:
        return _result(
            status=STATUS_INSUFFICIENT,
            abstained=True,
            candidate_supported=False,
            reason="quality_below_threshold",
            route="manual_review",
            regional=regional,
            calibration=calibration,
            coverage=coverage,
            config=cfg,
        )
    if regional.source_match_score is None or regional.source_match_score < cfg.minimum_source_match:
        return _result(
            status=STATUS_INSUFFICIENT,
            abstained=True,
            candidate_supported=False,
            reason="source_match_below_threshold",
            route="manual_review",
            regional=regional,
            calibration=calibration,
            coverage=coverage,
            config=cfg,
        )
    if regional.coverage_raw is None or regional.coverage_raw < cfg.minimum_coverage:
        return _result(
            status=STATUS_INSUFFICIENT,
            abstained=True,
            candidate_supported=False,
            reason="regional_coverage_below_threshold",
            route="manual_review",
            regional=regional,
            calibration=calibration,
            coverage=coverage,
            config=cfg,
        )
    if not calibration.evaluated:
        return _result(
            status=STATUS_INSUFFICIENT,
            abstained=True,
            candidate_supported=False,
            reason="calibration_unavailable",
            route="manual_review",
            regional=regional,
            calibration=calibration,
            coverage=coverage,
            config=cfg,
        )
    if calibration.null_count < cfg.minimum_null_count:
        return _result(
            status=STATUS_INSUFFICIENT,
            abstained=True,
            candidate_supported=False,
            reason="calibration_support_below_threshold",
            route="manual_review",
            regional=regional,
            calibration=calibration,
            coverage=coverage,
            config=cfg,
        )
    if calibration.fallback != "none" and not cfg.allow_calibration_fallback:
        return _result(
            status=STATUS_INSUFFICIENT,
            abstained=True,
            candidate_supported=False,
            reason="calibration_fallback_not_allowed",
            route="manual_review",
            regional=regional,
            calibration=calibration,
            coverage=coverage,
            config=cfg,
        )
    if coverage.status == STATUS_ABSTAINED:
        return _result(
            status=STATUS_INSUFFICIENT,
            abstained=True,
            candidate_supported=False,
            reason=f"patch_gate:{coverage.reason}",
            route="manual_review",
            regional=regional,
            calibration=calibration,
            coverage=coverage,
            config=cfg,
        )
    if cfg.require_patch_shape and coverage.status == STATUS_AMBIGUOUS:
        return _result(
            status=STATUS_REVIEW,
            abstained=True,
            candidate_supported=False,
            reason=f"patch_shape:{coverage.reason}",
            route="manual_review",
            regional=regional,
            calibration=calibration,
            coverage=coverage,
            config=cfg,
        )
    if not calibration.unknown:
        return _result(
            status=STATUS_NULL_CONSISTENT,
            abstained=False,
            candidate_supported=False,
            reason="ordinary_propagation_null_consistent",
            route="ordinary_propagation_review",
            regional=regional,
            calibration=calibration,
            coverage=coverage,
            config=cfg,
        )
    if coverage.status not in {STATUS_GLOBAL, STATUS_LOCAL}:
        return _result(
            status=STATUS_REVIEW,
            abstained=True,
            candidate_supported=False,
            reason="positive_null_rejection_without_usable_shape",
            route="manual_review",
            regional=regional,
            calibration=calibration,
            coverage=coverage,
            config=cfg,
        )
    return _result(
        status=STATUS_CANDIDATE,
        abstained=False,
        candidate_supported=True,
        reason="ordinary_propagation_null_rejected_with_usable_shape",
        route=coverage.route,
        regional=regional,
        calibration=calibration,
        coverage=coverage,
        config=cfg,
    )


__all__ = [
    "VERSION",
    "STATUS_CANDIDATE",
    "STATUS_NULL_CONSISTENT",
    "STATUS_REVIEW",
    "STATUS_INSUFFICIENT",
    "PCSCFTConfig",
    "PCSCFTResult",
    "decide_pc_scft",
]
