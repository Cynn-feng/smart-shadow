"""Blind reference-specificity control for source-conditioned evidence.

Source-conditioned forensics can fail before the detector stage: a query may
be paired with a visually similar but wrong registered reference.  A large
observed-minus-null contrast under that wrong reference is not evidence of a
local AI edit.  This module compares the candidate reference with a blind,
matched decoy reference pool for the same query and binds the selection and
evaluation partitions so that reference choice is auditable.

The output is deliberately raw evidence.  It is not an AIGC probability,
generator attribution, authorship statement, or legal finding.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple


VERSION = "reference-specificity-v1"
SCHEMA = "reference-specificity-result-v1"

ROUTE_REFERENCE_SPECIFIC = "reference_specific_candidate"
ROUTE_REFERENCE_AMBIGUOUS = "reference_ambiguous"
ROUTE_REFERENCE_NULL_CONSISTENT = "reference_null_consistent"
ROUTE_INSUFFICIENT = "insufficient"


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _digest_hex(name: str, value: str) -> str:
    normalized = _text(name, value).lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return normalized


def _unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    return normalized


def _contrast(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number between -2 and 2")
    normalized = float(value)
    if not math.isfinite(normalized) or not -2.0 <= normalized <= 2.0:
        raise ValueError(f"{name} must be finite and between -2 and 2")
    return normalized


def _gap(name: str, value: float) -> float:
    """Validate a difference between two bounded contrasts.

    Each contrast is bounded to ``[-2, 2]``; their difference therefore has
    the wider, exact range ``[-4, 4]``.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number between -4 and 4")
    normalized = float(value)
    if not math.isfinite(normalized) or not -4.0 <= normalized <= 4.0:
        raise ValueError(f"{name} must be finite and between -4 and 4")
    return normalized


def _alpha(value: float) -> float:
    normalized = _unit("alpha", value)
    if normalized <= 0.0 or normalized >= 1.0:
        raise ValueError("alpha must be strictly between 0 and 1")
    return normalized


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _upper_quantile(values: Sequence[float], q: float) -> float:
    """Return a deterministic nearest-rank upper quantile."""

    ordered = sorted(float(value) for value in values)
    index = min(len(ordered) - 1, max(0, int(math.ceil(q * len(ordered))) - 1))
    return ordered[index]


@dataclass(frozen=True)
class ReferenceSpecificityConfig:
    """Frozen gates for a blind reference comparison."""

    minimum_decoy_count: int = 3
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    decoy_quantile: float = 0.75
    alpha: float = 0.05
    minimum_candidate_contrast_raw: float = 0.05
    minimum_specificity_gap_raw: float = 0.05

    def __post_init__(self) -> None:
        if (
            isinstance(self.minimum_decoy_count, bool)
            or not isinstance(self.minimum_decoy_count, int)
            or self.minimum_decoy_count < 1
        ):
            raise ValueError("minimum_decoy_count must be a positive integer")
        object.__setattr__(self, "minimum_quality", _unit("minimum_quality", self.minimum_quality))
        object.__setattr__(self, "minimum_source_match", _unit("minimum_source_match", self.minimum_source_match))
        object.__setattr__(self, "decoy_quantile", _unit("decoy_quantile", self.decoy_quantile))
        if not 0.0 < self.decoy_quantile < 1.0:
            raise ValueError("decoy_quantile must be strictly between 0 and 1")
        object.__setattr__(self, "alpha", _alpha(self.alpha))
        for name in ("minimum_candidate_contrast_raw", "minimum_specificity_gap_raw"):
            value = _contrast(name, getattr(self, name))
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative")
            object.__setattr__(self, name, value)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "minimum_decoy_count": self.minimum_decoy_count,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "decoy_quantile": self.decoy_quantile,
            "alpha": self.alpha,
            "minimum_candidate_contrast_raw": self.minimum_candidate_contrast_raw,
            "minimum_specificity_gap_raw": self.minimum_specificity_gap_raw,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class ReferenceSpecificityObservation:
    """One candidate or decoy reference contrast for the same query."""

    observation_id: str
    reference_digest: str
    role: str
    contrast_raw: float
    quality_score: float
    source_match_score: float
    quality_bucket: str
    source_match_bucket: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_id", _text("observation_id", self.observation_id))
        object.__setattr__(self, "reference_digest", _digest_hex("reference_digest", self.reference_digest))
        object.__setattr__(self, "role", _text("role", self.role))
        if self.role not in {"candidate", "decoy"}:
            raise ValueError("role must be candidate or decoy")
        object.__setattr__(self, "contrast_raw", _contrast("contrast_raw", self.contrast_raw))
        object.__setattr__(self, "quality_score", _unit("quality_score", self.quality_score))
        object.__setattr__(self, "source_match_score", _unit("source_match_score", self.source_match_score))
        object.__setattr__(self, "quality_bucket", _text("quality_bucket", self.quality_bucket))
        object.__setattr__(self, "source_match_bucket", _text("source_match_bucket", self.source_match_bucket))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "observation_id": self.observation_id,
            "reference_digest": self.reference_digest,
            "role": self.role,
            "contrast_raw": self.contrast_raw,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "quality_bucket": self.quality_bucket,
            "source_match_bucket": self.source_match_bucket,
        }


