"""Source-conditioned phase/spectral raw evidence.

This module is a lightweight research adapter for the PC-SCFT pipeline.  It
compares a registered reference grid with an observed query in a fixed
coordinate frame.  When an ordinary-propagation counterfactual is available,
the query score is corrected by the counterfactual score under the same
spectral nuisance representation.  The result is bounded raw evidence only:
it is not a probability, AIGC label, provenance claim or legal finding.

The implementation uses NumPy, already locked for the real-image adapter.
The per-grid normalization removes a robust global affine nuisance before the
FFT; phase is measured through weighted circular incoherence so near-zero FFT
bins do not create arbitrary phase spikes.  Every accepted score preserves
both uncorrected observations, the paired delta, quality support, digests and
the versioned configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

try:
    import numpy as np
except ModuleNotFoundError:  # pragma: no cover - dependency gate
    np = None  # type: ignore[assignment]


VERSION = "source-spectral-evidence-v1"
DETECTOR_VERSION = "source-spectral-phase-v1"
SCORE_SCHEMA = "source-spectral-score-v1"
PREPROCESS_VERSION = "centered-rms-hann-fft-v1"


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _bytes_digest(array: Any) -> str:
    _require_numpy()
    contiguous = np.ascontiguousarray(array, dtype=np.dtype("<f4"))
    return hashlib.sha256(contiguous.tobytes(order="C")).hexdigest()


def _require_numpy() -> None:
    if np is None:
        raise RuntimeError("spectral evidence requires NumPy; install requirements-research.txt")


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


def _positive(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive finite number")
    value = float(value)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be a positive finite number")
    return value


def _grid(name: str, value: Any) -> Any:
    _require_numpy()
    try:
        array = np.asarray(value, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a numeric 2-D grid") from exc
    if array.ndim != 2 or array.shape[0] < 2 or array.shape[1] < 2:
        raise ValueError(f"{name} must be a 2-D grid with both sides >= 2")
    if not bool(np.isfinite(array).all()):
        raise ValueError(f"{name} contains nonfinite values")
    if float(array.min()) < 0.0 or float(array.max()) > 1.0:
        raise ValueError(f"{name} values must be between 0 and 1")
    return np.ascontiguousarray(array, dtype=np.float32)


@dataclass(frozen=True)
class SpectralEvidenceConfig:
    """Versioned scales and nuisance gates for the raw spectral feature."""

    minimum_side: int = 8
    minimum_quality: float = 0.15
    minimum_contrast: float = 0.01
    high_frequency_cutoff: float = 0.50
    amplitude_scale: float = 0.35
    high_amplitude_scale: float = 0.20
    epsilon: float = 1e-6
    detector_version: str = DETECTOR_VERSION
    score_schema: str = SCORE_SCHEMA
    preprocess_version: str = PREPROCESS_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.minimum_side, bool) or not isinstance(self.minimum_side, int) or self.minimum_side < 2:
            raise ValueError("minimum_side must be an integer >= 2")
        for name in ("minimum_quality", "minimum_contrast", "high_frequency_cutoff"):
            _unit(name, getattr(self, name))
        _positive("amplitude_scale", self.amplitude_scale)
        _positive("high_amplitude_scale", self.high_amplitude_scale)
        _positive("epsilon", self.epsilon)
        _text("detector_version", self.detector_version)
        _text("score_schema", self.score_schema)
        _text("preprocess_version", self.preprocess_version)
        if self.high_frequency_cutoff <= 0.0 or self.high_frequency_cutoff > 1.0:
            raise ValueError("high_frequency_cutoff must be in (0, 1]")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "minimum_side": self.minimum_side,
            "minimum_quality": self.minimum_quality,
            "minimum_contrast": self.minimum_contrast,
            "high_frequency_cutoff": self.high_frequency_cutoff,
            "amplitude_scale": self.amplitude_scale,
            "high_amplitude_scale": self.high_amplitude_scale,
            "epsilon": self.epsilon,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "preprocess_version": self.preprocess_version,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class SpectralRegion:
    """A fixed coordinate-frame window used by the spectral adapter."""

    region_id: str
    bbox_xyxy: Tuple[int, int, int, int]

    def __post_init__(self) -> None:
        _text("region_id", self.region_id)
        if len(self.bbox_xyxy) != 4 or any(
            isinstance(item, bool) or not isinstance(item, int) for item in self.bbox_xyxy
        ):
            raise ValueError("bbox_xyxy must contain four integer coordinates")
        x0, y0, x1, y1 = self.bbox_xyxy
        if not (0 <= x0 < x1 and 0 <= y0 < y1):
            raise ValueError("bbox_xyxy must be a non-empty half-open rectangle")

    def to_dict(self) -> Dict[str, Any]:
        return {"region_id": self.region_id, "bbox_xyxy": list(self.bbox_xyxy)}


@dataclass(frozen=True)
class SpectralScore:
    """One region's raw spectral and phase observations."""

    region_id: str
    bbox_xyxy: Tuple[int, int, int, int]
    shape: Tuple[int, int]
    score_raw: float
    query_score_raw: float
    counterfactual_score_raw: Optional[float]
    paired_delta_raw: Optional[float]
    phase_incoherence_raw: float
    amplitude_delta_raw: float
    high_frequency_delta_raw: float
    quality_score: float
    reference_sha256: str
    query_sha256: str
    counterfactual_sha256: Optional[str]
    detector_version: str = DETECTOR_VERSION
    score_schema: str = SCORE_SCHEMA
    config_digest: str = ""
    preprocess_version: str = PREPROCESS_VERSION
    warnings: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text("region_id", self.region_id)
        if len(self.bbox_xyxy) != 4:
            raise ValueError("bbox_xyxy must contain four coordinates")
        x0, y0, x1, y1 = self.bbox_xyxy
        if not (0 <= x0 < x1 and 0 <= y0 < y1):
            raise ValueError("bbox_xyxy must be a non-empty half-open rectangle")
        if len(self.shape) != 2 or any(isinstance(item, bool) or not isinstance(item, int) or item < 2 for item in self.shape):
            raise ValueError("shape must contain two integers >= 2")
        for name, value in (
            ("score_raw", self.score_raw),
            ("query_score_raw", self.query_score_raw),
            ("phase_incoherence_raw", self.phase_incoherence_raw),
            ("amplitude_delta_raw", self.amplitude_delta_raw),
            ("high_frequency_delta_raw", self.high_frequency_delta_raw),
            ("quality_score", self.quality_score),
        ):
            _unit(name, value)
        for name, value in (("counterfactual_score_raw", self.counterfactual_score_raw), ("paired_delta_raw", self.paired_delta_raw)):
            if value is not None:
                _unit(name, value)
        for name, value in (
            ("reference_sha256", self.reference_sha256),
            ("query_sha256", self.query_sha256),
            ("config_digest", self.config_digest),
        ):
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
                raise ValueError(f"{name} must be a SHA-256 hex digest")
        if self.counterfactual_sha256 is not None and (
            not isinstance(self.counterfactual_sha256, str)
            or len(self.counterfactual_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in self.counterfactual_sha256.lower())
        ):
            raise ValueError("counterfactual_sha256 must be a SHA-256 hex digest")
        _text("detector_version", self.detector_version)
        _text("score_schema", self.score_schema)
        _text("preprocess_version", self.preprocess_version)
        if not isinstance(self.warnings, tuple) or any(not isinstance(item, str) or not item for item in self.warnings):
            raise ValueError("warnings must be a tuple of non-empty strings")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "region_id": self.region_id,
            "bbox_xyxy": list(self.bbox_xyxy),
            "shape": list(self.shape),
            "score_raw": self.score_raw,
            "query_score_raw": self.query_score_raw,
            "counterfactual_score_raw": self.counterfactual_score_raw,
            "paired_delta_raw": self.paired_delta_raw,
            "phase_incoherence_raw": self.phase_incoherence_raw,
            "amplitude_delta_raw": self.amplitude_delta_raw,
            "high_frequency_delta_raw": self.high_frequency_delta_raw,
            "quality_score": self.quality_score,
            "reference_sha256": self.reference_sha256,
            "query_sha256": self.query_sha256,
            "counterfactual_sha256": self.counterfactual_sha256,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "config_digest": self.config_digest,
            "preprocess_version": self.preprocess_version,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class SpectralEvidenceResult:
    """Typed batch result for spectral raw evidence."""

    accepted: bool
    reason: Optional[str]
    paired: bool
    reference_sha256: Optional[str]
    query_sha256: Optional[str]
    counterfactual_sha256: Optional[str]
    scores: Tuple[SpectralScore, ...]
    config_digest: str
    detector_version: str = DETECTOR_VERSION
    score_schema: str = SCORE_SCHEMA
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.accepted and (self.reason is not None or not self.scores):
            raise ValueError("accepted result requires scores and no reason")
        if not self.accepted and (not isinstance(self.reason, str) or not self.reason):
            raise ValueError("rejected result requires a stable reason")
        if not isinstance(self.paired, bool):
            raise ValueError("paired must be bool")
        if (
            not isinstance(self.config_digest, str)
            or len(self.config_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.config_digest.lower())
        ):
            raise ValueError("config_digest must be a SHA-256 hex digest")
        if len({score.region_id for score in self.scores}) != len(self.scores):
            raise ValueError("score region IDs must be unique")

    @property
    def evidence_digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> Dict[str, Any]:
        result = {
            "version": self.version,
            "accepted": self.accepted,
            "reason": self.reason,
            "paired": self.paired,
            "reference_sha256": self.reference_sha256,
            "query_sha256": self.query_sha256,
            "counterfactual_sha256": self.counterfactual_sha256,
            "scores": [score.to_dict() for score in self.scores],
            "config_digest": self.config_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
        }
        if include_digest:
            result["evidence_digest"] = self.evidence_digest
        return result


