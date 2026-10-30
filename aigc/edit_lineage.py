"""Operation-aware edit traces and conservative lineage consistency checks.

This module records an ordered *claimed* edit trace and checks whether the
available regional raw evidence can be joined to that trace.  It deliberately
does not infer a missing edit history from a final image.  A step must carry a
stable mask/operation digest, explicit parent steps and output regions; raw
observations must identify the step they belong to.  The result is an audit
route (consistent, inconsistent, or insufficient), never an AIGC probability,
author identity, or legal conclusion.

The contract is dependency-light so that a future model adapter can attach
real mask overlap and source-conditioned deltas without changing the replay
schema.  Current thresholds are engineering gates and must be calibrated on a
frozen authorised manifest before use with real images.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union


VERSION = "edit-lineage-v1"
RESULT_SCHEMA = "edit-lineage-result-v1"

ROUTE_CONSISTENT = "lineage_consistent"
ROUTE_INCONSISTENT = "lineage_inconsistent"
ROUTE_INSUFFICIENT = "insufficient"

STATUS_CONSISTENT = ROUTE_CONSISTENT
STATUS_INCONSISTENT = ROUTE_INCONSISTENT
STATUS_INSUFFICIENT = ROUTE_INSUFFICIENT

# The list intentionally contains both content-edit operations and ordinary
# propagation operations.  A propagation step can be represented in a trace
# as a hard-negative lineage event, but it must not silently become an edit.
CONTENT_OPERATIONS = frozenset(
    {"add", "remove", "replace", "inpaint", "outpaint", "retouch", "style_transfer"}
)
PROPAGATION_OPERATIONS = frozenset(
    {"identity", "jpeg_reencode", "reencode", "resize", "center_crop", "blur", "screenshot_sim", "transform", "upscale"}
)
SUPPORTED_OPERATIONS = CONTENT_OPERATIONS | PROPAGATION_OPERATIONS
OPERATION_SCOPE_CONTENT = "content_edit"
OPERATION_SCOPE_PROPAGATION = "ordinary_propagation"
OPERATION_SCOPE_MIXED = "mixed"


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _normalise_operation(value: str) -> str:
    value = _text("operation_type", value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "insert": "add",
        "delete": "remove",
        "substitute": "replace",
        "paint": "inpaint",
        "extend": "outpaint",
        "jpeg": "jpeg_reencode",
        "style": "style_transfer",
        "background_remove": "remove",
        "object_removal": "remove",
        "background_replace": "replace",
    }
    return aliases.get(value, value)


def _sha256(name: str, value: Optional[str], *, allow_none: bool = False) -> Optional[str]:
    if value is None and allow_none:
        return None
    value = _text(name, value or "")
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
    return value.lower()


def _finite(name: str, value: float, *, lower: Optional[float] = None, upper: Optional[float] = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if lower is not None and value < lower:
        raise ValueError(f"{name} must be >= {lower}")
    if upper is not None and value > upper:
        raise ValueError(f"{name} must be <= {upper}")
    return value


def _unit(name: str, value: float) -> float:
    return _finite(name, value, lower=0.0, upper=1.0)


def _positive_int(name: str, value: int, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be a {qualifier} integer")
    return value


def _id_tuple(name: str, values: Iterable[str]) -> Tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a sequence of strings")
    result = tuple(_text(name, value) for value in values)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must not contain duplicate IDs")
    return result


def _json_mapping(name: str, value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Normalise audit parameters without allowing probability claims."""

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")

    def normalise(item: Any) -> Any:
        if isinstance(item, Mapping):
            result: Dict[str, Any] = {}
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError(f"{name} keys must be strings")
                lowered = key.lower()
                if "probability" in lowered or lowered in {"aigc_prob", "ai_prob"}:
                    raise ValueError(f"{name} cannot contain probability fields")
                result[key] = normalise(child)
            return dict(sorted(result.items()))
        if isinstance(item, (list, tuple)):
            return [normalise(child) for child in item]
        if item is None or isinstance(item, (bool, str, int)):
            return item
        if isinstance(item, float) and math.isfinite(item):
            return float(item)
        raise ValueError(f"{name} contains a non-JSON or non-finite value")

    return normalise(value)


def _operation_scope(steps: Sequence["EditTraceStep"]) -> str:
    kinds = {step.operation_type for step in steps}
    has_content = bool(kinds.intersection(CONTENT_OPERATIONS))
    has_propagation = bool(kinds.intersection(PROPAGATION_OPERATIONS))
    if has_content and has_propagation:
        return OPERATION_SCOPE_MIXED
    if has_content:
        return OPERATION_SCOPE_CONTENT
    if has_propagation:
        return OPERATION_SCOPE_PROPAGATION
    return OPERATION_SCOPE_MIXED


