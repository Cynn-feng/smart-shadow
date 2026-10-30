"""Conflict-aware routing for independent source-conditioned evidence streams.

The pixel residual and phase/spectral adapters intentionally keep different
raw observations.  This module is only the boundary that records those
observations side by side and chooses a review route.  It never averages
scores into a probability, emits an AIGC label, or treats a null-consistent
route as proof of human creation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


VERSION = "source-multistream-router-v1"
ROUTER_SCHEMA = "source-multistream-route-v1"
ROUTE_CANDIDATE = "candidate_edit"
ROUTE_NULL_CONSISTENT = "null_consistent"
ROUTE_CONFLICT_REVIEW = "conflict_review"
ROUTE_INSUFFICIENT = "insufficient"


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _hex_digest(name: str, value: str) -> str:
    _text(name, value)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return value.lower()


def _unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return normalized


@dataclass(frozen=True)
class EvidenceStreamObservation:
    """One independent stream observation kept in the evidence sidecar.

    ``score_raw`` is deliberately a bounded raw feature.  ``None`` is used
    for a failed/unavailable stream so the router cannot silently turn a
    detector error into a zero score.
    """

    stream_id: str
    accepted: bool
    paired: bool
    score_raw: Optional[float]
    quality_score: Optional[float]
    reason: Optional[str]
    detector_version: str
    score_schema: str
    config_digest: str
    input_digests: Tuple[str, ...]
    evidence_digest: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text("stream_id", self.stream_id)
        if not isinstance(self.accepted, bool) or not isinstance(self.paired, bool):
            raise ValueError("accepted and paired must be bools")
        if self.accepted:
            if self.score_raw is None or self.quality_score is None:
                raise ValueError("accepted stream requires score_raw and quality_score")
            if self.reason is not None:
                raise ValueError("accepted stream cannot have a reason")
            _unit("score_raw", self.score_raw)
            _unit("quality_score", self.quality_score)
            if not self.input_digests:
                raise ValueError("accepted stream requires input digests")
        else:
            if not isinstance(self.reason, str) or not self.reason:
                raise ValueError("rejected stream requires a stable reason")
            if self.score_raw is not None or self.quality_score is not None:
                raise ValueError("rejected stream cannot contain score or quality")
        _text("detector_version", self.detector_version)
        _text("score_schema", self.score_schema)
        _hex_digest("config_digest", self.config_digest)
        _hex_digest("evidence_digest", self.evidence_digest)
        if not isinstance(self.input_digests, tuple):
            raise ValueError("input_digests must be a tuple")
        if len(set(self.input_digests)) != len(self.input_digests):
            raise ValueError("input_digests must be unique")
        for digest in self.input_digests:
            _hex_digest("input_digest", digest)
        if not isinstance(self.details, Mapping):
            raise ValueError("details must be a mapping")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "stream_id": self.stream_id,
            "accepted": self.accepted,
            "paired": self.paired,
            "score_raw": self.score_raw,
            "quality_score": self.quality_score,
            "reason": self.reason,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "config_digest": self.config_digest,
            "input_digests": list(self.input_digests),
            "evidence_digest": self.evidence_digest,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class MultiStreamRouteConfig:
    """Raw-score gates for selective routing, not a calibrated classifier."""

    raw_positive_threshold: float = 0.50
    disagreement_margin: float = 0.25
    minimum_quality: float = 0.25
    minimum_accepted_streams: int = 2
    minimum_positive_streams: int = 2
    require_paired: bool = True

    def __post_init__(self) -> None:
        _unit("raw_positive_threshold", self.raw_positive_threshold)
        _unit("disagreement_margin", self.disagreement_margin)
        _unit("minimum_quality", self.minimum_quality)
        for name in ("minimum_accepted_streams", "minimum_positive_streams"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(self.require_paired, bool):
            raise ValueError("require_paired must be bool")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "router_schema": ROUTER_SCHEMA,
            "raw_positive_threshold": self.raw_positive_threshold,
            "disagreement_margin": self.disagreement_margin,
            "minimum_quality": self.minimum_quality,
            "minimum_accepted_streams": self.minimum_accepted_streams,
            "minimum_positive_streams": self.minimum_positive_streams,
            "require_paired": self.require_paired,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class MultiStreamRouteResult:
    """Auditable route preserving every stream's independent raw evidence."""

    route: str
    abstained: bool
    reason: str
    accepted_streams: Tuple[str, ...]
    positive_streams: Tuple[str, ...]
    negative_streams: Tuple[str, ...]
    unavailable_streams: Tuple[str, ...]
    conflict_streams: Tuple[str, ...]
    streams: Tuple[Mapping[str, Any], ...]
    router_config_digest: str
    evidence_digest: str
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.route not in {
            ROUTE_CANDIDATE,
            ROUTE_NULL_CONSISTENT,
            ROUTE_CONFLICT_REVIEW,
            ROUTE_INSUFFICIENT,
        }:
            raise ValueError("invalid multistream route")
        if self.route in {ROUTE_CONFLICT_REVIEW, ROUTE_INSUFFICIENT} and not self.abstained:
            raise ValueError("review and insufficient routes must abstain")
        if self.route in {ROUTE_CANDIDATE, ROUTE_NULL_CONSISTENT} and self.abstained:
            raise ValueError("concordant routes cannot abstain")
        if not isinstance(self.abstained, bool):
            raise ValueError("abstained must be bool")
        _text("reason", self.reason)
        _hex_digest("router_config_digest", self.router_config_digest)
        _hex_digest("evidence_digest", self.evidence_digest)
        for name in (
            "accepted_streams",
            "positive_streams",
            "negative_streams",
            "unavailable_streams",
            "conflict_streams",
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple) or len(set(values)) != len(values):
                raise ValueError(f"{name} must be a tuple of unique IDs")
        if not isinstance(self.streams, tuple) or not self.streams:
            raise ValueError("streams must preserve at least one stream record")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "router_schema": ROUTER_SCHEMA,
            "route": self.route,
            "abstained": self.abstained,
            "reason": self.reason,
            "accepted_streams": list(self.accepted_streams),
            "positive_streams": list(self.positive_streams),
            "negative_streams": list(self.negative_streams),
            "unavailable_streams": list(self.unavailable_streams),
            "conflict_streams": list(self.conflict_streams),
            "streams": [dict(stream) for stream in self.streams],
            "router_config_digest": self.router_config_digest,
            "evidence_digest": self.evidence_digest,
        }