def _normalise_grid(array: Any, *, config: SpectralEvidenceConfig) -> Tuple[Any, float, Tuple[str, ...]]:
    grid = _grid("grid", array)
    height, width = (int(item) for item in grid.shape)
    if min(height, width) < config.minimum_side:
        raise ValueError("grid_side_too_small")
    contrast = float(np.std(grid))
    quality = min(1.0, min(height, width) / 64.0)
    quality = min(quality, min(1.0, contrast / max(config.minimum_contrast, config.epsilon)))
    warnings = []
    if contrast < config.minimum_contrast:
        warnings.append("flat_region")
    centered = grid - np.median(grid)
    scale = float(np.sqrt(np.mean(centered * centered)))
    if not math.isfinite(scale) or scale <= config.epsilon:
        raise ValueError("flat_region")
    normalized = centered / scale
    return np.ascontiguousarray(normalized, dtype=np.float32), quality, tuple(warnings)


def _spectral_components(reference: Any, query: Any, *, config: SpectralEvidenceConfig) -> Tuple[float, float, float]:
    height, width = reference.shape
    window = np.outer(np.hanning(height), np.hanning(width)).astype(np.float32)
    reference_fft = np.fft.fftshift(np.fft.fft2(reference * window))
    query_fft = np.fft.fftshift(np.fft.fft2(query * window))
    reference_magnitude = np.abs(reference_fft).astype(np.float64)
    query_magnitude = np.abs(query_fft).astype(np.float64)
    phase_difference = np.angle(np.exp(1j * (np.angle(query_fft) - np.angle(reference_fft))))
    # Circular incoherence is bounded and does not suffer from a phase wrap at
    # -pi/pi.  Magnitude weighting suppresses arbitrary phase at near-zero FFT
    # bins, which otherwise turns an affine brightness change into evidence.
    spectral_weight = reference_magnitude + query_magnitude + config.epsilon
    phase_incoherence = (1.0 - np.cos(phase_difference)) / 2.0
    phase_raw = float(np.average(phase_incoherence, weights=spectral_weight))
    amplitude_difference = np.abs(
        np.log1p(query_magnitude) - np.log1p(reference_magnitude)
    )
    amplitude_raw = float(np.mean(amplitude_difference))
    yy, xx = np.indices((height, width), dtype=np.float64)
    radius = np.sqrt((yy - (height - 1.0) / 2.0) ** 2 + (xx - (width - 1.0) / 2.0) ** 2)
    radius /= max(1.0, min(height, width) / 2.0)
    high_frequency = radius >= config.high_frequency_cutoff
    high_raw = float(np.mean(amplitude_difference[high_frequency])) if bool(high_frequency.any()) else amplitude_raw
    return (
        max(0.0, min(1.0, phase_raw)),
        max(0.0, min(1.0, amplitude_raw / config.amplitude_scale)),
        max(0.0, min(1.0, high_raw / config.high_amplitude_scale)),
    )