@dataclass(frozen=True)
class EditTraceStep:
    """One operation in an ordered, versioned edit trace.

    ``sequence_index`` is one-based.  ``parent_step_ids`` describes the
    operation DAG and must always reference an earlier step.  Region IDs are
    canonical IDs in the same coordinate frame; this module does not derive
    overlap from image pixels.
    """

    step_id: str
    sequence_index: int
    operation_type: str
    parent_step_ids: Tuple[str, ...] = ()
    input_region_ids: Tuple[str, ...] = ()
    output_region_ids: Tuple[str, ...] = ()
    mask_digest: Optional[str] = None
    operation_params_digest: Optional[str] = None
    source_digest: Optional[str] = None
    output_digest: Optional[str] = None
    metadata: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _text("step_id", self.step_id))
        _positive_int("sequence_index", self.sequence_index)
        object.__setattr__(self, "operation_type", _normalise_operation(self.operation_type))
        object.__setattr__(self, "parent_step_ids", _id_tuple("parent_step_ids", self.parent_step_ids))
        object.__setattr__(self, "input_region_ids", _id_tuple("input_region_ids", self.input_region_ids))
        object.__setattr__(self, "output_region_ids", _id_tuple("output_region_ids", self.output_region_ids))
        object.__setattr__(self, "mask_digest", _sha256("mask_digest", self.mask_digest, allow_none=True))
        object.__setattr__(self, "operation_params_digest", _sha256("operation_params_digest", self.operation_params_digest, allow_none=True))
        object.__setattr__(self, "source_digest", _sha256("source_digest", self.source_digest, allow_none=True))
        object.__setattr__(self, "output_digest", _sha256("output_digest", self.output_digest, allow_none=True))
        object.__setattr__(self, "metadata", _json_mapping("metadata", self.metadata))

    @property
    def operation(self) -> str:
        """Short alias used by adapters that call the field ``operation``."""

        return self.operation_type

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "sequence_index": self.sequence_index,
            "operation_type": self.operation_type,
            "parent_step_ids": list(self.parent_step_ids),
            "input_region_ids": list(self.input_region_ids),
            "output_region_ids": list(self.output_region_ids),
            "mask_digest": self.mask_digest,
            "operation_params_digest": self.operation_params_digest,
            "source_digest": self.source_digest,
            "output_digest": self.output_digest,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EditLineageTrace:
    """Identity and ordered steps for one source-to-observed version edge."""

    asset_id: str
    source_version_id: str
    observed_version_id: str
    detector_version: str
    score_schema: str
    steps: Tuple[EditTraceStep, ...]
    pair_id: Optional[str] = None
    transform_family: Optional[str] = None
    canonical_frame_digest: Optional[str] = None
    manifest_digest: Optional[str] = None
    binding_digest: Optional[str] = None
    trace_metadata: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        for name in ("asset_id", "source_version_id", "observed_version_id", "detector_version", "score_schema"):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        steps = tuple(self.steps)
        if any(not isinstance(step, EditTraceStep) for step in steps):
            raise ValueError("steps must contain EditTraceStep values")
        object.__setattr__(self, "steps", steps)
        for name in ("pair_id", "transform_family"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _text(name, value))
        for name in ("canonical_frame_digest", "manifest_digest", "binding_digest"):
            object.__setattr__(self, name, _sha256(name, getattr(self, name), allow_none=True))
        object.__setattr__(self, "trace_metadata", _json_mapping("trace_metadata", self.trace_metadata))

    @property
    def binding_context_complete(self) -> bool:
        return all(
            value is not None
            for value in (
                self.pair_id,
                self.transform_family,
                self.canonical_frame_digest,
                self.manifest_digest,
                self.binding_digest,
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "asset_id": self.asset_id,
            "source_version_id": self.source_version_id,
            "observed_version_id": self.observed_version_id,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "pair_id": self.pair_id,
            "transform_family": self.transform_family,
            "canonical_frame_digest": self.canonical_frame_digest,
            "manifest_digest": self.manifest_digest,
            "binding_digest": self.binding_digest,
            "steps": [step.to_dict() for step in self.steps],
            "trace_metadata": dict(self.trace_metadata),
        }

    @property
    def trace_digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class EditRegionEvidence:
    """Raw region evidence bound to exactly one trace step."""

    step_id: str
    region_id: str
    delta_raw: float
    quality_score: float
    source_match_score: float
    operation_type: Optional[str] = None
    mask_overlap_raw: Optional[float] = None
    non_edit_consistency_raw: Optional[float] = None
    region_type: Optional[str] = None
    evidence_digest: Optional[str] = None
    metadata: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _text("step_id", self.step_id))
        object.__setattr__(self, "region_id", _text("region_id", self.region_id))
        object.__setattr__(self, "delta_raw", _finite("delta_raw", self.delta_raw, lower=-1.0, upper=1.0))
        object.__setattr__(self, "quality_score", _unit("quality_score", self.quality_score))
        object.__setattr__(self, "source_match_score", _unit("source_match_score", self.source_match_score))
        if self.operation_type is not None:
            object.__setattr__(self, "operation_type", _normalise_operation(self.operation_type))
        if self.mask_overlap_raw is not None:
            object.__setattr__(self, "mask_overlap_raw", _unit("mask_overlap_raw", self.mask_overlap_raw))
        if self.non_edit_consistency_raw is not None:
            object.__setattr__(self, "non_edit_consistency_raw", _unit("non_edit_consistency_raw", self.non_edit_consistency_raw))
        if self.region_type is not None:
            object.__setattr__(self, "region_type", _text("region_type", self.region_type))
        object.__setattr__(self, "evidence_digest", _sha256("evidence_digest", self.evidence_digest, allow_none=True))
        object.__setattr__(self, "metadata", _json_mapping("metadata", self.metadata))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "region_id": self.region_id,
            "delta_raw": self.delta_raw,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "operation_type": self.operation_type,
            "mask_overlap_raw": self.mask_overlap_raw,
            "non_edit_consistency_raw": self.non_edit_consistency_raw,
            "region_type": self.region_type,
            "evidence_digest": self.evidence_digest,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EditLineageConfig:
    """Conservative gates for the ordered trace audit."""

    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    minimum_evidence_coverage: float = 1.0
    minimum_lineage_consistency: float = 1.0
    minimum_operation_consistency: float = 1.0
    minimum_mask_overlap: float = 0.50
    quality_power: float = 1.0
    require_mask_for_content_operations: bool = True
    require_mask_overlap_for_content_operations: bool = True
    require_region_overlap_for_children: bool = True
    version: str = VERSION

    def __post_init__(self) -> None:
        for name in (
            "minimum_quality",
            "minimum_source_match",
            "minimum_evidence_coverage",
            "minimum_lineage_consistency",
            "minimum_operation_consistency",
            "minimum_mask_overlap",
        ):
            object.__setattr__(self, name, _unit(name, getattr(self, name)))
        object.__setattr__(self, "quality_power", _finite("quality_power", self.quality_power, lower=0.0))
        if not isinstance(self.require_mask_for_content_operations, bool):
            raise ValueError("require_mask_for_content_operations must be bool")
        if not isinstance(self.require_mask_overlap_for_content_operations, bool):
            raise ValueError("require_mask_overlap_for_content_operations must be bool")
        if not isinstance(self.require_region_overlap_for_children, bool):
            raise ValueError("require_region_overlap_for_children must be bool")
        object.__setattr__(self, "version", _text("version", self.version))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "minimum_evidence_coverage": self.minimum_evidence_coverage,
            "minimum_lineage_consistency": self.minimum_lineage_consistency,
            "minimum_operation_consistency": self.minimum_operation_consistency,
            "minimum_mask_overlap": self.minimum_mask_overlap,
            "quality_power": self.quality_power,
            "require_mask_for_content_operations": self.require_mask_for_content_operations,
            "require_mask_overlap_for_content_operations": self.require_mask_overlap_for_content_operations,
            "require_region_overlap_for_children": self.require_region_overlap_for_children,
        }

    @property
    def config_digest(self) -> str:
        return _digest(self.to_dict())

    @property
    def digest(self) -> str:
        return self.config_digest


