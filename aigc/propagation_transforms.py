"""Bounded, deterministic image propagation transforms for paired evidence.

The PC-SCFT protocol needs a real ordinary-propagation null: an observed image
and its no-edit counterfactual must pass through the same transform family and
parameters.  This module creates those byte-level variants with Pillow and
records the complete transform audit.  It deliberately does not create AI
edits, infer provenance, or produce an AIGC score.

Supported families are intentionally small and explicit: ``identity``,
``jpeg_reencode``, ``resize``, ``center_crop``, ``blur``, ``screenshot_sim``
and a bounded ``composite`` chain.  Unknown operations, malformed parameters,
animated/multipage inputs, and resource limits fail closed with stable reason
codes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import io
import json
import math
from typing import Any, Mapping, Optional, Sequence, Tuple

try:  # The research dependency is optional for the rest of the package.
    from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError
    from PIL import __version__ as PILLOW_VERSION
except ModuleNotFoundError:  # pragma: no cover - dependency gate
    Image = None  # type: ignore[assignment]
    ImageFilter = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]
    UnidentifiedImageError = Exception  # type: ignore[assignment,misc]
    PILLOW_VERSION = "unavailable"


TRANSFORM_VERSION = "propagation-transform-v1"
SUPPORTED_INPUT_FORMATS = ("JPEG", "PNG", "WEBP", "TIFF", "BMP")
SUPPORTED_OUTPUT_FORMATS = ("JPEG", "PNG", "WEBP")
SUPPORTED_FAMILIES = (
    "identity",
    "jpeg_reencode",
    "resize",
    "center_crop",
    "blur",
    "screenshot_sim",
    "composite",
)
REASON_CODES = (
    "dependency_unavailable",
    "input_too_large",
    "unsupported_format",
    "decode_failed",
    "animated_or_multipage",
    "pixel_limit_exceeded",
    "invalid_params",
    "unsupported_family",
    "chain_invalid",
    "encode_failed",
    "output_too_large",
)


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_json(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return _digest_bytes(payload.encode("utf-8"))


def _finite_number(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _bounded_int(name: str, value: Any, minimum: int, maximum: int) -> int:
    result = _positive_int(name, value)
    if result < minimum or result > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return result


def _canonical_value(value: Any) -> Any:
    """Validate JSON-like params and return a deterministic copy."""

    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("params must contain finite numbers")
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    raise ValueError(f"unsupported params value type: {type(value).__name__}")


@dataclass(frozen=True)
class PropagationConfig:
    """Resource and encoder bounds shared by both paired observations."""

    max_input_bytes: int = 20 * 1024 * 1024
    max_output_bytes: int = 20 * 1024 * 1024
    max_pixels: int = 25_000_000
    max_dimension: int = 8192
    max_chain_steps: int = 6
    default_output_format: str = "PNG"

    def __post_init__(self) -> None:
        for name in (
            "max_input_bytes",
            "max_output_bytes",
            "max_pixels",
            "max_dimension",
            "max_chain_steps",
        ):
            _positive_int(name, getattr(self, name))
        output = str(self.default_output_format).upper()
        if output not in SUPPORTED_OUTPUT_FORMATS:
            raise ValueError("default_output_format is unsupported")
        object.__setattr__(self, "default_output_format", output)

    def to_dict(self) -> dict:
        return {
            "version": TRANSFORM_VERSION,
            "max_input_bytes": self.max_input_bytes,
            "max_output_bytes": self.max_output_bytes,
            "max_pixels": self.max_pixels,
            "max_dimension": self.max_dimension,
            "max_chain_steps": self.max_chain_steps,
            "default_output_format": self.default_output_format,
        }

    @property
    def digest(self) -> str:
        return _digest_json(self.to_dict())


@dataclass(frozen=True)
class TransformSpec:
    family: str
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        family = str(self.family).strip().lower()
        if family not in SUPPORTED_FAMILIES:
            raise ValueError(f"unsupported propagation family: {self.family!r}")
        if not isinstance(self.params, Mapping):
            raise ValueError("params must be a mapping")
        params = _canonical_value(self.params)
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "params", params)

    def to_dict(self) -> dict:
        return {"family": self.family, "params": dict(self.params)}

    @property
    def digest(self) -> str:
        return _digest_json(self.to_dict())


@dataclass(frozen=True)
class PropagationAudit:
    parent_sha256: str
    output_sha256: Optional[str]
    input_bytes: int
    output_bytes: Optional[int]
    input_format: Optional[str]
    output_format: Optional[str]
    input_size: Optional[Tuple[int, int]]
    output_size: Optional[Tuple[int, int]]
    transform_family: str
    params_digest: str
    operation_chain: Tuple[str, ...]
    toolchain: str
    config_digest: str
    version: str = TRANSFORM_VERSION

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "parent_sha256": self.parent_sha256,
            "output_sha256": self.output_sha256,
            "input_bytes": self.input_bytes,
            "output_bytes": self.output_bytes,
            "input_format": self.input_format,
            "output_format": self.output_format,
            "input_size": list(self.input_size) if self.input_size else None,
            "output_size": list(self.output_size) if self.output_size else None,
            "transform_family": self.transform_family,
            "params_digest": self.params_digest,
            "operation_chain": list(self.operation_chain),
            "toolchain": self.toolchain,
            "config_digest": self.config_digest,
        }

    @property
    def digest(self) -> str:
        return _digest_json(self.to_dict())


@dataclass(frozen=True)
class PropagationVariant:
    accepted: bool
    reason: Optional[str]
    audit: PropagationAudit
    data: bytes = field(default=b"", repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.accepted and self.reason is not None:
            raise ValueError("accepted variant cannot have a reason")
        if not self.accepted and self.reason not in REASON_CODES:
            raise ValueError("rejected variant must use a stable reason")
        if self.accepted and not self.data:
            raise ValueError("accepted variant must contain bytes")

    def to_dict(self) -> dict:
        return {
            "version": TRANSFORM_VERSION,
            "accepted": self.accepted,
            "reason": self.reason,
            "audit": self.audit.to_dict(),
            "audit_digest": self.audit.digest,
        }


@dataclass(frozen=True)
class PairedPropagation:
    accepted: bool
    reason: Optional[str]
    spec: TransformSpec
    source: PropagationVariant
    query: PropagationVariant
    pair_digest: str
    version: str = "paired-propagation-v1"

    def __post_init__(self) -> None:
        if self.accepted and self.reason is not None:
            raise ValueError("accepted pair cannot have a reason")
        if not self.accepted and not self.reason:
            raise ValueError("rejected pair requires a reason")
        if self.accepted and (not self.source.accepted or not self.query.accepted):
            raise ValueError("accepted pair requires two accepted variants")

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "accepted": self.accepted,
            "reason": self.reason,
            "spec": self.spec.to_dict(),
            "source": self.source.to_dict(),
            "query": self.query.to_dict(),
            "pair_digest": self.pair_digest,
        }


def _toolchain() -> str:
    return f"Pillow/{PILLOW_VERSION}"


def _empty_audit(raw: bytes, spec: TransformSpec, config: PropagationConfig) -> PropagationAudit:
    return PropagationAudit(
        parent_sha256=_digest_bytes(raw),
        output_sha256=None,
        input_bytes=len(raw),
        output_bytes=None,
        input_format=None,
        output_format=None,
        input_size=None,
        output_size=None,
        transform_family=spec.family,
        params_digest=spec.digest,
        operation_chain=(spec.family,),
        toolchain=_toolchain(),
        config_digest=config.digest,
    )


def _rejected(raw: bytes, spec: TransformSpec, config: PropagationConfig, reason: str, **updates: Any) -> PropagationVariant:
    if reason not in REASON_CODES:
        raise ValueError(f"unsupported reason: {reason}")
    values = _empty_audit(raw, spec, config).to_dict()
    values.update(updates)
    values.pop("version", None)
    return PropagationVariant(False, reason, PropagationAudit(**values))


def _require_dependencies() -> None:
    if Image is None or ImageFilter is None or ImageOps is None:
        raise RuntimeError("propagation transforms require Pillow; install requirements-research.txt")


def _open_image(raw: bytes, config: PropagationConfig) -> Tuple[Any, str, Tuple[int, int]]:
    if len(raw) > config.max_input_bytes:
        raise ValueError("input_too_large")
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            image_format = str(opened.format or "").upper()
            if image_format not in SUPPORTED_INPUT_FORMATS:
                raise ValueError("unsupported_format")
            if getattr(opened, "n_frames", 1) != 1:
                raise ValueError("animated_or_multipage")
            width, height = (int(opened.width), int(opened.height))
            if width < 1 or height < 1 or width * height > config.max_pixels:
                raise ValueError("pixel_limit_exceeded")
            if width > config.max_dimension or height > config.max_dimension:
                raise ValueError("pixel_limit_exceeded")
            opened.load()
            image = ImageOps.exif_transpose(opened).convert("RGB")
            return image, image_format, (width, height)
    except ValueError:
        raise
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("decode_failed") from exc


def _output_format(params: Mapping[str, Any], config: PropagationConfig) -> str:
    value = str(params.get("output_format", config.default_output_format)).upper()
    if value not in SUPPORTED_OUTPUT_FORMATS:
        raise ValueError("invalid_params")
    return value


def _encode(image: Any, params: Mapping[str, Any], config: PropagationConfig) -> Tuple[bytes, str]:
    output_format = _output_format(params, config)
    output = io.BytesIO()
    try:
        if output_format == "JPEG":
            quality = _bounded_int("quality", params.get("quality", 75), 1, 95)
            progressive = params.get("progressive", False)
            if not isinstance(progressive, bool):
                raise ValueError("invalid_params")
            image.save(output, format="JPEG", quality=quality, optimize=False, progressive=progressive, subsampling=2)
        elif output_format == "WEBP":
            quality = _bounded_int("quality", params.get("quality", 80), 1, 100)
            lossless = params.get("lossless", False)
            if not isinstance(lossless, bool):
                raise ValueError("invalid_params")
            image.save(output, format="WEBP", quality=quality, lossless=lossless, method=4)
        else:
            compression = _bounded_int("compress_level", params.get("compress_level", 6), 0, 9)
            image.save(output, format="PNG", compress_level=compression, optimize=False)
    except ValueError:
        raise
    except (OSError, ValueError) as exc:
        raise ValueError("encode_failed") from exc
    data = output.getvalue()
    if not data:
        raise ValueError("encode_failed")
    if len(data) > config.max_output_bytes:
        raise ValueError("output_too_large")
    return data, output_format


def _transform_image(image: Any, spec: TransformSpec, config: PropagationConfig) -> Tuple[Any, Mapping[str, Any]]:
    params = spec.params
    if spec.family == "jpeg_reencode":
        # The image operation is identity; JPEG encoding is handled by caller.
        return image, {**params, "output_format": "JPEG"}
    if spec.family == "resize":
        scale = params.get("scale")
        if scale is not None:
            scale_value = _finite_number("scale", scale)
            if not 0.1 <= scale_value <= 4.0:
                raise ValueError("invalid_params")
            width = max(1, round(image.width * scale_value))
            height = max(1, round(image.height * scale_value))
        else:
            width = _positive_int("width", params.get("width"))
            height = _positive_int("height", params.get("height"))
        if width > config.max_dimension or height > config.max_dimension or width * height > config.max_pixels:
            raise ValueError("pixel_limit_exceeded")
        return image.resize((width, height), resample=Image.Resampling.LANCZOS), params
    if spec.family == "center_crop":
        fraction = _finite_number("fraction", params.get("fraction", 0.9))
        if not 0.1 <= fraction <= 1.0:
            raise ValueError("invalid_params")
        width = max(1, round(image.width * fraction))
        height = max(1, round(image.height * fraction))
        left = (image.width - width) // 2
        top = (image.height - height) // 2
        return image.crop((left, top, left + width, top + height)), params
    if spec.family == "blur":
        radius = _finite_number("radius", params.get("radius", 1.0))
        if not 0.0 <= radius <= 20.0:
            raise ValueError("invalid_params")
        return image.filter(ImageFilter.GaussianBlur(radius=radius)), params
    if spec.family == "screenshot_sim":
        scale = _finite_number("scale", params.get("scale", 1.0))
        if not 0.5 <= scale <= 1.5:
            raise ValueError("invalid_params")
        width = max(1, round(image.width * scale))
        height = max(1, round(image.height * scale))
        if width > config.max_dimension or height > config.max_dimension or width * height > config.max_pixels:
            raise ValueError("pixel_limit_exceeded")
        resized = image.resize((width, height), resample=Image.Resampling.BICUBIC)
        return resized, {**params, "output_format": "JPEG", "quality": params.get("quality", 75)}
    raise ValueError("unsupported_family")


def _apply_single(raw: bytes, spec: TransformSpec, config: PropagationConfig) -> PropagationVariant:
    audit_base = _empty_audit(raw, spec, config)
    try:
        _require_dependencies()
    except RuntimeError:
        return _rejected(raw, spec, config, "dependency_unavailable")
    if len(raw) > config.max_input_bytes:
        return _rejected(raw, spec, config, "input_too_large")
    try:
        image, input_format, input_size = _open_image(raw, config)
        if spec.family == "identity":
            output = raw
            output_format = input_format
            output_size = input_size
        else:
            transformed, encode_params = _transform_image(image, spec, config)
            output, output_format = _encode(transformed, encode_params, config)
            output_size = (int(transformed.width), int(transformed.height))
        # Encoders enforce the output bound themselves, but identity keeps the
        # original bytes and therefore must pass through the same gate.  This
        # prevents a caller from lowering ``max_output_bytes`` and receiving a
        # falsely accepted oversized variant.
        if len(output) > config.max_output_bytes:
            raise ValueError("output_too_large")
        audit = PropagationAudit(
            parent_sha256=_digest_bytes(raw),
            output_sha256=_digest_bytes(output),
            input_bytes=len(raw),
            output_bytes=len(output),
            input_format=input_format,
            output_format=output_format,
            input_size=input_size,
            output_size=output_size,
            transform_family=spec.family,
            params_digest=spec.digest,
            operation_chain=(spec.family,),
            toolchain=_toolchain(),
            config_digest=config.digest,
        )
        return PropagationVariant(True, None, audit, output)
    except ValueError as exc:
        reason = str(exc)
        if reason not in REASON_CODES:
            reason = "invalid_params"
        return _rejected(raw, spec, config, reason)


def apply_propagation_transform(
    raw: bytes,
    spec: TransformSpec | str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    config: Optional[PropagationConfig] = None,
) -> PropagationVariant:
    """Apply one bounded propagation transform and return an auditable variant."""

    active_config = config or PropagationConfig()
    try:
        active_spec = spec if isinstance(spec, TransformSpec) else TransformSpec(spec, params or {})
    except (TypeError, ValueError):
        fallback = TransformSpec("identity")
        return _rejected(raw if isinstance(raw, bytes) else b"", fallback, active_config, "invalid_params")
    if not isinstance(raw, bytes):
        return _rejected(b"", active_spec, active_config, "invalid_params")
    if active_spec.family != "composite":
        return _apply_single(raw, active_spec, active_config)

    steps = active_spec.params.get("steps")
    if not isinstance(steps, list) or not steps or len(steps) > active_config.max_chain_steps:
        return _rejected(raw, active_spec, active_config, "chain_invalid")
    current = raw
    audits = []
    for item in steps:
        if not isinstance(item, Mapping) or "family" not in item:
            return _rejected(raw, active_spec, active_config, "chain_invalid")
        try:
            step = TransformSpec(str(item["family"]), item.get("params", {}))
        except (TypeError, ValueError):
            return _rejected(raw, active_spec, active_config, "chain_invalid")
        if step.family == "composite":
            return _rejected(raw, active_spec, active_config, "chain_invalid")
        result = _apply_single(current, step, active_config)
        if not result.accepted:
            return _rejected(raw, active_spec, active_config, result.reason or "chain_invalid")
        current = result.data
        audits.append(result.audit)
    final = audits[-1]
    audit = PropagationAudit(
        parent_sha256=_digest_bytes(raw),
        output_sha256=_digest_bytes(current),
        input_bytes=len(raw),
        output_bytes=len(current),
        input_format=audits[0].input_format,
        output_format=final.output_format,
        input_size=audits[0].input_size,
        output_size=final.output_size,
        transform_family="composite",
        params_digest=active_spec.digest,
        operation_chain=tuple(item.transform_family for item in audits),
        toolchain=_toolchain(),
        config_digest=active_config.digest,
    )
    return PropagationVariant(True, None, audit, current)


def build_paired_propagation(
    source_raw: bytes,
    query_raw: bytes,
    spec: TransformSpec | str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    config: Optional[PropagationConfig] = None,
) -> PairedPropagation:
    """Apply one identical transform spec to source and query.

    The function only establishes a byte-level paired observation.  It does
    not decide whether the query is AI-generated, edited, human-made, or a
    copyright violation.
    """

    active_config = config or PropagationConfig()
    active_spec = spec if isinstance(spec, TransformSpec) else TransformSpec(spec, params or {})
    source = apply_propagation_transform(source_raw, active_spec, config=active_config)
    query = apply_propagation_transform(query_raw, active_spec, config=active_config)
    if not source.accepted:
        return PairedPropagation(False, f"source:{source.reason}", active_spec, source, query, "")
    if not query.accepted:
        return PairedPropagation(False, f"query:{query.reason}", active_spec, source, query, "")
    pair_payload = {
        "version": "paired-propagation-v1",
        "spec": active_spec.to_dict(),
        "source_parent_sha256": source.audit.parent_sha256,
        "query_parent_sha256": query.audit.parent_sha256,
        "source_output_sha256": source.audit.output_sha256,
        "query_output_sha256": query.audit.output_sha256,
        "config_digest": active_config.digest,
    }
    pair_digest = _digest_json(pair_payload)
    return PairedPropagation(True, None, active_spec, source, query, pair_digest)


__all__ = [
    "TRANSFORM_VERSION",
    "SUPPORTED_FAMILIES",
    "REASON_CODES",
    "PropagationConfig",
    "TransformSpec",
    "PropagationAudit",
    "PropagationVariant",
    "PairedPropagation",
    "apply_propagation_transform",
    "build_paired_propagation",
]
