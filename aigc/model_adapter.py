"""Versioned raw source-residual adapter for real-image experiments.

The competition service has several paths that read files and return a
single score.  This module intentionally has a much smaller contract: the
caller decodes both images with :mod:`aigc.image_adapter`, aligns their
normalized grayscale arrays, and supplies the resulting regions.  The
adapter never opens a path, never guesses provenance, and never turns a raw
score into an AIGC probability.

``RegionalScoreBatch`` is the evidence sidecar used by the real-image
runner.  It keeps the input normalization digest, detector/schema identity,
coordinates and quality/source-match support beside every regional score so
the observation can be replayed without retaining a private path in the
result JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .forensic_features import (
    DETECTOR_VERSION,
    SCORE_SCHEMA,
    ResidualConfig,
    compare_aligned_regions,
)
from .image_adapter import ImageAdapterResult
from .regional_alignment import AlignedRegion


ADAPTER_VERSION = "source-residual-adapter-v1"
PREPROCESS_VERSION = "image-adapter-normalized-gray-v1"
CHANNEL_ORDER = "gray"
DTYPE = "float32"


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return value


def _hex_digest(name: str, value: str) -> str:
    _text(name, value)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return value.lower()


@dataclass(frozen=True)
class SourceResidualAdapterConfig:
    """Immutable settings for the deterministic residual adapter."""

    residual_config: ResidualConfig = field(default_factory=ResidualConfig)
    preprocess_version: str = PREPROCESS_VERSION
    channel_order: str = CHANNEL_ORDER
    dtype: str = DTYPE
    model_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.residual_config, ResidualConfig):
            raise ValueError("residual_config must be ResidualConfig")
        _text("preprocess_version", self.preprocess_version)
        if self.channel_order != CHANNEL_ORDER:
            raise ValueError("channel_order must be gray")
        if self.dtype != DTYPE:
            raise ValueError("dtype must be float32")
        if self.model_digest:
            _hex_digest("model_digest", self.model_digest)

    @property
    def resolved_model_digest(self) -> str:
        # The residual adapter has no learned weights.  Still expose a stable
        # digest so an evidence sidecar can distinguish it from a future
        # learned adapter with the same score schema.
        return self.model_digest or _digest(
            {
                "adapter_version": ADAPTER_VERSION,
                "detector_version": self.residual_config.detector_version,
                "score_schema": self.residual_config.score_schema,
                "residual_config": {
                    "mean_scale": self.residual_config.mean_scale,
                    "p95_scale": self.residual_config.p95_scale,
                    "edge_scale": self.residual_config.edge_scale,
                    "coverage_threshold": self.residual_config.coverage_threshold,
                },
            }
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": ADAPTER_VERSION,
            "preprocess_version": self.preprocess_version,
            "channel_order": self.channel_order,
            "dtype": self.dtype,
            "model_digest": self.resolved_model_digest,
            "detector_version": self.residual_config.detector_version,
            "score_schema": self.residual_config.score_schema,
            "residual_config": {
                "mean_scale": self.residual_config.mean_scale,
                "p95_scale": self.residual_config.p95_scale,
                "edge_scale": self.residual_config.edge_scale,
                "coverage_threshold": self.residual_config.coverage_threshold,
            },
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class RegionalScore:
    """One bounded raw score with its coordinate and input audit fields."""

    sample_id: str
    asset_id: str
    pair_id: str
    role: str
    region_id: str
    bbox_xyxy: Tuple[int, int, int, int]
    score_raw: float
    quality_score: float
    source_match_score: float
    detector_version: str
    score_schema: str
    input_normalized_sha256: str
    adapter_config_digest: str
    model_digest: str
    model_summary: Mapping[str, Any] = field(default_factory=dict)
    preprocess_version: str = PREPROCESS_VERSION
    channel_order: str = CHANNEL_ORDER
    dtype: str = DTYPE
    shape: Tuple[int, int] = (0, 0)
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("sample_id", self.sample_id),
            ("asset_id", self.asset_id),
            ("pair_id", self.pair_id),
            ("role", self.role),
            ("region_id", self.region_id),
            ("detector_version", self.detector_version),
            ("score_schema", self.score_schema),
            ("preprocess_version", self.preprocess_version),
        ):
            _text(name, value)
        if self.role not in {"reference", "observed", "counterfactual"}:
            raise ValueError("role must be reference, observed, or counterfactual")
        if len(self.bbox_xyxy) != 4:
            raise ValueError("bbox_xyxy must contain four coordinates")
        x0, y0, x1, y1 = self.bbox_xyxy
        if any(isinstance(item, bool) or not isinstance(item, int) for item in self.bbox_xyxy):
            raise ValueError("bbox_xyxy coordinates must be integers")
        if not (0 <= x0 < x1 and 0 <= y0 < y1):
            raise ValueError("bbox_xyxy must be a non-empty half-open rectangle")
        for name, value in (
            ("score_raw", self.score_raw),
            ("quality_score", self.quality_score),
            ("source_match_score", self.source_match_score),
        ):
            _unit(name, value)
        _hex_digest("input_normalized_sha256", self.input_normalized_sha256)
        _hex_digest("adapter_config_digest", self.adapter_config_digest)
        _hex_digest("model_digest", self.model_digest)
        if not isinstance(self.model_summary, Mapping):
            raise ValueError("model_summary must be a mapping")
        if self.channel_order != CHANNEL_ORDER or self.dtype != DTYPE:
            raise ValueError("unsupported channel order or dtype")
        if len(self.shape) != 2 or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 1 for item in self.shape
        ):
            raise ValueError("shape must contain two positive integers")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "role": self.role,
            "region_id": self.region_id,
            "bbox_xyxy": list(self.bbox_xyxy),
            "score_raw": self.score_raw,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "input_normalized_sha256": self.input_normalized_sha256,
            "adapter_config_digest": self.adapter_config_digest,
            "model_digest": self.model_digest,
            "model_summary": dict(self.model_summary),
            "preprocess_version": self.preprocess_version,
            "channel_order": self.channel_order,
            "dtype": self.dtype,
            "shape": list(self.shape),
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class RegionalScoreBatch:
    """Result of scoring one normalized image against one registered source."""

    accepted: bool
    reason: Optional[str]
    sample_id: str
    asset_id: str
    pair_id: str
    role: str
    input_normalized_sha256: Optional[str]
    adapter_config_digest: str
    model_digest: str
    detector_version: str
    score_schema: str
    model_summary: Mapping[str, Any] = field(default_factory=dict)
    scores: Tuple[RegionalScore, ...] = ()
    version: str = ADAPTER_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("sample_id", self.sample_id),
            ("asset_id", self.asset_id),
            ("pair_id", self.pair_id),
            ("role", self.role),
            ("adapter_config_digest", self.adapter_config_digest),
            ("model_digest", self.model_digest),
            ("detector_version", self.detector_version),
            ("score_schema", self.score_schema),
            ("version", self.version),
        ):
            _text(name, value)
        if self.role not in {"reference", "observed", "counterfactual"}:
            raise ValueError("role must be reference, observed, or counterfactual")
        _hex_digest("adapter_config_digest", self.adapter_config_digest)
        _hex_digest("model_digest", self.model_digest)
        if not isinstance(self.model_summary, Mapping):
            raise ValueError("model_summary must be a mapping")
        if self.accepted:
            if self.reason is not None or not self.scores:
                raise ValueError("accepted batch requires scores and no reason")
            if self.input_normalized_sha256 is None:
                raise ValueError("accepted batch requires normalized input digest")
            _hex_digest("input_normalized_sha256", self.input_normalized_sha256)
            ids = [item.region_id for item in self.scores]
            if len(set(ids)) != len(ids):
                raise ValueError("score region IDs must be unique")
        else:
            if not isinstance(self.reason, str) or not self.reason:
                raise ValueError("rejected batch requires a stable reason")
            if self.scores:
                raise ValueError("rejected batch cannot contain scores")
            if self.input_normalized_sha256 is not None:
                _hex_digest("input_normalized_sha256", self.input_normalized_sha256)

    @property
    def evidence_digest(self) -> str:
        return _digest(self._canonical_dict())

    def _canonical_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "accepted": self.accepted,
            "reason": self.reason,
            "sample_id": self.sample_id,
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "role": self.role,
            "input_normalized_sha256": self.input_normalized_sha256,
            "adapter_config_digest": self.adapter_config_digest,
            "model_digest": self.model_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "model_summary": dict(self.model_summary),
            "scores": [item.to_dict() for item in self.scores],
        }

    def to_dict(self) -> Dict[str, Any]:
        result = self._canonical_dict()
        result["evidence_digest"] = self.evidence_digest if self.scores else None
        return result


def _nested_grid(value: Any) -> Tuple[Tuple[float, ...], ...]:
    # Avoid making NumPy part of the adapter's public contract.  AlignedRegion
    # validates the array; ``tolist`` gives the dependency-light residual
    # primitive a stable representation.
    try:
        rows = value.tolist()
    except AttributeError:
        rows = value
    return tuple(tuple(float(item) for item in row) for row in rows)


class SourceResidualAdapter:
    """Score aligned regions from two already-decoded image results."""

    def __init__(self, config: Optional[SourceResidualAdapterConfig] = None) -> None:
        self.config = config or SourceResidualAdapterConfig()

    @property
    def detector_version(self) -> str:
        return self.config.residual_config.detector_version

    @property
    def score_schema(self) -> str:
        return self.config.residual_config.score_schema

    @property
    def model_summary(self) -> Dict[str, str]:
        return {
            "adapter": ADAPTER_VERSION,
            "weights": "none",
            "detector": self.detector_version,
            "score_schema": self.score_schema,
        }

    def _rejected(
        self,
        *,
        sample_id: str,
        asset_id: str,
        pair_id: str,
        role: str,
        reason: str,
        input_digest: Optional[str] = None,
    ) -> RegionalScoreBatch:
        return RegionalScoreBatch(
            accepted=False,
            reason=reason,
            sample_id=sample_id,
            asset_id=asset_id,
            pair_id=pair_id,
            role=role,
            input_normalized_sha256=input_digest,
            adapter_config_digest=self.config.digest,
            model_digest=self.config.resolved_model_digest,
            detector_version=self.detector_version,
            score_schema=self.score_schema,
            model_summary=self.model_summary,
        )

    def score_regions(
        self,
        *,
        sample_id: str,
        asset_id: str,
        pair_id: str,
        role: str,
        reference_result: ImageAdapterResult,
        query_result: ImageAdapterResult,
        regions: Sequence[AlignedRegion],
    ) -> RegionalScoreBatch:
        """Score one query image using regions aligned to the same source.

        A caller must pass the exact ``ImageAdapterResult`` objects used to
        create ``regions``.  The adapter checks accepted status, config
        identity and normalized digest before touching any region pixels.
        """

        for name, value in (
            ("sample_id", sample_id),
            ("asset_id", asset_id),
            ("pair_id", pair_id),
            ("role", role),
        ):
            _text(name, value)
        if role not in {"reference", "observed", "counterfactual"}:
            raise ValueError("role must be reference, observed, or counterfactual")
        if not isinstance(reference_result, ImageAdapterResult) or not isinstance(query_result, ImageAdapterResult):
            raise ValueError("reference_result and query_result must be ImageAdapterResult")
        query_digest = query_result.audit.normalized_sha256
        if (
            not reference_result.accepted
            or not query_result.accepted
            or reference_result.quality is None
            or query_result.quality is None
        ):
            return self._rejected(
                sample_id=sample_id,
                asset_id=asset_id,
                pair_id=pair_id,
                role=role,
                reason="quality_insufficient",
                input_digest=query_digest,
            )
        if query_digest is None or reference_result.audit.normalized_sha256 is None:
            return self._rejected(
                sample_id=sample_id,
                asset_id=asset_id,
                pair_id=pair_id,
                role=role,
                reason="adapter_failed",
                input_digest=query_digest,
            )
        if reference_result.audit.config_digest != query_result.audit.config_digest:
            return self._rejected(
                sample_id=sample_id,
                asset_id=asset_id,
                pair_id=pair_id,
                role=role,
                reason="schema_mismatch",
                input_digest=query_digest,
            )
        if not isinstance(regions, Sequence) or isinstance(regions, (str, bytes)) or not regions:
            return self._rejected(
                sample_id=sample_id,
                asset_id=asset_id,
                pair_id=pair_id,
                role=role,
                reason="no_regions",
                input_digest=query_digest,
            )
        if not all(isinstance(region, AlignedRegion) for region in regions):
            raise ValueError("regions must contain AlignedRegion values")
        scores = []
        try:
            for region in regions:
                evidence = compare_aligned_regions(
                    _nested_grid(region.reference),
                    _nested_grid(region.query),
                    config=self.config.residual_config,
                )
                quality_score = min(evidence.quality_score, region.match_score, query_result.quality.quality_score)
                scores.append(
                    RegionalScore(
                        sample_id=sample_id,
                        asset_id=asset_id,
                        pair_id=pair_id,
                        role=role,
                        region_id=region.region_id,
                        bbox_xyxy=tuple(int(item) for item in region.bbox),
                        score_raw=evidence.edit_score,
                        quality_score=quality_score,
                        source_match_score=region.match_score,
                        detector_version=evidence.detector_version,
                        score_schema=evidence.score_schema,
                        input_normalized_sha256=query_digest,
                        adapter_config_digest=self.config.digest,
                        model_digest=self.config.resolved_model_digest,
                        model_summary=self.model_summary,
                        preprocess_version=self.config.preprocess_version,
                        shape=tuple(int(item) for item in region.shape),
                        evidence=evidence.to_region_dict(region.region_id),
                    )
                )
        except (TypeError, ValueError, OverflowError):
            return self._rejected(
                sample_id=sample_id,
                asset_id=asset_id,
                pair_id=pair_id,
                role=role,
                reason="adapter_failed",
                input_digest=query_digest,
            )
        return RegionalScoreBatch(
            accepted=True,
            reason=None,
            sample_id=sample_id,
            asset_id=asset_id,
            pair_id=pair_id,
            role=role,
            input_normalized_sha256=query_digest,
            adapter_config_digest=self.config.digest,
            model_digest=self.config.resolved_model_digest,
            detector_version=self.detector_version,
            score_schema=self.score_schema,
            model_summary=self.model_summary,
            scores=tuple(scores),
        )

    # Explicit alias for callers that describe the operation as an aligned
    # image score rather than a region score.  Both names share one contract.
    score_aligned_regions = score_regions


__all__ = [
    "ADAPTER_VERSION",
    "PREPROCESS_VERSION",
    "CHANNEL_ORDER",
    "DTYPE",
    "SourceResidualAdapterConfig",
    "RegionalScore",
    "RegionalScoreBatch",
    "SourceResidualAdapter",
]