@dataclass(frozen=True)
class EditStepAudit:
    step_id: str
    sequence_index: int
    operation_type: str
    total_evidence_count: int
    accepted_evidence_count: int
    evidence_coverage_raw: float
    weighted_delta_raw: Optional[float]
    mask_consistency_raw: Optional[float]
    lineage_ok: bool
    operation_ok: bool
    reasons: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text("step_id", self.step_id)
        _positive_int("sequence_index", self.sequence_index)
        _text("operation_type", self.operation_type)
        _positive_int("total_evidence_count", self.total_evidence_count, allow_zero=True)
        _positive_int("accepted_evidence_count", self.accepted_evidence_count, allow_zero=True)
        if self.accepted_evidence_count > self.total_evidence_count:
            raise ValueError("accepted_evidence_count cannot exceed total_evidence_count")
        object.__setattr__(self, "evidence_coverage_raw", _unit("evidence_coverage_raw", self.evidence_coverage_raw))
        if self.weighted_delta_raw is not None:
            object.__setattr__(self, "weighted_delta_raw", _finite("weighted_delta_raw", self.weighted_delta_raw, lower=-1.0, upper=1.0))
        if self.mask_consistency_raw is not None:
            object.__setattr__(self, "mask_consistency_raw", _unit("mask_consistency_raw", self.mask_consistency_raw))
        if not isinstance(self.lineage_ok, bool) or not isinstance(self.operation_ok, bool):
            raise ValueError("lineage_ok and operation_ok must be bool")
        object.__setattr__(self, "reasons", tuple(_text("reason", item) for item in self.reasons))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "sequence_index": self.sequence_index,
            "operation_type": self.operation_type,
            "total_evidence_count": self.total_evidence_count,
            "accepted_evidence_count": self.accepted_evidence_count,
            "evidence_coverage_raw": self.evidence_coverage_raw,
            "weighted_delta_raw": self.weighted_delta_raw,
            "mask_consistency_raw": self.mask_consistency_raw,
            "lineage_ok": self.lineage_ok,
            "operation_ok": self.operation_ok,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class EditLineageConsistencyResult:
    route: str
    abstained: bool
    reason: str
    asset_id: str
    source_version_id: str
    observed_version_id: str
    detector_version: str
    score_schema: str
    step_count: int
    evidence_count: int
    accepted_evidence_count: int
    accepted_step_count: int
    evidence_coverage_raw: float
    ordered_consistency_raw: float
    lineage_consistency_raw: float
    operation_consistency_raw: float
    mask_consistency_raw: Optional[float]
    weighted_delta_raw: Optional[float]
    step_audit: Tuple[EditStepAudit, ...]
    invalid_step_ids: Tuple[str, ...]
    invalid_evidence_ids: Tuple[str, ...]
    config_digest: str
    trace_digest: str
    evidence_digest: str
    operation_scope: str
    pair_id: Optional[str] = None
    transform_family: Optional[str] = None
    canonical_frame_digest: Optional[str] = None
    manifest_digest: Optional[str] = None
    binding_digest: Optional[str] = None
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.route not in {ROUTE_CONSISTENT, ROUTE_INCONSISTENT, ROUTE_INSUFFICIENT}:
            raise ValueError("invalid edit lineage route")
        if self.route == ROUTE_CONSISTENT and self.abstained:
            raise ValueError("consistent route cannot abstain")
        if self.route != ROUTE_CONSISTENT and not self.abstained:
            raise ValueError("inconsistent and insufficient routes must abstain")
        if not isinstance(self.abstained, bool):
            raise ValueError("abstained must be bool")
        if self.operation_scope not in {OPERATION_SCOPE_CONTENT, OPERATION_SCOPE_PROPAGATION, OPERATION_SCOPE_MIXED}:
            raise ValueError("invalid operation scope")
        _text("reason", self.reason)
        for name in ("asset_id", "source_version_id", "observed_version_id", "detector_version", "score_schema"):
            _text(name, getattr(self, name))
        for name in ("pair_id", "transform_family"):
            value = getattr(self, name)
            if value is not None:
                _text(name, value)
        for name in ("canonical_frame_digest", "manifest_digest", "binding_digest"):
            _sha256(name, getattr(self, name), allow_none=True)
        for name in ("step_count", "evidence_count", "accepted_evidence_count", "accepted_step_count"):
            _positive_int(name, getattr(self, name), allow_zero=True)
        if self.accepted_evidence_count > self.evidence_count or self.accepted_step_count > self.step_count:
            raise ValueError("accepted counts cannot exceed total counts")
        for name in ("evidence_coverage_raw", "ordered_consistency_raw", "lineage_consistency_raw", "operation_consistency_raw"):
            object.__setattr__(self, name, _unit(name, getattr(self, name)))
        if self.mask_consistency_raw is not None:
            object.__setattr__(self, "mask_consistency_raw", _unit("mask_consistency_raw", self.mask_consistency_raw))
        if self.weighted_delta_raw is not None:
            object.__setattr__(self, "weighted_delta_raw", _finite("weighted_delta_raw", self.weighted_delta_raw, lower=-1.0, upper=1.0))
        if any(not isinstance(item, EditStepAudit) for item in self.step_audit):
            raise ValueError("step_audit must contain EditStepAudit values")
        object.__setattr__(self, "invalid_step_ids", _id_tuple("invalid_step_ids", self.invalid_step_ids))
        object.__setattr__(self, "invalid_evidence_ids", _id_tuple("invalid_evidence_ids", self.invalid_evidence_ids))
        _sha256("config_digest", self.config_digest)
        _sha256("trace_digest", self.trace_digest)
        _sha256("evidence_digest", self.evidence_digest)

    @property
    def status(self) -> str:
        return self.route

    @property
    def audit(self) -> Tuple[Dict[str, Any], ...]:
        return tuple(item.to_dict() for item in self.step_audit)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "result_schema": RESULT_SCHEMA,
            "route": self.route,
            "status": self.route,
            "abstained": self.abstained,
            "reason": self.reason,
            "asset_id": self.asset_id,
            "source_version_id": self.source_version_id,
            "observed_version_id": self.observed_version_id,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "pair_id": self.pair_id,
            "transform_family": self.transform_family,
            "canonical_frame_digest": self.canonical_frame_digest,
            "manifest_digest": self.manifest_digest,
            "binding_digest": self.binding_digest,
            "step_count": self.step_count,
            "evidence_count": self.evidence_count,
            "accepted_evidence_count": self.accepted_evidence_count,
            "accepted_step_count": self.accepted_step_count,
            "evidence_coverage_raw": self.evidence_coverage_raw,
            "ordered_consistency_raw": self.ordered_consistency_raw,
            "lineage_consistency_raw": self.lineage_consistency_raw,
            "operation_consistency_raw": self.operation_consistency_raw,
            "mask_consistency_raw": self.mask_consistency_raw,
            "weighted_delta_raw": self.weighted_delta_raw,
            "step_audit": [item.to_dict() for item in self.step_audit],
            "invalid_step_ids": list(self.invalid_step_ids),
            "invalid_evidence_ids": list(self.invalid_evidence_ids),
            "config_digest": self.config_digest,
            "trace_digest": self.trace_digest,
            "evidence_digest": self.evidence_digest,
            "operation_scope": self.operation_scope,
        }


