"""Deterministic image-grid alignment for source-conditioned regional evidence.

The competition-era service does not provide a safe geometric registration
contract.  This module is a deliberately small adapter between the bounded
``image_adapter`` output and :mod:`aigc.regional_counterfactual`:

* validate normalized grayscale grids (or the ``gray`` array returned by the
  image adapter);
* optionally resize a propagation version to the registered source shape with
  a versioned bilinear sampler;
* search a bounded integer translation using a robust, median-centered cost;
* partition the common overlap into deterministic regions; and
* turn paired observed/counterfactual regions into raw
  ``RegionalObservation`` values.

All scores in this module are support/raw measurements.  ``match_score`` is a
bounded alignment support value, not a probability, and ``edit_score`` comes
from ``source-residual-v1``.  A geometry mismatch, weak overlap, or unstable
pair produces an explicit rejection so a caller cannot silently manufacture a
PC-SCFT pair.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:  # The real image adapter already requires NumPy.
    import numpy as np
except ModuleNotFoundError:  # pragma: no cover - dependency gate in callers
    np = None  # type: ignore[assignment]

from .forensic_features import ResidualConfig, ResidualEvidence, compare_aligned_regions
from .regional_counterfactual import RegionalObservation


ALIGNMENT_VERSION = "regional-alignment-v2"
RESIZE_VERSION = "bilinear-grid-resize-v1"
REGION_VERSION = "regional-window-v1"
RESULT_VERSION = "regional-observation-batch-v1"


def _unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return value


def _positive(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive finite number")
    value = float(value)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be a positive finite number")
    return value


def _non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _nested_grid(value: Any) -> Tuple[Tuple[float, ...], ...]:
    """Convert an internal NumPy region to the dependency-light grid shape."""

    _require_numpy()
    return tuple(tuple(float(item) for item in row) for row in value.tolist())


@dataclass(frozen=True)
class AlignmentConfig:
    """Versioned gates for bounded source/query alignment."""

    max_translation: int = 4
    minimum_overlap: float = 0.75
    minimum_match_score: float = 0.35
    allow_resize: bool = True
    min_region_side: int = 8
    grid_rows: int = 2
    grid_cols: int = 2
    resize_version: str = RESIZE_VERSION
    alignment_version: str = ALIGNMENT_VERSION

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_translation, bool)
            or not isinstance(self.max_translation, int)
            or self.max_translation < 0
        ):
            raise ValueError("max_translation must be a non-negative integer")
        for name in ("minimum_overlap", "minimum_match_score"):
            _unit(name, getattr(self, name))
        if not isinstance(self.allow_resize, bool):
            raise ValueError("allow_resize must be a bool")
        for name in ("min_region_side", "grid_rows", "grid_cols"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        _non_empty("resize_version", self.resize_version)
        _non_empty("alignment_version", self.alignment_version)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_translation": self.max_translation,
            "minimum_overlap": self.minimum_overlap,
            "minimum_match_score": self.minimum_match_score,
            "allow_resize": self.allow_resize,
            "min_region_side": self.min_region_side,
            "grid_rows": self.grid_rows,
            "grid_cols": self.grid_cols,
            "resize_version": self.resize_version,
            "alignment_version": self.alignment_version,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


def _require_numpy() -> None:
    if np is None:
        raise RuntimeError("regional alignment requires NumPy; install requirements-research.txt")


def _as_gray(name: str, value: Any) -> Any:
    """Validate a finite normalized 2-D array without silently clipping."""

    _require_numpy()
    try:
        array = np.asarray(value, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a 2-D numeric grid") from exc
    if array.ndim != 2 or array.shape[0] < 2 or array.shape[1] < 2:
        raise ValueError(f"{name} must be a 2-D grid with both sides >= 2")
    if not bool(np.isfinite(array).all()):
        raise ValueError(f"{name} must contain finite values")
    if float(array.min()) < 0.0 or float(array.max()) > 1.0:
        raise ValueError(f"{name} values must be between 0 and 1")
    return np.ascontiguousarray(array, dtype=np.float32)


def _resize_bilinear(grid: Any, target_shape: Tuple[int, int]) -> Any:
    """Resize a grid with a fixed center-aligned bilinear sampler."""

    _require_numpy()
    src_h, src_w = (int(v) for v in grid.shape)
    dst_h, dst_w = target_shape
    if (src_h, src_w) == (dst_h, dst_w):
        return grid
    # Center-aligned coordinates match common image resizers and are fully
    # deterministic across calls.  No extrapolation is permitted.
    ys = (np.arange(dst_h, dtype=np.float32) + 0.5) * src_h / dst_h - 0.5
    xs = (np.arange(dst_w, dtype=np.float32) + 0.5) * src_w / dst_w - 0.5
    # Clamp coordinates before deriving interpolation weights.  Without this
    # order, the first/last sample could borrow an interior pixel even though
    # the declared sampler has no extrapolation policy.
    ys = np.clip(ys, 0.0, float(src_h - 1))
    xs = np.clip(xs, 0.0, float(src_w - 1))
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    y1 = np.clip(y0 + 1, 0, src_h - 1)
    x1 = np.clip(x0 + 1, 0, src_w - 1)
    wy = np.clip(ys - np.floor(ys), 0.0, 1.0).astype(np.float32)
    wx = np.clip(xs - np.floor(xs), 0.0, 1.0).astype(np.float32)
    top = grid[y0[:, None], x0[None, :]] * (1.0 - wx[None, :]) + grid[
        y0[:, None], x1[None, :]
    ] * wx[None, :]
    bottom = grid[y1[:, None], x0[None, :]] * (1.0 - wx[None, :]) + grid[
        y1[:, None], x1[None, :]
    ] * wx[None, :]
    return np.ascontiguousarray(top * (1.0 - wy[:, None]) + bottom * wy[:, None], dtype=np.float32)


@dataclass(frozen=True)
class AlignmentResult:
    """Auditable common overlap of one source/query pair."""

    accepted: bool
    reason: Optional[str]
    reference_shape: Tuple[int, int]
    query_shape: Tuple[int, int]
    aligned_shape: Optional[Tuple[int, int]]
    reference_offset: Optional[Tuple[int, int]]
    query_offset: Optional[Tuple[int, int]]
    dx: Optional[int]
    dy: Optional[int]
    overlap_fraction: float
    match_score: Optional[float]
    cost_raw: Optional[float]
    global_shift_raw: Optional[float]
    resized_query: bool
    resize_version: Optional[str]
    alignment_version: str
    config_digest: str
    reference_aligned: Any = field(default=None, repr=False, compare=False)
    query_aligned: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.accepted and self.reason is not None:
            raise ValueError("accepted alignment cannot have a rejection reason")
        if not self.accepted and (not isinstance(self.reason, str) or not self.reason):
            raise ValueError("rejected alignment requires a stable reason")
        _unit("overlap_fraction", self.overlap_fraction)
        if self.match_score is not None:
            _unit("match_score", self.match_score)
        if self.cost_raw is not None:
            _unit("cost_raw", self.cost_raw)
        if self.global_shift_raw is not None and not math.isfinite(float(self.global_shift_raw)):
            raise ValueError("global_shift_raw must be finite")
        if self.accepted:
            if self.aligned_shape is None or self.reference_aligned is None or self.query_aligned is None:
                raise ValueError("accepted alignment must contain common grids")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": RESULT_VERSION,
            "accepted": self.accepted,
            "reason": self.reason,
            "reference_shape": list(self.reference_shape),
            "query_shape": list(self.query_shape),
            "aligned_shape": list(self.aligned_shape) if self.aligned_shape else None,
            "reference_offset": list(self.reference_offset) if self.reference_offset else None,
            "query_offset": list(self.query_offset) if self.query_offset else None,
            "dx": self.dx,
            "dy": self.dy,
            "overlap_fraction": self.overlap_fraction,
            "match_score": self.match_score,
            "cost_raw": self.cost_raw,
            "global_shift_raw": self.global_shift_raw,
            "resized_query": self.resized_query,
            "resize_version": self.resize_version,
            "alignment_version": self.alignment_version,
            "config_digest": self.config_digest,
        }


def _overlap_slices(shape: Tuple[int, int], dx: int, dy: int) -> Optional[Tuple[slice, slice, slice, slice]]:
    """Return reference/query slices for query = reference shifted by (dx,dy)."""

    height, width = shape
    # Positive dx/dy means query content starts to the right/down relative to
    # reference.  Both arrays share the resulting overlap dimensions.
    rx0 = max(0, dx)
    ry0 = max(0, dy)
    qx0 = max(0, -dx)
    qy0 = max(0, -dy)
    overlap_w = width - abs(dx)
    overlap_h = height - abs(dy)
    if overlap_w < 2 or overlap_h < 2:
        return None
    return (
        slice(ry0, ry0 + overlap_h),
        slice(rx0, rx0 + overlap_w),
        slice(qy0, qy0 + overlap_h),
        slice(qx0, qx0 + overlap_w),
    )


def _candidate_cost(reference: Any, query: Any, slices: Tuple[slice, slice, slice, slice]) -> Tuple[float, float]:
    ref = reference[slices[0], slices[1]]
    qry = query[slices[2], slices[3]]
    residual = (qry - ref).astype(np.float32, copy=False)
    shift = float(np.median(residual))
    centered = np.abs(residual - shift).reshape(-1)
    # A local edit should not move the registration away from the source
    # coordinate frame.  Use a fixed lower-quartile trimmed cost for the
    # alignment search, while keeping the full residual available to the
    # downstream forensic feature.  The trim is deliberately part of the
    # versioned algorithm, rather than a hidden data-dependent threshold.
    trim_cut = float(np.quantile(centered, 0.75))
    trimmed = centered[centered <= trim_cut + 1e-7]
    if trimmed.size == 0:  # defensive; quantile guarantees one element
        trimmed = centered
    # The median term makes ties on flat/near-flat regions deterministic and
    # p95 is intentionally *not* used for registration: it would let a local
    # edit dominate the geometric search.  Full p95 remains in residual raw
    # evidence after alignment.
    cost = float(0.70 * np.mean(trimmed) + 0.30 * np.median(trimmed))
    return cost, shift


def align_gray_grids(
    reference: Any,
    query: Any,
    *,
    config: Optional[AlignmentConfig] = None,
) -> AlignmentResult:
    """Align one normalized source/query pair with a bounded integer search.

    ``query`` is resized to the reference dimensions only when
    ``config.allow_resize`` is true.  Every accepted result records the resize
    algorithm and the source/query offsets; callers must retain these fields
    when constructing a manifest.
    """

    cfg = config or AlignmentConfig()
    ref = _as_gray("reference", reference)
    raw_query = _as_gray("query", query)
    ref_shape = tuple(int(v) for v in ref.shape)
    query_shape = tuple(int(v) for v in raw_query.shape)
    resized = ref_shape != query_shape
    if resized and not cfg.allow_resize:
        return AlignmentResult(
            accepted=False,
            reason="shape_mismatch",
            reference_shape=ref_shape,
            query_shape=query_shape,
            aligned_shape=None,
            reference_offset=None,
            query_offset=None,
            dx=None,
            dy=None,
            overlap_fraction=0.0,
            match_score=None,
            cost_raw=None,
            global_shift_raw=None,
            resized_query=False,
            resize_version=None,
            alignment_version=cfg.alignment_version,
            config_digest=cfg.digest,
        )
    aligned_query = _resize_bilinear(raw_query, ref_shape) if resized else raw_query

    candidates: List[Tuple[float, float, int, int, int, int, float]] = []
    height, width = ref_shape
    for dy in range(-cfg.max_translation, cfg.max_translation + 1):
        for dx in range(-cfg.max_translation, cfg.max_translation + 1):
            slices = _overlap_slices(ref_shape, dx, dy)
            if slices is None:
                continue
            overlap_h = slices[0].stop - slices[0].start
            overlap_w = slices[1].stop - slices[1].start
            overlap = (overlap_h * overlap_w) / float(height * width)
            if overlap < cfg.minimum_overlap:
                continue
            cost, shift = _candidate_cost(ref, aligned_query, slices)
            # Sort by cost first, then overlap, then smallest transform, then
            # deterministic coordinates.  Do not let a quality tie vary by
            # dictionary/hash iteration order.
            candidates.append((cost, -overlap, abs(dx) + abs(dy), abs(dy), dy, dx, shift))
    if not candidates:
        return AlignmentResult(
            accepted=False,
            reason="overlap_below_threshold",
            reference_shape=ref_shape,
            query_shape=query_shape,
            aligned_shape=None,
            reference_offset=None,
            query_offset=None,
            dx=None,
            dy=None,
            overlap_fraction=0.0,
            match_score=None,
            cost_raw=None,
            global_shift_raw=None,
            resized_query=resized,
            resize_version=cfg.resize_version if resized else None,
            alignment_version=cfg.alignment_version,
            config_digest=cfg.digest,
        )
    best = min(candidates)
    cost, negative_overlap, _, _, dy, dx, shift = best
    overlap = -negative_overlap
    match_score = max(0.0, min(1.0, 1.0 - cost))
    if match_score < cfg.minimum_match_score:
        return AlignmentResult(
            accepted=False,
            reason="match_below_threshold",
            reference_shape=ref_shape,
            query_shape=query_shape,
            aligned_shape=None,
            reference_offset=None,
            query_offset=None,
            dx=dx,
            dy=dy,
            overlap_fraction=overlap,
            match_score=match_score,
            cost_raw=cost,
            global_shift_raw=shift,
            resized_query=resized,
            resize_version=cfg.resize_version if resized else None,
            alignment_version=cfg.alignment_version,
            config_digest=cfg.digest,
        )
    slices = _overlap_slices(ref_shape, dx, dy)
    assert slices is not None
    ref_overlap = np.ascontiguousarray(ref[slices[0], slices[1]], dtype=np.float32)
    query_overlap = np.ascontiguousarray(aligned_query[slices[2], slices[3]], dtype=np.float32)
    aligned_shape = tuple(int(v) for v in ref_overlap.shape)
    return AlignmentResult(
        accepted=True,
        reason=None,
        reference_shape=ref_shape,
        query_shape=query_shape,
        aligned_shape=aligned_shape,
        reference_offset=(int(slices[0].start), int(slices[1].start)),
        query_offset=(int(slices[2].start), int(slices[3].start)),
        dx=int(dx),
        dy=int(dy),
        overlap_fraction=overlap,
        match_score=match_score,
        cost_raw=cost,
        global_shift_raw=shift,
        resized_query=resized,
        resize_version=cfg.resize_version if resized else None,
        alignment_version=cfg.alignment_version,
        config_digest=cfg.digest,
        reference_aligned=ref_overlap,
        query_aligned=query_overlap,
    )


@dataclass(frozen=True)
class AlignedRegion:
    """One deterministic region in a common aligned overlap."""

    region_id: str
    bbox: Tuple[int, int, int, int]
    reference: Any = field(repr=False, compare=False)
    query: Any = field(repr=False, compare=False)
    alignment_version: str = ALIGNMENT_VERSION
    overlap_fraction: float = 1.0
    match_score: float = 0.0

    def __post_init__(self) -> None:
        _non_empty("region_id", self.region_id)
        if len(self.bbox) != 4:
            raise ValueError("bbox must contain four coordinates")
        x0, y0, x1, y1 = self.bbox
        if not (0 <= x0 < x1 and 0 <= y0 < y1):
            raise ValueError("bbox must be a non-empty half-open rectangle")
        _unit("overlap_fraction", self.overlap_fraction)
        _unit("match_score", self.match_score)
        ref = _as_gray("reference_region", self.reference)
        qry = _as_gray("query_region", self.query)
        if ref.shape != qry.shape:
            raise ValueError("reference_region and query_region must share shape")

    @property
    def shape(self) -> Tuple[int, int]:
        return tuple(int(v) for v in self.reference.shape)


def partition_aligned_regions(
    alignment: AlignmentResult,
    *,
    config: Optional[AlignmentConfig] = None,
) -> Tuple[AlignedRegion, ...]:
    """Split an accepted overlap into deterministic row/column regions."""

    cfg = config or AlignmentConfig()
    if not alignment.accepted:
        raise ValueError("cannot partition a rejected alignment")
    assert alignment.aligned_shape is not None
    height, width = alignment.aligned_shape
    if height < cfg.grid_rows * cfg.min_region_side or width < cfg.grid_cols * cfg.min_region_side:
        raise ValueError("aligned grid is too small for configured regions")
    assert alignment.reference_aligned is not None and alignment.query_aligned is not None
    regions: List[AlignedRegion] = []
    y_edges = [round(index * height / cfg.grid_rows) for index in range(cfg.grid_rows + 1)]
    x_edges = [round(index * width / cfg.grid_cols) for index in range(cfg.grid_cols + 1)]
    for row in range(cfg.grid_rows):
        for col in range(cfg.grid_cols):
            y0, y1 = y_edges[row], y_edges[row + 1]
            x0, x1 = x_edges[col], x_edges[col + 1]
            if y1 - y0 < cfg.min_region_side or x1 - x0 < cfg.min_region_side:
                continue
            regions.append(
                AlignedRegion(
                    region_id=f"g{row}c{col}",
                    bbox=(x0, y0, x1, y1),
                    reference=alignment.reference_aligned[y0:y1, x0:x1],
                    query=alignment.query_aligned[y0:y1, x0:x1],
                    alignment_version=alignment.alignment_version,
                    overlap_fraction=alignment.overlap_fraction,
                    match_score=alignment.match_score or 0.0,
                )
            )
    if not regions:
        raise ValueError("no regions survived configured minimum side")
    return tuple(regions)


@dataclass(frozen=True)
class RegionalObservationBatch:
    """Paired image-derived observations ready for PC-SCFT fusion."""

    accepted: bool
    reason: Optional[str]
    asset_id: str
    pair_id: str
    transform_family: str
    observed_alignment: AlignmentResult
    counterfactual_alignment: AlignmentResult
    observations: Tuple[RegionalObservation, ...] = ()
    region_count: int = 0
    version: str = RESULT_VERSION

    def __post_init__(self) -> None:
        _non_empty("asset_id", self.asset_id)
        _non_empty("pair_id", self.pair_id)
        _non_empty("transform_family", self.transform_family)
        if self.accepted and self.reason is not None:
            raise ValueError("accepted batch cannot have a rejection reason")
        if not self.accepted and (not isinstance(self.reason, str) or not self.reason):
            raise ValueError("rejected batch requires a stable reason")
        if self.accepted and len(self.observations) != self.region_count * 2:
            raise ValueError("accepted batch must contain observed and counterfactual rows")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "accepted": self.accepted,
            "reason": self.reason,
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "transform_family": self.transform_family,
            "observed_alignment": self.observed_alignment.to_dict(),
            "counterfactual_alignment": self.counterfactual_alignment.to_dict(),
            "observations": [item.to_dict() for item in self.observations],
            "region_count": self.region_count,
        }


def _reject_batch(
    *,
    reason: str,
    asset_id: str,
    pair_id: str,
    transform_family: str,
    observed_alignment: AlignmentResult,
    counterfactual_alignment: AlignmentResult,
) -> RegionalObservationBatch:
    return RegionalObservationBatch(
        accepted=False,
        reason=reason,
        asset_id=asset_id,
        pair_id=pair_id,
        transform_family=transform_family,
        observed_alignment=observed_alignment,
        counterfactual_alignment=counterfactual_alignment,
    )


def build_paired_regional_observations(
    reference: Any,
    observed: Any,
    counterfactual: Any,
    *,
    asset_id: str,
    pair_id: str,
    transform_family: str,
    alignment_config: Optional[AlignmentConfig] = None,
    residual_config: Optional[ResidualConfig] = None,
) -> RegionalObservationBatch:
    """Build one image-backed observed/counterfactual regional pair.

    Both versions are aligned independently to the same registered source,
    then their overlap geometry is required to match exactly.  This strict
    check prevents an edit-induced alignment drift from comparing different
    source coordinates under the same ``region_id``.
    """

    _non_empty("asset_id", asset_id)
    _non_empty("pair_id", pair_id)
    _non_empty("transform_family", transform_family)
    cfg = alignment_config or AlignmentConfig()
    residual_cfg = residual_config or ResidualConfig()
    observed_alignment = align_gray_grids(reference, observed, config=cfg)
    counterfactual_alignment = align_gray_grids(reference, counterfactual, config=cfg)
    if not observed_alignment.accepted:
        return _reject_batch(
            reason=f"observed_{observed_alignment.reason}",
            asset_id=asset_id,
            pair_id=pair_id,
            transform_family=transform_family,
            observed_alignment=observed_alignment,
            counterfactual_alignment=counterfactual_alignment,
        )
    if not counterfactual_alignment.accepted:
        return _reject_batch(
            reason=f"counterfactual_{counterfactual_alignment.reason}",
            asset_id=asset_id,
            pair_id=pair_id,
            transform_family=transform_family,
            observed_alignment=observed_alignment,
            counterfactual_alignment=counterfactual_alignment,
        )
    if observed_alignment.aligned_shape != counterfactual_alignment.aligned_shape:
        return _reject_batch(
            reason="paired_shape_mismatch",
            asset_id=asset_id,
            pair_id=pair_id,
            transform_family=transform_family,
            observed_alignment=observed_alignment,
            counterfactual_alignment=counterfactual_alignment,
        )
    if observed_alignment.reference_offset != counterfactual_alignment.reference_offset:
        return _reject_batch(
            reason="paired_reference_offset_mismatch",
            asset_id=asset_id,
            pair_id=pair_id,
            transform_family=transform_family,
            observed_alignment=observed_alignment,
            counterfactual_alignment=counterfactual_alignment,
        )
    try:
        observed_regions = partition_aligned_regions(observed_alignment, config=cfg)
        counterfactual_regions = partition_aligned_regions(counterfactual_alignment, config=cfg)
    except ValueError as exc:
        return _reject_batch(
            reason=f"region_partition_failed:{str(exc)}",
            asset_id=asset_id,
            pair_id=pair_id,
            transform_family=transform_family,
            observed_alignment=observed_alignment,
            counterfactual_alignment=counterfactual_alignment,
        )
    observed_by_id = {region.region_id: region for region in observed_regions}
    counterfactual_by_id = {region.region_id: region for region in counterfactual_regions}
    if set(observed_by_id) != set(counterfactual_by_id):
        return _reject_batch(
            reason="paired_region_set_mismatch",
            asset_id=asset_id,
            pair_id=pair_id,
            transform_family=transform_family,
            observed_alignment=observed_alignment,
            counterfactual_alignment=counterfactual_alignment,
        )
    ordered_ids = tuple(sorted(observed_by_id))
    output: List[RegionalObservation] = []
    for region_id in ordered_ids:
        obs_region = observed_by_id[region_id]
        cf_region = counterfactual_by_id[region_id]
        obs_evidence = compare_aligned_regions(
            _nested_grid(obs_region.reference),
            _nested_grid(obs_region.query),
            config=residual_cfg,
        )
        cf_evidence = compare_aligned_regions(
            _nested_grid(cf_region.reference),
            _nested_grid(cf_region.query),
            config=residual_cfg,
        )
        # Keep the stricter of residual quality and geometric support.  This
        # only gates evidence support; it does not become a probability.
        obs_quality = min(obs_evidence.quality_score, obs_region.match_score)
        cf_quality = min(cf_evidence.quality_score, cf_region.match_score)
        output.extend(
            (
                RegionalObservation(
                    asset_id=asset_id,
                    pair_id=pair_id,
                    region_id=region_id,
                    version_id=f"{pair_id}:observed:{region_id}",
                    transform_family=transform_family,
                    score_raw=obs_evidence.edit_score,
                    quality_score=obs_quality,
                    source_match_score=obs_region.match_score,
                    kind="observed",
                    detector_version=obs_evidence.detector_version,
                    score_schema=obs_evidence.score_schema,
                    propagation_chain=(transform_family,),
                ),
                RegionalObservation(
                    asset_id=asset_id,
                    pair_id=pair_id,
                    region_id=region_id,
                    version_id=f"{pair_id}:counterfactual:{region_id}",
                    transform_family=transform_family,
                    score_raw=cf_evidence.edit_score,
                    quality_score=cf_quality,
                    source_match_score=cf_region.match_score,
                    kind="counterfactual",
                    detector_version=cf_evidence.detector_version,
                    score_schema=cf_evidence.score_schema,
                    propagation_chain=(transform_family,),
                ),
            )
        )
    return RegionalObservationBatch(
        accepted=True,
        reason=None,
        asset_id=asset_id,
        pair_id=pair_id,
        transform_family=transform_family,
        observed_alignment=observed_alignment,
        counterfactual_alignment=counterfactual_alignment,
        observations=tuple(output),
        region_count=len(ordered_ids),
    )


__all__ = [
    "ALIGNMENT_VERSION",
    "RESIZE_VERSION",
    "REGION_VERSION",
    "RESULT_VERSION",
    "AlignmentConfig",
    "AlignmentResult",
    "align_gray_grids",
    "AlignedRegion",
    "partition_aligned_regions",
    "RegionalObservationBatch",
    "build_paired_regional_observations",
]
