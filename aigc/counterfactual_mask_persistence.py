"""Counterfactual mask-persistence audit for source-conditioned evidence.

This module checks whether a detector's *regional evidence mask* survives the
same canonical views when the factual query is replaced with ordinary
propagation, a decoy counterfactual, or a deliberately wrong reference.  It
is a segmentation/evidence sanity check, not a detector and not a probability
calibration layer.

The protocol deliberately keeps four kinds of observations separate:

``factual``
    The observed query paired with the registered source.
``ordinary_propagation``
    A same-label no-edit propagation null.
``decoy``
    A counterfactual whose edit is outside the proposed evidence region.
``wrong_reference``
    A query evaluated against a reference that is intentionally not the
    registered source.

The proposed factual region set is first frozen from the factual views.  A
control is considered a mask hallucination only when its predicted regions
overlap that same set.  This prevents a control's unrelated, low-level mask
from being silently interpreted as support for the source-conditioned claim.
Every result is raw evidence and must be kept in the offline research layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


VERSION = "counterfactual-mask-persistence-v1"
SCHEMA = "counterfactual-mask-persistence-v1"

ROUTE_PERSISTENT_CANDIDATE = "persistent_candidate"
ROUTE_NULL_CONSISTENT = "null_consistent"
ROUTE_MASK_INCONSISTENT = "mask_inconsistent"
ROUTE_INSUFFICIENT = "insufficient"

KIND_FACTUAL = "factual"
KIND_ORDINARY_PROPAGATION = "ordinary_propagation"
KIND_DECOY = "decoy"
KIND_WRONG_REFERENCE = "wrong_reference"
CONTROL_KINDS = (KIND_ORDINARY_PROPAGATION, KIND_DECOY, KIND_WRONG_REFERENCE)
KINDS = (KIND_FACTUAL,) + CONTROL_KINDS

_SCOPE_FOR_KIND = {
    KIND_FACTUAL: "content",
    KIND_ORDINARY_PROPAGATION: "ordinary_propagation",
    KIND_DECOY: "decoy",
    KIND_WRONG_REFERENCE: "wrong_reference",
}


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _digest_hex(name: str, value: str) -> str:
    value = _text(name, value).lower()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return value


def _finite(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _unit(name: str, value: float) -> float:
    value = _finite(name, value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


def _positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _regions(name: str, values: Sequence[str]) -> Tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a sequence of region IDs")
    try:
        normalized = tuple(sorted({_text("region_id", value) for value in values}))
    except TypeError as exc:
        raise ValueError(f"{name} must be a sequence of region IDs") from exc
    return normalized


def _metadata(name: str, value: Mapping[str, Any]) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    forbidden = {"confidence", "probability", "aigc_probability", "aigc_status"}
    if any(str(key).lower() in forbidden for key in value):
        raise ValueError(f"{name} contains a forbidden decision field")
    # Round-trip through JSON so a digest cannot depend on an unserialisable
    # object supplied by a caller.
    try:
        normalized = json.loads(json.dumps(dict(value), sort_keys=True, ensure_ascii=True))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be JSON serialisable") from exc
    return normalized


@dataclass(frozen=True)
class MaskPersistenceConfig:
    """Research gates.  Values are operating points, not production defaults."""

    minimum_view_count: int = 3
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    minimum_region_persistence: float = 0.67
    minimum_factual_set_jaccard: float = 0.67
    maximum_control_overlap: float = 0.34
    minimum_mask_overlap: float = 0.50
    require_factual_mask_overlap: bool = False
    required_control_kinds: Tuple[str, ...] = CONTROL_KINDS

    def __post_init__(self) -> None:
        _positive_int("minimum_view_count", self.minimum_view_count)
        for name in (
            "minimum_quality",
            "minimum_source_match",
            "minimum_region_persistence",
            "minimum_factual_set_jaccard",
            "maximum_control_overlap",
            "minimum_mask_overlap",
        ):
            object.__setattr__(self, name, _unit(name, getattr(self, name)))
        if not isinstance(self.require_factual_mask_overlap, bool):
            raise ValueError("require_factual_mask_overlap must be a bool")
        try:
            controls = tuple(_text("required_control_kind", item) for item in self.required_control_kinds)
        except TypeError as exc:
            raise ValueError("required_control_kinds must be a sequence") from exc
        if not controls or any(item not in CONTROL_KINDS for item in controls):
            raise ValueError("required_control_kinds must contain supported control kinds")
        if len(set(controls)) != len(controls):
            raise ValueError("required_control_kinds must be unique")
        object.__setattr__(self, "required_control_kinds", controls)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "minimum_view_count": self.minimum_view_count,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "minimum_region_persistence": self.minimum_region_persistence,
            "minimum_factual_set_jaccard": self.minimum_factual_set_jaccard,
            "maximum_control_overlap": self.maximum_control_overlap,
            "minimum_mask_overlap": self.minimum_mask_overlap,
            "require_factual_mask_overlap": self.require_factual_mask_overlap,
            "required_control_kinds": list(self.required_control_kinds),
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class MaskPersistenceObservation:
    """One detector evidence mask for one canonical view and control kind."""

    asset_id: str
    pair_id: str
    view_id: str
    view_order: int
    kind: str
    canonical_frame_digest: str
    manifest_digest: str
    detector_version: str
    score_schema: str
    proposal_mask_digest: str
    operator_digest: str
    view_spec_digest: str
    reference_digest: str
    observed_digest: str
    evidence_region_ids: Tuple[str, ...] = ()
    quality_score: float = 1.0
    source_match_score: float = 1.0
    mask_overlap_raw: Optional[float] = None
    intervention_executed: bool = True
    operation_scope: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "asset_id", "pair_id", "view_id", "detector_version", "score_schema",
        ):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        for name in (
            "canonical_frame_digest", "manifest_digest", "proposal_mask_digest",
            "operator_digest", "view_spec_digest", "reference_digest", "observed_digest",
        ):
            object.__setattr__(self, name, _digest_hex(name, getattr(self, name)))
        object.__setattr__(self, "view_order", _positive_int("view_order", self.view_order))
        kind = _text("kind", self.kind).lower()
        if kind not in KINDS:
            raise ValueError(f"unsupported kind: {kind!r}")
        object.__setattr__(self, "kind", kind)
        expected_scope = _SCOPE_FOR_KIND[kind]
        scope = expected_scope if self.operation_scope is None else _text("operation_scope", self.operation_scope)
        if scope != expected_scope:
            raise ValueError(f"operation_scope must be {expected_scope!r} for kind={kind!r}")
        object.__setattr__(self, "operation_scope", scope)
        object.__setattr__(self, "evidence_region_ids", _regions("evidence_region_ids", self.evidence_region_ids))
        object.__setattr__(self, "quality_score", _unit("quality_score", self.quality_score))
        object.__setattr__(self, "source_match_score", _unit("source_match_score", self.source_match_score))
        if self.mask_overlap_raw is not None:
            object.__setattr__(self, "mask_overlap_raw", _unit("mask_overlap_raw", self.mask_overlap_raw))
        if not isinstance(self.intervention_executed, bool):
            raise ValueError("intervention_executed must be a bool")
        object.__setattr__(self, "metadata", _metadata("metadata", self.metadata))

    @property
    def weight(self) -> float:
        return self.quality_score * self.source_match_score

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "view_id": self.view_id,
            "view_order": self.view_order,
            "kind": self.kind,
            "canonical_frame_digest": self.canonical_frame_digest,
            "manifest_digest": self.manifest_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "proposal_mask_digest": self.proposal_mask_digest,
            "operator_digest": self.operator_digest,
            "view_spec_digest": self.view_spec_digest,
            "reference_digest": self.reference_digest,
            "observed_digest": self.observed_digest,
            "evidence_region_ids": list(self.evidence_region_ids),
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "mask_overlap_raw": self.mask_overlap_raw,
            "intervention_executed": self.intervention_executed,
            "operation_scope": self.operation_scope,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class MaskPersistenceResult:
    """Raw result of the four-way factual/counterfactual mask audit."""

    route: str
    abstained: bool
    reason: str
    factual_mask_persistence_raw: Optional[float]
    factual_set_jaccard_raw: Optional[float]
    null_mask_hallucination_rate_raw: Optional[float]
    control_persistence_raw: Mapping[str, float]
    consensus_region_ids: Tuple[str, ...]
    factual_view_count: int
    control_view_counts: Mapping[str, int]
    factual_mask_overlap_raw: Optional[float]
    binding_digest: str
    config_digest: str
    evidence_digest: str
    schema: str = SCHEMA
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.route not in {
            ROUTE_PERSISTENT_CANDIDATE,
            ROUTE_NULL_CONSISTENT,
            ROUTE_MASK_INCONSISTENT,
            ROUTE_INSUFFICIENT,
        }:
            raise ValueError("unsupported route")
        if not isinstance(self.abstained, bool):
            raise ValueError("abstained must be a bool")
        expected_abstained = self.route != ROUTE_PERSISTENT_CANDIDATE
        if self.abstained != expected_abstained:
            raise ValueError("abstained must match route")
        object.__setattr__(self, "reason", _text("reason", self.reason))
        for name in (
            "factual_mask_persistence_raw", "factual_set_jaccard_raw",
            "null_mask_hallucination_rate_raw", "factual_mask_overlap_raw",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _unit(name, value))
        object.__setattr__(self, "consensus_region_ids", _regions("consensus_region_ids", self.consensus_region_ids))
        if isinstance(self.factual_view_count, bool) or not isinstance(self.factual_view_count, int) or self.factual_view_count < 0:
            raise ValueError("factual_view_count must be a non-negative integer")
        normalized_counts: Dict[str, int] = {}
        for kind, count in dict(self.control_view_counts).items():
            if kind not in CONTROL_KINDS:
                raise ValueError("unsupported control kind")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("control view counts must be non-negative integers")
            normalized_counts[kind] = count
        object.__setattr__(self, "control_view_counts", dict(sorted(normalized_counts.items())))
        normalized_persistence: Dict[str, float] = {}
        for kind, value in dict(self.control_persistence_raw).items():
            if kind not in CONTROL_KINDS:
                raise ValueError("unsupported control kind")
            normalized_persistence[kind] = _unit(f"control_persistence_raw[{kind}]", value)
        object.__setattr__(self, "control_persistence_raw", dict(sorted(normalized_persistence.items())))
        for name in ("binding_digest", "config_digest", "evidence_digest"):
            object.__setattr__(self, name, _digest_hex(name, getattr(self, name)))
        if self.schema != SCHEMA:
            raise ValueError("unsupported schema")
        object.__setattr__(self, "schema", _text("schema", self.schema))
        object.__setattr__(self, "version", _text("version", self.version))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "schema": self.schema,
            "route": self.route,
            "abstained": self.abstained,
            "reason": self.reason,
            "factual_mask_persistence_raw": self.factual_mask_persistence_raw,
            "factual_set_jaccard_raw": self.factual_set_jaccard_raw,
            "null_mask_hallucination_rate_raw": self.null_mask_hallucination_rate_raw,
            "control_persistence_raw": dict(self.control_persistence_raw),
            "consensus_region_ids": list(self.consensus_region_ids),
            "factual_view_count": self.factual_view_count,
            "control_view_counts": dict(self.control_view_counts),
            "factual_mask_overlap_raw": self.factual_mask_overlap_raw,
            "binding_digest": self.binding_digest,
            "config_digest": self.config_digest,
            "evidence_digest": self.evidence_digest,
        }


def _empty(
    config: MaskPersistenceConfig,
    reason: str,
    *,
    binding_digest: Optional[str] = None,
    factual_view_count: int = 0,
    control_view_counts: Optional[Mapping[str, int]] = None,
    evidence_digest: Optional[str] = None,
) -> MaskPersistenceResult:
    empty_binding = binding_digest or _digest({"version": VERSION, "binding": "missing"})
    empty_evidence = evidence_digest or _digest({"version": VERSION, "evidence": "missing"})
    return MaskPersistenceResult(
        route=ROUTE_INSUFFICIENT,
        abstained=True,
        reason=reason,
        factual_mask_persistence_raw=None,
        factual_set_jaccard_raw=None,
        null_mask_hallucination_rate_raw=None,
        control_persistence_raw={},
        consensus_region_ids=(),
        factual_view_count=factual_view_count,
        control_view_counts=control_view_counts or {},
        factual_mask_overlap_raw=None,
        binding_digest=empty_binding,
        config_digest=config.digest,
        evidence_digest=empty_evidence,
    )


def _weighted_mean(values: Sequence[float], weights: Sequence[float]) -> Optional[float]:
    if not values or len(values) != len(weights):
        return None
    total = sum(weights)
    if total <= 0.0:
        return None
    return sum(value * weight for value, weight in zip(values, weights)) / total


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 1.0
    return len(left & right) / len(union)


def evaluate_counterfactual_mask_persistence(
    observations: Iterable[MaskPersistenceObservation],
    *,
    config: Optional[MaskPersistenceConfig] = None,
) -> MaskPersistenceResult:
    """Evaluate factual mask persistence against matched counterfactuals.

    A result is ``persistent_candidate`` only when all required controls are
    present, the factual region mask is persistent across views, and no
    control repeatedly activates the same proposed regions.  The route is a
    raw review route; it does not assert that the image is AI-generated.
    """

    cfg = config or MaskPersistenceConfig()
    if isinstance(observations, (str, bytes)):
        raise ValueError("observations must be an iterable of MaskPersistenceObservation")
    try:
        items = list(observations)
    except TypeError as exc:
        raise ValueError("observations must be an iterable of MaskPersistenceObservation") from exc
    if not items:
        return _empty(cfg, "no_observations")
    if any(not isinstance(item, MaskPersistenceObservation) for item in items):
        raise ValueError("observations must contain MaskPersistenceObservation values")

    # Every comparison is source-conditioned on one asset/query, canonical
    # frame, detector/schema and intervention operator.  The reference digest
    # may differ only for the intentional wrong-reference control.
    shared_fields = (
        "asset_id", "pair_id", "canonical_frame_digest", "manifest_digest",
        "detector_version", "score_schema", "proposal_mask_digest", "operator_digest",
        "observed_digest",
    )
    binding_values = {field: getattr(items[0], field) for field in shared_fields}
    if any(any(getattr(item, field) != value for field, value in binding_values.items()) for item in items[1:]):
        return _empty(cfg, "binding_mismatch", binding_digest=_digest({"items": [item.to_dict() for item in items]}))
    binding_payload = {
        "shared": binding_values,
        "references": sorted((item.kind, item.view_id, item.reference_digest) for item in items),
        "view_specs": sorted((item.kind, item.view_id, item.view_spec_digest) for item in items),
    }
    binding_digest = _digest(binding_payload)

    seen = set()
    for item in items:
        key = (item.kind, item.view_id)
        if key in seen:
            return _empty(cfg, "duplicate_kind_view", binding_digest=binding_digest)
        seen.add(key)
        if not item.intervention_executed:
            return _empty(cfg, "intervention_not_executed", binding_digest=binding_digest)

    grouped = {kind: [item for item in items if item.kind == kind] for kind in KINDS}
    factual = grouped[KIND_FACTUAL]
    if len(factual) < cfg.minimum_view_count:
        return _empty(cfg, "factual_view_support_insufficient", binding_digest=binding_digest, factual_view_count=len(factual), control_view_counts={kind: len(grouped[kind]) for kind in CONTROL_KINDS})
    for kind in cfg.required_control_kinds:
        if len(grouped[kind]) < cfg.minimum_view_count:
            return _empty(cfg, f"{kind}_view_support_insufficient", binding_digest=binding_digest, factual_view_count=len(factual), control_view_counts={k: len(grouped[k]) for k in CONTROL_KINDS})

    # The controls must be the *same canonical views* as the factual query.
    # Counting a different view set as persistence would silently turn view
    # coverage into a selection bias.
    factual_view_ids = {item.view_id for item in factual}
    factual_orders = {item.view_id: item.view_order for item in factual}
    for kind in cfg.required_control_kinds:
        if {item.view_id for item in grouped[kind]} != factual_view_ids:
            return _empty(cfg, f"{kind}_view_set_mismatch", binding_digest=binding_digest, factual_view_count=len(factual), control_view_counts={k: len(grouped[k]) for k in CONTROL_KINDS})
        if {item.view_id: item.view_order for item in grouped[kind]} != factual_orders:
            return _empty(cfg, f"{kind}_view_order_mismatch", binding_digest=binding_digest, factual_view_count=len(factual), control_view_counts={k: len(grouped[k]) for k in CONTROL_KINDS})

    factual_references = {item.reference_digest for item in factual}
    if len(factual_references) != 1:
        return _empty(cfg, "factual_reference_mismatch", binding_digest=binding_digest, factual_view_count=len(factual), control_view_counts={kind: len(grouped[kind]) for kind in CONTROL_KINDS})
    factual_reference = next(iter(factual_references))
    for kind in (KIND_ORDINARY_PROPAGATION, KIND_DECOY):
        if any(item.reference_digest != factual_reference for item in grouped[kind]):
            return _empty(cfg, f"{kind}_reference_mismatch", binding_digest=binding_digest, factual_view_count=len(factual), control_view_counts={k: len(grouped[k]) for k in CONTROL_KINDS})

    # A wrong-reference control must actually use a different reference.  A
    # same-reference row is a mislabeled control and is unsafe to interpret.
    if any(item.reference_digest in factual_references for item in grouped[KIND_WRONG_REFERENCE]):
        return _empty(cfg, "wrong_reference_not_distinct", binding_digest=binding_digest, factual_view_count=len(factual), control_view_counts={kind: len(grouped[kind]) for kind in CONTROL_KINDS})

    eligible = {}
    for kind, rows in grouped.items():
        bad_quality = [row for row in rows if row.quality_score < cfg.minimum_quality]
        bad_source = [row for row in rows if row.source_match_score < cfg.minimum_source_match]
        if bad_quality:
            return _empty(cfg, f"{kind}_quality_below_threshold", binding_digest=binding_digest, factual_view_count=len(factual), control_view_counts={k: len(grouped[k]) for k in CONTROL_KINDS})
        if bad_source:
            return _empty(cfg, f"{kind}_source_match_below_threshold", binding_digest=binding_digest, factual_view_count=len(factual), control_view_counts={k: len(grouped[k]) for k in CONTROL_KINDS})
        if rows:
            eligible[kind] = rows

    total_weight = sum(row.weight for row in factual)
    if total_weight <= 0.0:
        return _empty(cfg, "factual_weight_zero", binding_digest=binding_digest, factual_view_count=len(factual), control_view_counts={kind: len(grouped[kind]) for kind in CONTROL_KINDS})

    region_support: Dict[str, float] = {}
    all_regions = sorted({region for row in factual for region in row.evidence_region_ids})
    for region in all_regions:
        region_support[region] = sum(row.weight for row in factual if region in row.evidence_region_ids) / total_weight
    consensus_regions = tuple(sorted(region for region, support in region_support.items() if support >= cfg.minimum_region_persistence))
    if not consensus_regions:
        evidence_digest = _digest({"items": [item.to_dict() for item in items], "region_support": region_support})
        return MaskPersistenceResult(
            route=ROUTE_MASK_INCONSISTENT,
            abstained=True,
            reason="no_persistent_factual_region",
            factual_mask_persistence_raw=0.0,
            factual_set_jaccard_raw=0.0,
            null_mask_hallucination_rate_raw=0.0,
            control_persistence_raw={kind: 0.0 for kind in CONTROL_KINDS if grouped[kind]},
            consensus_region_ids=(),
            factual_view_count=len(factual),
            control_view_counts={kind: len(grouped[kind]) for kind in CONTROL_KINDS},
            factual_mask_overlap_raw=None,
            binding_digest=binding_digest,
            config_digest=cfg.digest,
            evidence_digest=evidence_digest,
        )

    target = set(consensus_regions)
    factual_presence = [1.0 if target & set(row.evidence_region_ids) else 0.0 for row in factual]
    factual_mask_persistence = _weighted_mean(factual_presence, [row.weight for row in factual])
    factual_jaccard = _weighted_mean([_jaccard(set(row.evidence_region_ids), target) for row in factual], [row.weight for row in factual])
    overlap_values = [row.mask_overlap_raw for row in factual if row.mask_overlap_raw is not None]
    factual_mask_overlap = _weighted_mean(
        [float(row.mask_overlap_raw) for row in factual if row.mask_overlap_raw is not None],
        [row.weight for row in factual if row.mask_overlap_raw is not None],
    )
    if cfg.require_factual_mask_overlap and len(overlap_values) != len(factual):
        return _empty(cfg, "factual_mask_overlap_missing", binding_digest=binding_digest, factual_view_count=len(factual), control_view_counts={kind: len(grouped[kind]) for kind in CONTROL_KINDS})

    controls: Dict[str, float] = {}
    for kind in CONTROL_KINDS:
        rows = grouped[kind]
        if not rows:
            continue
        controls[kind] = float(_weighted_mean(
            [1.0 if target & set(row.evidence_region_ids) else 0.0 for row in rows],
            [row.weight for row in rows],
        ) or 0.0)
    max_control = max((controls.get(kind, 0.0) for kind in cfg.required_control_kinds), default=0.0)
    evidence_payload = {
        "items": [item.to_dict() for item in items],
        "region_support": region_support,
        "consensus_region_ids": list(consensus_regions),
        "factual_mask_persistence_raw": factual_mask_persistence,
        "factual_set_jaccard_raw": factual_jaccard,
        "control_persistence_raw": controls,
    }
    evidence_digest = _digest(evidence_payload)
    common = dict(
        factual_mask_persistence_raw=factual_mask_persistence,
        factual_set_jaccard_raw=factual_jaccard,
        null_mask_hallucination_rate_raw=max_control,
        control_persistence_raw=controls,
        consensus_region_ids=consensus_regions,
        factual_view_count=len(factual),
        control_view_counts={kind: len(grouped[kind]) for kind in CONTROL_KINDS},
        factual_mask_overlap_raw=factual_mask_overlap,
        binding_digest=binding_digest,
        config_digest=cfg.digest,
        evidence_digest=evidence_digest,
    )
    if factual_mask_persistence is None or factual_mask_persistence < cfg.minimum_region_persistence:
        return MaskPersistenceResult(route=ROUTE_MASK_INCONSISTENT, abstained=True, reason="factual_mask_persistence_below_threshold", **common)
    if factual_jaccard is None or factual_jaccard < cfg.minimum_factual_set_jaccard:
        return MaskPersistenceResult(route=ROUTE_MASK_INCONSISTENT, abstained=True, reason="factual_mask_set_inconsistent", **common)
    if factual_mask_overlap is not None and factual_mask_overlap < cfg.minimum_mask_overlap:
        return MaskPersistenceResult(route=ROUTE_MASK_INCONSISTENT, abstained=True, reason="factual_mask_overlap_below_threshold", **common)
    if max_control > cfg.maximum_control_overlap:
        return MaskPersistenceResult(route=ROUTE_NULL_CONSISTENT, abstained=True, reason="counterfactual_mask_hallucination", **common)
    return MaskPersistenceResult(route=ROUTE_PERSISTENT_CANDIDATE, abstained=False, reason="factual_mask_persistent_controls_quiet", **common)