@dataclass(frozen=True)
class ReferenceSpecificityBatch:
    """Candidate and blind decoy references bound to one query."""

    query_digest: str
    evaluation_split_digest: str
    selection_split_digest: str
    manifest_digest: str
    canonical_frame_digest: str
    transform_spec_digest: str
    operator_digest: str
    detector_version: str
    score_schema: str
    quality_bucket: str
    source_match_bucket: str
    selection_policy_digest: str
    candidate: ReferenceSpecificityObservation
    decoys: Tuple[ReferenceSpecificityObservation, ...]

    def __post_init__(self) -> None:
        for name in (
            "query_digest",
            "evaluation_split_digest",
            "selection_split_digest",
            "manifest_digest",
            "canonical_frame_digest",
            "transform_spec_digest",
            "operator_digest",
            "selection_policy_digest",
        ):
            object.__setattr__(self, name, _digest_hex(name, getattr(self, name)))
        if self.evaluation_split_digest == self.selection_split_digest:
            raise ValueError("evaluation and selection splits must be distinct")
        for name in ("detector_version", "score_schema", "quality_bucket", "source_match_bucket"):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        if not isinstance(self.candidate, ReferenceSpecificityObservation):
            raise ValueError("candidate must be ReferenceSpecificityObservation")
        if self.candidate.role != "candidate":
            raise ValueError("candidate role must be candidate")
        if isinstance(self.decoys, (str, bytes)):
            raise ValueError("decoys must be a sequence")
        try:
            ordered = tuple(self.decoys)
        except TypeError as exc:
            raise ValueError("decoys must be a sequence") from exc
        if any(not isinstance(item, ReferenceSpecificityObservation) for item in ordered):
            raise ValueError("decoys must contain ReferenceSpecificityObservation values")
        if any(item.role != "decoy" for item in ordered):
            raise ValueError("all decoy observations must have role decoy")
        ids = tuple(item.observation_id for item in ordered)
        if len(set(ids)) != len(ids):
            raise ValueError("decoy observation IDs must be unique")
        references = tuple(item.reference_digest for item in ordered)
        if len(set(references)) != len(references):
            raise ValueError("decoy reference digests must be unique")
        if self.candidate.reference_digest in set(references):
            raise ValueError("candidate reference must differ from every decoy")
        object.__setattr__(self, "decoys", tuple(sorted(ordered, key=lambda item: item.observation_id)))

    def binding_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "query_digest": self.query_digest,
            "evaluation_split_digest": self.evaluation_split_digest,
            "selection_split_digest": self.selection_split_digest,
            "manifest_digest": self.manifest_digest,
            "canonical_frame_digest": self.canonical_frame_digest,
            "transform_spec_digest": self.transform_spec_digest,
            "operator_digest": self.operator_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "quality_bucket": self.quality_bucket,
            "source_match_bucket": self.source_match_bucket,
            "selection_policy_digest": self.selection_policy_digest,
        }

    @property
    def binding_digest(self) -> str:
        return _digest(self.binding_dict())

    @property
    def decoy_pool_digest(self) -> str:
        return _digest(
            {
                "version": VERSION,
                "query_digest": self.query_digest,
                "selection_split_digest": self.selection_split_digest,
                "decoys": [item.to_dict() for item in self.decoys],
            }
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.binding_dict(),
            "binding_digest": self.binding_digest,
            "decoy_pool_digest": self.decoy_pool_digest,
            "candidate": self.candidate.to_dict(),
            "decoys": [item.to_dict() for item in self.decoys],
        }