def _result(
    *,
    route: str,
    abstained: bool,
    reason: str,
    accepted: Sequence[EvidenceStreamObservation],
    positive: Sequence[EvidenceStreamObservation],
    negative: Sequence[EvidenceStreamObservation],
    unavailable: Sequence[EvidenceStreamObservation],
    conflicts: Sequence[EvidenceStreamObservation],
    streams: Sequence[EvidenceStreamObservation],
    config: MultiStreamRouteConfig,
) -> MultiStreamRouteResult:
    records = tuple(stream.to_dict() for stream in streams)
    canonical = {
        "version": VERSION,
        "route": route,
        "abstained": abstained,
        "reason": reason,
        "accepted_streams": [stream.stream_id for stream in accepted],
        "positive_streams": [stream.stream_id for stream in positive],
        "negative_streams": [stream.stream_id for stream in negative],
        "unavailable_streams": [stream.stream_id for stream in unavailable],
        "conflict_streams": [stream.stream_id for stream in conflicts],
        "streams": records,
        "router_config_digest": config.digest,
    }
    return MultiStreamRouteResult(
        route=route,
        abstained=abstained,
        reason=reason,
        accepted_streams=tuple(stream.stream_id for stream in accepted),
        positive_streams=tuple(stream.stream_id for stream in positive),
        negative_streams=tuple(stream.stream_id for stream in negative),
        unavailable_streams=tuple(stream.stream_id for stream in unavailable),
        conflict_streams=tuple(stream.stream_id for stream in conflicts),
        streams=records,
        router_config_digest=config.digest,
        evidence_digest=_digest(canonical),
    )


