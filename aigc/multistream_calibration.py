"""Conservative calibration for independent source-conditioned evidence streams.

This module calibrates the null hypothesis that each stream is compatible with
ordinary propagation.  Pixel residual and spectral/phase observations keep
separate null profiles and p-values.  A candidate route requires every
required stream to reject its own null under a conservative Bonferroni-gated
intersection rule; mixed, borderline, missing, or incompatible evidence is
sent to review or insufficient.  Scores are never averaged and no AIGC
probability or authorship state is emitted.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .multistream import (
    EvidenceStreamObservation,
    ROUTE_CANDIDATE,
    ROUTE_CONFLICT_REVIEW,
    ROUTE_INSUFFICIENT,
    ROUTE_NULL_CONSISTENT,
)


VERSION = "source-multistream-conformal-v1"
PROFILE_SCHEMA = "source-stream-null-profile-v1"
RESULT_SCHEMA = "source-multistream-conformal-result-v1"


def _text(name: str, value: str) -> str:
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


def _alpha(name: str, value: float) -> float:
    normalized = _unit(name, value)
    if normalized <= 0.0 or normalized >= 1.0:
        raise ValueError(f"{name} must be strictly between 0 and 1")
    return normalized


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hex_digest(name: str, value: str) -> str:
    _text(name, value)
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
    return value.lower()


@dataclass(frozen=True)
class StreamNullExample:
    """One ordinary-propagation null score for one evidence stream."""

    stream_id: str
    score_raw: float
    group_id: str
    detector_version: str
    score_schema: str
    quality_score: float = 1.0
    transform_family: str = "ordinary_propagation"

    def __post_init__(self) -> None:
        _text("stream_id", self.stream_id)
        _text("group_id", self.group_id)
        _text("detector_version", self.detector_version)
        _text("score_schema", self.score_schema)
        _text("transform_family", self.transform_family)
        _unit("score_raw", self.score_raw)
        _unit("quality_score", self.quality_score)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "score_raw": self.score_raw,
            "group_id": self.group_id,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "quality_score": self.quality_score,
            "transform_family": self.transform_family,
        }


@dataclass(frozen=True)
class StreamNullProfile:
    """Frozen null distribution for exactly one detector stream."""

    stream_id: str
    detector_version: str
    score_schema: str
    dataset_digest: str
    null_scores: Tuple[float, ...]
    group_ids: Tuple[str, ...]
    transform_families: Tuple[str, ...]
    minimum_quality: float = 0.0
    profile_version: str = VERSION

    def __post_init__(self) -> None:
        _text("stream_id", self.stream_id)
        _text("detector_version", self.detector_version)
        _text("score_schema", self.score_schema)
        _hex_digest("dataset_digest", self.dataset_digest)
        if isinstance(self.null_scores, (str, bytes)) or not self.null_scores:
            raise ValueError("null_scores must be non-empty")
        scores = tuple(_unit("null_score", value) for value in self.null_scores)
        ids = tuple(_text("group_id", value) for value in self.group_ids)
        families = tuple(_text("transform_family", value) for value in self.transform_families)
        if len(scores) != len(ids) or len(scores) != len(families):
            raise ValueError("null_scores, group_ids and transform_families must align")
        if len(set(ids)) != len(ids):
            raise ValueError("group_ids must be unique within a profile")
        ordered = tuple(sorted(zip(scores, ids, families), key=lambda item: (item[0], item[1])))
        object.__setattr__(self, "null_scores", tuple(item[0] for item in ordered))
        object.__setattr__(self, "group_ids", tuple(item[1] for item in ordered))
        object.__setattr__(self, "transform_families", tuple(item[2] for item in ordered))
        _unit("minimum_quality", self.minimum_quality)
        _text("profile_version", self.profile_version)

    @property
    def count(self) -> int:
        return len(self.null_scores)

    @property
    def profile_digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    def p_value(self, score_raw: float) -> float:
        """Tie-inclusive upper-tail p-value for a high-is-more-AI score."""

        score = _unit("score_raw", score_raw)
        exceedances = sum(value >= score for value in self.null_scores)
        return (1.0 + exceedances) / (self.count + 1.0)

    def to_dict(self, *, include_digest: bool = True) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "version": self.profile_version,
            "profile_schema": PROFILE_SCHEMA,
            "stream_id": self.stream_id,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "dataset_digest": self.dataset_digest,
            "null_scores": list(self.null_scores),
            "group_ids": list(self.group_ids),
            "transform_families": list(self.transform_families),
            "minimum_quality": self.minimum_quality,
            "null_count": self.count,
        }
        if include_digest:
            result["profile_digest"] = self.profile_digest
        return result


@dataclass(frozen=True)
class MultiStreamCalibrationConfig:
    """Selective gates for calibrated stream intersection."""

    alpha: float = 0.05
    minimum_null_count: int = 20
    minimum_quality: float = 0.35
    require_paired: bool = True
    require_all_streams: bool = True
    bonferroni_intersection: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "alpha", _alpha("alpha", self.alpha))
        if (
            isinstance(self.minimum_null_count, bool)
            or not isinstance(self.minimum_null_count, int)
            or self.minimum_null_count < 1
        ):
            raise ValueError("minimum_null_count must be a positive integer")
        _unit("minimum_quality", self.minimum_quality)
        if not isinstance(self.require_paired, bool):
            raise ValueError("require_paired must be bool")
        if not isinstance(self.require_all_streams, bool):
            raise ValueError("require_all_streams must be bool")
        if not isinstance(self.bonferroni_intersection, bool):
            raise ValueError("bonferroni_intersection must be bool")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "alpha": self.alpha,
            "minimum_null_count": self.minimum_null_count,
            "minimum_quality": self.minimum_quality,
            "require_paired": self.require_paired,
            "require_all_streams": self.require_all_streams,
            "bonferroni_intersection": self.bonferroni_intersection,
        }

    @property
    def config_digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class StreamCalibrationObservation:
    stream_id: str
    score_raw: Optional[float]
    p_value: Optional[float]
    reject_null: bool
    alpha_used: float
    null_count: int
    profile_digest: Optional[str]
    detector_version: str
    score_schema: str
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        _text("stream_id", self.stream_id)
        if self.score_raw is not None:
            _unit("score_raw", self.score_raw)
        _unit("alpha_used", self.alpha_used)
        _text("detector_version", self.detector_version)
        _text("score_schema", self.score_schema)
        if not isinstance(self.reject_null, bool):
            raise ValueError("reject_null must be bool")
        if not isinstance(self.null_count, int) or self.null_count < 0:
            raise ValueError("null_count must be non-negative")
        if self.p_value is None:
            if self.reject_null:
                raise ValueError("missing p_value cannot reject null")
            if not self.reason:
                raise ValueError("missing p_value requires reason")
        else:
            p_value = _unit("p_value", self.p_value)
            if p_value <= 0.0:
                raise ValueError("p_value must be greater than zero")
            if self.reject_null != (p_value <= self.alpha_used):
                raise ValueError("reject_null must equal p_value <= alpha_used")
        if self.profile_digest is not None:
            _hex_digest("profile_digest", self.profile_digest)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "score_raw": self.score_raw,
            "p_value": self.p_value,
            "reject_null": self.reject_null,
            "alpha_used": self.alpha_used,
            "null_count": self.null_count,
            "profile_digest": self.profile_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MultiStreamCalibrationResult:
    route: str
    abstained: bool
    reason: str
    null_hypothesis: str
    alpha: float
    per_stream_alpha: float
    stream_results: Tuple[StreamCalibrationObservation, ...]
    config_digest: str
    profile_digests: Tuple[str, ...]
    evidence_digest: str
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.route not in {
            ROUTE_CANDIDATE,
            ROUTE_NULL_CONSISTENT,
            ROUTE_CONFLICT_REVIEW,
            ROUTE_INSUFFICIENT,
        }:
            raise ValueError("invalid calibrated multistream route")
        if self.route in {ROUTE_CONFLICT_REVIEW, ROUTE_INSUFFICIENT} and not self.abstained:
            raise ValueError("review and insufficient routes must abstain")
        if self.route in {ROUTE_CANDIDATE, ROUTE_NULL_CONSISTENT} and self.abstained:
            raise ValueError("concordant routes cannot abstain")
        if not isinstance(self.stream_results, tuple) or not self.stream_results:
            raise ValueError("stream_results must be non-empty")
        _text("reason", self.reason)
        _text("null_hypothesis", self.null_hypothesis)
        _alpha("alpha", self.alpha)
        _alpha("per_stream_alpha", self.per_stream_alpha)
        _hex_digest("config_digest", self.config_digest)
        _hex_digest("evidence_digest", self.evidence_digest)
        if not isinstance(self.profile_digests, tuple):
            raise ValueError("profile_digests must be a tuple")
        for digest in self.profile_digests:
            _hex_digest("profile_digest", digest)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "result_schema": RESULT_SCHEMA,
            "route": self.route,
            "abstained": self.abstained,
            "reason": self.reason,
            "null_hypothesis": self.null_hypothesis,
            "alpha": self.alpha,
            "per_stream_alpha": self.per_stream_alpha,
            "stream_results": [item.to_dict() for item in self.stream_results],
            "config_digest": self.config_digest,
            "profile_digests": list(self.profile_digests),
            "evidence_digest": self.evidence_digest,
        }


def fit_stream_null_profiles(
    examples: Sequence[StreamNullExample],
    *,
    minimum_quality: float = 0.0,
) -> Tuple[StreamNullProfile, ...]:
    """Fit independent profiles from frozen ordinary-propagation examples."""

    if isinstance(examples, (str, bytes)) or not examples:
        raise ValueError("examples must be non-empty")
    _unit("minimum_quality", minimum_quality)
    items = tuple(examples)
    if any(not isinstance(item, StreamNullExample) for item in items):
        raise ValueError("examples must contain StreamNullExample values")
    groups: Dict[str, list[StreamNullExample]] = {}
    for item in items:
        if item.quality_score < minimum_quality:
            continue
        groups.setdefault(item.stream_id, []).append(item)
    if not groups:
        raise ValueError("no null examples pass the quality gate")
    profiles = []
    for stream_id in sorted(groups):
        stream_items = groups[stream_id]
        detector_versions = {item.detector_version for item in stream_items}
        score_schemas = {item.score_schema for item in stream_items}
        if len(detector_versions) != 1 or len(score_schemas) != 1:
            raise ValueError("each stream profile requires one detector/schema")
        dataset_digest = _digest([item.to_dict() for item in stream_items])
        profiles.append(
            StreamNullProfile(
                stream_id=stream_id,
                detector_version=stream_items[0].detector_version,
                score_schema=stream_items[0].score_schema,
                dataset_digest=dataset_digest,
                null_scores=tuple(item.score_raw for item in stream_items),
                group_ids=tuple(item.group_id for item in stream_items),
                transform_families=tuple(item.transform_family for item in stream_items),
                minimum_quality=minimum_quality,
            )
        )
    return tuple(profiles)


def _make_result(
    *,
    route: str,
    abstained: bool,
    reason: str,
    stream_results: Sequence[StreamCalibrationObservation],
    config: MultiStreamCalibrationConfig,
    profiles: Sequence[StreamNullProfile],
) -> MultiStreamCalibrationResult:
    profile_digests = tuple(profile.profile_digest for profile in profiles)
    canonical = {
        "version": VERSION,
        "route": route,
        "abstained": abstained,
        "reason": reason,
        "null_hypothesis": "ordinary_propagation_per_stream",
        "alpha": config.alpha,
        "per_stream_alpha": config.alpha / max(1, len(profiles))
        if config.bonferroni_intersection
        else config.alpha,
        "stream_results": [item.to_dict() for item in stream_results],
        "config_digest": config.config_digest,
        "profile_digests": profile_digests,
    }
    return MultiStreamCalibrationResult(
        route=route,
        abstained=abstained,
        reason=reason,
        null_hypothesis="ordinary_propagation_per_stream",
        alpha=config.alpha,
        per_stream_alpha=canonical["per_stream_alpha"],
        stream_results=tuple(stream_results),
        config_digest=config.config_digest,
        profile_digests=profile_digests,
        evidence_digest=_digest(canonical),
    )


def evaluate_calibrated_multistream(
    streams: Sequence[EvidenceStreamObservation],
    profiles: Sequence[StreamNullProfile],
    *,
    config: Optional[MultiStreamCalibrationConfig] = None,
) -> MultiStreamCalibrationResult:
    """Evaluate streams against independent frozen null profiles.

    ``candidate_edit`` requires every accepted stream to reject its ordinary
    propagation null at ``alpha / number_of_streams`` when Bonferroni gating is
    enabled.  ``null_consistent`` requires every stream to remain above the
    unadjusted alpha.  Everything in between is review; missing or incompatible
    calibration is insufficient.  This is a selective evidence protocol, not a
    probability classifier.
    """

    cfg = config or MultiStreamCalibrationConfig()
    if isinstance(streams, (str, bytes)) or not streams:
        raise ValueError("streams must contain at least one observation")
    if isinstance(profiles, (str, bytes)) or not profiles:
        raise ValueError("profiles must contain at least one profile")
    stream_items = tuple(streams)
    profile_items = tuple(profiles)
    if any(not isinstance(item, EvidenceStreamObservation) for item in stream_items):
        raise ValueError("streams must contain EvidenceStreamObservation values")
    if any(not isinstance(item, StreamNullProfile) for item in profile_items):
        raise ValueError("profiles must contain StreamNullProfile values")
    if len({item.stream_id for item in stream_items}) != len(stream_items):
        raise ValueError("stream IDs must be unique")
    if len({item.stream_id for item in profile_items}) != len(profile_items):
        raise ValueError("profile stream IDs must be unique")

    by_id = {profile.stream_id: profile for profile in profile_items}
    accepted = tuple(item for item in stream_items if item.accepted)
    unavailable = tuple(item for item in stream_items if not item.accepted)
    if unavailable:
        observations = tuple(
            StreamCalibrationObservation(
                stream_id=item.stream_id,
                score_raw=float(item.score_raw) if item.accepted else None,
                p_value=None,
                reject_null=False,
                alpha_used=cfg.alpha,
                null_count=by_id[item.stream_id].count if item.stream_id in by_id else 0,
                profile_digest=by_id[item.stream_id].profile_digest if item.stream_id in by_id else None,
                detector_version=item.detector_version,
                score_schema=item.score_schema,
                reason=item.reason or "peer_stream_unavailable",
            )
            for item in stream_items
        )
        return _make_result(
            route=ROUTE_INSUFFICIENT,
            abstained=True,
            reason="stream_unavailable",
            stream_results=observations,
            config=cfg,
            profiles=profile_items,
        )
    if not accepted:
        raise ValueError("at least one accepted stream is required")
    if cfg.require_paired and any(not item.paired for item in accepted):
        observations = tuple(
            StreamCalibrationObservation(
                stream_id=item.stream_id,
                score_raw=float(item.score_raw),
                p_value=None,
                reject_null=False,
                alpha_used=cfg.alpha,
                null_count=0,
                profile_digest=None,
                detector_version=item.detector_version,
                score_schema=item.score_schema,
                reason="paired_counterfactual_required",
            )
            for item in accepted
        )
        return _make_result(
            route=ROUTE_INSUFFICIENT,
            abstained=True,
            reason="paired_counterfactual_required",
            stream_results=observations,
            config=cfg,
            profiles=profile_items,
        )

    if cfg.require_all_streams and set(by_id) != {item.stream_id for item in accepted}:
        observations = tuple(
            StreamCalibrationObservation(
                stream_id=item.stream_id,
                score_raw=float(item.score_raw),
                p_value=None,
                reject_null=False,
                alpha_used=cfg.alpha,
                null_count=0,
                profile_digest=None,
                detector_version=item.detector_version,
                score_schema=item.score_schema,
                reason="missing_stream_profile" if item.stream_id not in by_id else None,
            )
            for item in accepted
        )
        return _make_result(
            route=ROUTE_INSUFFICIENT,
            abstained=True,
            reason="missing_stream_profile",
            stream_results=observations,
            config=cfg,
            profiles=profile_items,
        )

    per_stream_alpha = cfg.alpha / len(accepted) if cfg.bonferroni_intersection else cfg.alpha
    observations = []
    for item in accepted:
        profile = by_id.get(item.stream_id)
        if profile is None:
            observations.append(
                StreamCalibrationObservation(
                    stream_id=item.stream_id,
                    score_raw=float(item.score_raw),
                    p_value=None,
                    reject_null=False,
                    alpha_used=per_stream_alpha,
                    null_count=0,
                    profile_digest=None,
                    detector_version=item.detector_version,
                    score_schema=item.score_schema,
                    reason="missing_stream_profile",
                )
            )
            continue
        if item.quality_score is None or item.quality_score < max(cfg.minimum_quality, profile.minimum_quality):
            observations.append(
                StreamCalibrationObservation(
                    stream_id=item.stream_id,
                    score_raw=float(item.score_raw),
                    p_value=None,
                    reject_null=False,
                    alpha_used=per_stream_alpha,
                    null_count=profile.count,
                    profile_digest=profile.profile_digest,
                    detector_version=item.detector_version,
                    score_schema=item.score_schema,
                    reason="quality_below_threshold",
                )
            )
            continue
        if item.detector_version != profile.detector_version or item.score_schema != profile.score_schema:
            observations.append(
                StreamCalibrationObservation(
                    stream_id=item.stream_id,
                    score_raw=float(item.score_raw),
                    p_value=None,
                    reject_null=False,
                    alpha_used=per_stream_alpha,
                    null_count=profile.count,
                    profile_digest=profile.profile_digest,
                    detector_version=item.detector_version,
                    score_schema=item.score_schema,
                    reason="detector_or_schema_mismatch",
                )
            )
            continue
        if profile.count < cfg.minimum_null_count:
            observations.append(
                StreamCalibrationObservation(
                    stream_id=item.stream_id,
                    score_raw=float(item.score_raw),
                    p_value=None,
                    reject_null=False,
                    alpha_used=per_stream_alpha,
                    null_count=profile.count,
                    profile_digest=profile.profile_digest,
                    detector_version=item.detector_version,
                    score_schema=item.score_schema,
                    reason="null_support_below_minimum",
                )
            )
            continue
        p_value = profile.p_value(float(item.score_raw))
        observations.append(
            StreamCalibrationObservation(
                stream_id=item.stream_id,
                score_raw=float(item.score_raw),
                p_value=p_value,
                reject_null=p_value <= per_stream_alpha,
                alpha_used=per_stream_alpha,
                null_count=profile.count,
                profile_digest=profile.profile_digest,
                detector_version=item.detector_version,
                score_schema=item.score_schema,
            )
        )

    result_items = tuple(observations)
    if any(item.p_value is None for item in result_items):
        return _make_result(
            route=ROUTE_INSUFFICIENT,
            abstained=True,
            reason=next(item.reason or "stream_calibration_unavailable" for item in result_items if item.p_value is None),
            stream_results=result_items,
            config=cfg,
            profiles=profile_items,
        )
    if all(item.reject_null for item in result_items):
        return _make_result(
            route=ROUTE_CANDIDATE,
            abstained=False,
            reason="all_streams_reject_ordinary_propagation",
            stream_results=result_items,
            config=cfg,
            profiles=profile_items,
        )
    if all(float(item.p_value) > cfg.alpha for item in result_items):
        return _make_result(
            route=ROUTE_NULL_CONSISTENT,
            abstained=False,
            reason="all_streams_consistent_with_ordinary_propagation",
            stream_results=result_items,
            config=cfg,
            profiles=profile_items,
        )
    return _make_result(
        route=ROUTE_CONFLICT_REVIEW,
        abstained=True,
        reason="stream_null_decision_conflict_or_borderline",
        stream_results=result_items,
        config=cfg,
        profiles=profile_items,
    )


__all__ = [
    "VERSION",
    "PROFILE_SCHEMA",
    "RESULT_SCHEMA",
    "StreamNullExample",
    "StreamNullProfile",
    "MultiStreamCalibrationConfig",
    "StreamCalibrationObservation",
    "MultiStreamCalibrationResult",
    "fit_stream_null_profiles",
    "evaluate_calibrated_multistream",
]
