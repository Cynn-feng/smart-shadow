"""Dependency-light source-conditioned residual features.

This module is deliberately an *adapter-level* primitive.  It compares two
already aligned, normalized grayscale regions and returns raw residual
observations that a calibrated detector may later consume.  It does not read
image files, infer AIGC, or replace a C2PA verifier.  Keeping the operation
free of Pillow/NumPy makes the protocol testable before a production image
adapter is selected.

The intended research hypothesis is that a registered source lets us ask a
more specific question than "is this image AI?": which aligned region changed
and is the change consistent with a local edit?  The score below is therefore
named ``edit_score_raw`` and must be calibrated against a fixed perturbation
set before it is passed to :func:`aigc.fusion.fuse_signals`.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, Optional, Sequence, Tuple


DETECTOR_VERSION = "source-residual-v1"
SCORE_SCHEMA = "source-residual-score-v1"


def _finite_unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return result


def _finite_signed_unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or not -1.0 <= result <= 1.0:
        raise ValueError(f"{name} must be finite and between -1 and 1")
    return result


def _positive(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive finite number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be a positive finite number")
    return result


def _grid(name: str, values: Sequence[Sequence[float]]) -> Tuple[Tuple[float, ...], ...]:
    """Validate and freeze a normalized 2-D grid.

    Pixel values are expected to be in ``[0, 1]``.  Silent clipping would hide
    an adapter bug and make the residual score irreproducible, so invalid
    values are rejected instead.
    """

    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be a non-empty 2-D sequence")
    rows = list(values)
    if not rows:
        raise ValueError(f"{name} must be a non-empty 2-D sequence")
    frozen = []
    width: Optional[int] = None
    for row_index, row in enumerate(rows):
        if isinstance(row, (str, bytes)) or not isinstance(row, Sequence):
            raise ValueError(f"{name}[{row_index}] must be a sequence")
        row_values = list(row)
        if width is None:
            width = len(row_values)
            if width == 0:
                raise ValueError(f"{name} rows must not be empty")
        elif len(row_values) != width:
            raise ValueError(f"{name} must be rectangular")
        normalized = []
        for column_index, value in enumerate(row_values):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name}[{row_index}][{column_index}] must be a number")
            number = float(value)
            if not math.isfinite(number) or not 0.0 <= number <= 1.0:
                raise ValueError(
                    f"{name}[{row_index}][{column_index}] must be finite and between 0 and 1"
                )
            normalized.append(number)
        frozen.append(tuple(normalized))
    return tuple(frozen)


def _mask(
    values: Optional[Sequence[Sequence[float]]], height: int, width: int
) -> Tuple[Tuple[bool, ...], ...]:
    if values is None:
        return tuple(tuple(True for _ in range(width)) for _ in range(height))
    raw = _grid("mask", values)
    if len(raw) != height or len(raw[0]) != width:
        raise ValueError("mask must have the same shape as reference and query")
    result = tuple(tuple(value > 0.5 for value in row) for row in raw)
    if not any(any(row) for row in result):
        raise ValueError("mask must select at least one pixel")
    return result


def _quantile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("quantile requires at least one value")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


@dataclass(frozen=True)
class ResidualConfig:
    """Normalization constants for the raw residual score.

    These values only put heterogeneous observations on a bounded scale.  A
    validation run must still learn decision thresholds and calibration from a
    held-out manifest; the defaults are not a claim of detector accuracy.
    """

    mean_scale: float = 0.08
    p95_scale: float = 0.20
    edge_scale: float = 0.20
    coverage_threshold: float = 0.08
    detector_version: str = DETECTOR_VERSION
    score_schema: str = SCORE_SCHEMA

    def __post_init__(self) -> None:
        _positive("mean_scale", self.mean_scale)
        _positive("p95_scale", self.p95_scale)
        _positive("edge_scale", self.edge_scale)
        _finite_unit("coverage_threshold", self.coverage_threshold)
        if not isinstance(self.detector_version, str) or not self.detector_version.strip():
            raise ValueError("detector_version must be a non-empty string")
        if not isinstance(self.score_schema, str) or not self.score_schema.strip():
            raise ValueError("score_schema must be a non-empty string")


@dataclass(frozen=True)
class ResidualEvidence:
    """Raw, auditable source-conditioned observations for one aligned region."""

    height: int
    width: int
    mask_fraction: float
    global_shift: float
    mean_abs_residual: float
    p95_abs_residual: float
    mean_centered_residual: float
    p95_centered_residual: float
    edge_delta: float
    residual_coverage: float
    quality_score: float
    edit_score: float
    detector_version: str = DETECTOR_VERSION
    score_schema: str = SCORE_SCHEMA
    warnings: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.height < 1 or self.width < 1:
            raise ValueError("height and width must be positive")
        for name in (
            "mask_fraction",
            "mean_abs_residual",
            "p95_abs_residual",
            "edge_delta",
            "residual_coverage",
            "quality_score",
            "edit_score",
        ):
            _finite_unit(name, getattr(self, name))
        _finite_signed_unit("global_shift", self.global_shift)
        if not isinstance(self.warnings, tuple) or any(
            not isinstance(item, str) or not item for item in self.warnings
        ):
            raise ValueError("warnings must be a tuple of non-empty strings")

    def to_region_dict(self, region_id: str) -> Dict[str, Any]:
        """Serialize evidence in the shape accepted by ``AIGCResult.regions``."""

        if not isinstance(region_id, str) or not region_id.strip():
            raise ValueError("region_id must be a non-empty string")
        return {
            "region_id": region_id,
            "score_raw": self.edit_score,
            "edit_score_raw": self.edit_score,
            "global_shift_raw": self.global_shift,
            "mean_abs_residual_raw": self.mean_abs_residual,
            "p95_abs_residual_raw": self.p95_abs_residual,
            "mean_centered_residual_raw": self.mean_centered_residual,
            "p95_centered_residual_raw": self.p95_centered_residual,
            "edge_delta_raw": self.edge_delta,
            "residual_coverage_raw": self.residual_coverage,
            "quality_raw": self.quality_score,
            "mask_fraction": self.mask_fraction,
            "height": self.height,
            "width": self.width,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "warnings": list(self.warnings),
        }


ROI_DETECTOR_VERSION = "source-residual-roi-v1"
ROI_SCORE_SCHEMA = "source-residual-roi-score-v1"


@dataclass(frozen=True)
class ResidualROI:
    """A raw, source-conditioned candidate region for human review.

    The mask is computed after the same robust global-shift removal as
    :func:`compare_aligned_regions`.  It is a localization observation, not
    an AIGC decision; its threshold must be learned on held-out data.
    ``bbox`` uses image coordinates and a half-open ``(x0, y0, x1, y1)``
    convention.  A null box means that no pixel passed the raw threshold.
    """

    height: int
    width: int
    threshold: float
    global_shift: float
    selected_fraction: float
    quality_score: float
    bbox: Optional[Tuple[int, int, int, int]]
    mask: Tuple[Tuple[bool, ...], ...]
    detector_version: str = ROI_DETECTOR_VERSION
    score_schema: str = ROI_SCORE_SCHEMA
    warnings: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.height < 1 or self.width < 1:
            raise ValueError("height and width must be positive")
        _finite_unit("threshold", self.threshold)
        _finite_signed_unit("global_shift", self.global_shift)
        _finite_unit("selected_fraction", self.selected_fraction)
        _finite_unit("quality_score", self.quality_score)
        if len(self.mask) != self.height or any(len(row) != self.width for row in self.mask):
            raise ValueError("mask must match height and width")
        if any(not isinstance(value, bool) for row in self.mask for value in row):
            raise ValueError("mask values must be bool")
        if self.bbox is not None:
            if len(self.bbox) != 4:
                raise ValueError("bbox must contain four coordinates")
            x0, y0, x1, y1 = self.bbox
            if not (0 <= x0 < x1 <= self.width and 0 <= y0 < y1 <= self.height):
                raise ValueError("bbox coordinates are out of bounds")
        if not isinstance(self.warnings, tuple) or any(
            not isinstance(item, str) or not item for item in self.warnings
        ):
            raise ValueError("warnings must be a tuple of non-empty strings")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "height": self.height,
            "width": self.width,
            "threshold_raw": self.threshold,
            "global_shift_raw": self.global_shift,
            "selected_fraction_raw": self.selected_fraction,
            "quality_raw": self.quality_score,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "mask": [list(row) for row in self.mask],
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "warnings": list(self.warnings),
        }


def extract_residual_roi(
    reference: Sequence[Sequence[float]],
    query: Sequence[Sequence[float]],
    *,
    mask: Optional[Sequence[Sequence[float]]] = None,
    threshold: float = 0.12,
    config: Optional[ResidualConfig] = None,
) -> ResidualROI:
    """Return a thresholded residual ROI after removing global shift.

    This intentionally exposes the pixel mask and nuisance shift so a later
    calibrated model can audit why a region was selected.  It does not apply
    connected-component heuristics, infer an edit type, or map the result to
    one of the four AIGC states.
    """

    threshold = _finite_unit("threshold", threshold)
    reference_grid = _grid("reference", reference)
    query_grid = _grid("query", query)
    if len(reference_grid) != len(query_grid) or len(reference_grid[0]) != len(query_grid[0]):
        raise ValueError("reference and query must have the same shape")
    height = len(reference_grid)
    width = len(reference_grid[0])
    selected = _mask(mask, height, width)
    active = [
        query_grid[row][column] - reference_grid[row][column]
        for row in range(height)
        for column in range(width)
        if selected[row][column]
    ]
    if not active:
        raise ValueError("mask must select at least one pixel")
    global_shift = _quantile(active, 0.50)
    candidate = tuple(
        tuple(
            bool(
                selected[row][column]
                and abs(
                    (query_grid[row][column] - reference_grid[row][column])
                    - global_shift
                )
                >= threshold
            )
            for column in range(width)
        )
        for row in range(height)
    )
    coordinates = [
        (column, row)
        for row in range(height)
        for column in range(width)
        if candidate[row][column]
    ]
    bbox = None
    warnings = []
    if coordinates:
        xs = [item[0] for item in coordinates]
        ys = [item[1] for item in coordinates]
        bbox = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
    else:
        warnings.append("no_residual_above_threshold")
    evidence = compare_aligned_regions(reference_grid, query_grid, mask=mask, config=config)
    selected_fraction = len(coordinates) / len(active)
    if selected_fraction > 0.5:
        warnings.append("broad_residual")
    return ResidualROI(
        height=height,
        width=width,
        threshold=threshold,
        global_shift=global_shift,
        selected_fraction=selected_fraction,
        quality_score=evidence.quality_score,
        bbox=bbox,
        mask=candidate,
        warnings=tuple(warnings),
    )


def compare_aligned_regions(
    reference: Sequence[Sequence[float]],
    query: Sequence[Sequence[float]],
    *,
    mask: Optional[Sequence[Sequence[float]]] = None,
    config: Optional[ResidualConfig] = None,
) -> ResidualEvidence:
    """Compute deterministic residual evidence for two aligned gray regions.

    ``reference`` should be the registered source region and ``query`` the
    candidate region after geometric alignment.  The operation compares
    absolute residuals and first-order edge residuals.  It is sensitive to
    ordinary edits as well as AI edits, which is why its output remains raw
    evidence and must be paired with source matching, model calibration and
    human review.
    """

    reference_grid = _grid("reference", reference)
    query_grid = _grid("query", query)
    if len(reference_grid) != len(query_grid) or len(reference_grid[0]) != len(query_grid[0]):
        raise ValueError("reference and query must have the same shape")
    height = len(reference_grid)
    width = len(reference_grid[0])
    selected = _mask(mask, height, width)
    active = [
        (reference_grid[row][column], query_grid[row][column])
        for row in range(height)
        for column in range(width)
        if selected[row][column]
    ]
    if not active:
        raise ValueError("mask must select at least one pixel")
    cfg = config or ResidualConfig()

    signed_residuals = [query_value - reference_value for reference_value, query_value in active]
    residuals = [abs(value) for value in signed_residuals]
    mean_abs = sum(residuals) / len(residuals)
    p95_abs = _quantile(residuals, 0.95)
    # Robustly remove a global brightness/colour shift before scoring local
    # editing.  The median is insensitive to a minority edited region and is
    # retained as an auditable nuisance estimate rather than hidden in a
    # learned model.
    global_shift = _quantile(signed_residuals, 0.50)
    centered_residuals = [abs(value - global_shift) for value in signed_residuals]
    mean_centered = sum(centered_residuals) / len(centered_residuals)
    p95_centered = _quantile(centered_residuals, 0.95)
    coverage = sum(value >= cfg.coverage_threshold for value in centered_residuals) / len(centered_residuals)

    # Compare first derivatives rather than raw pixels so a global brightness
    # shift does not dominate the local-edit signal.  Each derivative
    # difference is in [0, 2], hence division by 2 bounds the statistic.
    edge_residuals = []
    for row in range(height):
        for column in range(width):
            if not selected[row][column]:
                continue
            if column + 1 < width and selected[row][column + 1]:
                reference_delta = reference_grid[row][column + 1] - reference_grid[row][column]
                query_delta = query_grid[row][column + 1] - query_grid[row][column]
                edge_residuals.append(abs(query_delta - reference_delta) / 2.0)
            if row + 1 < height and selected[row + 1][column]:
                reference_delta = reference_grid[row + 1][column] - reference_grid[row][column]
                query_delta = query_grid[row + 1][column] - query_grid[row][column]
                edge_residuals.append(abs(query_delta - reference_delta) / 2.0)
    warnings = []
    if not edge_residuals:
        edge_delta = 0.0
        warnings.append("insufficient_edge_pairs")
    else:
        edge_delta = sum(edge_residuals) / len(edge_residuals)

    # Quality reflects measurement support, not whether the image is human or
    # AI.  Small/flat regions get a lower quality gate and must not be allowed
    # to produce a confident downstream decision.
    mask_fraction = len(active) / (height * width)
    mean_intensity = sum((reference_value + query_value) / 2.0 for reference_value, query_value in active) / len(active)
    variance = sum(
        (((reference_value + query_value) / 2.0) - mean_intensity) ** 2
        for reference_value, query_value in active
    ) / len(active)
    shape_factor = min(1.0, min(height, width) / 8.0)
    contrast_factor = min(1.0, math.sqrt(variance / 0.02)) if variance > 0.0 else 0.0
    quality = mask_fraction * shape_factor * contrast_factor
    if mask_fraction < 0.05:
        warnings.append("sparse_mask")
    if variance == 0.0:
        warnings.append("flat_region")

    normalized_mean = min(1.0, mean_centered / cfg.mean_scale)
    normalized_p95 = min(1.0, p95_centered / cfg.p95_scale)
    normalized_edge = min(1.0, edge_delta / cfg.edge_scale)
    # A p95 term captures concentrated edits, while the coverage term avoids
    # treating one isolated numerical outlier as a broad edit.  The score is
    # a bounded raw feature, not a calibrated probability.
    edit_score = (
        0.40 * normalized_mean
        + 0.35 * normalized_p95
        + 0.20 * normalized_edge
        + 0.05 * coverage
    )

    return ResidualEvidence(
        height=height,
        width=width,
        mask_fraction=mask_fraction,
        global_shift=global_shift,
        mean_abs_residual=mean_abs,
        p95_abs_residual=p95_abs,
        mean_centered_residual=mean_centered,
        p95_centered_residual=p95_centered,
        edge_delta=edge_delta,
        residual_coverage=coverage,
        quality_score=quality,
        edit_score=edit_score,
        detector_version=cfg.detector_version,
        score_schema=cfg.score_schema,
        warnings=tuple(warnings),
    )