def route_multistream_evidence(
    streams: Sequence[EvidenceStreamObservation],
    *,
    config: Optional[MultiStreamRouteConfig] = None,
) -> MultiStreamRouteResult:
    """Route independent raw streams with explicit conflict and abstention.

    Stream IDs must be unique.  Scores are never averaged or converted to
    probabilities.  A positive route requires concordant positive streams;
    a null route only says that all accepted raw streams were below the
    configured gate and does not establish human authorship.
    """

    cfg = config or MultiStreamRouteConfig()
    if isinstance(streams, (str, bytes)) or not streams:
        raise ValueError("streams must contain at least one observation")
    items = tuple(streams)
    if any(not isinstance(stream, EvidenceStreamObservation) for stream in items):
        raise ValueError("streams must contain EvidenceStreamObservation values")
    if len({stream.stream_id for stream in items}) != len(items):
        raise ValueError("stream IDs must be unique")
    accepted = tuple(stream for stream in items if stream.accepted)
    unavailable = tuple(stream for stream in items if not stream.accepted)
    if not accepted:
        return _result(
            route=ROUTE_INSUFFICIENT,
            abstained=True,
            reason="no_accepted_streams",
            accepted=(),
            positive=(),
            negative=(),
            unavailable=unavailable,
            conflicts=(),
            streams=items,
            config=cfg,
        )
    low_quality = tuple(stream for stream in accepted if float(stream.quality_score) < cfg.minimum_quality)
    if low_quality:
        return _result(
            route=ROUTE_INSUFFICIENT,
            abstained=True,
            reason="quality_below_threshold",
            accepted=accepted,
            positive=(),
            negative=(),
            unavailable=unavailable,
            conflicts=low_quality,
            streams=items,
            config=cfg,
        )
    if len(accepted) < cfg.minimum_accepted_streams:
        return _result(
            route=ROUTE_INSUFFICIENT,
            abstained=True,
            reason="accepted_stream_count_below_minimum",
            accepted=accepted,
            positive=(),
            negative=(),
            unavailable=unavailable,
            conflicts=(),
            streams=items,
            config=cfg,
        )
    if cfg.require_paired and any(not stream.paired for stream in accepted):
        unpaired = tuple(stream for stream in accepted if not stream.paired)
        return _result(
            route=ROUTE_INSUFFICIENT,
            abstained=True,
            reason="paired_counterfactual_required",
            accepted=accepted,
            positive=(),
            negative=(),
            unavailable=unavailable,
            conflicts=unpaired,
            streams=items,
            config=cfg,
        )
    positive = tuple(stream for stream in accepted if float(stream.score_raw) >= cfg.raw_positive_threshold)
    negative = tuple(stream for stream in accepted if float(stream.score_raw) < cfg.raw_positive_threshold)
    conflicts: Tuple[EvidenceStreamObservation, ...] = ()
    if positive and negative:
        score_spread = max(float(stream.score_raw) for stream in accepted) - min(
            float(stream.score_raw) for stream in accepted
        )
        conflicts = tuple(positive + negative)
        reason = "raw_score_conflict" if score_spread >= cfg.disagreement_margin else "near_threshold_disagreement"
        return _result(
            route=ROUTE_CONFLICT_REVIEW,
            abstained=True,
            reason=reason,
            accepted=accepted,
            positive=positive,
            negative=negative,
            unavailable=unavailable,
            conflicts=conflicts,
            streams=items,
            config=cfg,
        )
    if len(positive) >= cfg.minimum_positive_streams:
        return _result(
            route=ROUTE_CANDIDATE,
            abstained=False,
            reason="concordant_positive_raw_evidence",
            accepted=accepted,
            positive=positive,
            negative=negative,
            unavailable=unavailable,
            conflicts=(),
            streams=items,
            config=cfg,
        )
    if len(negative) == len(accepted):
        return _result(
            route=ROUTE_NULL_CONSISTENT,
            abstained=False,
            reason="concordant_null_raw_evidence",
            accepted=accepted,
            positive=positive,
            negative=negative,
            unavailable=unavailable,
            conflicts=(),
            streams=items,
            config=cfg,
        )
    return _result(
        route=ROUTE_CONFLICT_REVIEW,
        abstained=True,
        reason="positive_stream_count_below_minimum",
        accepted=accepted,
        positive=positive,
        negative=negative,
        unavailable=unavailable,
        conflicts=positive,
        streams=items,
        config=cfg,
    )


def observation_from_spectral_result(
    result: Any,
    *,
    stream_id: str = "spectral",
    paired: Optional[bool] = None,
) -> EvidenceStreamObservation:
    """Adapt ``SpectralEvidenceResult`` without discarding region records."""

    accepted = bool(result.accepted)
    scores = tuple(result.scores) if accepted else ()
    input_digests = tuple(
        digest
        for digest in (
            result.reference_sha256,
            result.query_sha256,
            result.counterfactual_sha256,
        )
        if digest
    )
    return EvidenceStreamObservation(
        stream_id=stream_id,
        accepted=accepted,
        paired=bool(result.paired if paired is None else paired),
        score_raw=max((float(score.score_raw) for score in scores), default=None),
        quality_score=min((float(score.quality_score) for score in scores), default=None),
        reason=None if accepted else str(result.reason),
        detector_version=result.detector_version,
        score_schema=result.score_schema,
        config_digest=result.config_digest,
        input_digests=tuple(dict.fromkeys(input_digests)),
        evidence_digest=result.evidence_digest,
        details={"regions": [score.to_dict() for score in scores]},
    )


def observation_from_regional_batch(
    batch: Any,
    *,
    stream_id: str = "pixel_residual",
    paired: bool = True,
) -> EvidenceStreamObservation:
    """Adapt ``RegionalScoreBatch`` and retain every regional raw score."""

    accepted = bool(batch.accepted)
    scores = tuple(batch.scores) if accepted else ()
    input_digests = tuple(dict.fromkeys(score.input_normalized_sha256 for score in scores))
    return EvidenceStreamObservation(
        stream_id=stream_id,
        accepted=accepted,
        paired=paired,
        score_raw=max((float(score.score_raw) for score in scores), default=None),
        quality_score=min((float(score.quality_score) for score in scores), default=None),
        reason=None if accepted else str(batch.reason),
        detector_version=batch.detector_version,
        score_schema=batch.score_schema,
        config_digest=batch.adapter_config_digest,
        input_digests=input_digests,
        evidence_digest=batch.evidence_digest,
        details={"regions": [score.to_dict() for score in scores]},
    )


__all__ = [
    "VERSION",
    "ROUTER_SCHEMA",
    "ROUTE_CANDIDATE",
    "ROUTE_NULL_CONSISTENT",
    "ROUTE_CONFLICT_REVIEW",
    "ROUTE_INSUFFICIENT",
    "EvidenceStreamObservation",
    "MultiStreamRouteConfig",
    "MultiStreamRouteResult",
    "route_multistream_evidence",
    "observation_from_spectral_result",
    "observation_from_regional_batch",
]
