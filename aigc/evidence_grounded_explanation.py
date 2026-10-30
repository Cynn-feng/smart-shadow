"""Evidence-grounded explanation and counterfactual faithfulness audit.

This module treats an explanation as a versioned evidence sidecar.  It does
not generate free-form explanations and it does not classify an image.  A
caller must provide already-bound regional evidence plus scores obtained by
actually applying the same intervention operator to an observed query and a
matched ordinary-propagation null.  The observed-minus-null intervention
contrast is the useful project-specific quantity; a mask-out score alone is
not an innovation claim.
The result is a conservative raw-evidence route:

* grounded_consistent: both counterfactual checks support the proposed region;
* maskout_inconsistent: masking the proposed region does not reduce the raw score;
* inconclusive: the mask-out check passes but the region-swap check is missing
  or does not provide enough support;
* insufficient: provenance, quality, operation scope, or execution evidence is
  missing.

All thresholds are engineering gates.  They are not calibrated probabilities,
causal guarantees, provenance claims, or legal findings.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Dict, Mapping, Optional, Tuple


VERSION = "explanation-audit-v1"
SCHEMA = "explanation-audit-result-v1"

ROUTE_GROUNDED_CONSISTENT = "grounded_consistent"
ROUTE_MASKOUT_INCONSISTENT = "maskout_inconsistent"
ROUTE_INCONCLUSIVE = "inconclusive"
ROUTE_INSUFFICIENT = "insufficient"

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


def _hex(name: str, value: str) -> str:
    value = _text(name, value).lower()
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
    return value


def _finite(name: str, value: float, *, lower: float = -1.0, upper: float = 1.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or value < lower or value > upper:
        raise ValueError(f"{name} must be finite and between {lower} and {upper}")
    return value


def _unit(name: str, value: float) -> float:
    return _finite(name, value, lower=0.0, upper=1.0)


def _effect(name: str, value: float) -> float:
    return _finite(name, value, lower=-2.0, upper=2.0)


def _regions(value: Tuple[str, ...]) -> Tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError("evidence_region_ids must be a tuple of strings")
    result = tuple(_text("evidence_region_ids", item) for item in value)
    if not result:
        raise ValueError("evidence_region_ids must not be empty")
    if len(set(result)) != len(result):
        raise ValueError("evidence_region_ids must not contain duplicates")
    return result


def _review_ref(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return _hex("human_review_ref", value)


def _category(name: str, value: str) -> str:
    value = _text(name, value).lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.:-]*", value):
        raise ValueError(f"{name} must be a taxonomy category id")
    return value


def _safe_metadata(value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("metadata must be a mapping")

    def normalise(item: Any) -> Any:
        if isinstance(item, Mapping):
            result: Dict[str, Any] = {}
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("metadata keys must be strings")
                lowered = key.lower()
                if (
                    "probability" in lowered
                    or "confidence" in lowered
                    or "aigc" in lowered
                    or lowered in {"ai_prob", "ai_status", "ai_label"}
                ):
                    raise ValueError("metadata cannot contain uncalibrated confidence/AIGC fields")
                result[key] = normalise(child)
            return dict(sorted(result.items()))
        if isinstance(item, (list, tuple)):
            return [normalise(child) for child in item]
        if item is None or isinstance(item, (bool, str, int)):
            return item
        if isinstance(item, float) and math.isfinite(item):
            return float(item)
        raise ValueError("metadata contains a non-JSON or non-finite value")

    return normalise(value)


@dataclass(frozen=True)
class ExplanationAuditConfig:
    """Fixed raw-score gates for the explanation audit."""

    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    minimum_maskout_drop_raw: float = 0.10
    minimum_matched_contrast_raw: float = 0.05
    minimum_region_swap_drop_raw: float = 0.10
    minimum_matched_swap_contrast_raw: float = 0.05
    maximum_abs_null_effect_raw: float = 0.40

    def __post_init__(self) -> None:
        _unit("minimum_quality", self.minimum_quality)
        _unit("minimum_source_match", self.minimum_source_match)
        _unit("minimum_maskout_drop_raw", self.minimum_maskout_drop_raw)
        _unit("minimum_matched_contrast_raw", self.minimum_matched_contrast_raw)
        _unit("minimum_region_swap_drop_raw", self.minimum_region_swap_drop_raw)
        _unit("minimum_matched_swap_contrast_raw", self.minimum_matched_swap_contrast_raw)
        _unit("maximum_abs_null_effect_raw", self.maximum_abs_null_effect_raw)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "minimum_maskout_drop_raw": self.minimum_maskout_drop_raw,
            "minimum_matched_contrast_raw": self.minimum_matched_contrast_raw,
            "minimum_region_swap_drop_raw": self.minimum_region_swap_drop_raw,
            "minimum_matched_swap_contrast_raw": self.minimum_matched_swap_contrast_raw,
            "maximum_abs_null_effect_raw": self.maximum_abs_null_effect_raw,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class ExplanationAuditObservation:
    """One already-executed, source-bound explanation audit input."""

    asset_id: str
    pair_id: str
    transform_family: str
    transform_spec_digest: str
    reference_digest: str
    observed_digest: str
    null_digest: str
    manifest_digest: str
    canonical_frame_digest: str
    detector_version: str
    score_schema: str
    operation_scope: str
    evidence_region_ids: Tuple[str, ...]
    taxonomy_version: str
    artifact_category: str
    proposal_mask_digest: str
    intervention_operator_digest: str
    null_intervention_operator_digest: str
    evidence_digest: str
    crop_policy_digest: str
    control_pair_id: str
    null_profile_digest: str
    intervention_execution_digest: str
    quality_score: float
    source_match_raw: float
    null_quality_score: float
    null_source_match_raw: float
    score_before_raw: float
    score_after_maskout_raw: float
    score_after_region_swap_raw: Optional[float]
    null_score_before_raw: float
    null_score_after_maskout_raw: float
    null_score_after_region_swap_raw: Optional[float]
    observed_mask_out_executed: bool
    null_mask_out_executed: bool
    observed_region_swap_executed: bool
    null_region_swap_executed: bool
    human_review_ref: Optional[str] = None
    metadata: Optional[Mapping[str, Any]] = None
    score_direction: str = "higher_is_more_suspicious"

    def __post_init__(self) -> None:
        for name in (
            "asset_id",
            "pair_id",
            "transform_family",
            "detector_version",
            "score_schema",
            "taxonomy_version",
            "artifact_category",
        ):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        for name in (
            "manifest_digest",
            "canonical_frame_digest",
            "transform_spec_digest",
            "reference_digest",
            "observed_digest",
            "null_digest",
            "proposal_mask_digest",
            "intervention_operator_digest",
            "null_intervention_operator_digest",
            "evidence_digest",
            "crop_policy_digest",
            "null_profile_digest",
            "intervention_execution_digest",
        ):
            object.__setattr__(self, name, _hex(name, getattr(self, name)))
        object.__setattr__(self, "control_pair_id", _text("control_pair_id", self.control_pair_id))
        if self.operation_scope not in {
            OPERATION_SCOPE_CONTENT,
            OPERATION_SCOPE_PROPAGATION,
            OPERATION_SCOPE_MIXED,
        }:
            raise ValueError("unsupported operation_scope")
        object.__setattr__(self, "evidence_region_ids", _regions(self.evidence_region_ids))
        _unit("quality_score", self.quality_score)
        _unit("source_match_raw", self.source_match_raw)
        _unit("null_quality_score", self.null_quality_score)
        _unit("null_source_match_raw", self.null_source_match_raw)
        _finite("score_before_raw", self.score_before_raw)
        _finite("score_after_maskout_raw", self.score_after_maskout_raw)
        if self.score_after_region_swap_raw is not None:
            _finite("score_after_region_swap_raw", self.score_after_region_swap_raw)
        _finite("null_score_before_raw", self.null_score_before_raw)
        _finite("null_score_after_maskout_raw", self.null_score_after_maskout_raw)
        if self.null_score_after_region_swap_raw is not None:
            _finite("null_score_after_region_swap_raw", self.null_score_after_region_swap_raw)
        for name in (
            "observed_mask_out_executed",
            "null_mask_out_executed",
            "observed_region_swap_executed",
            "null_region_swap_executed",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be bool")
        if self.observed_region_swap_executed and self.score_after_region_swap_raw is None:
            raise ValueError("observed_region_swap_executed requires score_after_region_swap_raw")
        if self.null_region_swap_executed and self.null_score_after_region_swap_raw is None:
            raise ValueError("null_region_swap_executed requires null_score_after_region_swap_raw")
        if not self.observed_region_swap_executed and self.score_after_region_swap_raw is not None:
            raise ValueError("observed region swap scores require observed_region_swap_executed")
        if not self.null_region_swap_executed and self.null_score_after_region_swap_raw is not None:
            raise ValueError("null region swap scores require null_region_swap_executed")
        object.__setattr__(self, "human_review_ref", _review_ref(self.human_review_ref))
        object.__setattr__(self, "metadata", _safe_metadata(self.metadata))
        if self.score_direction != "higher_is_more_suspicious":
            raise ValueError("unsupported score_direction")

    @property
    def binding_digest(self) -> str:
        return _digest(
            {
                "version": VERSION,
                "asset_id": self.asset_id,
                "pair_id": self.pair_id,
                "transform_family": self.transform_family,
                "manifest_digest": self.manifest_digest,
                "canonical_frame_digest": self.canonical_frame_digest,
                "transform_spec_digest": self.transform_spec_digest,
                "reference_digest": self.reference_digest,
                "observed_digest": self.observed_digest,
                "null_digest": self.null_digest,
                "detector_version": self.detector_version,
                "score_schema": self.score_schema,
                "score_direction": self.score_direction,
                "operation_scope": self.operation_scope,
                "evidence_region_ids": list(self.evidence_region_ids),
                "taxonomy_version": self.taxonomy_version,
                "proposal_mask_digest": self.proposal_mask_digest,
                "intervention_operator_digest": self.intervention_operator_digest,
                "null_intervention_operator_digest": self.null_intervention_operator_digest,
                "evidence_digest": self.evidence_digest,
                "crop_policy_digest": self.crop_policy_digest,
                "control_pair_id": self.control_pair_id,
                "null_profile_digest": self.null_profile_digest,
                "intervention_execution_digest": self.intervention_execution_digest,
                "quality_score": self.quality_score,
                "source_match_raw": self.source_match_raw,
                "null_quality_score": self.null_quality_score,
                "null_source_match_raw": self.null_source_match_raw,
                "observed_mask_out_executed": self.observed_mask_out_executed,
                "null_mask_out_executed": self.null_mask_out_executed,
                "observed_region_swap_executed": self.observed_region_swap_executed,
                "null_region_swap_executed": self.null_region_swap_executed,
            }
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "transform_family": self.transform_family,
            "manifest_digest": self.manifest_digest,
            "canonical_frame_digest": self.canonical_frame_digest,
            "transform_spec_digest": self.transform_spec_digest,
            "reference_digest": self.reference_digest,
            "observed_digest": self.observed_digest,
            "null_digest": self.null_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "score_direction": self.score_direction,
            "operation_scope": self.operation_scope,
            "evidence_region_ids": list(self.evidence_region_ids),
            "taxonomy_version": self.taxonomy_version,
            "artifact_category": self.artifact_category,
            "proposal_mask_digest": self.proposal_mask_digest,
            "intervention_operator_digest": self.intervention_operator_digest,
            "null_intervention_operator_digest": self.null_intervention_operator_digest,
            "evidence_digest": self.evidence_digest,
            "crop_policy_digest": self.crop_policy_digest,
            "control_pair_id": self.control_pair_id,
            "null_profile_digest": self.null_profile_digest,
            "intervention_execution_digest": self.intervention_execution_digest,
            "quality_score": self.quality_score,
            "source_match_raw": self.source_match_raw,
            "null_quality_score": self.null_quality_score,
            "null_source_match_raw": self.null_source_match_raw,
            "score_before_raw": self.score_before_raw,
            "score_after_maskout_raw": self.score_after_maskout_raw,
            "score_after_region_swap_raw": self.score_after_region_swap_raw,
            "null_score_before_raw": self.null_score_before_raw,
            "null_score_after_maskout_raw": self.null_score_after_maskout_raw,
            "null_score_after_region_swap_raw": self.null_score_after_region_swap_raw,
            "observed_mask_out_executed": self.observed_mask_out_executed,
            "null_mask_out_executed": self.null_mask_out_executed,
            "observed_region_swap_executed": self.observed_region_swap_executed,
            "null_region_swap_executed": self.null_region_swap_executed,
            "human_review_ref": self.human_review_ref,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ExplanationAuditResult:
    """Replayable raw explanation-audit output."""

    route: str
    abstained: bool
    reason: str
    faithfulness_delta_raw: Optional[float]
    null_effect_raw: Optional[float]
    contrast_faithfulness_raw: Optional[float]
    region_swap_delta_raw: Optional[float]
    null_region_swap_delta_raw: Optional[float]
    swap_contrast_raw: Optional[float]
    evidence_region_ids: Tuple[str, ...]
    taxonomy_version: str
    artifact_category: str
    pair_id: str
    operation_scope: str
    binding_digest: str
    config_digest: str
    explanation_digest: str
    human_review_ref: Optional[str]
    version: str = VERSION
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.route not in {
            ROUTE_GROUNDED_CONSISTENT,
            ROUTE_MASKOUT_INCONSISTENT,
            ROUTE_INCONCLUSIVE,
            ROUTE_INSUFFICIENT,
        }:
            raise ValueError("unsupported explanation audit route")
        if self.route == ROUTE_GROUNDED_CONSISTENT and self.abstained:
            raise ValueError("grounded_consistent cannot be abstained")
        if self.route != ROUTE_GROUNDED_CONSISTENT and not self.abstained:
            raise ValueError("conservative routes must be abstained")
        object.__setattr__(self, "reason", _text("reason", self.reason))
        object.__setattr__(self, "evidence_region_ids", _regions(self.evidence_region_ids))
        object.__setattr__(self, "taxonomy_version", _text("taxonomy_version", self.taxonomy_version))
        object.__setattr__(self, "artifact_category", _category("artifact_category", self.artifact_category))
        object.__setattr__(self, "pair_id", _text("pair_id", self.pair_id))
        object.__setattr__(self, "binding_digest", _hex("binding_digest", self.binding_digest))
        object.__setattr__(self, "config_digest", _hex("config_digest", self.config_digest))
        object.__setattr__(self, "explanation_digest", _hex("explanation_digest", self.explanation_digest))
        if self.faithfulness_delta_raw is not None:
            _effect("faithfulness_delta_raw", self.faithfulness_delta_raw)
        if self.region_swap_delta_raw is not None:
            _effect("region_swap_delta_raw", self.region_swap_delta_raw)
        if self.null_effect_raw is not None:
            _effect("null_effect_raw", self.null_effect_raw)
        if self.contrast_faithfulness_raw is not None:
            _effect("contrast_faithfulness_raw", self.contrast_faithfulness_raw)
        if self.null_region_swap_delta_raw is not None:
            _effect("null_region_swap_delta_raw", self.null_region_swap_delta_raw)
        if self.swap_contrast_raw is not None:
            _effect("swap_contrast_raw", self.swap_contrast_raw)
        object.__setattr__(self, "human_review_ref", _review_ref(self.human_review_ref))
        if self.operation_scope not in {
            OPERATION_SCOPE_CONTENT,
            OPERATION_SCOPE_PROPAGATION,
            OPERATION_SCOPE_MIXED,
        }:
            raise ValueError("unsupported operation_scope")
        if self.schema != SCHEMA:
            raise ValueError("unsupported explanation audit schema")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "schema": self.schema,
            "route": self.route,
            "abstained": self.abstained,
            "reason": self.reason,
            "faithfulness_delta_raw": self.faithfulness_delta_raw,
            "null_effect_raw": self.null_effect_raw,
            "contrast_faithfulness_raw": self.contrast_faithfulness_raw,
            "region_swap_delta_raw": self.region_swap_delta_raw,
            "null_region_swap_delta_raw": self.null_region_swap_delta_raw,
            "swap_contrast_raw": self.swap_contrast_raw,
            "evidence_region_ids": list(self.evidence_region_ids),
            "taxonomy_version": self.taxonomy_version,
            "artifact_category": self.artifact_category,
            "pair_id": self.pair_id,
            "operation_scope": self.operation_scope,
            "binding_digest": self.binding_digest,
            "config_digest": self.config_digest,
            "explanation_digest": self.explanation_digest,
            "human_review_ref": self.human_review_ref,
        }


def _result(
    observation: ExplanationAuditObservation,
    config: ExplanationAuditConfig,
    *,
    route: str,
    reason: str,
    faithfulness_delta_raw: Optional[float],
    null_effect_raw: Optional[float],
    contrast_faithfulness_raw: Optional[float],
    region_swap_delta_raw: Optional[float],
    null_region_swap_delta_raw: Optional[float],
    swap_contrast_raw: Optional[float] = None,
) -> ExplanationAuditResult:
    payload = {
        "version": VERSION,
        "schema": SCHEMA,
        "route": route,
        "reason": reason,
        "binding_digest": observation.binding_digest,
        "config_digest": config.digest,
        "faithfulness_delta_raw": faithfulness_delta_raw,
        "null_effect_raw": null_effect_raw,
        "contrast_faithfulness_raw": contrast_faithfulness_raw,
        "region_swap_delta_raw": region_swap_delta_raw,
        "null_region_swap_delta_raw": null_region_swap_delta_raw,
        "swap_contrast_raw": swap_contrast_raw,
        "evidence_region_ids": list(observation.evidence_region_ids),
        "taxonomy_version": observation.taxonomy_version,
        "artifact_category": observation.artifact_category,
        "pair_id": observation.pair_id,
        "operation_scope": observation.operation_scope,
        "observation": observation.to_dict(),
    }
    return ExplanationAuditResult(
        route=route,
        abstained=route != ROUTE_GROUNDED_CONSISTENT,
        reason=reason,
        faithfulness_delta_raw=faithfulness_delta_raw,
        null_effect_raw=null_effect_raw,
        contrast_faithfulness_raw=contrast_faithfulness_raw,
        region_swap_delta_raw=region_swap_delta_raw,
        null_region_swap_delta_raw=null_region_swap_delta_raw,
        swap_contrast_raw=swap_contrast_raw,
        evidence_region_ids=observation.evidence_region_ids,
        taxonomy_version=observation.taxonomy_version,
        artifact_category=observation.artifact_category,
        pair_id=observation.pair_id,
        operation_scope=observation.operation_scope,
        binding_digest=observation.binding_digest,
        config_digest=config.digest,
        explanation_digest=_digest(payload),
        human_review_ref=observation.human_review_ref,
    )


def evaluate_explanation_audit(
    observation: ExplanationAuditObservation,
    *,
    config: Optional[ExplanationAuditConfig] = None,
) -> ExplanationAuditResult:
    """Evaluate one bound explanation sidecar with fail-closed routes."""

    cfg = config or ExplanationAuditConfig()
    if observation.intervention_operator_digest != observation.null_intervention_operator_digest:
        return _result(
            observation,
            cfg,
            route=ROUTE_INSUFFICIENT,
            reason="intervention_operator_mismatch",
            faithfulness_delta_raw=None,
            null_effect_raw=None,
            contrast_faithfulness_raw=None,
            region_swap_delta_raw=None,
            null_region_swap_delta_raw=None,
        )
    if observation.null_quality_score < cfg.minimum_quality:
        return _result(
            observation,
            cfg,
            route=ROUTE_INSUFFICIENT,
            reason="null_quality_below_threshold",
            faithfulness_delta_raw=None,
            null_effect_raw=None,
            contrast_faithfulness_raw=None,
            region_swap_delta_raw=None,
            null_region_swap_delta_raw=None,
        )
    if observation.null_source_match_raw < cfg.minimum_source_match:
        return _result(
            observation,
            cfg,
            route=ROUTE_INSUFFICIENT,
            reason="null_source_match_below_threshold",
            faithfulness_delta_raw=None,
            null_effect_raw=None,
            contrast_faithfulness_raw=None,
            region_swap_delta_raw=None,
            null_region_swap_delta_raw=None,
        )
    if observation.artifact_category == "unknown":
        return _result(
            observation,
            cfg,
            route=ROUTE_INCONCLUSIVE,
            reason="unknown_artifact_category",
            faithfulness_delta_raw=None,
            null_effect_raw=None,
            contrast_faithfulness_raw=None,
            region_swap_delta_raw=None,
            null_region_swap_delta_raw=None,
        )
    if observation.operation_scope in {
        OPERATION_SCOPE_PROPAGATION,
        OPERATION_SCOPE_MIXED,
    }:
        return _result(
            observation,
            cfg,
            route=ROUTE_INSUFFICIENT,
            reason="ordinary_propagation_or_mixed_scope",
            faithfulness_delta_raw=None,
            null_effect_raw=None,
            contrast_faithfulness_raw=None,
            region_swap_delta_raw=None,
            null_region_swap_delta_raw=None,
        )
    if observation.quality_score < cfg.minimum_quality:
        return _result(
            observation,
            cfg,
            route=ROUTE_INSUFFICIENT,
            reason="quality_below_threshold",
            faithfulness_delta_raw=None,
            null_effect_raw=None,
            contrast_faithfulness_raw=None,
            region_swap_delta_raw=None,
            null_region_swap_delta_raw=None,
        )
    if observation.source_match_raw < cfg.minimum_source_match:
        return _result(
            observation,
            cfg,
            route=ROUTE_INSUFFICIENT,
            reason="source_match_below_threshold",
            faithfulness_delta_raw=None,
            null_effect_raw=None,
            contrast_faithfulness_raw=None,
            region_swap_delta_raw=None,
            null_region_swap_delta_raw=None,
        )
    if not observation.observed_mask_out_executed or not observation.null_mask_out_executed:
        return _result(
            observation,
            cfg,
            route=ROUTE_INSUFFICIENT,
            reason="matched_mask_out_not_executed",
            faithfulness_delta_raw=None,
            null_effect_raw=None,
            contrast_faithfulness_raw=None,
            region_swap_delta_raw=None,
            null_region_swap_delta_raw=None,
        )

    faithfulness_delta = observation.score_before_raw - observation.score_after_maskout_raw
    null_effect = observation.null_score_before_raw - observation.null_score_after_maskout_raw
    contrast = faithfulness_delta - null_effect
    if abs(null_effect) > cfg.maximum_abs_null_effect_raw:
        return _result(
            observation,
            cfg,
            route=ROUTE_INSUFFICIENT,
            reason="null_effect_unstable",
            faithfulness_delta_raw=faithfulness_delta,
            null_effect_raw=null_effect,
            contrast_faithfulness_raw=contrast,
            region_swap_delta_raw=None,
            null_region_swap_delta_raw=None,
        )
    if faithfulness_delta < cfg.minimum_maskout_drop_raw:
        return _result(
            observation,
            cfg,
            route=ROUTE_MASKOUT_INCONSISTENT,
            reason="maskout_drop_below_threshold",
            faithfulness_delta_raw=faithfulness_delta,
            null_effect_raw=null_effect,
            contrast_faithfulness_raw=contrast,
            region_swap_delta_raw=None,
            null_region_swap_delta_raw=None,
        )
    if contrast < cfg.minimum_matched_contrast_raw:
        return _result(
            observation,
            cfg,
            route=ROUTE_MASKOUT_INCONSISTENT,
            reason="matched_contrast_below_threshold",
            faithfulness_delta_raw=faithfulness_delta,
            null_effect_raw=null_effect,
            contrast_faithfulness_raw=contrast,
            region_swap_delta_raw=None,
            null_region_swap_delta_raw=None,
        )
    if (
        not observation.observed_region_swap_executed
        or not observation.null_region_swap_executed
        or observation.score_after_region_swap_raw is None
        or observation.null_score_after_region_swap_raw is None
    ):
        return _result(
            observation,
            cfg,
            route=ROUTE_INCONCLUSIVE,
            reason="matched_region_swap_missing",
            faithfulness_delta_raw=faithfulness_delta,
            null_effect_raw=null_effect,
            contrast_faithfulness_raw=contrast,
            region_swap_delta_raw=None,
            null_region_swap_delta_raw=None,
        )

    region_swap_delta = observation.score_before_raw - observation.score_after_region_swap_raw
    null_region_swap_delta = (
        observation.null_score_before_raw - observation.null_score_after_region_swap_raw
        if observation.null_score_after_region_swap_raw is not None
        else None
    )
    if null_region_swap_delta is None:
        return _result(
            observation,
            cfg,
            route=ROUTE_INCONCLUSIVE,
            reason="matched_region_swap_missing",
            faithfulness_delta_raw=faithfulness_delta,
            null_effect_raw=null_effect,
            contrast_faithfulness_raw=contrast,
            region_swap_delta_raw=region_swap_delta,
            null_region_swap_delta_raw=None,
        )
    if abs(null_region_swap_delta) > cfg.maximum_abs_null_effect_raw:
        return _result(
            observation,
            cfg,
            route=ROUTE_INSUFFICIENT,
            reason="null_region_swap_unstable",
            faithfulness_delta_raw=faithfulness_delta,
            null_effect_raw=null_effect,
            contrast_faithfulness_raw=contrast,
            region_swap_delta_raw=region_swap_delta,
            null_region_swap_delta_raw=null_region_swap_delta,
            swap_contrast_raw=None,
        )
    swap_contrast = region_swap_delta - null_region_swap_delta
    if region_swap_delta < cfg.minimum_region_swap_drop_raw:
        return _result(
            observation,
            cfg,
            route=ROUTE_INCONCLUSIVE,
            reason="region_swap_drop_below_threshold",
            faithfulness_delta_raw=faithfulness_delta,
            null_effect_raw=null_effect,
            contrast_faithfulness_raw=contrast,
            region_swap_delta_raw=region_swap_delta,
            null_region_swap_delta_raw=null_region_swap_delta,
            swap_contrast_raw=swap_contrast,
        )
    if swap_contrast < cfg.minimum_matched_swap_contrast_raw:
        return _result(
            observation,
            cfg,
            route=ROUTE_INCONCLUSIVE,
            reason="matched_swap_contrast_below_threshold",
            faithfulness_delta_raw=faithfulness_delta,
            null_effect_raw=null_effect,
            contrast_faithfulness_raw=contrast,
            region_swap_delta_raw=region_swap_delta,
            null_region_swap_delta_raw=null_region_swap_delta,
            swap_contrast_raw=swap_contrast,
        )
    return _result(
        observation,
        cfg,
        route=ROUTE_GROUNDED_CONSISTENT,
        reason="grounded_counterfactual_consistent",
        faithfulness_delta_raw=faithfulness_delta,
        null_effect_raw=null_effect,
        contrast_faithfulness_raw=contrast,
        region_swap_delta_raw=region_swap_delta,
        null_region_swap_delta_raw=null_region_swap_delta,
        swap_contrast_raw=swap_contrast,
    )