def _coerce_trace(
    trace_or_steps: Union[EditLineageTrace, Sequence[EditTraceStep]],
    *,
    asset_id: Optional[str],
    source_version_id: Optional[str],
    observed_version_id: Optional[str],
    detector_version: Optional[str],
    score_schema: Optional[str],
    pair_id: Optional[str],
    transform_family: Optional[str],
    canonical_frame_digest: Optional[str],
    manifest_digest: Optional[str],
    binding_digest: Optional[str],
) -> EditLineageTrace:
    if isinstance(trace_or_steps, EditLineageTrace):
        return trace_or_steps
    steps = tuple(trace_or_steps)
    # Direct list input is useful for lightweight adapters.  The sentinel
    # identity is explicit in the result and is not a claim that the asset was
    # authenticated.
    return EditLineageTrace(
        asset_id=asset_id or "unbound_asset",
        source_version_id=source_version_id or "unbound_source",
        observed_version_id=observed_version_id or "unbound_observed",
        detector_version=detector_version or "unbound_detector",
        score_schema=score_schema or "unbound_schema",
        steps=steps,
        pair_id=pair_id,
        transform_family=transform_family,
        canonical_frame_digest=canonical_frame_digest,
        manifest_digest=manifest_digest,
        binding_digest=binding_digest,
    )


