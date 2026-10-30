"""Stable, model-independent contracts for AIGC evidence.

Scores are deliberately represented as observations.  A score becomes a
decision only after a calibration policy is supplied to :mod:`aigc.fusion`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


SCHEMA_VERSION = "aigc_result_v1"


class AIGCStatus(str, Enum):
    HUMAN_SUPPORTED = "human_supported"
    AI_GENERATED_SUPPORTED = "ai_generated_supported"
    AI_EDITED_SUPPORTED = "ai_edited_supported"
    UNKNOWN = "unknown_or_inconclusive"


def _check_score(name: str, value: Optional[float]) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number or None")
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class Evidence:
    """One auditable observation; it is never silently converted to truth."""

    type: str
    status: str
    value: Optional[float] = None
    provider: Optional[str] = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.type or not self.status:
            raise ValueError("evidence type and status are required")
        _check_score("evidence.value", self.value)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"type": self.type, "status": self.status}
        if self.value is not None:
            result["value"] = float(self.value)
        if self.provider:
            result["provider"] = self.provider
        if self.details:
            result["details"] = dict(self.details)
        return result


@dataclass(frozen=True)
class DetectorSignals:
    """Model observations passed to the conservative fusion policy.

    The score fields are raw by default.  A fusion policy will not use them
    for a user-facing decision until the adapter marks them as calibrated and
    supplies the matching score schema.
    """

    ai_score: Optional[float] = None
    artifact_score: Optional[float] = None
    reconstruction_score: Optional[float] = None
    source_match_score: Optional[float] = None
    source_conditioned_edit_score: Optional[float] = None
    quality_score: Optional[float] = None
    model_available: bool = False
    detector_version: str = "unknown"
    score_schema: str = "raw"
    scores_calibrated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.model_available, bool):
            raise ValueError("model_available must be a bool")
        if not isinstance(self.scores_calibrated, bool):
            raise ValueError("scores_calibrated must be a bool")
        if not isinstance(self.detector_version, str) or not self.detector_version.strip():
            raise ValueError("detector_version must be a non-empty string")
        if not isinstance(self.score_schema, str) or not self.score_schema.strip():
            raise ValueError("score_schema must be a non-empty string")
        for name in (
            "ai_score",
            "artifact_score",
            "reconstruction_score",
            "source_match_score",
            "source_conditioned_edit_score",
            "quality_score",
        ):
            _check_score(name, getattr(self, name))

    def observed_scores(self) -> Tuple[Tuple[str, float], ...]:
        names = (
            "ai_score",
            "artifact_score",
            "reconstruction_score",
        )
        return tuple(
            (name, float(value))
            for name in names
            if (value := getattr(self, name)) is not None
        )


@dataclass(frozen=True)
class AIGCResult:
    """Versioned API result shared by model adapters and the Go gateway."""

    status: AIGCStatus
    confidence: Optional[float]
    unknown_reason: Optional[str]
    evidence: Tuple[Evidence, ...] = ()
    generator_hypotheses: Tuple[Mapping[str, Any], ...] = ()
    regions: Tuple[Mapping[str, Any], ...] = ()
    detector_version: str = "unknown"
    calibration_id: str = "un-calibrated"
    schema: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.status, AIGCStatus):
            try:
                object.__setattr__(self, "status", AIGCStatus(self.status))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unsupported AIGC status: {self.status!r}") from exc
        if self.schema != SCHEMA_VERSION:
            raise ValueError(f"unsupported result schema: {self.schema!r}")
        _check_score("confidence", self.confidence)
        if self.status is AIGCStatus.UNKNOWN and not self.unknown_reason:
            raise ValueError("unknown results must include unknown_reason")
        if self.status is not AIGCStatus.UNKNOWN and self.unknown_reason:
            raise ValueError("non-unknown results cannot include unknown_reason")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "status": self.status.value,
            "confidence": self.confidence,
            "unknown_reason": self.unknown_reason,
            "evidence": [item.to_dict() for item in self.evidence],
            "generator_hypotheses": [dict(item) for item in self.generator_hypotheses],
            "regions": [dict(item) for item in self.regions],
            "detector_version": self.detector_version,
            "calibration_id": self.calibration_id,
        }