def _score(components: Tuple[float, float, float]) -> float:
    phase_raw, amplitude_raw, high_raw = components
    return max(0.0, min(1.0, 0.55 * phase_raw + 0.30 * amplitude_raw + 0.15 * high_raw))


def _region_grid(grid: Any, region: SpectralRegion) -> Any:
    height, width = grid.shape
    x0, y0, x1, y1 = region.bbox_xyxy
    if x1 > width or y1 > height:
        raise ValueError("region_bbox_out_of_bounds")
    return np.ascontiguousarray(grid[y0:y1, x0:x1], dtype=np.float32)


def score_spectral_regions(
    reference: Any,
    query: Any,
    counterfactual: Any = None,
    *,
    regions: Optional[Sequence[SpectralRegion]] = None,
    config: Optional[SpectralEvidenceConfig] = None,
) -> SpectralEvidenceResult:
    """Compute source-conditioned spectral raw evidence for one or more regions.

    ``reference``, ``query`` and ``counterfactual`` must be normalized gray
    grids in the same coordinate frame.  ``counterfactual`` is optional; if
    absent the result retains an unpaired query score and warning rather than
    inventing a null correction.
    """

    cfg = config or SpectralEvidenceConfig()
    try:
        reference_grid = _grid("reference", reference)
        query_grid = _grid("query", query)
    except ValueError as exc:
        reason = "nonfinite_input" if "nonfinite" in str(exc) else str(exc)
        return SpectralEvidenceResult(False, reason, False, None, None, None, (), cfg.digest, cfg.detector_version, cfg.score_schema)
    if reference_grid.shape != query_grid.shape:
        return SpectralEvidenceResult(False, "shape_mismatch", False, _bytes_digest(reference_grid), _bytes_digest(query_grid), None, (), cfg.digest, cfg.detector_version, cfg.score_schema)
    cf_grid = None
    if counterfactual is not None:
        try:
            cf_grid = _grid("counterfactual", counterfactual)
        except ValueError as exc:
            reason = "nonfinite_input" if "nonfinite" in str(exc) else str(exc)
            return SpectralEvidenceResult(False, reason, False, _bytes_digest(reference_grid), _bytes_digest(query_grid), None, (), cfg.digest, cfg.detector_version, cfg.score_schema)
        if cf_grid.shape != reference_grid.shape:
            return SpectralEvidenceResult(False, "counterfactual_shape_mismatch", False, _bytes_digest(reference_grid), _bytes_digest(query_grid), _bytes_digest(cf_grid), (), cfg.digest, cfg.detector_version, cfg.score_schema)
    try:
        reference_norm, reference_quality, reference_warnings = _normalise_grid(reference_grid, config=cfg)
        query_norm, query_quality, query_warnings = _normalise_grid(query_grid, config=cfg)
        cf_norm = None
        cf_quality = 1.0
        cf_warnings: Tuple[str, ...] = ()
        if cf_grid is not None:
            cf_norm, cf_quality, cf_warnings = _normalise_grid(cf_grid, config=cfg)
    except ValueError as exc:
        return SpectralEvidenceResult(False, str(exc), cf_grid is not None, _bytes_digest(reference_grid), _bytes_digest(query_grid), _bytes_digest(cf_grid) if cf_grid is not None else None, (), cfg.digest, cfg.detector_version, cfg.score_schema)
    if regions is None:
        regions = (SpectralRegion("full", (0, 0, int(reference_grid.shape[1]), int(reference_grid.shape[0]))),)
    if isinstance(regions, (str, bytes)) or not regions:
        return SpectralEvidenceResult(False, "no_regions", cf_grid is not None, _bytes_digest(reference_grid), _bytes_digest(query_grid), _bytes_digest(cf_grid) if cf_grid is not None else None, (), cfg.digest, cfg.detector_version, cfg.score_schema)
    try:
        region_items = tuple(regions)
        if any(not isinstance(region, SpectralRegion) for region in region_items):
            raise ValueError("invalid_region")
        if len({region.region_id for region in region_items}) != len(region_items):
            raise ValueError("duplicate_region_id")
        scores = []
        for region in region_items:
            ref_region = _region_grid(reference_norm, region)
            query_region = _region_grid(query_norm, region)
            cf_region = _region_grid(cf_norm, region) if cf_norm is not None else None
            if min(ref_region.shape) < cfg.minimum_side or min(query_region.shape) < cfg.minimum_side:
                raise ValueError("region_side_too_small")
            query_components = _spectral_components(ref_region, query_region, config=cfg)
            query_score = _score(query_components)
            cf_score = None
            paired_delta = None
            warnings = tuple(sorted(set(reference_warnings + query_warnings)))
            quality = min(reference_quality, query_quality)
            if cf_region is not None:
                cf_components = _spectral_components(ref_region, cf_region, config=cfg)
                cf_score = _score(cf_components)
                paired_delta = max(0.0, query_score - cf_score)
                score_raw = paired_delta
                warnings = tuple(sorted(set(warnings + cf_warnings)))
                quality = min(quality, cf_quality)
            else:
                score_raw = query_score
                warnings = tuple(sorted(set(warnings + ("counterfactual_missing",))))
            if quality < cfg.minimum_quality:
                raise ValueError("quality_below_threshold")
            scores.append(
                SpectralScore(
                    region_id=region.region_id,
                    bbox_xyxy=region.bbox_xyxy,
                    shape=tuple(int(item) for item in ref_region.shape),
                    score_raw=score_raw,
                    query_score_raw=query_score,
                    counterfactual_score_raw=cf_score,
                    paired_delta_raw=paired_delta,
                    phase_incoherence_raw=query_components[0],
                    amplitude_delta_raw=query_components[1],
                    high_frequency_delta_raw=query_components[2],
                    quality_score=quality,
                    reference_sha256=_bytes_digest(ref_region),
                    query_sha256=_bytes_digest(query_region),
                    counterfactual_sha256=_bytes_digest(cf_region) if cf_region is not None else None,
                    detector_version=cfg.detector_version,
                    score_schema=cfg.score_schema,
                    config_digest=cfg.digest,
                    preprocess_version=cfg.preprocess_version,
                    warnings=warnings,
                )
            )
    except ValueError as exc:
        return SpectralEvidenceResult(False, str(exc), cf_grid is not None, _bytes_digest(reference_grid), _bytes_digest(query_grid), _bytes_digest(cf_grid) if cf_grid is not None else None, (), cfg.digest, cfg.detector_version, cfg.score_schema)
    return SpectralEvidenceResult(
        accepted=True,
        reason=None,
        paired=cf_grid is not None,
        reference_sha256=_bytes_digest(reference_grid),
        query_sha256=_bytes_digest(query_grid),
        counterfactual_sha256=_bytes_digest(cf_grid) if cf_grid is not None else None,
        scores=tuple(scores),
        config_digest=cfg.digest,
        detector_version=cfg.detector_version,
        score_schema=cfg.score_schema,
    )


def compute_spectral_evidence(
    reference: Any,
    query: Any,
    counterfactual: Any = None,
    *,
    config: Optional[SpectralEvidenceConfig] = None,
) -> SpectralEvidenceResult:
    """Convenience wrapper for one full-grid score."""

    return score_spectral_regions(reference, query, counterfactual, config=config)


__all__ = [
    "VERSION",
    "DETECTOR_VERSION",
    "SCORE_SCHEMA",
    "PREPROCESS_VERSION",
    "SpectralEvidenceConfig",
    "SpectralRegion",
    "SpectralScore",
    "SpectralEvidenceResult",
    "score_spectral_regions",
    "compute_spectral_evidence",
]
