"""Policy-level calibration for the A9 sequential evidence strategy.

Single-probe conformal values do not automatically remain valid after a
policy adaptively chooses more probes.  This module therefore treats a whole
ordinary-propagation replay as one calibration unit and reports only the
empirical false-positive rate (FPR) of that policy, with a finite-sample
Wilson confidence interval.  The output contains no detector score and no
AIGC probability.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from statistics import NormalDist
from typing import Any, Iterable, Optional, Sequence, Tuple, Union

from .sequential_evidence import (
    ROUTE_CANDIDATE,
    ROUTE_CONFLICT_REVIEW,
    ROUTE_INSUFFICIENT,
    ROUTE_NULL_CONSISTENT,
    ROUTE_REVIEW,
    SequentialEvidenceResult,
)


VERSION = "policy-calibration-v1"
PROFILE_SCHEMA = "ordinary-propagation-policy-null-profile-v1"
RESULT_SCHEMA = "ordinary-propagation-policy-fpr-result-v1"
ORDINARY_PROPAGATION = "ordinary_propagation"

_ROUTES = {
    ROUTE_CANDIDATE,
    ROUTE_NULL_CONSISTENT,
    ROUTE_CONFLICT_REVIEW,
    ROUTE_REVIEW,
    ROUTE_INSUFFICIENT,
}


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _hex_digest(name: str, value: str) -> str:
    value = _text(name, value)
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
    return value.lower()


def _unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite and between 0 and 1")
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return value


def _alpha(name: str, value: float) -> float:
    value = _unit(name, value)
    if value <= 0.0 or value >= 1.0:
        raise ValueError(f"{name} must be strictly between 0 and 1")
    return value


def _nonnegative_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class PolicyNullExample:
    """One complete replay on an ordinary-propagation null group.

    A candidate route is counted as a policy false positive.  ``raw score``
    is intentionally absent: an adaptive policy is calibrated from its final
    route and audit trace, not by interpreting any intermediate score as a
    probability.
    """

    group_id: str
    route: str
    abstained: bool
    policy_digest: str
    transform_family: str = ORDINARY_PROPAGATION
    quality_score: float = 1.0
    step_count: int = 0
    spent_cost: int = 0
    evidence_digest: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_id", _text("group_id", self.group_id))
        route = _text("route", self.route)
        if route not in _ROUTES:
            raise ValueError("invalid policy null route")
        object.__setattr__(self, "route", route)
        if not isinstance(self.abstained, bool):
            raise ValueError("abstained must be bool")
        if route in {ROUTE_CANDIDATE, ROUTE_NULL_CONSISTENT} and self.abstained:
            raise ValueError("concordant route cannot be abstained")
        if route in {ROUTE_CONFLICT_REVIEW, ROUTE_REVIEW, ROUTE_INSUFFICIENT} and not self.abstained:
            raise ValueError("review/insufficient route must abstain")
        object.__setattr__(self, "policy_digest", _hex_digest("policy_digest", self.policy_digest))
        object.__setattr__(self, "transform_family", _text("transform_family", self.transform_family))
        _unit("quality_score", self.quality_score)
        _nonnegative_int("step_count", self.step_count)
        _nonnegative_int("spent_cost", self.spent_cost)
        if self.evidence_digest is not None:
            _hex_digest("evidence_digest", self.evidence_digest)

    @property
    def false_positive(self) -> bool:
        return self.route == ROUTE_CANDIDATE and not self.abstained

    @classmethod
    def from_result(
        cls,
        group_id: str,
        result: SequentialEvidenceResult,
        *,
        transform_family: str = ORDINARY_PROPAGATION,
        quality_score: float = 1.0,
    ) -> "PolicyNullExample":
        if not isinstance(result, SequentialEvidenceResult):
            raise ValueError("result must be SequentialEvidenceResult")
        return cls(
            group_id=group_id,
            route=result.route,
            abstained=result.abstained,
            policy_digest=result.policy_digest,
            transform_family=transform_family,
            quality_score=quality_score,
            step_count=len(result.steps),
            spent_cost=result.spent_cost,
            evidence_digest=result.evidence_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "route": self.route,
            "abstained": self.abstained,
            "policy_digest": self.policy_digest,
            "transform_family": self.transform_family,
            "quality_score": self.quality_score,
            "step_count": self.step_count,
            "spent_cost": self.spent_cost,
            "evidence_digest": self.evidence_digest,
            "false_positive": self.false_positive,
        }


@dataclass(frozen=True)
class PolicyNullProfile:
    """Frozen policy-level ordinary-propagation null replay profile."""

    policy_digest: str
    group_ids: Tuple[str, ...]
    routes: Tuple[str, ...]
    false_positive_flags: Tuple[bool, ...]
    dataset_digest: str
    transform_family: str = ORDINARY_PROPAGATION
    profile_version: str = VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_digest", _hex_digest("policy_digest", self.policy_digest))
        group_ids = tuple(_text("group_id", item) for item in self.group_ids)
        routes = tuple(_text("route", item) for item in self.routes)
        flags = tuple(self.false_positive_flags)
        if not group_ids or len(group_ids) != len(routes) or len(routes) != len(flags):
            raise ValueError("group_ids, routes and false_positive_flags must be non-empty and aligned")
        if len(set(group_ids)) != len(group_ids):
            raise ValueError("group_ids must be unique")
        if any(route not in _ROUTES for route in routes):
            raise ValueError("invalid route in profile")
        if any(not isinstance(flag, bool) for flag in flags):
            raise ValueError("false_positive_flags must contain bool values")
        if any(flag != (route == ROUTE_CANDIDATE) for flag, route in zip(flags, routes)):
            raise ValueError("false_positive_flags must equal candidate routes")
        object.__setattr__(self, "group_ids", group_ids)
        object.__setattr__(self, "routes", routes)
        object.__setattr__(self, "false_positive_flags", flags)
        _hex_digest("dataset_digest", self.dataset_digest)
        object.__setattr__(self, "transform_family", _text("transform_family", self.transform_family))
        object.__setattr__(self, "profile_version", _text("profile_version", self.profile_version))

    @property
    def count(self) -> int:
        return len(self.group_ids)

    @property
    def false_positive_count(self) -> int:
        return sum(self.false_positive_flags)

    @property
    def profile_digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "version": self.profile_version,
            "profile_schema": PROFILE_SCHEMA,
            "policy_digest": self.policy_digest,
            "group_ids": list(self.group_ids),
            "routes": list(self.routes),
            "false_positive_flags": list(self.false_positive_flags),
            "false_positive_count": self.false_positive_count,
            "null_count": self.count,
            "dataset_digest": self.dataset_digest,
            "transform_family": self.transform_family,
        }
        if include_digest:
            result["profile_digest"] = self.profile_digest
        return result


@dataclass(frozen=True)
class PolicyCalibrationConfig:
    """Finite-sample gates for policy-level empirical FPR."""

    alpha: float = 0.05
    minimum_null_count: int = 20
    minimum_quality: float = 0.0
    require_ordinary_propagation: bool = True
    version: str = VERSION

    def __post_init__(self) -> None:
        _alpha("alpha", self.alpha)
        _nonnegative_int("minimum_null_count", self.minimum_null_count)
        if self.minimum_null_count < 1:
            raise ValueError("minimum_null_count must be positive")
        _unit("minimum_quality", self.minimum_quality)
        if not isinstance(self.require_ordinary_propagation, bool):
            raise ValueError("require_ordinary_propagation must be bool")
        _text("version", self.version)

    @property
    def confidence_level(self) -> float:
        return 1.0 - self.alpha

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "alpha": self.alpha,
            "minimum_null_count": self.minimum_null_count,
            "minimum_quality": self.minimum_quality,
            "require_ordinary_propagation": self.require_ordinary_propagation,
        }

    @property
    def config_digest(self) -> str:
        return _digest(self.to_dict())

    @property
    def digest(self) -> str:
        return self.config_digest


@dataclass(frozen=True)
class PolicyCalibrationResult:
    """Empirical policy FPR and confidence interval, or an explicit refusal."""

    evaluated: bool
    reason: str
    policy_digest: str
    profile_digest: Optional[str]
    null_count: int
    false_positive_count: int
    empirical_fpr: Optional[float]
    ci_low: Optional[float]
    ci_high: Optional[float]
    confidence_level: float
    interval_method: str
    config_digest: str
    evidence_digest: str
    version: str = VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.evaluated, bool):
            raise ValueError("evaluated must be bool")
        _text("reason", self.reason)
        _hex_digest("policy_digest", self.policy_digest)
        if self.profile_digest is not None:
            _hex_digest("profile_digest", self.profile_digest)
        _nonnegative_int("null_count", self.null_count)
        _nonnegative_int("false_positive_count", self.false_positive_count)
        if self.false_positive_count > self.null_count:
            raise ValueError("false_positive_count cannot exceed null_count")
        _unit("confidence_level", self.confidence_level)
        _text("interval_method", self.interval_method)
        _hex_digest("config_digest", self.config_digest)
        _hex_digest("evidence_digest", self.evidence_digest)
        values = (self.empirical_fpr, self.ci_low, self.ci_high)
        if self.evaluated:
            if any(value is None for value in values):
                raise ValueError("evaluated result requires FPR and confidence interval")
            for name, value in zip(("empirical_fpr", "ci_low", "ci_high"), values):
                _unit(name, value)  # type: ignore[arg-type]
            if self.ci_low > self.empirical_fpr or self.empirical_fpr > self.ci_high:  # type: ignore[operator]
                raise ValueError("FPR must lie within confidence interval")
        elif any(value is not None for value in values):
            raise ValueError("unevaluated result cannot carry FPR values")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "result_schema": RESULT_SCHEMA,
            "evaluated": self.evaluated,
            "reason": self.reason,
            "policy_digest": self.policy_digest,
            "profile_digest": self.profile_digest,
            "null_count": self.null_count,
            "false_positive_count": self.false_positive_count,
            "empirical_fpr": self.empirical_fpr,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "confidence_level": self.confidence_level,
            "interval_method": self.interval_method,
            "config_digest": self.config_digest,
            "evidence_digest": self.evidence_digest,
        }


def policy_null_example_from_result(
    group_id: str,
    result: SequentialEvidenceResult,
    *,
    transform_family: str = ORDINARY_PROPAGATION,
    quality_score: float = 1.0,
) -> PolicyNullExample:
    return PolicyNullExample.from_result(
        group_id,
        result,
        transform_family=transform_family,
        quality_score=quality_score,
    )


def fit_policy_null_profile(
    examples: Iterable[PolicyNullExample],
    *,
    policy_digest: Optional[str] = None,
    dataset_digest: Optional[str] = None,
    minimum_quality: float = 0.0,
    require_ordinary_propagation: bool = True,
    minimum_count: int = 1,
) -> PolicyNullProfile:
    """Freeze complete ordinary-propagation replays for one exact policy."""

    if isinstance(examples, (str, bytes)):
        raise ValueError("examples must be an iterable of PolicyNullExample")
    items = tuple(examples)
    if not items or any(not isinstance(item, PolicyNullExample) for item in items):
        raise ValueError("examples must contain PolicyNullExample values")
    _unit("minimum_quality", minimum_quality)
    _nonnegative_int("minimum_count", minimum_count)
    if minimum_count < 1:
        raise ValueError("minimum_count must be positive")
    if policy_digest is not None:
        policy_digest = _hex_digest("policy_digest", policy_digest)
    accepted = []
    for item in items:
        if require_ordinary_propagation and item.transform_family != ORDINARY_PROPAGATION:
            raise ValueError("policy null profile requires ordinary_propagation examples")
        if item.quality_score >= minimum_quality:
            accepted.append(item)
    if len(accepted) < minimum_count:
        raise ValueError("insufficient_policy_null_examples")
    if len({item.group_id for item in accepted}) != len(accepted):
        raise ValueError("group_id values must be unique")
    observed_policy_digests = {item.policy_digest for item in accepted}
    if policy_digest is not None and observed_policy_digests != {policy_digest}:
        raise ValueError("policy_digest_mismatch")
    if len(observed_policy_digests) != 1:
        raise ValueError("all null examples must use one policy digest")
    accepted = sorted(accepted, key=lambda item: item.group_id)
    if dataset_digest is None:
        dataset_digest = _digest([item.to_dict() for item in accepted])
    else:
        dataset_digest = _hex_digest("dataset_digest", dataset_digest)
    return PolicyNullProfile(
        policy_digest=next(iter(observed_policy_digests)),
        group_ids=tuple(item.group_id for item in accepted),
        routes=tuple(item.route for item in accepted),
        false_positive_flags=tuple(item.false_positive for item in accepted),
        dataset_digest=dataset_digest,
    )


def _wilson_interval(successes: int, trials: int, *, alpha: float) -> Tuple[float, float]:
    if trials < 1:
        raise ValueError("trials must be positive")
    if successes < 0 or successes > trials:
        raise ValueError("successes must be between zero and trials")
    z = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    estimate = successes / trials
    denominator = 1.0 + z * z / trials
    center = (estimate + z * z / (2.0 * trials)) / denominator
    radius = z * math.sqrt((estimate * (1.0 - estimate) / trials) + z * z / (4.0 * trials * trials)) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


def evaluate_policy_fpr(
    profile: Optional[PolicyNullProfile],
    *,
    config: Optional[PolicyCalibrationConfig] = None,
    policy_digest: Optional[str] = None,
) -> PolicyCalibrationResult:
    """Evaluate empirical FPR for a whole replay policy.

    ``empirical_fpr`` is a frequency over ordinary null groups.  It is not a
    probability assigned to any individual image, and the result carries no
    score-to-probability conversion.
    """

    cfg = config or PolicyCalibrationConfig()
    expected_policy = policy_digest or (profile.policy_digest if profile is not None else None)
    if expected_policy is None:
        raise ValueError("policy_digest is required when profile is unavailable")
    expected_policy = _hex_digest("policy_digest", expected_policy)
    profile_digest = profile.profile_digest if profile is not None else None
    if profile is None:
        reason = "profile_unavailable"
        count = 0
        false_positives = 0
    elif profile.policy_digest != expected_policy:
        reason = "policy_digest_mismatch"
        count = profile.count
        false_positives = profile.false_positive_count
    elif cfg.require_ordinary_propagation and profile.transform_family != ORDINARY_PROPAGATION:
        reason = "ordinary_null_required"
        count = profile.count
        false_positives = profile.false_positive_count
    elif profile.count < cfg.minimum_null_count:
        reason = "insufficient_policy_null_support"
        count = profile.count
        false_positives = profile.false_positive_count
    else:
        reason = "evaluated"
        count = profile.count
        false_positives = profile.false_positive_count
    if reason != "evaluated":
        evidence_digest = _digest({
            "version": VERSION,
            "reason": reason,
            "policy_digest": expected_policy,
            "profile_digest": profile_digest,
            "config_digest": cfg.config_digest,
        })
        return PolicyCalibrationResult(
            evaluated=False,
            reason=reason,
            policy_digest=expected_policy,
            profile_digest=profile_digest,
            null_count=count,
            false_positive_count=false_positives,
            empirical_fpr=None,
            ci_low=None,
            ci_high=None,
            confidence_level=cfg.confidence_level,
            interval_method="wilson",
            config_digest=cfg.config_digest,
            evidence_digest=evidence_digest,
        )
    empirical = false_positives / count
    ci_low, ci_high = _wilson_interval(false_positives, count, alpha=cfg.alpha)
    evidence_digest = _digest({
        "version": VERSION,
        "policy_digest": expected_policy,
        "profile": profile.to_dict(),
        "config_digest": cfg.config_digest,
        "empirical_fpr": empirical,
        "ci_low": ci_low,
        "ci_high": ci_high,
    })
    return PolicyCalibrationResult(
        evaluated=True,
        reason=reason,
        policy_digest=expected_policy,
        profile_digest=profile_digest,
        null_count=count,
        false_positive_count=false_positives,
        empirical_fpr=empirical,
        ci_low=ci_low,
        ci_high=ci_high,
        confidence_level=cfg.confidence_level,
        interval_method="wilson",
        config_digest=cfg.config_digest,
        evidence_digest=evidence_digest,
    )


def fit_and_evaluate_policy_fpr(
    examples: Iterable[PolicyNullExample],
    *,
    config: Optional[PolicyCalibrationConfig] = None,
    policy_digest: Optional[str] = None,
) -> Tuple[PolicyNullProfile, PolicyCalibrationResult]:
    cfg = config or PolicyCalibrationConfig()
    profile = fit_policy_null_profile(
        examples,
        policy_digest=policy_digest,
        minimum_quality=cfg.minimum_quality,
        require_ordinary_propagation=cfg.require_ordinary_propagation,
        minimum_count=1,
    )
    result = evaluate_policy_fpr(profile, config=cfg, policy_digest=profile.policy_digest)
    return profile, result


# Friendly aliases for callers using the terminology from the design notes.
PolicyNullTrace = PolicyNullExample
PolicyFPRResult = PolicyCalibrationResult
fit_policy_calibration = fit_policy_null_profile
evaluate_policy_null = evaluate_policy_fpr


__all__ = [
    "VERSION",
    "PROFILE_SCHEMA",
    "RESULT_SCHEMA",
    "ORDINARY_PROPAGATION",
    "PolicyNullExample",
    "PolicyNullTrace",
    "PolicyNullProfile",
    "PolicyCalibrationConfig",
    "PolicyCalibrationResult",
    "PolicyFPRResult",
    "policy_null_example_from_result",
    "fit_policy_null_profile",
    "evaluate_policy_fpr",
    "fit_and_evaluate_policy_fpr",
    "fit_policy_calibration",
    "evaluate_policy_null",
]
