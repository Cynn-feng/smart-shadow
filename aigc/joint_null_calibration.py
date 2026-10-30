"""Dependency-aware joint null calibration for multiple evidence streams.

Independent Bonferroni intersections are deliberately conservative, but they
can reject useful cases in which two streams provide moderate, concordant
evidence.  This module learns the *joint* ordinary-propagation null from
group-matched examples and calibrates a Cauchy combination statistic
empirically.  The empirical profile preserves dependence between streams;
the output remains a selective raw-evidence route, never an AIGC probability.

The profile must be built from ordinary-propagation groups that are disjoint
from the query groups.  Missing streams, duplicate groups, insufficient null
support, and excessive p-value disagreement fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


VERSION = "joint-stream-null-calibration-v1"
PROFILE_SCHEMA = "joint-stream-null-profile-v1"
RESULT_SCHEMA = "joint-stream-null-result-v1"

ROUTE_CANDIDATE = "candidate_edit"
ROUTE_NULL_CONSISTENT = "null_consistent"
ROUTE_CONFLICT_REVIEW = "conflict_review"
ROUTE_INSUFFICIENT = "insufficient"


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    return value


def _p_value(name: str, value: float) -> float:
    value = _unit(name, value)
    if value <= 0.0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _alpha(name: str, value: float) -> float:
    value = _p_value(name, value)
    if value >= 1.0:
        raise ValueError(f"{name} must be strictly between 0 and 1")
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hex_digest(name: str, value: str) -> str:
    value = _text(name, value)
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
    return value.lower()


def _cauchy_p(p_values: Sequence[float]) -> float:
    """Return a bounded Cauchy combination p-value for high evidence."""

    if not p_values:
        raise ValueError("p_values must be non-empty")
    terms = [math.tan(math.pi * (0.5 - _p_value("p_value", value))) for value in p_values]
    statistic = sum(terms) / len(terms)
    # The arctan mapping is stable for finite p-values and is clipped only to
    # protect the serialized contract from floating point roundoff.
    combined = 0.5 - math.atan(statistic) / math.pi
    return max(1e-15, min(1.0, float(combined)))


def _evidence_from_p_values(p_values: Sequence[float]) -> Tuple[float, float]:
    combined = _cauchy_p(p_values)
    return combined, max(0.0, min(1.0, 1.0 - combined))


@dataclass(frozen=True)
class JointNullExample:
    """One group-matched ordinary-propagation p-value vector."""

    group_id: str
    p_values: Mapping[str, float]
    quality_score: float = 1.0

    def __post_init__(self) -> None:
        _text("group_id", self.group_id)
        _unit("quality_score", self.quality_score)
        if not isinstance(self.p_values, Mapping) or not self.p_values:
            raise ValueError("p_values must be a non-empty mapping")
        normalized = {
            _text("stream_id", stream_id): _p_value("p_value", value)
            for stream_id, value in self.p_values.items()
        }
        object.__setattr__(self, "group_id", self.group_id.strip())
        object.__setattr__(self, "p_values", dict(sorted(normalized.items())))

    @property
    def stream_ids(self) -> Tuple[str, ...]:
        return tuple(self.p_values.keys())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "p_values": dict(self.p_values),
            "quality_score": self.quality_score,
        }


@dataclass(frozen=True)
class JointNullProfile:
    """Frozen empirical profile for a dependent multi-stream null."""

    stream_ids: Tuple[str, ...]
    group_ids: Tuple[str, ...]
    null_evidence_raw: Tuple[float, ...]
    dataset_digest: str
    minimum_quality: float = 0.0
    profile_version: str = VERSION

    def __post_init__(self) -> None:
        if isinstance(self.stream_ids, (str, bytes)) or not self.stream_ids:
            raise ValueError("stream_ids must be a non-empty sequence")
        streams = tuple(sorted(_text("stream_id", item) for item in self.stream_ids))
        if len(set(streams)) != len(streams):
            raise ValueError("stream_ids must be unique")
        groups = tuple(_text("group_id", item) for item in self.group_ids)
        evidence = tuple(_unit("null_evidence_raw", item) for item in self.null_evidence_raw)
        if not evidence or len(groups) != len(evidence):
            raise ValueError("group_ids and null_evidence_raw must be non-empty and aligned")
        if len(set(groups)) != len(groups):
            raise ValueError("group_ids must be unique")
        ordered = tuple(sorted(zip(groups, evidence), key=lambda item: item[0]))
        object.__setattr__(self, "stream_ids", streams)
        object.__setattr__(self, "group_ids", tuple(item[0] for item in ordered))
        object.__setattr__(self, "null_evidence_raw", tuple(item[1] for item in ordered))
        _hex_digest("dataset_digest", self.dataset_digest)
        _unit("minimum_quality", self.minimum_quality)
        _text("profile_version", self.profile_version)

    @property
    def count(self) -> int:
        return len(self.null_evidence_raw)

    @property
    def profile_digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    def p_value(self, evidence_raw: float) -> float:
        evidence_raw = _unit("evidence_raw", evidence_raw)
        exceedances = sum(value >= evidence_raw for value in self.null_evidence_raw)
        return (1.0 + exceedances) / (self.count + 1.0)

    def to_dict(self, *, include_digest: bool = True) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "version": self.profile_version,
            "profile_schema": PROFILE_SCHEMA,
            "stream_ids": list(self.stream_ids),
            "group_ids": list(self.group_ids),
            "null_evidence_raw": list(self.null_evidence_raw),
            "dataset_digest": self.dataset_digest,
            "null_count": self.count,
            "minimum_quality": self.minimum_quality,
        }
        if include_digest:
            result["profile_digest"] = self.profile_digest
        return result


def fit_joint_null_profile(
    examples: Iterable[JointNullExample],
    *,
    dataset_digest: str,
    minimum_quality: float = 0.0,
    minimum_count: int = 1,
) -> JointNullProfile:
    """Fit a dependency-preserving profile from grouped null examples."""

    _hex_digest("dataset_digest", dataset_digest)
    _unit("minimum_quality", minimum_quality)
    if isinstance(minimum_count, bool) or not isinstance(minimum_count, int) or minimum_count < 1:
        raise ValueError("minimum_count must be a positive integer")
    if isinstance(examples, (str, bytes)):
        raise ValueError("examples must be an iterable of JointNullExample")
    try:
        items = tuple(examples)
    except TypeError as exc:
        raise ValueError("examples must be an iterable of JointNullExample") from exc
    if not items or any(not isinstance(item, JointNullExample) for item in items):
        raise ValueError("examples must contain JointNullExample values")
    if len({item.group_id for item in items}) != len(items):
        raise ValueError("group_id values must be unique")
    stream_ids = items[0].stream_ids
    if any(item.stream_ids != stream_ids for item in items):
        raise ValueError("all null examples must contain the same stream IDs")
    accepted = [item for item in items if item.quality_score >= minimum_quality]
    if len(accepted) < minimum_count:
        raise ValueError("insufficient_joint_null_examples")
    evidence = [_evidence_from_p_values([item.p_values[key] for key in stream_ids])[1] for item in accepted]
    return JointNullProfile(
        stream_ids=stream_ids,
        group_ids=tuple(item.group_id for item in accepted),
        null_evidence_raw=tuple(evidence),
        dataset_digest=dataset_digest,
        minimum_quality=minimum_quality,
    )


@dataclass(frozen=True)
class JointNullConfig:
    alpha: float = 0.05
    minimum_null_count: int = 20
    minimum_support_streams: int = 2
    maximum_p_spread: float = 0.80
    consistency_alpha: float = 0.20

    def __post_init__(self) -> None:
        _alpha("alpha", self.alpha)
        if isinstance(self.minimum_null_count, bool) or not isinstance(self.minimum_null_count, int) or self.minimum_null_count < 1:
            raise ValueError("minimum_null_count must be a positive integer")
        if isinstance(self.minimum_support_streams, bool) or not isinstance(self.minimum_support_streams, int) or self.minimum_support_streams < 1:
            raise ValueError("minimum_support_streams must be a positive integer")
        _unit("maximum_p_spread", self.maximum_p_spread)
        _alpha("consistency_alpha", self.consistency_alpha)

    @property
    def digest(self) -> str:
        return _digest({
            "version": VERSION,
            "alpha": self.alpha,
            "minimum_null_count": self.minimum_null_count,
            "minimum_support_streams": self.minimum_support_streams,
            "maximum_p_spread": self.maximum_p_spread,
            "consistency_alpha": self.consistency_alpha,
        })


@dataclass(frozen=True)
class JointNullResult:
    route: str
    abstained: bool
    reason: str
    combined_p_raw: Optional[float]
    calibrated_p_value: Optional[float]
    evidence_raw: Optional[float]
    p_spread_raw: Optional[float]
    support_stream_count: int
    stream_ids: Tuple[str, ...]
    profile_digest: Optional[str]
    config_digest: str
    evidence_digest: str
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.route not in {ROUTE_CANDIDATE, ROUTE_NULL_CONSISTENT, ROUTE_CONFLICT_REVIEW, ROUTE_INSUFFICIENT}:
            raise ValueError("invalid joint null route")
        if self.route in {ROUTE_CONFLICT_REVIEW, ROUTE_INSUFFICIENT} and not self.abstained:
            raise ValueError("review and insufficient routes must abstain")
        if self.route in {ROUTE_CANDIDATE, ROUTE_NULL_CONSISTENT} and self.abstained:
            raise ValueError("concordant routes cannot abstain")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason is required")
        for name, value in (("combined_p_raw", self.combined_p_raw), ("calibrated_p_value", self.calibrated_p_value), ("evidence_raw", self.evidence_raw), ("p_spread_raw", self.p_spread_raw)):
            if value is not None:
                _unit(name, value)
        if self.combined_p_raw is not None and self.combined_p_raw <= 0.0:
            raise ValueError("combined_p_raw must be greater than zero")
        if self.calibrated_p_value is not None and self.calibrated_p_value <= 0.0:
            raise ValueError("calibrated_p_value must be greater than zero")
        if not isinstance(self.support_stream_count, int) or self.support_stream_count < 0:
            raise ValueError("support_stream_count must be non-negative")
        if isinstance(self.stream_ids, (str, bytes)):
            raise ValueError("stream_ids must be a tuple")
        _hex_digest("config_digest", self.config_digest)
        _hex_digest("evidence_digest", self.evidence_digest)
        if self.profile_digest is not None:
            _hex_digest("profile_digest", self.profile_digest)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "result_schema": RESULT_SCHEMA,
            "route": self.route,
            "abstained": self.abstained,
            "reason": self.reason,
            "combined_p_raw": self.combined_p_raw,
            "calibrated_p_value": self.calibrated_p_value,
            "evidence_raw": self.evidence_raw,
            "p_spread_raw": self.p_spread_raw,
            "support_stream_count": self.support_stream_count,
            "stream_ids": list(self.stream_ids),
            "profile_digest": self.profile_digest,
            "config_digest": self.config_digest,
            "evidence_digest": self.evidence_digest,
        }


def evaluate_joint_null(
    p_values: Mapping[str, float],
    profile: Optional[JointNullProfile],
    *,
    config: Optional[JointNullConfig] = None,
) -> JointNullResult:
    """Calibrate a query p-value vector and route it conservatively."""

    cfg = config or JointNullConfig()
    if not isinstance(p_values, Mapping) or not p_values:
        raise ValueError("p_values must be a non-empty mapping")
    normalized = {_text("stream_id", key): _p_value("p_value", value) for key, value in p_values.items()}
    stream_ids = tuple(sorted(normalized))
    if profile is None:
        evidence_digest = _digest({"version": VERSION, "p_values": normalized, "reason": "profile_unavailable", "config": cfg.digest})
        return JointNullResult(
            route=ROUTE_INSUFFICIENT,
            abstained=True,
            reason="profile_unavailable",
            combined_p_raw=None,
            calibrated_p_value=None,
            evidence_raw=None,
            p_spread_raw=None,
            support_stream_count=0,
            stream_ids=stream_ids,
            profile_digest=None,
            config_digest=cfg.digest,
            evidence_digest=evidence_digest,
        )
    if profile.count < cfg.minimum_null_count:
        reason = "insufficient_joint_null_support"
    elif stream_ids != profile.stream_ids:
        reason = "stream_set_mismatch"
    else:
        reason = None
    if reason is not None:
        evidence_digest = _digest({"version": VERSION, "p_values": normalized, "profile": profile.to_dict(), "reason": reason, "config": cfg.digest})
        return JointNullResult(
            route=ROUTE_INSUFFICIENT,
            abstained=True,
            reason=reason,
            combined_p_raw=None,
            calibrated_p_value=None,
            evidence_raw=None,
            p_spread_raw=None,
            support_stream_count=0,
            stream_ids=stream_ids,
            profile_digest=profile.profile_digest,
            config_digest=cfg.digest,
            evidence_digest=evidence_digest,
        )
    combined_p, evidence = _evidence_from_p_values([normalized[key] for key in profile.stream_ids])
    calibrated_p = profile.p_value(evidence)
    spread = max(normalized.values()) - min(normalized.values())
    support = sum(value <= cfg.consistency_alpha for value in normalized.values())
    if spread > cfg.maximum_p_spread:
        route, abstained, route_reason = ROUTE_CONFLICT_REVIEW, True, "joint_p_value_conflict"
    elif calibrated_p <= cfg.alpha and support >= cfg.minimum_support_streams:
        route, abstained, route_reason = ROUTE_CANDIDATE, False, "joint_null_rejected_with_concordant_support"
    elif calibrated_p > cfg.alpha and support == 0:
        route, abstained, route_reason = ROUTE_NULL_CONSISTENT, False, "joint_null_consistent"
    else:
        route, abstained, route_reason = ROUTE_CONFLICT_REVIEW, True, "joint_null_borderline_or_partial_support"
    evidence_digest = _digest({
        "version": VERSION,
        "p_values": normalized,
        "combined_p_raw": combined_p,
        "calibrated_p_value": calibrated_p,
        "evidence_raw": evidence,
        "profile_digest": profile.profile_digest,
        "config": cfg.digest,
        "route": route,
        "reason": route_reason,
    })
    return JointNullResult(
        route=route,
        abstained=abstained,
        reason=route_reason,
        combined_p_raw=combined_p,
        calibrated_p_value=calibrated_p,
        evidence_raw=evidence,
        p_spread_raw=spread,
        support_stream_count=support,
        stream_ids=profile.stream_ids,
        profile_digest=profile.profile_digest,
        config_digest=cfg.digest,
        evidence_digest=evidence_digest,
    )


__all__ = [
    "VERSION",
    "PROFILE_SCHEMA",
    "RESULT_SCHEMA",
    "ROUTE_CANDIDATE",
    "ROUTE_NULL_CONSISTENT",
    "ROUTE_CONFLICT_REVIEW",
    "ROUTE_INSUFFICIENT",
    "JointNullExample",
    "JointNullProfile",
    "JointNullConfig",
    "JointNullResult",
    "fit_joint_null_profile",
    "evaluate_joint_null",
]
