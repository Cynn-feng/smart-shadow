"""Compliance-facing provenance labels and contradiction handling.

This layer intentionally stays separate from the forensic four-state result.
It describes what a propagation or audit workflow may safely say about the
available signals.  In particular, an absent provider watermark is not proof
of human authorship, and a provider-specific negative result is not a global
negative result.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from .provenance import ProvenanceReport
from .schema import AIGCResult, AIGCStatus


class ComplianceLabel(str, Enum):
    VERIFIED_AI = "verified_ai"
    USER_DECLARED_AI = "user_declared_ai"
    SUSPECTED_AI = "suspected_ai"
    NO_SIGNAL_OR_UNKNOWN = "no_signal_or_unknown"


WATERMARK_STATUSES = {"positive", "negative", "possible", "missing", "unverified", "error"}


@dataclass(frozen=True)
class WatermarkSignal:
    """A provider-scoped watermark observation.

    ``negative`` only means that this provider's detector did not find its own
    signal.  It must never be interpreted as a global human-authored result.
    """

    provider: str
    status: str
    detector_version: str = "unknown"

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("watermark provider must be a non-empty string")
        if self.status not in WATERMARK_STATUSES:
            raise ValueError(f"unsupported watermark status: {self.status}")
        if not isinstance(self.detector_version, str) or not self.detector_version.strip():
            raise ValueError("watermark detector_version must be non-empty")


@dataclass(frozen=True)
class ComplianceObservation:
    label: ComplianceLabel
    reason: str
    conflicts: Tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "label": self.label.value,
            "reason": self.reason,
            "conflicts": list(self.conflicts),
        }


def classify_compliance(
    provenance: ProvenanceReport,
    *,
    forensic_result: Optional[AIGCResult] = None,
    watermark: Optional[WatermarkSignal] = None,
    user_declared_ai: Optional[bool] = None,
) -> ComplianceObservation:
    """Map evidence to a conservative propagation label.

    The order reflects evidence strength: trusted bound provenance, explicit
    user declaration, then calibrated forensic suspicion.  Contradictions
    involving a trusted non-AI declaration and a positive watermark are
    deliberately returned as unknown for human review.
    """

    positive_watermark = watermark is not None and watermark.status == "positive"
    trusted_ai = provenance.c2pa_status == "valid" and provenance.ai_disclosure is True
    trusted_non_ai = provenance.c2pa_status == "valid" and provenance.ai_disclosure is False
    declared_ai = user_declared_ai if user_declared_ai is not None else provenance.user_declared_ai

    if provenance.errors:
        return ComplianceObservation(
            ComplianceLabel.NO_SIGNAL_OR_UNKNOWN,
            "provenance_error",
        )
    forensic_ai = forensic_result is not None and forensic_result.status in {
        AIGCStatus.AI_GENERATED_SUPPORTED,
        AIGCStatus.AI_EDITED_SUPPORTED,
    }
    if trusted_non_ai and (positive_watermark or declared_ai is True or forensic_ai):
        sources = []
        if positive_watermark:
            sources.append("watermark_positive")
        if declared_ai is True:
            sources.append("user_declared_ai")
        if forensic_ai:
            sources.append("forensic_ai")
        return ComplianceObservation(
            ComplianceLabel.NO_SIGNAL_OR_UNKNOWN,
            "conflicting_trusted_signals",
            tuple(f"trusted_non_ai_vs_{source}" for source in sources),
        )
    if trusted_ai:
        return ComplianceObservation(ComplianceLabel.VERIFIED_AI, "trusted_provenance_ai")
    if declared_ai is True:
        return ComplianceObservation(ComplianceLabel.USER_DECLARED_AI, "user_declaration")
    if positive_watermark:
        return ComplianceObservation(ComplianceLabel.SUSPECTED_AI, "watermark_positive")
    if watermark is not None and watermark.status == "possible":
        return ComplianceObservation(ComplianceLabel.SUSPECTED_AI, "watermark_possible")
    if forensic_ai:
        return ComplianceObservation(ComplianceLabel.SUSPECTED_AI, "calibrated_forensic_signal")
    return ComplianceObservation(ComplianceLabel.NO_SIGNAL_OR_UNKNOWN, "no_reliable_signal")
