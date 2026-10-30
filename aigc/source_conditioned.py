"""Source-conditioned regional evidence aggregation.

The module does not extract pixels itself.  A CLIP/patch adapter supplies
region pair observations between a query image and a registered source.  The
aggregator preserves region-level raw scores and produces the inputs consumed
by :func:`aigc.fusion.fuse_signals`.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


def _score(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return float(value)


@dataclass(frozen=True)
class RegionPair:
    """Raw output from a query/reference regional alignment adapter."""

    region_id: str
    semantic_similarity: float
    edit_score: Optional[float]
    quality_score: float
    alignment_version: str = "unknown"

    def __post_init__(self) -> None:
        if not self.region_id:
            raise ValueError("region_id is required")
        if not isinstance(self.alignment_version, str) or not self.alignment_version.strip():
            raise ValueError("alignment_version must be a non-empty string")
        _score("semantic_similarity", self.semantic_similarity)
        if self.edit_score is not None:
            _score("edit_score", self.edit_score)
        _score("quality_score", self.quality_score)


@dataclass(frozen=True)
class SourceConditionedAggregate:
    matched: bool
    source_match_score: Optional[float]
    edit_score: Optional[float]
    quality_score: Optional[float]
    regions: Tuple[Mapping[str, Any], ...]
    reason: Optional[str] = None

    def to_signals(self) -> Dict[str, Any]:
        """Return keyword arguments for ``DetectorSignals``."""

        return {
            "source_match_score": self.source_match_score,
            "source_conditioned_edit_score": self.edit_score,
            "quality_score": self.quality_score,
        }


def aggregate_region_pairs(
    pairs: Sequence[RegionPair],
    *,
    match_threshold: float = 0.75,
    max_regions: int = 8,
) -> SourceConditionedAggregate:
    """Aggregate aligned regions without collapsing them into a fake proof.

    Semantic similarity supplies the weight for the edit evidence.  This keeps
    a weakly aligned patch from dominating the result while preserving each
    selected ROI for later review.  The returned value is still a raw
    observation and must pass the calibrated fusion policy.
    """

    _score("match_threshold", match_threshold)
    if isinstance(max_regions, bool) or not isinstance(max_regions, int) or max_regions < 1:
        raise ValueError("max_regions must be positive")
    if not pairs:
        return SourceConditionedAggregate(
            matched=False,
            source_match_score=None,
            edit_score=None,
            quality_score=None,
            regions=(),
            reason="no_source_match",
        )

    # Combining scores produced by different alignment implementations would
    # make the aggregate irreproducible.  Refuse the entire batch so an
    # adapter cannot accidentally turn a version mismatch into edit evidence.
    versions = {pair.alignment_version for pair in pairs}
    if len(versions) > 1:
        return SourceConditionedAggregate(
            matched=False,
            source_match_score=None,
            edit_score=None,
            quality_score=None,
            regions=(),
            reason="alignment_version_conflict",
        )

    region_ids = [pair.region_id for pair in pairs]
    if len(set(region_ids)) != len(region_ids):
        raise ValueError("region_id values must be unique within one aggregate")
    matched = [
        pair for pair in pairs if pair.semantic_similarity >= match_threshold
    ]
    matched.sort(key=lambda pair: pair.semantic_similarity, reverse=True)
    matched = matched[:max_regions]
    if not matched:
        return SourceConditionedAggregate(
            matched=False,
            source_match_score=None,
            edit_score=None,
            quality_score=None,
            regions=(),
            reason="no_source_match",
        )

    edit_pairs = [pair for pair in matched if pair.edit_score is not None]
    total_weight = sum(pair.semantic_similarity for pair in edit_pairs)
    edit_score = None
    if total_weight:
        edit_score = sum(
            pair.semantic_similarity * float(pair.edit_score)
            for pair in edit_pairs
        ) / total_weight

    regions = tuple(
        {
            "region_id": pair.region_id,
            "semantic_similarity_raw": pair.semantic_similarity,
            "edit_score_raw": pair.edit_score,
            "quality_raw": pair.quality_score,
            "alignment_version": pair.alignment_version,
        }
        for pair in matched
    )
    return SourceConditionedAggregate(
        matched=True,
        source_match_score=max(pair.semantic_similarity for pair in matched),
        edit_score=edit_score,
        quality_score=min(pair.quality_score for pair in matched),
        regions=regions,
        reason=None if edit_score is not None else "no_edit_signal",
    )