@dataclass(frozen=True)
class ReferenceSpecificityResult:
    """Auditable route and specificity statistics."""

    route: str
    abstained: bool
    candidate_supported: bool
    reason: str
    candidate_reference_digest: str
    candidate_contrast_raw: float
    decoy_count: int
    decoy_ids: Tuple[str, ...]
    decoy_contrasts_raw: Tuple[float, ...]
    decoy_upper_quantile_raw: Optional[float]
    specificity_gap_raw: Optional[float]
    decoy_exceedance_count: Optional[int]
    decoy_exceedance_p_value_raw: Optional[float]
    minimum_decoy_count: int
    alpha: float
    config_digest: str
    binding_digest: str
    decoy_pool_digest: str
    evidence_digest: str
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.route not in {
            ROUTE_REFERENCE_SPECIFIC,
            ROUTE_REFERENCE_AMBIGUOUS,
            ROUTE_REFERENCE_NULL_CONSISTENT,
            ROUTE_INSUFFICIENT,
        }:
            raise ValueError("invalid reference specificity route")
        expected_abstain = self.route in {ROUTE_REFERENCE_AMBIGUOUS, ROUTE_INSUFFICIENT}
        if self.abstained != expected_abstain:
            raise ValueError("abstained does not match route")
        if self.candidate_supported != (self.route == ROUTE_REFERENCE_SPECIFIC):
            raise ValueError("candidate_supported does not match route")
        object.__setattr__(self, "reason", _text("reason", self.reason))
        object.__setattr__(self, "candidate_reference_digest", _digest_hex("candidate_reference_digest", self.candidate_reference_digest))
        _contrast("candidate_contrast_raw", self.candidate_contrast_raw)
        if isinstance(self.decoy_count, bool) or not isinstance(self.decoy_count, int) or self.decoy_count < 0:
            raise ValueError("decoy_count must be a non-negative integer")
        if len(self.decoy_ids) != len(self.decoy_contrasts_raw):
            raise ValueError("decoy IDs and contrasts must have equal length")
        ids = tuple(_text("decoy_id", item) for item in self.decoy_ids)
        if len(set(ids)) != len(ids):
            raise ValueError("decoy IDs must be unique")
        object.__setattr__(self, "decoy_ids", ids)
        object.__setattr__(self, "decoy_contrasts_raw", tuple(_contrast("decoy_contrast_raw", item) for item in self.decoy_contrasts_raw))
        if self.decoy_count != len(self.decoy_ids):
            raise ValueError("decoy_count does not match decoy IDs")
        if isinstance(self.minimum_decoy_count, bool) or not isinstance(self.minimum_decoy_count, int) or self.minimum_decoy_count < 1:
            raise ValueError("minimum_decoy_count must be a positive integer")
        object.__setattr__(self, "alpha", _alpha(self.alpha))
        for name in ("config_digest", "binding_digest", "decoy_pool_digest", "evidence_digest"):
            _digest_hex(name, getattr(self, name))
        if self.version != VERSION:
            raise ValueError("unsupported reference specificity version")
        stats = (
            self.decoy_upper_quantile_raw,
            self.specificity_gap_raw,
            self.decoy_exceedance_count,
            self.decoy_exceedance_p_value_raw,
        )
        if self.route == ROUTE_INSUFFICIENT:
            if any(value is not None for value in stats):
                raise ValueError("insufficient route cannot expose specificity statistics")
        else:
            if any(value is None for value in stats):
                raise ValueError("evaluated route requires specificity statistics")
            _contrast("decoy_upper_quantile_raw", self.decoy_upper_quantile_raw)
            _gap("specificity_gap_raw", self.specificity_gap_raw)
            if (
                isinstance(self.decoy_exceedance_count, bool)
                or not isinstance(self.decoy_exceedance_count, int)
                or not 0 <= self.decoy_exceedance_count <= self.decoy_count
            ):
                raise ValueError("decoy exceedance count is outside range")
            _unit("decoy_exceedance_p_value_raw", self.decoy_exceedance_p_value_raw)
            if self.decoy_exceedance_p_value_raw <= 0.0:
                raise ValueError("decoy p-value must be greater than zero")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "schema": SCHEMA,
            "route": self.route,
            "abstained": self.abstained,
            "candidate_supported": self.candidate_supported,
            "reason": self.reason,
            "candidate_reference_digest": self.candidate_reference_digest,
            "candidate_contrast_raw": self.candidate_contrast_raw,
            "decoy_count": self.decoy_count,
            "decoy_ids": list(self.decoy_ids),
            "decoy_contrasts_raw": list(self.decoy_contrasts_raw),
            "decoy_upper_quantile_raw": self.decoy_upper_quantile_raw,
            "specificity_gap_raw": self.specificity_gap_raw,
            "decoy_exceedance_count": self.decoy_exceedance_count,
            "decoy_exceedance_p_value_raw": self.decoy_exceedance_p_value_raw,
            "minimum_decoy_count": self.minimum_decoy_count,
            "alpha": self.alpha,
            "config_digest": self.config_digest,
            "binding_digest": self.binding_digest,
            "decoy_pool_digest": self.decoy_pool_digest,
            "evidence_digest": self.evidence_digest,
        }