def _empty_result(
    trace: EditLineageTrace,
    evidence: Sequence[EditRegionEvidence],
    *,
    config: EditLineageConfig,
    reason: str,
    route: str = ROUTE_INSUFFICIENT,
    invalid_step_ids: Sequence[str] = (),
    invalid_evidence_ids: Sequence[str] = (),
    step_audit: Sequence[EditStepAudit] = (),
    evidence_coverage: float = 0.0,
    ordered_consistency: float = 0.0,
    lineage_consistency: float = 0.0,
    operation_consistency: float = 0.0,
    mask_consistency: Optional[float] = None,
    weighted_delta: Optional[float] = None,
) -> EditLineageConsistencyResult:
    evidence_payload = [item.to_dict() for item in evidence]
    return EditLineageConsistencyResult(
        route=route,
        abstained=route != ROUTE_CONSISTENT,
        reason=reason,
        asset_id=trace.asset_id,
        source_version_id=trace.source_version_id,
        observed_version_id=trace.observed_version_id,
        detector_version=trace.detector_version,
        score_schema=trace.score_schema,
        step_count=len(trace.steps),
        evidence_count=len(evidence),
        accepted_evidence_count=0,
        accepted_step_count=0,
        evidence_coverage_raw=max(0.0, min(1.0, evidence_coverage)),
        ordered_consistency_raw=max(0.0, min(1.0, ordered_consistency)),
        lineage_consistency_raw=max(0.0, min(1.0, lineage_consistency)),
        operation_consistency_raw=max(0.0, min(1.0, operation_consistency)),
        mask_consistency_raw=mask_consistency,
        weighted_delta_raw=weighted_delta,
        step_audit=tuple(step_audit),
        invalid_step_ids=tuple(invalid_step_ids),
        invalid_evidence_ids=tuple(invalid_evidence_ids),
        config_digest=config.config_digest,
        trace_digest=trace.trace_digest,
        evidence_digest=_digest({"version": VERSION, "binding_digest": trace.binding_digest, "evidence": evidence_payload}),
        operation_scope=_operation_scope(trace.steps),
        pair_id=trace.pair_id,
        transform_family=trace.transform_family,
        canonical_frame_digest=trace.canonical_frame_digest,
        manifest_digest=trace.manifest_digest,
        binding_digest=trace.binding_digest,
    )


