"""Deterministic, bounded image decoding for forensic experiments.

The adapter is deliberately separate from the competition-era ``ai_server``.
It turns one byte string into a normalized RGB/gray array only after bounded
decoding, format and geometry checks, and it records enough information to
reproduce the decision.  A quality score is a *support/triage signal*; it is
never an AIGC probability and never maps a failure to ``human``.

The first supported formats are JPEG/JFIF, PNG, WebP, non-animated TIFF and
BMP.  Multi-page/animated inputs, unsupported codecs, malformed bytes and
pixel bombs are rejected with a stable reason code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

try:  # Keep the rest of the lightweight contract importable without wheels.
    import numpy as np
    from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError
    from PIL import __version__ as PILLOW_VERSION
except ModuleNotFoundError:  # pragma: no cover - exercised by dependency checks
    np = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    ImageFile = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]
    UnidentifiedImageError = Exception  # type: ignore[assignment,misc]
    PILLOW_VERSION = "unavailable"


ADAPTER_VERSION = "image-adapter-v1"
SUPPORTED_FORMATS = ("JPEG", "PNG", "WEBP", "TIFF", "BMP")
REASON_CODES = (
    "bytes_too_large",
    "unsupported_format",
    "decode_failed",
    "truncated_or_corrupt",
    "animated_or_multipage",
    "pixel_limit_exceeded",
    "aspect_ratio_exceeded",
    "min_side_too_small",
    "alpha_policy_rejected",
    "nonfinite_pixels",
    "flat_region",
    "clipping_excessive",
    "quality_below_threshold",
)


def _finite_unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return _digest(payload.encode("utf-8"))


@dataclass(frozen=True)
class AdapterConfig:
    max_bytes: int = 20 * 1024 * 1024
    max_pixels: int = 25_000_000
    min_side: int = 16
    max_aspect_ratio: float = 20.0
    min_quality: float = 0.15
    min_contrast: float = 0.015
    max_clipping_fraction: float = 0.98
    alpha_policy: str = "reject"
    background_rgb: Tuple[int, int, int] = (255, 255, 255)
    allowed_formats: Tuple[str, ...] = SUPPORTED_FORMATS

    def __post_init__(self) -> None:
        integer_fields = ("max_bytes", "max_pixels", "min_side")
        for name in integer_fields:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if (
            isinstance(self.max_aspect_ratio, bool)
            or not isinstance(self.max_aspect_ratio, (int, float))
            or not math.isfinite(float(self.max_aspect_ratio))
            or float(self.max_aspect_ratio) < 1.0
        ):
            raise ValueError("max_aspect_ratio must be a finite number >= 1")
        _finite_unit("min_quality", self.min_quality)
        if (
            isinstance(self.min_contrast, bool)
            or not isinstance(self.min_contrast, (int, float))
            or not math.isfinite(float(self.min_contrast))
            or float(self.min_contrast) < 0.0
        ):
            raise ValueError("min_contrast must be a finite non-negative number")
        _finite_unit("max_clipping_fraction", self.max_clipping_fraction)
        if self.alpha_policy not in {"reject", "composite"}:
            raise ValueError("alpha_policy must be reject or composite")
        if (
            not isinstance(self.background_rgb, tuple)
            or len(self.background_rgb) != 3
            or any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255 for v in self.background_rgb)
        ):
            raise ValueError("background_rgb must contain three integers in [0, 255]")
        formats = tuple(str(item).upper() for item in self.allowed_formats)
        if not formats or any(item not in SUPPORTED_FORMATS for item in formats):
            raise ValueError("allowed_formats contains an unsupported format")
        object.__setattr__(self, "allowed_formats", formats)

    def to_dict(self) -> dict:
        return {
            "version": ADAPTER_VERSION,
            "max_bytes": self.max_bytes,
            "max_pixels": self.max_pixels,
            "min_side": self.min_side,
            "max_aspect_ratio": float(self.max_aspect_ratio),
            "min_quality": float(self.min_quality),
            "min_contrast": float(self.min_contrast),
            "max_clipping_fraction": float(self.max_clipping_fraction),
            "alpha_policy": self.alpha_policy,
            "background_rgb": list(self.background_rgb),
            "allowed_formats": list(self.allowed_formats),
        }

    @property
    def digest(self) -> str:
        return _json_digest(self.to_dict())


@dataclass(frozen=True)
class DecodeAudit:
    raw_sha256: str
    raw_bytes: int
    detected_format: Optional[str]
    decoder: str
    original_size: Optional[Tuple[int, int]]
    original_mode: Optional[str]
    exif_orientation: Optional[int]
    normalized_size: Optional[Tuple[int, int]]
    normalized_mode: Optional[str]
    normalized_sha256: Optional[str]
    warnings: Tuple[str, ...] = ()
    config_digest: str = ""
    adapter_version: str = ADAPTER_VERSION

    def to_dict(self) -> dict:
        return {
            "adapter_version": self.adapter_version,
            "raw_sha256": self.raw_sha256,
            "raw_bytes": self.raw_bytes,
            "detected_format": self.detected_format,
            "decoder": self.decoder,
            "original_size": list(self.original_size) if self.original_size else None,
            "original_mode": self.original_mode,
            "exif_orientation": self.exif_orientation,
            "normalized_size": list(self.normalized_size) if self.normalized_size else None,
            "normalized_mode": self.normalized_mode,
            "normalized_sha256": self.normalized_sha256,
            "warnings": list(self.warnings),
            "config_digest": self.config_digest,
        }

    @property
    def digest(self) -> str:
        return _json_digest(self.to_dict())


@dataclass(frozen=True)
class QualityReport:
    geometry_score: float
    contrast_score: float
    clipping_score: float
    alpha_score: float
    quality_score: float
    contrast_std: float
    clipping_fraction: float
    flags: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("geometry_score", "contrast_score", "clipping_score", "alpha_score", "quality_score"):
            _finite_unit(name, getattr(self, name))
        for name in ("contrast_std", "clipping_fraction"):
            if not isinstance(getattr(self, name), (int, float)) or not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")

    def to_dict(self) -> dict:
        return {
            "geometry_score": float(self.geometry_score),
            "contrast_score": float(self.contrast_score),
            "clipping_score": float(self.clipping_score),
            "alpha_score": float(self.alpha_score),
            "quality_score": float(self.quality_score),
            "contrast_std": float(self.contrast_std),
            "clipping_fraction": float(self.clipping_fraction),
            "flags": list(self.flags),
        }


@dataclass(frozen=True)
class ImageAdapterResult:
    accepted: bool
    reason: Optional[str]
    audit: DecodeAudit
    quality: Optional[QualityReport] = None
    gray: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.accepted and self.reason is not None:
            raise ValueError("accepted result cannot have a rejection reason")
        if not self.accepted and self.reason not in REASON_CODES:
            raise ValueError("rejected result must use a stable adapter reason code")
        if self.accepted and self.gray is None:
            raise ValueError("accepted result must contain normalized gray pixels")

    def to_dict(self) -> dict:
        return {
            "adapter_version": ADAPTER_VERSION,
            "accepted": self.accepted,
            "reason": self.reason,
            "audit": self.audit.to_dict(),
            "audit_digest": self.audit.digest,
            "quality": self.quality.to_dict() if self.quality else None,
        }


def _require_dependencies() -> None:
    if np is None or Image is None or ImageOps is None:
        raise RuntimeError(
            "image adapter requires Pillow and NumPy; install requirements-research.txt"
        )


def _decoder_name() -> str:
    numpy_version = getattr(np, "__version__", "unavailable")
    return f"Pillow/{PILLOW_VERSION};NumPy/{numpy_version}"


def _audit(
    *,
    raw: bytes,
    config: AdapterConfig,
    detected_format: Optional[str] = None,
    original_size: Optional[Tuple[int, int]] = None,
    original_mode: Optional[str] = None,
    exif_orientation: Optional[int] = None,
    normalized_size: Optional[Tuple[int, int]] = None,
    normalized_mode: Optional[str] = None,
    normalized_sha256: Optional[str] = None,
    warnings: Sequence[str] = (),
) -> DecodeAudit:
    return DecodeAudit(
        raw_sha256=_digest(raw),
        raw_bytes=len(raw),
        detected_format=detected_format,
        decoder=_decoder_name(),
        original_size=original_size,
        original_mode=original_mode,
        exif_orientation=exif_orientation,
        normalized_size=normalized_size,
        normalized_mode=normalized_mode,
        normalized_sha256=normalized_sha256,
        warnings=tuple(warnings),
        config_digest=config.digest,
    )


def _reject(raw: bytes, config: AdapterConfig, reason: str, **kwargs: Any) -> ImageAdapterResult:
    if reason not in REASON_CODES:
        raise ValueError(f"unsupported adapter reason: {reason}")
    return ImageAdapterResult(False, reason, _audit(raw=raw, config=config, **kwargs))


def _quality_report(
    gray: Any,
    *,
    width: int,
    height: int,
    alpha_score: float,
    config: AdapterConfig,
) -> QualityReport:
    contrast_std = float(np.std(gray))
    contrast_score = min(1.0, contrast_std / 0.25)
    clipping_fraction = float(np.mean((gray <= 1.0 / 255.0) | (gray >= 254.0 / 255.0)))
    clipping_score = max(0.0, 1.0 - clipping_fraction / max(config.max_clipping_fraction, 1e-9))
    geometry_score = min(1.0, min(width, height) / 128.0)
    flags = []
    if contrast_std < config.min_contrast:
        flags.append("flat_region")
    if clipping_fraction > config.max_clipping_fraction:
        flags.append("clipping_excessive")
    quality_score = min(geometry_score, contrast_score, clipping_score, alpha_score)
    return QualityReport(
        geometry_score=geometry_score,
        contrast_score=contrast_score,
        clipping_score=clipping_score,
        alpha_score=alpha_score,
        quality_score=quality_score,
        contrast_std=contrast_std,
        clipping_fraction=clipping_fraction,
        flags=tuple(flags),
    )


def decode_image_bytes(data: bytes, config: AdapterConfig = AdapterConfig()) -> ImageAdapterResult:
    """Decode one bounded image byte string into normalized gray pixels.

    The function always returns a typed rejection for content problems.  It
    raises only for invalid caller/config types or missing research wheels.
    """

    _require_dependencies()
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes-like")
    raw = bytes(data)
    if len(raw) > config.max_bytes:
        return _reject(raw, config, "bytes_too_large")

    try:
        # Pillow's verify() must be called immediately after open.  Metadata
        # is read from a fresh handle below so the verifier and decoder never
        # share a partially consumed parser.
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(raw)) as metadata:
            detected_format = (metadata.format or "").upper() or None
            original_size = tuple(int(v) for v in metadata.size)
            original_mode = str(metadata.mode)
            exif = metadata.getexif()
            orientation = int(exif.get(274, 1)) if exif else 1
            frame_count = int(getattr(metadata, "n_frames", 1))
    except UnidentifiedImageError:
        return _reject(raw, config, "decode_failed")
    except (OSError, ValueError, SyntaxError, RuntimeError):
        return _reject(raw, config, "truncated_or_corrupt")

    if detected_format not in config.allowed_formats:
        return _reject(
            raw,
            config,
            "unsupported_format",
            detected_format=detected_format,
            original_size=original_size,
            original_mode=original_mode,
            exif_orientation=orientation,
        )
    if frame_count > 1:
        return _reject(
            raw,
            config,
            "animated_or_multipage",
            detected_format=detected_format,
            original_size=original_size,
            original_mode=original_mode,
            exif_orientation=orientation,
        )
    width, height = original_size
    if width * height > config.max_pixels:
        return _reject(
            raw,
            config,
            "pixel_limit_exceeded",
            detected_format=detected_format,
            original_size=original_size,
            original_mode=original_mode,
            exif_orientation=orientation,
        )
    if min(width, height) < config.min_side:
        return _reject(
            raw,
            config,
            "min_side_too_small",
            detected_format=detected_format,
            original_size=original_size,
            original_mode=original_mode,
            exif_orientation=orientation,
        )
    aspect_ratio = max(width, height) / max(1, min(width, height))
    if aspect_ratio > float(config.max_aspect_ratio):
        return _reject(
            raw,
            config,
            "aspect_ratio_exceeded",
            detected_format=detected_format,
            original_size=original_size,
            original_mode=original_mode,
            exif_orientation=orientation,
        )

    warnings = []
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            alpha_score = 1.0
            if has_alpha and config.alpha_policy == "reject":
                return _reject(
                    raw,
                    config,
                    "alpha_policy_rejected",
                    detected_format=detected_format,
                    original_size=original_size,
                    original_mode=original_mode,
                    exif_orientation=orientation,
                )
            if ImageOps is not None:
                image = ImageOps.exif_transpose(image)
            if has_alpha:
                rgba = image.convert("RGBA")
                alpha = np.asarray(rgba.getchannel("A"), dtype=np.float32) / 255.0
                opaque_fraction = float(np.mean(alpha >= 0.999))
                # Explicit compositing makes the RGB pixels usable.  Keep a
                # conservative penalty for transparency without making every
                # semi-transparent asset fail solely because of its alpha.
                alpha_score = max(0.5, min(1.0, 0.5 + 0.5 * opaque_fraction))
                bg = Image.new("RGBA", rgba.size, config.background_rgb + (255,))
                image = Image.alpha_composite(bg, rgba).convert("RGB")
                warnings.append("alpha_composited")
            else:
                image = image.convert("RGB")
            image.load()
            arr = np.asarray(image, dtype=np.uint8)
    except (OSError, ValueError, SyntaxError):
        return _reject(
            raw,
            config,
            "truncated_or_corrupt",
            detected_format=detected_format,
            original_size=original_size,
            original_mode=original_mode,
            exif_orientation=orientation,
        )

    if arr.ndim != 3 or arr.shape[2] != 3:
        return _reject(
            raw,
            config,
            "decode_failed",
            detected_format=detected_format,
            original_size=original_size,
            original_mode=original_mode,
            exif_orientation=orientation,
        )
    normalized_rgb = arr.astype(np.float32) / 255.0
    if not bool(np.isfinite(normalized_rgb).all()):
        return _reject(
            raw,
            config,
            "nonfinite_pixels",
            detected_format=detected_format,
            original_size=original_size,
            original_mode=original_mode,
            exif_orientation=orientation,
        )
    gray = (
        normalized_rgb[:, :, 0] * 0.299
        + normalized_rgb[:, :, 1] * 0.587
        + normalized_rgb[:, :, 2] * 0.114
    ).astype(np.float32)
    quality = _quality_report(
        gray,
        width=int(arr.shape[1]),
        height=int(arr.shape[0]),
        alpha_score=alpha_score,
        config=config,
    )
    if "flat_region" in quality.flags:
        reason = "flat_region"
    elif "clipping_excessive" in quality.flags:
        reason = "clipping_excessive"
    elif quality.quality_score < config.min_quality:
        reason = "quality_below_threshold"
    else:
        reason = None
    normalized_bytes = np.ascontiguousarray(arr).tobytes()
    audit = _audit(
        raw=raw,
        config=config,
        detected_format=detected_format,
        original_size=original_size,
        original_mode=original_mode,
        exif_orientation=orientation,
        normalized_size=(int(arr.shape[1]), int(arr.shape[0])),
        normalized_mode="RGB",
        normalized_sha256=_digest(normalized_bytes),
        warnings=warnings,
    )
    if reason is not None:
        return ImageAdapterResult(False, reason, audit, quality=quality)
    return ImageAdapterResult(True, None, audit, quality=quality, gray=gray)


def decode_image_file(path: str | Path, config: AdapterConfig = AdapterConfig()) -> ImageAdapterResult:
    """Read a file once with the byte limit, then delegate to byte decoding."""

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    with path.open("rb") as handle:
        raw = handle.read(config.max_bytes + 1)
    return decode_image_bytes(raw, config)