def _empty_result(
    batch: ReferenceSpecificityBatch,
    config: ReferenceSpecificityConfig,
    reason: str,
) -> ReferenceSpecificityResult:
    evidence_digest = _digest(
        {
            "version": VERSION,
            "route": ROUTE_INSUFFICIENT,
            "reason": reason,
            "binding_digest": batch.binding_digest,
            "decoy_pool_digest": batch.decoy_pool_digest,
            "candidate_reference_digest": batch.candidate.reference_digest,
            "candidate_contrast_raw": batch.candidate.contrast_raw,
            "decoy_ids": [item.observation_id for item in batch.decoys],
        }
    )
    return ReferenceSpecificityResult(
        route=ROUTE_INSUFFICIENT,
        abstained=True,
        candidate_supported=False,
        reason=reason,
        candidate_reference_digest=batch.candidate.reference_digest,
        candidate_contrast_raw=batch.candidate.contrast_raw,
        decoy_count=len(batch.decoys),
        decoy_ids=tuple(item.observation_id for item in batch.decoys),
        decoy_contrasts_raw=tuple(item.contrast_raw for item in batch.decoys),
        decoy_upper_quantile_raw=None,
        specificity_gap_raw=None,
        decoy_exceedance_count=None,
        decoy_exceedance_p_value_raw=None,
        minimum_decoy_count=config.minimum_decoy_count,
        alpha=config.alpha,
        config_digest=config.digest,
        binding_digest=batch.binding_digest,
        decoy_pool_digest=batch.decoy_pool_digest,
        evidence_digest=evidence_digest,
    )


