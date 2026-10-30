"""Dependency-light operating-point calibration with conservative rejection.

The functions here calibrate a bounded raw score on a held-out validation
stream.  They do not fit a probability model and do not decide legal or
human-authorship questions.  A threshold is only an operating point with a
measured empirical false-positive rate; deployment still needs a frozen
manifest, time/creator split and an explicit review policy.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from bisect import bisect_left
from typing import Any, Dict, Optional, Sequence, Tuple

from .fusion import CalibrationProfile


CALIBRATION_VERSION = "score-operating-point-v1"
NEGATIVE_CONFORMAL_VERSION = "negative-conformal-v1"


def _validate_stream(scores: Sequence[float], labels: Sequence[int]) -> Tuple[Tuple[float, ...], Tuple[int, ...]]:
    if isinstance(scores, (str, bytes)) or isinstance(labels, (str, bytes)):
        raise ValueError("scores and labels must be sequences")
    if len(scores) != len(labels) or not scores:
        raise ValueError("scores and labels must be non-empty and have equal length")
    normalized_scores = []
    normalized_labels = []
    for index, (score, label) in enumerate(zip(scores, labels)):
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValueError(f"scores[{index}] must be a finite number")
        score = float(score)
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError(f"scores[{index}] must be finite and between 0 and 1")
        if isinstance(label, bool) or not isinstance(label, int) or label not in (0, 1):
            raise ValueError(f"labels[{index}] must be 0 or 1")
        normalized_scores.append(score)
        normalized_labels.append(int(label))
    if not any(label == 0 for label in normalized_labels):
        raise ValueError("at least one negative calibration example is required")
    if not any(label == 1 for label in normalized_labels):
        raise ValueError("at least one positive calibration example is required")
    return tuple(normalized_scores), tuple(normalized_labels)


def _digest(scores: Sequence[float], labels: Sequence[int]) -> str:
    payload = json.dumps(
        [{"label": int(label), "score": float(score)} for score, label in zip(scores, labels)],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _negative_score_digest(scores: Sequence[float]) -> str:
    """Hash the frozen negative score stream separately from its manifest.

    ``CalibrationProfile.dataset_digest`` identifies the held-out dataset.  A
    score-stream digest is also retained because a detector/preprocessing
    change can alter scores while leaving the dataset manifest unchanged.
    """

    payload = json.dumps(
        [float(score) for score in scores],
        sort_keys=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_score(name: str, score: float) -> float:
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    normalized = float(score)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return normalized


def _validate_alpha(alpha: float) -> float:
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
        raise ValueError("alpha must be a finite number in (0, 1)")
    normalized = float(alpha)
    if not math.isfinite(normalized) or not 0.0 < normalized < 1.0:
        raise ValueError("alpha must be a finite number in (0, 1)")
    return normalized


@dataclass(frozen=True)
class OperatingPoint:
    """A measured threshold for a single raw detector score."""

    detector_version: str
    score_schema: str
    calibration_id: str
    dataset_digest: str
    target_fpr: float
    threshold: float
    empirical_fpr: float
    validation_recall: float
    negative_count: int
    positive_count: int
    version: str = CALIBRATION_VERSION

    def __post_init__(self) -> None:
        for name in ("target_fpr", "threshold", "empirical_fpr", "validation_recall"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            value = float(value)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and between 0 and 1")
        if not isinstance(self.detector_version, str) or not self.detector_version.strip():
            raise ValueError("detector_version is required")
        if not isinstance(self.score_schema, str) or not self.score_schema.strip():
            raise ValueError("score_schema is required")
        if len(self.dataset_digest) != 64:
            raise ValueError("dataset_digest must be a SHA-256 hex digest")
        try:
            int(self.dataset_digest, 16)
        except ValueError as exc:
            raise ValueError("dataset_digest must be a SHA-256 hex digest") from exc
        if not isinstance(self.negative_count, int) or self.negative_count < 1:
            raise ValueError("negative_count must be positive")
        if not isinstance(self.positive_count, int) or self.positive_count < 1:
            raise ValueError("positive_count must be positive")

    def accepts(self, score: float) -> bool:
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValueError("score must be a finite number")
        score = float(score)
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError("score must be finite and between 0 and 1")
        return score >= self.threshold

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "calibration_id": self.calibration_id,
            "dataset_digest": self.dataset_digest,
            "target_fpr": self.target_fpr,
            "threshold": self.threshold,
            "empirical_fpr": self.empirical_fpr,
            "validation_recall": self.validation_recall,
            "negative_count": self.negative_count,
            "positive_count": self.positive_count,
        }


@dataclass(frozen=True)
class NegativeConformalResult:
    """One-sided negative-class conformal observation.

    ``unknown=True`` means the score is unusual under the held-out negative
    stream at the configured significance level.  It deliberately does not
    mean that the image is AI-generated, and ``unknown=False`` does not prove
    human authorship; callers must keep this observation in the evidence layer
    and combine it with the existing four-state policy.
    """

    score: float
    negative_p_value: float
    alpha: float
    unknown: bool
    unknown_reason: Optional[str]
    detector_version: str
    score_schema: str
    calibration_id: str
    negative_score_digest: str
    negative_count: int
    version: str = NEGATIVE_CONFORMAL_VERSION

    def __post_init__(self) -> None:
        _validate_score("score", self.score)
        p_value = _validate_score("negative_p_value", self.negative_p_value)
        if p_value <= 0.0:
            raise ValueError("negative_p_value must be greater than 0")
        _validate_alpha(self.alpha)
        if not isinstance(self.unknown, bool):
            raise ValueError("unknown must be a bool")
        expected_unknown = p_value <= float(self.alpha)
        if self.unknown != expected_unknown:
            raise ValueError("unknown must equal negative_p_value <= alpha")
        if self.unknown:
            if self.unknown_reason != "negative_conformal_reject":
                raise ValueError(
                    "unknown results must use negative_conformal_reject"
                )
        elif self.unknown_reason is not None:
            raise ValueError("non-unknown results cannot include unknown_reason")
        for name, value in (
            ("detector_version", self.detector_version),
            ("score_schema", self.score_schema),
            ("calibration_id", self.calibration_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
        if len(self.negative_score_digest) != 64:
            raise ValueError("negative_score_digest must be a SHA-256 hex digest")
        try:
            int(self.negative_score_digest, 16)
        except ValueError as exc:
            raise ValueError(
                "negative_score_digest must be a SHA-256 hex digest"
            ) from exc
        if (
            isinstance(self.negative_count, bool)
            or not isinstance(self.negative_count, int)
            or self.negative_count < 1
        ):
            raise ValueError("negative_count must be positive")

    @property
    def consistent_with_negative_stream(self) -> bool:
        """Whether the score was *not* rejected as a negative-class outlier."""

        return not self.unknown

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "score": self.score,
            "negative_p_value": self.negative_p_value,
            "alpha": self.alpha,
            "unknown": self.unknown,
            "unknown_reason": self.unknown_reason,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "calibration_id": self.calibration_id,
            "negative_score_digest": self.negative_score_digest,
            "negative_count": self.negative_count,
        }


@dataclass(frozen=True)
class NegativeConformalProfile:
    """A split-conformal profile fitted only on held-out negative scores.

    For a high-is-AI score, the valid one-sided negative p-value is
    ``(1 + count(negative_score >= query_score)) / (n + 1)``.  The additive
    correction is retained so even a query above every calibration negative
    receives a non-zero, finite p-value.  The profile references the existing
    :class:`CalibrationProfile` for detector/schema/calibration identity; it
    does not silently create a new calibration identity.
    """

    calibration: CalibrationProfile
    negative_scores: Tuple[float, ...]
    alpha: float = 0.05
    version: str = NEGATIVE_CONFORMAL_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.calibration, CalibrationProfile):
            raise ValueError("calibration must be a CalibrationProfile")
        if isinstance(self.negative_scores, (str, bytes)):
            raise ValueError("negative_scores must be a non-empty sequence")
        try:
            normalized = tuple(
                sorted(
                    _validate_score("negative_scores", score)
                    for score in self.negative_scores
                )
            )
        except TypeError as exc:
            raise ValueError("negative_scores must be a non-empty sequence") from exc
        if not normalized:
            raise ValueError("negative_scores must be a non-empty sequence")
        object.__setattr__(self, "negative_scores", normalized)
        object.__setattr__(self, "alpha", _validate_alpha(self.alpha))
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("version is required")

    @classmethod
    def from_scores(
        cls,
        negative_scores: Sequence[float],
        *,
        calibration: CalibrationProfile,
        alpha: float = 0.05,
    ) -> "NegativeConformalProfile":
        return cls(
            calibration=calibration,
            negative_scores=tuple(negative_scores),
            alpha=alpha,
        )

    @property
    def negative_score_digest(self) -> str:
        return _negative_score_digest(self.negative_scores)

    def assert_compatible(
        self,
        *,
        detector_version: Optional[str] = None,
        score_schema: Optional[str] = None,
        calibration_id: Optional[str] = None,
    ) -> None:
        """Reject runtime metadata that does not match the frozen profile."""

        expected = self.calibration
        if detector_version is not None and detector_version != expected.detector_version:
            raise ValueError("detector_version does not match conformal calibration")
        if score_schema is not None and score_schema != expected.score_schema:
            raise ValueError("score_schema does not match conformal calibration")
        if calibration_id is not None and calibration_id != expected.calibration_id:
            raise ValueError("calibration_id does not match conformal calibration")

    def negative_p_value(self, score: float) -> float:
        """Return the conservative one-sided p-value for a raw score."""

        score = _validate_score("score", score)
        # ``bisect_left`` counts values strictly below score; all remaining
        # calibration negatives are ties or exceedances and belong in the tail.
        below = bisect_left(self.negative_scores, score)
        exceedances = len(self.negative_scores) - below
        return (1.0 + exceedances) / (len(self.negative_scores) + 1.0)

    def evaluate(
        self,
        score: float,
        *,
        detector_version: Optional[str] = None,
        score_schema: Optional[str] = None,
        calibration_id: Optional[str] = None,
    ) -> NegativeConformalResult:
        """Evaluate a score and abstain when it is rejected as negative."""

        self.assert_compatible(
            detector_version=detector_version,
            score_schema=score_schema,
            calibration_id=calibration_id,
        )
        score = _validate_score("score", score)
        p_value = self.negative_p_value(score)
        unknown = p_value <= self.alpha
        return NegativeConformalResult(
            score=score,
            negative_p_value=p_value,
            alpha=self.alpha,
            unknown=unknown,
            unknown_reason="negative_conformal_reject" if unknown else None,
            detector_version=self.calibration.detector_version,
            score_schema=self.calibration.score_schema,
            calibration_id=self.calibration.calibration_id,
            negative_score_digest=self.negative_score_digest,
            negative_count=len(self.negative_scores),
            version=self.version,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "calibration_id": self.calibration.calibration_id,
            "detector_version": self.calibration.detector_version,
            "score_schema": self.calibration.score_schema,
            "dataset_digest": self.calibration.dataset_digest,
            "negative_score_digest": self.negative_score_digest,
            "negative_count": len(self.negative_scores),
            "alpha": self.alpha,
        }


def fit_negative_conformal_profile(
    negative_scores: Sequence[float],
    *,
    calibration: CalibrationProfile,
    alpha: float = 0.05,
) -> NegativeConformalProfile:
    """Fit a negative-only conformal profile against an existing calibration.

    The caller must pass scores from the held-out negative stream identified by
    ``calibration.dataset_digest``.  This function stores a separate score
    digest so preprocessing or detector drift is visible during audit.
    """

    return NegativeConformalProfile.from_scores(
        negative_scores,
        calibration=calibration,
        alpha=alpha,
    )


def evaluate_negative_conformal(
    score: float,
    profile: NegativeConformalProfile,
    *,
    detector_version: Optional[str] = None,
    score_schema: Optional[str] = None,
    calibration_id: Optional[str] = None,
) -> NegativeConformalResult:
    """Functional wrapper for adapters that do not retain profile methods."""

    if not isinstance(profile, NegativeConformalProfile):
        raise ValueError("profile must be a NegativeConformalProfile")
    return profile.evaluate(
        score,
        detector_version=detector_version,
        score_schema=score_schema,
        calibration_id=calibration_id,
    )


def fit_conservative_ai_threshold(
    scores: Sequence[float],
    labels: Sequence[int],
    *,
    detector_version: str,
    score_schema: str,
    target_fpr: float = 0.01,
) -> OperatingPoint:
    """Choose the lowest empirical threshold whose negative FPR is bounded.

    Ties at the largest negative score are moved one representable float above
    that score when `target_fpr=0`, preventing a negative tie from being
    counted as an AI positive.  The returned recall is validation-only and
    must be reported alongside the operating point.
    """

    if isinstance(target_fpr, bool) or not isinstance(target_fpr, (int, float)):
        raise ValueError("target_fpr must be a finite number in [0, 1)")
    target_fpr = float(target_fpr)
    if not math.isfinite(target_fpr) or not 0.0 <= target_fpr < 1.0:
        raise ValueError("target_fpr must be a finite number in [0, 1)")
    normalized_scores, normalized_labels = _validate_stream(scores, labels)
    negatives = [score for score, label in zip(normalized_scores, normalized_labels) if label == 0]
    positives = [score for score, label in zip(normalized_scores, normalized_labels) if label == 1]
    candidates = sorted(set(negatives + positives))
    threshold = None
    for candidate in candidates:
        fpr = sum(score >= candidate for score in negatives) / len(negatives)
        if fpr <= target_fpr:
            threshold = candidate
            break
    if threshold is None:
        threshold = math.nextafter(max(negatives), 1.0)
    empirical_fpr = sum(score >= threshold for score in negatives) / len(negatives)
    validation_recall = sum(score >= threshold for score in positives) / len(positives)
    digest = _digest(normalized_scores, normalized_labels)
    calibration_id = f"{detector_version}:{digest[:16]}:fpr-{target_fpr:g}"
    return OperatingPoint(
        detector_version=detector_version,
        score_schema=score_schema,
        calibration_id=calibration_id,
        dataset_digest=digest,
        target_fpr=target_fpr,
        threshold=threshold,
        empirical_fpr=empirical_fpr,
        validation_recall=validation_recall,
        negative_count=len(negatives),
        positive_count=len(positives),
    )