def evaluate_edit_lineage(
    trace_or_steps: Union[EditLineageTrace, Sequence[EditTraceStep]],
    evidence: Optional[Sequence[EditRegionEvidence]] = None,
    *,
    config: Optional[EditLineageConfig] = None,
    asset_id: Optional[str] = None,
    source_version_id: Optional[str] = None,
    observed_version_id: Optional[str] = None,
    detector_version: Optional[str] = None,
    score_schema: Optional[str] = None,
    pair_id: Optional[str] = None,
    transform_family: Optional[str] = None,
    canonical_frame_digest: Optional[str] = None,
    manifest_digest: Optional[str] = None,
    binding_digest: Optional[str] = None,
) -> EditLineageConsistencyResult:
    """Evaluate one ordered operation trace against regional raw evidence.

    The function accepts either an :class:`EditLineageTrace` or a sequence of
    steps.  The latter form is a convenience for tests/adapters; callers that
    have authenticated identity should use ``EditLineageTrace``.
    """

    cfg = config or EditLineageConfig()
    trace = _coerce_trace(
        trace_or_steps,
        asset_id=asset_id,
        source_version_id=source_version_id,
        observed_version_id=observed_version_id,
        detector_version=detector_version,
        score_schema=score_schema,
        pair_id=pair_id,
        transform_family=transform_family,
        canonical_frame_digest=canonical_frame_digest,
        manifest_digest=manifest_digest,
        binding_digest=binding_digest,
    )
    observations = tuple(evidence or ())
    if any(not isinstance(item, EditRegionEvidence) for item in observations):
        raise ValueError("evidence must contain EditRegionEvidence values")
    if not trace.steps:
        return _empty_result(trace, observations, config=cfg, reason="no_edit_steps")
    if not trace.binding_context_complete:
        return _empty_result(trace, observations, config=cfg, reason="binding_context_missing")

    # Reject duplicate IDs, sequence gaps, and input order changes before any
    # aggregation.  Silently sorting a malformed trace would erase evidence of
    # a tampered or truncated operation log.
    step_ids = [step.step_id for step in trace.steps]
    duplicate_steps = tuple(sorted({item for item in step_ids if step_ids.count(item) > 1}))
    sequence_indices = [step.sequence_index for step in trace.steps]
    expected = list(range(1, len(trace.steps) + 1))
    structural_reasons = []
    invalid_steps = set(duplicate_steps)
    if duplicate_steps:
        structural_reasons.append("duplicate_step_id")
    if sequence_indices != expected:
        structural_reasons.append("sequence_gap_or_reorder")
        invalid_steps.update(step.step_id for step in trace.steps if step.sequence_index not in expected)
    by_id = {step.step_id: step for step in trace.steps if step.step_id not in duplicate_steps}
    by_index = {step.sequence_index: step for step in trace.steps if step.step_id not in duplicate_steps}
    for step in trace.steps:
        for parent_id in step.parent_step_ids:
            parent = by_id.get(parent_id)
            if parent is None:
                structural_reasons.append("missing_parent_step")
                invalid_steps.add(step.step_id)
            elif parent.sequence_index >= step.sequence_index:
                structural_reasons.append("future_parent_step")
                invalid_steps.add(step.step_id)

    evidence_ids = [f"{item.step_id}:{item.region_id}" for item in observations]
    duplicate_evidence = tuple(sorted({item for item in evidence_ids if evidence_ids.count(item) > 1}))
    invalid_evidence = set(duplicate_evidence)
    if duplicate_evidence:
        structural_reasons.append("duplicate_region_evidence")
    for item in observations:
        if item.step_id not in by_id:
            structural_reasons.append("evidence_step_missing")
            invalid_evidence.add(f"{item.step_id}:{item.region_id}")

    if structural_reasons:
        return _empty_result(
            trace,
            observations,
            config=cfg,
            reason=structural_reasons[0],
            invalid_step_ids=tuple(sorted(invalid_steps)),
            invalid_evidence_ids=tuple(sorted(invalid_evidence)),
        )

    grouped: Dict[str, list[EditRegionEvidence]] = {step.step_id: [] for step in trace.steps}
    for item in observations:
        grouped[item.step_id].append(item)

    step_audits = []
    accepted_total = 0
    accepted_steps = 0
    weighted_numerator = 0.0
    weighted_denominator = 0.0
    mask_numerator = 0.0
    mask_denominator = 0.0
    content_mask_missing = False
    operation_ok_count = 0
    lineage_ok_count = 0
    invalid_step_reasons: Dict[str, list[str]] = {step.step_id: [] for step in trace.steps}
    accepted_by_step: Dict[str, list[EditRegionEvidence]] = {}

    for step in trace.steps:
        reasons = invalid_step_reasons[step.step_id]
        operation_ok = step.operation_type in SUPPORTED_OPERATIONS
        if not operation_ok:
            reasons.append("unsupported_operation")
        if step.operation_type in CONTENT_OPERATIONS and cfg.require_mask_for_content_operations and not step.mask_digest:
            operation_ok = False
            reasons.append("content_operation_missing_mask_digest")
        if step.operation_type in CONTENT_OPERATIONS and not step.output_region_ids:
            operation_ok = False
            reasons.append("content_operation_missing_output_region")
        if step.operation_type in {"remove", "replace", "inpaint", "retouch", "style_transfer"} and not step.input_region_ids:
            operation_ok = False
            reasons.append("operation_missing_input_region")
        if step.operation_type in PROPAGATION_OPERATIONS and step.sequence_index > 1 and not step.input_region_ids:
            operation_ok = False
            reasons.append("propagation_missing_input_region")
        declared_observation_operations = {
            item.operation_type
            for item in grouped[step.step_id]
            if item.operation_type is not None
        }
        if declared_observation_operations and declared_observation_operations != {step.operation_type}:
            operation_ok = False
            reasons.append("evidence_operation_mismatch")
        if operation_ok:
            operation_ok_count += 1

        lineage_ok = True
        if step.sequence_index > 1 and not step.parent_step_ids:
            lineage_ok = False
            reasons.append("missing_parent_step")
        for parent_id in step.parent_step_ids:
            parent = by_id[parent_id]
            parent_regions = set(parent.output_region_ids)
            child_regions = set(step.input_region_ids) | set(step.output_region_ids)
            overlap = parent_regions.intersection(child_regions)
            # An add/outpaint may introduce a new output region, but it must
            # still carry an input/parent edge.  Without overlap the edge is
            # not auditable in a canonical region frame.
            if cfg.require_region_overlap_for_children and not overlap:
                lineage_ok = False
                reasons.append(f"lineage_region_gap:{parent_id}")
        if lineage_ok:
            lineage_ok_count += 1

        accepted: list[EditRegionEvidence] = []
        for item in grouped[step.step_id]:
            evidence_key = f"{item.step_id}:{item.region_id}"
            if evidence_key in invalid_evidence:
                continue
            if item.quality_score < cfg.minimum_quality:
                continue
            if item.source_match_score < cfg.minimum_source_match:
                continue
            accepted.append(item)
        accepted_by_step[step.step_id] = accepted
        total = len(grouped[step.step_id])
        accepted_count = len(accepted)
        coverage = accepted_count / total if total else 0.0
        if not accepted:
            reasons.append("no_accepted_evidence")
        else:
            accepted_steps += 1
            accepted_total += accepted_count
            weights = [max(0.0, item.quality_score) ** cfg.quality_power * item.source_match_score for item in accepted]
            weight_sum = sum(weights)
            step_delta = sum(weight * item.delta_raw for weight, item in zip(weights, accepted)) / weight_sum if weight_sum else None
            weighted_numerator += sum(weight * item.delta_raw for weight, item in zip(weights, accepted))
            weighted_denominator += weight_sum
            overlaps = [(weight, item.mask_overlap_raw) for weight, item in zip(weights, accepted) if item.mask_overlap_raw is not None]
            if overlaps:
                overlap_weight = sum(weight for weight, _ in overlaps)
                step_mask = sum(weight * float(value) for weight, value in overlaps) / overlap_weight if overlap_weight else None
                if step_mask is not None and step_mask < cfg.minimum_mask_overlap:
                    reasons.append("mask_overlap_below_threshold")
                mask_numerator += sum(weight * float(value) for weight, value in overlaps)
                mask_denominator += overlap_weight
            else:
                step_mask = None
            if (
                step.operation_type in CONTENT_OPERATIONS
                and cfg.require_mask_overlap_for_content_operations
                and any(item.mask_overlap_raw is None for item in accepted)
            ):
                content_mask_missing = True
                reasons.append("content_evidence_missing_mask_overlap")
        if coverage < cfg.minimum_evidence_coverage:
            reasons.append("evidence_coverage_below_threshold")
        step_audits.append(EditStepAudit(
            step_id=step.step_id,
            sequence_index=step.sequence_index,
            operation_type=step.operation_type,
            total_evidence_count=total,
            accepted_evidence_count=accepted_count,
            evidence_coverage_raw=coverage,
            weighted_delta_raw=step_delta if accepted else None,
            mask_consistency_raw=step_mask if accepted else None,
            lineage_ok=lineage_ok,
            operation_ok=operation_ok,
            reasons=tuple(dict.fromkeys(reasons)),
        ))

    invalid_steps.update(step_id for step_id, reasons in invalid_step_reasons.items() if reasons)
    # Report region-evidence coverage over all supplied observations, while
    # separately retaining accepted_step_count for step-level coverage.  A
    # single low-quality region must not disappear merely because another
    # region from the same step passed the gate.
    evidence_coverage = accepted_total / len(observations) if observations else 0.0
    coverage_fail = accepted_steps < len(trace.steps) or any(
        audit.evidence_coverage_raw < cfg.minimum_evidence_coverage for audit in step_audits
    )
    ordered_consistency = 1.0 if sequence_indices == expected else 0.0
    lineage_consistency = lineage_ok_count / len(trace.steps)
    operation_consistency = operation_ok_count / len(trace.steps)
    mask_consistency = mask_numerator / mask_denominator if mask_denominator else None
    weighted_delta = weighted_numerator / weighted_denominator if weighted_denominator else None

    # Preserve the strongest reason in a deterministic order.  Missing or
    # low-quality evidence is insufficient; structural lineage is insufficient
    # only when the trace cannot be interpreted.  A structurally valid but
    # internally inconsistent trace is explicitly separated for review.
    missing_evidence = coverage_fail
    if content_mask_missing:
        route = ROUTE_INSUFFICIENT
        reason = "content_evidence_missing_mask_overlap"
    elif missing_evidence:
        route = ROUTE_INSUFFICIENT
        reason = "evidence_coverage_below_threshold"
    elif operation_consistency < cfg.minimum_operation_consistency:
        route = ROUTE_INCONSISTENT
        reason = "operation_semantics_inconsistent"
    elif lineage_consistency < cfg.minimum_lineage_consistency:
        route = ROUTE_INCONSISTENT
        reason = "lineage_region_gap"
    elif mask_consistency is not None and mask_consistency < cfg.minimum_mask_overlap:
        route = ROUTE_INCONSISTENT
        reason = "mask_overlap_below_threshold"
    elif evidence_coverage < cfg.minimum_evidence_coverage:
        route = ROUTE_INSUFFICIENT
        reason = "evidence_coverage_below_threshold"
    else:
        route = ROUTE_CONSISTENT
        reason = "ordered_lineage_consistent"

    return EditLineageConsistencyResult(
        route=route,
        abstained=route != ROUTE_CONSISTENT,
        reason=reason,
        asset_id=trace.asset_id,
        source_version_id=trace.source_version_id,
        observed_version_id=trace.observed_version_id,
        detector_version=trace.detector_version,
        score_schema=trace.score_schema,
        step_count=len(trace.steps),
        evidence_count=len(observations),
        accepted_evidence_count=accepted_total,
        accepted_step_count=accepted_steps,
        evidence_coverage_raw=evidence_coverage,
        ordered_consistency_raw=ordered_consistency,
        lineage_consistency_raw=lineage_consistency,
        operation_consistency_raw=operation_consistency,
        mask_consistency_raw=mask_consistency,
        weighted_delta_raw=weighted_delta,
        step_audit=tuple(step_audits),
        invalid_step_ids=tuple(sorted(invalid_steps)),
        invalid_evidence_ids=tuple(sorted(invalid_evidence)),
        config_digest=cfg.config_digest,
        trace_digest=trace.trace_digest,
        evidence_digest=_digest({"version": VERSION, "binding_digest": trace.binding_digest, "evidence": [item.to_dict() for item in observations]}),
        operation_scope=_operation_scope(trace.steps),
        pair_id=trace.pair_id,
        transform_family=trace.transform_family,
        canonical_frame_digest=trace.canonical_frame_digest,
        manifest_digest=trace.manifest_digest,
        binding_digest=trace.binding_digest,
    )


def fuse_edit_lineage(*args: Any, **kwargs: Any) -> EditLineageConsistencyResult:
    """Compatibility alias following the naming of other raw fusion layers."""

    return evaluate_edit_lineage(*args, **kwargs)


__all__ = [
    "VERSION",
    "RESULT_SCHEMA",
    "ROUTE_CONSISTENT",
    "ROUTE_INCONSISTENT",
    "ROUTE_INSUFFICIENT",
    "STATUS_CONSISTENT",
    "STATUS_INCONSISTENT",
    "STATUS_INSUFFICIENT",
    "CONTENT_OPERATIONS",
    "PROPAGATION_OPERATIONS",
    "SUPPORTED_OPERATIONS",
    "OPERATION_SCOPE_CONTENT",
    "OPERATION_SCOPE_PROPAGATION",
    "OPERATION_SCOPE_MIXED",
    "EditTraceStep",
    "EditLineageTrace",
    "EditRegionEvidence",
    "EditLineageConfig",
    "EditStepAudit",
    "EditLineageConsistencyResult",
    "evaluate_edit_lineage",
    "fuse_edit_lineage",
]