def evaluate_reference_specificity(
    batch: ReferenceSpecificityBatch,
    *,
    config: Optional[ReferenceSpecificityConfig] = None,
) -> ReferenceSpecificityResult:
    """Evaluate one candidate reference against matched blind decoys."""

    if not isinstance(batch, ReferenceSpecificityBatch):
        raise ValueError("batch must be ReferenceSpecificityBatch")
    cfg = config or ReferenceSpecificityConfig()
    observations = (batch.candidate, *batch.decoys)
    for item in observations:
        if item.quality_bucket != batch.quality_bucket:
            return _empty_result(batch, cfg, "quality_bucket_mismatch")
        if item.source_match_bucket != batch.source_match_bucket:
            return _empty_result(batch, cfg, "source_match_bucket_mismatch")
        if item.quality_score < cfg.minimum_quality:
            return _empty_result(batch, cfg, "quality_below_threshold")
        if item.source_match_score < cfg.minimum_source_match:
            return _empty_result(batch, cfg, "source_match_below_threshold")
    if len(batch.decoys) < cfg.minimum_decoy_count:
        return _empty_result(batch, cfg, "decoy_sample_insufficient")

    candidate = batch.candidate.contrast_raw
    decoy_values = tuple(item.contrast_raw for item in batch.decoys)
    upper = _upper_quantile(decoy_values, cfg.decoy_quantile)
    gap = candidate - upper
    exceedances = sum(value >= candidate for value in decoy_values)
    p_value = (1.0 + exceedances) / (len(decoy_values) + 1.0)

    if candidate < cfg.minimum_candidate_contrast_raw:
        route = ROUTE_REFERENCE_NULL_CONSISTENT
        reason = "candidate_contrast_below_gate"
    elif p_value <= cfg.alpha and gap >= cfg.minimum_specificity_gap_raw:
        route = ROUTE_REFERENCE_SPECIFIC
        reason = "candidate_exceeds_blind_decoy_pool"
    else:
        route = ROUTE_REFERENCE_AMBIGUOUS
        reason = "candidate_not_specific_against_blind_decoys"

    payload = {
        "version": VERSION,
        "route": route,
        "reason": reason,
        "batch": batch.to_dict(),
        "candidate_contrast_raw": candidate,
        "decoy_contrasts_raw": list(decoy_values),
        "decoy_upper_quantile_raw": upper,
        "specificity_gap_raw": gap,
        "decoy_exceedance_count": exceedances,
        "decoy_exceedance_p_value_raw": p_value,
        "config_digest": cfg.digest,
    }
    return ReferenceSpecificityResult(
        route=route,
        abstained=route in {ROUTE_REFERENCE_AMBIGUOUS, ROUTE_INSUFFICIENT},
        candidate_supported=route == ROUTE_REFERENCE_SPECIFIC,
        reason=reason,
        candidate_reference_digest=batch.candidate.reference_digest,
        candidate_contrast_raw=candidate,
        decoy_count=len(batch.decoys),
        decoy_ids=tuple(item.observation_id for item in batch.decoys),
        decoy_contrasts_raw=decoy_values,
        decoy_upper_quantile_raw=upper,
        specificity_gap_raw=gap,
        decoy_exceedance_count=exceedances,
        decoy_exceedance_p_value_raw=p_value,
        minimum_decoy_count=cfg.minimum_decoy_count,
        alpha=cfg.alpha,
        config_digest=cfg.digest,
        binding_digest=batch.binding_digest,
        decoy_pool_digest=batch.decoy_pool_digest,
        evidence_digest=_digest(payload),
    )


__all__ = [
    "VERSION",
    "SCHEMA",
    "ROUTE_REFERENCE_SPECIFIC",
    "ROUTE_REFERENCE_AMBIGUOUS",
    "ROUTE_REFERENCE_NULL_CONSISTENT",
    "ROUTE_INSUFFICIENT",
    "ReferenceSpecificityConfig",
    "ReferenceSpecificityObservation",
    "ReferenceSpecificityBatch",
    "ReferenceSpecificityResult",
    "evaluate_reference_specificity",
]
