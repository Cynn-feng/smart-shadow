"""Step-conditioned multi-view audit over existing raw evidence.

The lower layers already provide ordered edit traces, paired
observed/counterfactual deltas, matched-placebo controls and crop-view
bindings.  This module only composes those outputs.  It does not run a model,
re-fit a placebo p-value, create a crop, or replace any existing route.  Its
question is narrower: does a declared multi-step trace retain control-backed
regional evidence across multiple canonical views in the declared order?

All results are raw audit evidence.  They are not provenance verification,
AIGC probabilities, authorship findings or legal conclusions.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .edit_lineage import (
    CONTENT_OPERATIONS,
    PROPAGATION_OPERATIONS,
    OPERATION_SCOPE_CONTENT,
    OPERATION_SCOPE_PROPAGATION,
    OPERATION_SCOPE_MIXED,
    EditLineageTrace,
)


VERSION = "lineage-view-control-v1"
RESULT_SCHEMA = "lineage-view-control-result-v1"

ROUTE_CONSISTENT = "consistent_controlled_lineage"
ROUTE_INCONSISTENT = "trajectory_inconsistent"
ROUTE_INSUFFICIENT = "insufficient"

CONTROL_CANDIDATE = "candidate_edit"
CONTROL_CONSISTENT = "control_consistent"
CONTROL_INSUFFICIENT = "insufficient"
_CONTROL_ROUTES = {CONTROL_CANDIDATE, CONTROL_CONSISTENT, CONTROL_INSUFFICIENT}


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _sha256(name: str, value: str) -> str:
    value = _text(name, value).lower()
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
    return value


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


def _signed_unit(name: str, value: float) -> float:
    return _finite(name, value, lower=-1.0, upper=1.0)


def _positive_int(name: str, value: int, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an {'non-negative' if allow_zero else 'positive'} integer")
    return value


def _ids(name: str, values: Iterable[str]) -> Tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    result = tuple(_text(name, item) for item in values)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must not contain duplicates")
    return result


def _json_mapping(name: str, value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")

    def normalise(item: Any) -> Any:
        if isinstance(item, Mapping):
            output: Dict[str, Any] = {}
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError(f"{name} keys must be strings")
                lowered = key.lower()
                if "probability" in lowered or lowered in {"aigc_prob", "ai_prob"}:
                    raise ValueError(f"{name} cannot contain probability fields")
                output[key] = normalise(child)
            return dict(sorted(output.items()))
        if isinstance(item, (list, tuple)):
            return [normalise(child) for child in item]
        if item is None or isinstance(item, (bool, int, str)):
            return item
        if isinstance(item, float) and math.isfinite(item):
            return float(item)
        raise ValueError(f"{name} contains a non-JSON or non-finite value")

    return normalise(value)


@dataclass(frozen=True)
class LineageViewControlObservation:
    """One step/region observation in one canonical view.

    ``control_*`` fields are copied from an already evaluated MPCF result.
    Keeping the upstream control digest makes this adapter auditable without
    implementing another p-value or placebo estimator here.
    """

    trace_digest: str
    asset_id: str
    pair_id: str
    transform_family: str
    canonical_frame_digest: str
    manifest_digest: str
    binding_digest: str
    detector_version: str
    score_schema: str
    view_id: str
    view_order: int
    view_spec_digest: str
    step_id: str
    region_id: str
    operation_type: str
    delta_raw: float
    quality_score: float
    source_match_score: float
    control_route: str
    control_contrast_raw: Optional[float] = None
    control_p_value_raw: Optional[float] = None
    control_digest: Optional[str] = None
    mask_overlap_raw: Optional[float] = None
    metadata: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        for name in ("trace_digest", "canonical_frame_digest", "manifest_digest", "binding_digest", "view_spec_digest"):
            object.__setattr__(self, name, _sha256(name, getattr(self, name)))
        for name in ("asset_id", "pair_id", "transform_family", "detector_version", "score_schema", "view_id", "step_id", "region_id", "operation_type"):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        _positive_int("view_order", self.view_order)
        object.__setattr__(self, "operation_type", self.operation_type.lower().replace("-", "_"))
        object.__setattr__(self, "delta_raw", _signed_unit("delta_raw", self.delta_raw))
        object.__setattr__(self, "quality_score", _unit("quality_score", self.quality_score))
        object.__setattr__(self, "source_match_score", _unit("source_match_score", self.source_match_score))
        if self.control_route not in _CONTROL_ROUTES:
            raise ValueError("invalid control_route")
        if self.control_contrast_raw is not None:
            object.__setattr__(self, "control_contrast_raw", _signed_unit("control_contrast_raw", self.control_contrast_raw))
        if self.control_p_value_raw is not None:
            object.__setattr__(self, "control_p_value_raw", _unit("control_p_value_raw", self.control_p_value_raw))
        if self.control_digest is not None:
            object.__setattr__(self, "control_digest", _sha256("control_digest", self.control_digest))
        if self.mask_overlap_raw is not None:
            object.__setattr__(self, "mask_overlap_raw", _unit("mask_overlap_raw", self.mask_overlap_raw))
        object.__setattr__(self, "metadata", _json_mapping("metadata", self.metadata))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_digest": self.trace_digest,
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "transform_family": self.transform_family,
            "canonical_frame_digest": self.canonical_frame_digest,
            "manifest_digest": self.manifest_digest,
            "binding_digest": self.binding_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "view_id": self.view_id,
            "view_order": self.view_order,
            "view_spec_digest": self.view_spec_digest,
            "step_id": self.step_id,
            "region_id": self.region_id,
            "operation_type": self.operation_type,
            "delta_raw": self.delta_raw,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "control_route": self.control_route,
            "control_contrast_raw": self.control_contrast_raw,
            "control_p_value_raw": self.control_p_value_raw,
            "control_digest": self.control_digest,
            "mask_overlap_raw": self.mask_overlap_raw,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class LineageViewControlConfig:
    minimum_views_per_step: int = 2
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    minimum_view_coverage: float = 1.0
    minimum_positive_persistence: float = 0.50
    maximum_view_dispersion: float = 0.25
    maximum_pairwise_disagreement: float = 0.50
    minimum_mask_overlap: float = 0.50
    quality_power: float = 1.0
    require_content_scope: bool = True
    require_mask_overlap_for_content: bool = True
    version: str = VERSION

    def __post_init__(self) -> None:
        _positive_int("minimum_views_per_step", self.minimum_views_per_step)
        for name in ("minimum_quality", "minimum_source_match", "minimum_view_coverage", "minimum_positive_persistence", "maximum_pairwise_disagreement", "minimum_mask_overlap"):
            object.__setattr__(self, name, _unit(name, getattr(self, name)))
        object.__setattr__(self, "maximum_view_dispersion", _finite("maximum_view_dispersion", self.maximum_view_dispersion, lower=0.0, upper=2.0))
        object.__setattr__(self, "quality_power", _finite("quality_power", self.quality_power, lower=0.0))
        if not isinstance(self.require_content_scope, bool) or not isinstance(self.require_mask_overlap_for_content, bool):
            raise ValueError("scope and mask gates must be bool")
        object.__setattr__(self, "version", _text("version", self.version))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "minimum_views_per_step": self.minimum_views_per_step,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "minimum_view_coverage": self.minimum_view_coverage,
            "minimum_positive_persistence": self.minimum_positive_persistence,
            "maximum_view_dispersion": self.maximum_view_dispersion,
            "maximum_pairwise_disagreement": self.maximum_pairwise_disagreement,
            "minimum_mask_overlap": self.minimum_mask_overlap,
            "quality_power": self.quality_power,
            "require_content_scope": self.require_content_scope,
            "require_mask_overlap_for_content": self.require_mask_overlap_for_content,
        }

    @property
    def config_digest(self) -> str:
        return _digest(self.to_dict())

    @property
    def digest(self) -> str:
        return self.config_digest


@dataclass(frozen=True)
class LineageViewAudit:
    view_id: str
    view_order: int
    step_id: str
    region_id: str
    accepted: bool
    control_supported: bool
    delta_raw: Optional[float]
    control_contrast_raw: Optional[float]
    control_p_value_raw: Optional[float]
    weight_raw: float
    reasons: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "view_id": self.view_id,
            "view_order": self.view_order,
            "step_id": self.step_id,
            "region_id": self.region_id,
            "accepted": self.accepted,
            "control_supported": self.control_supported,
            "delta_raw": self.delta_raw,
            "control_contrast_raw": self.control_contrast_raw,
            "control_p_value_raw": self.control_p_value_raw,
            "weight_raw": self.weight_raw,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class LineageStepAudit:
    step_id: str
    sequence_index: int
    operation_type: str
    view_count: int
    accepted_view_count: int
    positive_view_count: int
    view_coverage_raw: float
    persistence_raw: float
    weighted_delta_raw: Optional[float]
    view_dispersion_raw: Optional[float]
    pairwise_disagreement_rate: Optional[float]
    mask_consistency_raw: Optional[float]
    first_support_view_order: Optional[int]
    ordered_position_ok: bool
    route: str
    reasons: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "sequence_index": self.sequence_index,
            "operation_type": self.operation_type,
            "view_count": self.view_count,
            "accepted_view_count": self.accepted_view_count,
            "positive_view_count": self.positive_view_count,
            "view_coverage_raw": self.view_coverage_raw,
            "persistence_raw": self.persistence_raw,
            "weighted_delta_raw": self.weighted_delta_raw,
            "view_dispersion_raw": self.view_dispersion_raw,
            "pairwise_disagreement_rate": self.pairwise_disagreement_rate,
            "mask_consistency_raw": self.mask_consistency_raw,
            "first_support_view_order": self.first_support_view_order,
            "ordered_position_ok": self.ordered_position_ok,
            "route": self.route,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class LineageViewControlResult:
    route: str
    abstained: bool
    reason: str
    operation_scope: str
    asset_id: str
    pair_id: str
    transform_family: str
    canonical_frame_digest: str
    manifest_digest: str
    binding_digest: str
    trace_digest: str
    detector_version: str
    score_schema: str
    step_count: int
    view_count: int
    accepted_view_count: int
    supported_step_count: int
    view_coverage_raw: float
    persistence_raw: float
    ordered_consistency_raw: float
    trajectory_dispersion_raw: Optional[float]
    step_audit: Tuple[LineageStepAudit, ...]
    view_audit: Tuple[LineageViewAudit, ...]
    config_digest: str
    evidence_digest: str
    control_digest: str
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.route not in {ROUTE_CONSISTENT, ROUTE_INCONSISTENT, ROUTE_INSUFFICIENT}:
            raise ValueError("invalid lineage view route")
        if self.route == ROUTE_CONSISTENT and self.abstained:
            raise ValueError("consistent route cannot abstain")
        if self.route != ROUTE_CONSISTENT and not self.abstained:
            raise ValueError("conservative routes must abstain")
        if not isinstance(self.abstained, bool):
            raise ValueError("abstained must be bool")
        _text("reason", self.reason)
        _text("operation_scope", self.operation_scope)
        for name in ("asset_id", "pair_id", "transform_family", "detector_version", "score_schema"):
            _text(name, getattr(self, name))
        for name in ("canonical_frame_digest", "manifest_digest", "binding_digest", "trace_digest", "config_digest", "evidence_digest", "control_digest"):
            _sha256(name, getattr(self, name))
        for name in ("step_count", "view_count", "accepted_view_count", "supported_step_count"):
            _positive_int(name, getattr(self, name), allow_zero=True)
        if self.accepted_view_count > self.view_count or self.supported_step_count > self.step_count:
            raise ValueError("accepted counts cannot exceed totals")
        for name in ("view_coverage_raw", "persistence_raw", "ordered_consistency_raw"):
            object.__setattr__(self, name, _unit(name, getattr(self, name)))
        if self.trajectory_dispersion_raw is not None:
            object.__setattr__(self, "trajectory_dispersion_raw", _finite("trajectory_dispersion_raw", self.trajectory_dispersion_raw, lower=0.0, upper=2.0))

    @property
    def status(self) -> str:
        return self.route

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "result_schema": RESULT_SCHEMA,
            "route": self.route,
            "status": self.route,
            "abstained": self.abstained,
            "reason": self.reason,
            "operation_scope": self.operation_scope,
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "transform_family": self.transform_family,
            "canonical_frame_digest": self.canonical_frame_digest,
            "manifest_digest": self.manifest_digest,
            "binding_digest": self.binding_digest,
            "trace_digest": self.trace_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "step_count": self.step_count,
            "view_count": self.view_count,
            "accepted_view_count": self.accepted_view_count,
            "supported_step_count": self.supported_step_count,
            "view_coverage_raw": self.view_coverage_raw,
            "persistence_raw": self.persistence_raw,
            "ordered_consistency_raw": self.ordered_consistency_raw,
            "trajectory_dispersion_raw": self.trajectory_dispersion_raw,
            "step_audit": [item.to_dict() for item in self.step_audit],
            "view_audit": [item.to_dict() for item in self.view_audit],
            "config_digest": self.config_digest,
            "evidence_digest": self.evidence_digest,
            "control_digest": self.control_digest,
        }


def _empty(trace: EditLineageTrace, observations: Sequence[LineageViewControlObservation], *, config: LineageViewControlConfig, reason: str, operation_scope: Optional[str] = None) -> LineageViewControlResult:
    control_digest = _digest(sorted((item.control_digest for item in observations if item.control_digest is not None)))
    evidence_digest = _digest({"version": VERSION, "binding_digest": trace.binding_digest, "observations": [item.to_dict() for item in observations]})
    return LineageViewControlResult(
        route=ROUTE_INSUFFICIENT,
        abstained=True,
        reason=reason,
        operation_scope=operation_scope or "mixed",
        asset_id=trace.asset_id,
        pair_id=trace.pair_id or "unbound_pair",
        transform_family=trace.transform_family or "unbound_transform",
        canonical_frame_digest=trace.canonical_frame_digest or "0" * 64,
        manifest_digest=trace.manifest_digest or "0" * 64,
        binding_digest=trace.binding_digest or "0" * 64,
        trace_digest=trace.trace_digest,
        detector_version=trace.detector_version,
        score_schema=trace.score_schema,
        step_count=len(trace.steps),
        view_count=len({item.view_id for item in observations}),
        accepted_view_count=0,
        supported_step_count=0,
        view_coverage_raw=0.0,
        persistence_raw=0.0,
        ordered_consistency_raw=0.0,
        trajectory_dispersion_raw=None,
        step_audit=(),
        view_audit=(),
        config_digest=config.config_digest,
        evidence_digest=evidence_digest,
        control_digest=control_digest,
    )


def evaluate_lineage_view_control(
    trace: EditLineageTrace,
    observations: Sequence[LineageViewControlObservation],
    *,
    config: Optional[LineageViewControlConfig] = None,
) -> LineageViewControlResult:
    """Audit ordered, control-backed regional evidence across canonical views."""

    if not isinstance(trace, EditLineageTrace):
        raise ValueError("trace must be EditLineageTrace")
    cfg = config or LineageViewControlConfig()
    items = tuple(observations)
    if any(not isinstance(item, LineageViewControlObservation) for item in items):
        raise ValueError("observations must contain LineageViewControlObservation values")
    if not trace.steps:
        return _empty(trace, items, config=cfg, reason="no_edit_steps")
    step_operations = {step.operation_type for step in trace.steps}
    if step_operations and step_operations.issubset(CONTENT_OPERATIONS):
        operation_scope = OPERATION_SCOPE_CONTENT
    elif step_operations and step_operations.issubset(PROPAGATION_OPERATIONS):
        operation_scope = OPERATION_SCOPE_PROPAGATION
    else:
        operation_scope = OPERATION_SCOPE_MIXED
    if not trace.binding_context_complete:
        return _empty(trace, items, config=cfg, reason="binding_context_missing", operation_scope=operation_scope)
    if cfg.require_content_scope and operation_scope != OPERATION_SCOPE_CONTENT:
        reason = (
            "ordinary_propagation_scope"
            if operation_scope == OPERATION_SCOPE_PROPAGATION
            else "mixed_operation_scope"
        )
        return _empty(trace, items, config=cfg, reason=reason, operation_scope=operation_scope)
    if not items:
        return _empty(trace, items, config=cfg, reason="no_view_observations", operation_scope=operation_scope)

    by_step = {step.step_id: step for step in trace.steps}
    expected_binding = {
        "trace_digest": trace.trace_digest,
        "asset_id": trace.asset_id,
        "pair_id": trace.pair_id,
        "transform_family": trace.transform_family,
        "canonical_frame_digest": trace.canonical_frame_digest,
        "manifest_digest": trace.manifest_digest,
        "binding_digest": trace.binding_digest,
        "detector_version": trace.detector_version,
        "score_schema": trace.score_schema,
    }
    keys = [(item.view_id, item.step_id, item.region_id) for item in items]
    if len(set(keys)) != len(keys):
        return _empty(trace, items, config=cfg, reason="duplicate_view_step_region", operation_scope=operation_scope)
    view_orders: Dict[str, int] = {}
    for item in items:
        if any(getattr(item, name) != value for name, value in expected_binding.items()):
            return _empty(trace, items, config=cfg, reason="binding_mismatch", operation_scope=operation_scope)
        step = by_step.get(item.step_id)
        if step is None:
            return _empty(trace, items, config=cfg, reason="unknown_step", operation_scope=operation_scope)
        if item.operation_type != step.operation_type:
            return _empty(trace, items, config=cfg, reason="operation_type_mismatch", operation_scope=operation_scope)
        allowed_regions = set(step.input_region_ids) | set(step.output_region_ids)
        if item.region_id not in allowed_regions:
            return _empty(trace, items, config=cfg, reason="region_not_in_trace", operation_scope=operation_scope)
        prior = view_orders.setdefault(item.view_id, item.view_order)
        if prior != item.view_order:
            return _empty(trace, items, config=cfg, reason="view_order_mismatch", operation_scope=operation_scope)
        if item.control_route == CONTROL_INSUFFICIENT:
            return _empty(trace, items, config=cfg, reason="control_summary_insufficient", operation_scope=operation_scope)
        if item.control_contrast_raw is None or item.control_p_value_raw is None or item.control_digest is None:
            return _empty(trace, items, config=cfg, reason="control_summary_missing", operation_scope=operation_scope)
        if item.quality_score < cfg.minimum_quality or item.source_match_score < cfg.minimum_source_match:
            return _empty(trace, items, config=cfg, reason="view_quality_below_threshold", operation_scope=operation_scope)

    if len(view_orders) < cfg.minimum_views_per_step:
        return _empty(trace, items, config=cfg, reason="view_support_below_threshold", operation_scope=operation_scope)

    sorted_items = sorted(items, key=lambda item: (item.step_id, item.view_order, item.region_id))
    audits = []
    for item in sorted_items:
        weight = item.quality_score ** cfg.quality_power * item.source_match_score
        # MPCF has already made the matched-control route decision.  This
        # adapter consumes that route as raw evidence and never re-fits its
        # placebo statistic here.
        supported = item.control_route == CONTROL_CANDIDATE
        reason = () if supported else ("control_consistent",)
        audits.append(LineageViewAudit(item.view_id, item.view_order, item.step_id, item.region_id, True, supported, item.delta_raw, item.control_contrast_raw, item.control_p_value_raw, weight, reason))

    step_audits = []
    step_first_order: Dict[str, Optional[int]] = {}
    total_positive_weight = 0.0
    total_weight = 0.0
    all_view_values = []
    for step in trace.steps:
        step_items = [item for item in items if item.step_id == step.step_id]
        by_view: Dict[str, list[LineageViewControlObservation]] = {}
        for item in step_items:
            by_view.setdefault(item.view_id, []).append(item)
        view_count = len(by_view)
        if view_count < cfg.minimum_views_per_step:
            return _empty(trace, items, config=cfg, reason="step_view_support_below_threshold", operation_scope=operation_scope)
        view_values = []
        positive_views = []
        accepted_views = 0
        mask_values = []
        for view_id, view_items in sorted(by_view.items(), key=lambda pair: (pair[1][0].view_order, pair[0])):
            weights = [item.quality_score ** cfg.quality_power * item.source_match_score for item in view_items]
            weight_sum = sum(weights)
            view_delta = sum(weight * item.delta_raw for weight, item in zip(weights, view_items)) / weight_sum
            view_values.append((view_items[0].view_order, view_delta))
            accepted_views += 1
            positive_weight = sum(weight for weight, item in zip(weights, view_items) if item.control_route == CONTROL_CANDIDATE)
            if positive_weight / weight_sum >= cfg.minimum_positive_persistence:
                positive_views.append(view_items[0].view_order)
            for item in view_items:
                if item.mask_overlap_raw is not None:
                    mask_values.append((weights[view_items.index(item)], item.mask_overlap_raw))
        view_coverage = accepted_views / view_count if view_count else 0.0
        persistence = len(positive_views) / view_count if view_count else 0.0
        step_first_order[step.step_id] = min(positive_views) if positive_views else None
        if view_values:
            mean_delta = sum(value for _, value in view_values) / len(view_values)
            # Use a median-centred absolute dispersion so one quiet view does
            # not make an otherwise repeated signal fail the trajectory gate.
            # The weighted mean remains the reported raw delta; this robust
            # spread is only a cross-view consistency diagnostic.
            ordered_values = sorted(value for _, value in view_values)
            centre = ordered_values[len(ordered_values) // 2]
            dispersion = sum(abs(value - centre) for _, value in view_values) / len(view_values)
            all_view_values.extend(value for _, value in view_values)
        else:
            mean_delta = None
            dispersion = None
        disagreements = 0
        comparisons = 0
        for index, (_, left) in enumerate(view_values):
            for _, right in view_values[index + 1 :]:
                comparisons += 1
                if (left >= 0) != (right >= 0):
                    disagreements += 1
        disagreement_rate = disagreements / comparisons if comparisons else 0.0
        if mask_values:
            mask_weight = sum(weight for weight, _ in mask_values)
            mask_consistency = sum(weight * value for weight, value in mask_values) / mask_weight
        else:
            mask_consistency = None
        reasons = []
        if view_coverage < cfg.minimum_view_coverage:
            reasons.append("view_coverage_below_threshold")
        if persistence < cfg.minimum_positive_persistence:
            reasons.append("positive_persistence_below_threshold")
        if dispersion is not None and dispersion > cfg.maximum_view_dispersion:
            reasons.append("view_dispersion_above_threshold")
        if disagreement_rate > cfg.maximum_pairwise_disagreement:
            reasons.append("pairwise_disagreement_above_threshold")
        if step.operation_type in CONTENT_OPERATIONS and cfg.require_mask_overlap_for_content:
            if any(item.mask_overlap_raw is None for item in step_items):
                reasons.append("content_mask_overlap_missing")
            elif mask_consistency is not None and mask_consistency < cfg.minimum_mask_overlap:
                reasons.append("mask_overlap_below_threshold")
        total_positive_weight += sum(item.quality_score ** cfg.quality_power * item.source_match_score for item in step_items if item.control_route == CONTROL_CANDIDATE)
        total_weight += sum(item.quality_score ** cfg.quality_power * item.source_match_score for item in step_items)
        step_audits.append(LineageStepAudit(step.step_id, step.sequence_index, step.operation_type, view_count, accepted_views, len(positive_views), view_coverage, persistence, mean_delta, dispersion, disagreement_rate, mask_consistency, step_first_order[step.step_id], True, ROUTE_CONSISTENT if not reasons else ROUTE_INCONSISTENT, tuple(reasons)))

    first_orders = [step_first_order[step.step_id] for step in trace.steps]
    ordered_ok = all(value is not None for value in first_orders)
    if ordered_ok:
        ordered_ok = all(first_orders[index] <= first_orders[index + 1] for index in range(len(first_orders) - 1))
    ordered_consistency = 1.0 if ordered_ok else 0.0
    failed_steps = [audit for audit in step_audits if audit.route != ROUTE_CONSISTENT]
    persistence = total_positive_weight / total_weight if total_weight else 0.0
    dispersions = [audit.view_dispersion_raw for audit in step_audits if audit.view_dispersion_raw is not None]
    trajectory_dispersion = sum(dispersions) / len(dispersions) if dispersions else None
    if failed_steps or not ordered_ok:
        route = ROUTE_INCONSISTENT
        reason = "trajectory_inconsistent" if ordered_ok else "step_onset_order_inconsistent"
    else:
        route = ROUTE_CONSISTENT
        reason = "controlled_lineage_consistent"
    evidence_digest = _digest({"version": VERSION, "binding_digest": trace.binding_digest, "views": [item.to_dict() for item in sorted_items]})
    control_digest = _digest(sorted(item.control_digest for item in items if item.control_digest is not None))
    return LineageViewControlResult(route, route != ROUTE_CONSISTENT, reason, operation_scope, trace.asset_id, trace.pair_id or "unbound_pair", trace.transform_family or "unbound_transform", trace.canonical_frame_digest or "0" * 64, trace.manifest_digest or "0" * 64, trace.binding_digest or "0" * 64, trace.trace_digest, trace.detector_version, trace.score_schema, len(trace.steps), len(view_orders), len(view_orders), sum(a.route == ROUTE_CONSISTENT for a in step_audits), len(view_orders) / len(view_orders), persistence, ordered_consistency, trajectory_dispersion, tuple(step_audits), tuple(audits), cfg.config_digest, evidence_digest, control_digest)


def fuse_lineage_view_control(*args: Any, **kwargs: Any) -> LineageViewControlResult:
    return evaluate_lineage_view_control(*args, **kwargs)


__all__ = [
    "VERSION", "RESULT_SCHEMA", "ROUTE_CONSISTENT", "ROUTE_INCONSISTENT", "ROUTE_INSUFFICIENT",
    "CONTROL_CANDIDATE", "CONTROL_CONSISTENT", "CONTROL_INSUFFICIENT",
    "LineageViewControlObservation", "LineageViewControlConfig", "LineageViewAudit", "LineageStepAudit", "LineageViewControlResult",
    "evaluate_lineage_view_control", "fuse_lineage_view_control",
]
