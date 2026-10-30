"""Conservative fusion and abstention policy for AIGC evidence."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Optional, Sequence, Tuple

from .provenance import ProvenanceReport
from .schema import AIGCResult, AIGCStatus, DetectorSignals, Evidence


@dataclass(frozen=True)
class CalibrationProfile:
    """A held-out calibration identity required for model-only decisions.

    The profile is intentionally explicit: an arbitrary string must not be
    enough to turn a raw detector score into a user-facing conclusion.
    ``dataset_digest`` is the manifest/hash of the calibration data, not a
    claim that the model is universally valid.
    """

    calibration_id: str
    detector_version: str
    score_schema: str
    dataset_digest: str
    min_negative_streams: int = 2

    def __post_init__(self) -> None:
        if not self.calibration_id or self.calibration_id == "un-calibrated":
            raise ValueError("calibration_id must identify a held-out calibration")
        if not self.detector_version or not self.score_schema:
            raise ValueError("detector_version and score_schema are required")
        if len(self.dataset_digest) != 64:
            raise ValueError("dataset_digest must be a SHA-256 hex digest")
        try:
            int(self.dataset_digest, 16)
        except ValueError as exc:
            raise ValueError("dataset_digest must be a SHA-256 hex digest") from exc
        if (
            isinstance(self.min_negative_streams, bool)
            or not isinstance(self.min_negative_streams, int)
            or self.min_negative_streams < 1
        ):
            raise ValueError("min_negative_streams must be positive")


@dataclass(frozen=True)
class FusionPolicy:
    """Operating points learned outside the code and supplied at runtime."""

    ai_threshold: float = 0.80
    human_threshold: float = 0.20
    edit_threshold: float = 0.80
    source_match_threshold: float = 0.75
    minimum_quality: float = 0.35
    calibration: Optional[CalibrationProfile] = None
    require_region_evidence_for_edit: bool = True
    require_quality_for_edit: bool = True

    def __post_init__(self) -> None:
        if self.calibration is not None and not isinstance(self.calibration, CalibrationProfile):
            raise ValueError("calibration must be a CalibrationProfile")
        if not isinstance(self.require_region_evidence_for_edit, bool):
            raise ValueError("require_region_evidence_for_edit must be a bool")
        if not isinstance(self.require_quality_for_edit, bool):
            raise ValueError("require_quality_for_edit must be a bool")
        values = (
            self.ai_threshold,
            self.human_threshold,
            self.edit_threshold,
            self.source_match_threshold,
            self.minimum_quality,
        )
        if any(
            not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value < 0
            or value > 1
            for value in values
        ):
            raise ValueError("fusion thresholds must be finite numbers between 0 and 1")
        if self.human_threshold >= self.ai_threshold:
            raise ValueError("human_threshold must be lower than ai_threshold")

    @property
    def calibration_id(self) -> str:
        return self.calibration.calibration_id if self.calibration else "un-calibrated"

    def accepts_model(self, signals: DetectorSignals) -> bool:
        return bool(
            self.calibration
            and signals.model_available
            and signals.detector_version == self.calibration.detector_version
            and signals.scores_calibrated
            and signals.score_schema == self.calibration.score_schema
        )


def _signal_evidence(signals: DetectorSignals) -> Tuple[Evidence, ...]:
    result = []
    for name, value in signals.observed_scores():
        result.append(Evidence(type=name, status="observed", value=value))
    if signals.source_match_score is not None:
        result.append(
            Evidence(
                type="source_match_score",
                status="observed",
                value=signals.source_match_score,
            )
        )
    if signals.source_conditioned_edit_score is not None:
        result.append(
            Evidence(
                type="source_conditioned_edit_score",
                status="observed",
                value=signals.source_conditioned_edit_score,
            )
        )
    if signals.quality_score is not None:
        result.append(
            Evidence(type="quality_score", status="observed", value=signals.quality_score)
        )
    return tuple(result)


def _weighted_score(signals: DetectorSignals) -> Optional[float]:
    weights = {
        "ai_score": 0.45,
        "artifact_score": 0.35,
        "reconstruction_score": 0.20,
    }
    observed = signals.observed_scores()
    if not observed:
        return None
    numerator = sum(weights[name] * value for name, value in observed)
    denominator = sum(weights[name] for name, _ in observed)
    return numerator / denominator


def _unknown(
    reason: str,
    evidence: Tuple[Evidence, ...],
    signals: DetectorSignals,
    policy: FusionPolicy,
    *,
    regions: Sequence[Mapping[str, Any]] = (),
    generator_hypotheses: Sequence[Mapping[str, Any]] = (),
) -> AIGCResult:
    return AIGCResult(
        status=AIGCStatus.UNKNOWN,
        confidence=None,
        unknown_reason=reason,
        evidence=evidence,
        regions=tuple(regions),
        generator_hypotheses=tuple(generator_hypotheses),
        detector_version=signals.detector_version,
        calibration_id=policy.calibration_id,
    )


def _with_provenance_errors(
    provenance: ProvenanceReport, signals: DetectorSignals
) -> Tuple[Evidence, ...]:
    result = list(provenance.evidence)
    result.extend(_signal_evidence(signals))
    result.extend(
        Evidence(
            type="provenance_error",
            status="observed",
            details={"error": error},
        )
        for error in provenance.errors
    )
    return tuple(result)


def fuse_signals(
    provenance: ProvenanceReport,
    signals: DetectorSignals,
    policy: FusionPolicy,
    *,
    regions: Sequence[Mapping[str, Any]] = (),
    generator_hypotheses: Sequence[Mapping[str, Any]] = (),
) -> AIGCResult:
    """Fuse evidence without allowing missing signals to become ``human``."""

    evidence = _with_provenance_errors(provenance, signals)
    if provenance.errors:
        return _unknown(
            "provenance_error",
            evidence,
            signals,
            policy,
            regions=regions,
            generator_hypotheses=generator_hypotheses,
        )

    score = _weighted_score(signals)
    calibrated_visual_negative = (
        score is not None
        and score <= policy.human_threshold
        and policy.accepts_model(signals)
    )

    # A cryptographically verified AI disclosure is a source assertion, not a
    # detector probability.  Confidence remains null because no calibrated
    # visual probability was produced.
    if provenance.c2pa_status == "valid" and provenance.ai_disclosure is True:
        if calibrated_visual_negative:
            return _unknown(
                "conflicting_evidence",
                evidence,
                signals,
                policy,
                regions=regions,
                generator_hypotheses=generator_hypotheses,
            )
        status = (
            AIGCStatus.AI_EDITED_SUPPORTED
            if provenance.ai_edit is True
            else AIGCStatus.AI_GENERATED_SUPPORTED
        )
        return AIGCResult(
            status=status,
            confidence=None,
            unknown_reason=None,
            evidence=evidence,
            regions=tuple(regions),
            generator_hypotheses=tuple(generator_hypotheses),
            detector_version=signals.detector_version,
            calibration_id=policy.calibration_id,
        )

    has_any_model_signal = score is not None or signals.source_conditioned_edit_score is not None
    if not signals.model_available:
        return _unknown(
            "model_unavailable",
            evidence,
            signals,
            policy,
            regions=regions,
            generator_hypotheses=generator_hypotheses,
        )
    if not has_any_model_signal:
        return _unknown(
            "no_model_signal",
            evidence,
            signals,
            policy,
            regions=regions,
            generator_hypotheses=generator_hypotheses,
        )
    if not policy.accepts_model(signals):
        reason = "uncalibrated_model" if (
            policy.calibration is None or not signals.scores_calibrated
        ) else "calibration_mismatch"
        return _unknown(
            reason,
            evidence,
            signals,
            policy,
            regions=regions,
            generator_hypotheses=generator_hypotheses,
        )
    if signals.quality_score is not None and signals.quality_score < policy.minimum_quality:
        return _unknown(
            "low_quality",
            evidence,
            signals,
            policy,
            regions=regions,
            generator_hypotheses=generator_hypotheses,
        )

    # Any invalid/unverified positive provenance observation conflicts with a
    # negative visual score.  It must not be silently rendered as human.
    positive_unverified = provenance.ai_disclosure is True and provenance.c2pa_status != "valid"
    invalid_source = provenance.c2pa_status == "invalid"
    if score is not None and score <= policy.human_threshold and (positive_unverified or invalid_source):
        return _unknown(
            "conflicting_evidence",
            evidence,
            signals,
            policy,
            regions=regions,
            generator_hypotheses=generator_hypotheses,
        )
    signed_non_ai = provenance.c2pa_status == "valid" and provenance.ai_disclosure is False
    if score is not None and score >= policy.ai_threshold and signed_non_ai:
        return _unknown(
            "conflicting_evidence",
            evidence,
            signals,
            policy,
            regions=regions,
            generator_hypotheses=generator_hypotheses,
        )

    if signals.source_conditioned_edit_score is not None:
        if policy.require_quality_for_edit and signals.quality_score is None:
            return _unknown(
                "missing_quality",
                evidence,
                signals,
                policy,
                regions=regions,
                generator_hypotheses=generator_hypotheses,
            )
        source_match = signals.source_match_score or 0.0
        if (
            signals.source_conditioned_edit_score >= policy.edit_threshold
            and source_match >= policy.source_match_threshold
        ):
            if policy.require_region_evidence_for_edit and not regions:
                return _unknown(
                    "missing_region_evidence",
                    evidence,
                    signals,
                    policy,
                    regions=regions,
                    generator_hypotheses=generator_hypotheses,
                )
            return AIGCResult(
                status=AIGCStatus.AI_EDITED_SUPPORTED,
                confidence=float(signals.source_conditioned_edit_score),
                unknown_reason=None,
                evidence=evidence,
                regions=tuple(regions),
                generator_hypotheses=tuple(generator_hypotheses),
                detector_version=signals.detector_version,
                calibration_id=policy.calibration_id,
            )

    if score is None:
        return _unknown(
            "no_model_signal",
            evidence,
            signals,
            policy,
            regions=regions,
            generator_hypotheses=generator_hypotheses,
        )

    if score >= policy.ai_threshold:
        status = AIGCStatus.AI_GENERATED_SUPPORTED
        reason = None
    elif score <= policy.human_threshold:
        observed_count = len(signals.observed_scores())
        has_signed_non_ai_source = signed_non_ai
        enough_negative_evidence = (
            has_signed_non_ai_source
            and policy.calibration is not None
            and observed_count >= policy.calibration.min_negative_streams
        )
        if not enough_negative_evidence:
            return _unknown(
                "insufficient_negative_evidence",
                evidence,
                signals,
                policy,
                regions=regions,
                generator_hypotheses=generator_hypotheses,
            )
        status = AIGCStatus.HUMAN_SUPPORTED
        reason = None
    else:
        status = AIGCStatus.UNKNOWN
        reason = "low_margin"

    return AIGCResult(
        status=status,
        confidence=round(float(score), 6),
        unknown_reason=reason,
        evidence=evidence,
        regions=tuple(regions),
        generator_hypotheses=tuple(generator_hypotheses),
        detector_version=signals.detector_version,
        calibration_id=policy.calibration_id,
    )
