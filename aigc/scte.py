"""Source-Conditioned Triadic Evidence (SCTE) adapter.

This module is the missing binding layer between regional raw observations and
the regional FDR selector.  It accepts an observed query and an ordinary-
propagation counterfactual that were both aligned against the same registered
reference.  It verifies the asset/pair/manifests, transform specification,
coordinate frame, detector schema and complete region set before emitting
``RegionalQueryDelta`` values.

The adapter only produces raw, auditable evidence.  ``e_edit`` is
``e_obs - e_null``; it is not an AIGC probability, an authorship assertion, or
a legal conclusion.  Any structural mismatch fails closed and returns an
``insufficient`` result with no query deltas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .regional_counterfactual import RegionalObservation
from .regional_fdr import RegionalQueryDelta


VERSION = "scte-triadic-evidence-v1"
SCHEMA = "scte-regional-query-delta-v1"
ROUTE_ACCEPTED = "accepted"
ROUTE_INSUFFICIENT = "insufficient"


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _hex_digest(name: str, value: str) -> str:
    value = _text(name, value).lower()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return value


def _unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    return value


def _signed_unit(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number between -1 and 1")
    value = float(value)
    if not math.isfinite(value) or not -1.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and between -1 and 1")
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _int_pair(name: str, value: Sequence[int], *, allow_negative: bool = False) -> Tuple[int, int]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must contain two integer coordinates")
    try:
        if len(value) != 2:
            raise ValueError(f"{name} must contain two integer coordinates")
        items = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{name} must contain two integer coordinates") from exc
    if any(isinstance(item, bool) or not isinstance(item, int) for item in items):
        raise ValueError(f"{name} must contain two integer coordinates")
    if not allow_negative and any(item < 0 for item in items):
        raise ValueError(f"{name} must contain non-negative coordinates")
    return items  # type: ignore[return-value]


def _shape(value: Sequence[int]) -> Tuple[int, int]:
    shape = _int_pair("aligned_shape", value)
    if any(item < 1 for item in shape):
        raise ValueError("aligned_shape must contain positive dimensions")
    return shape


@dataclass(frozen=True)
class SCTEAlignmentFrame:
    """Complete coordinate frame for one query/counterfactual alignment."""

    role: str
    aligned_shape: Tuple[int, int]
    reference_offset: Tuple[int, int]
    query_offset: Tuple[int, int]
    dx: int
    dy: int
    alignment_version: str
    resize_version: str
    config_digest: str

    def __post_init__(self) -> None:
        if self.role not in {"observed", "counterfactual"}:
            raise ValueError("role must be observed or counterfactual")
        object.__setattr__(self, "aligned_shape", _shape(self.aligned_shape))
        object.__setattr__(self, "reference_offset", _int_pair("reference_offset", self.reference_offset))
        object.__setattr__(self, "query_offset", _int_pair("query_offset", self.query_offset))
        for name, value in (("dx", self.dx), ("dy", self.dy)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        object.__setattr__(self, "alignment_version", _text("alignment_version", self.alignment_version))
        object.__setattr__(self, "resize_version", _text("resize_version", self.resize_version))
        object.__setattr__(self, "config_digest", _hex_digest("config_digest", self.config_digest))

    def geometry_key(self) -> Tuple[Any, ...]:
        """Return all fields that must match across observed/counterfactual."""

        return (
            self.aligned_shape,
            self.reference_offset,
            self.query_offset,
            self.dx,
            self.dy,
            self.alignment_version,
            self.resize_version,
            self.config_digest,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "aligned_shape": list(self.aligned_shape),
            "reference_offset": list(self.reference_offset),
            "query_offset": list(self.query_offset),
            "dx": self.dx,
            "dy": self.dy,
            "alignment_version": self.alignment_version,
            "resize_version": self.resize_version,
            "config_digest": self.config_digest,
        }


@dataclass(frozen=True)
class SCTEBinding:
    """Manifest and coordinate binding required for one triadic pair."""

    asset_id: str
    pair_id: str
    manifest_digest: str
    reference_digest: str
    observed_digest: str
    counterfactual_digest: str
    transform_family: str
    transform_spec_digest: str
    propagation_chain: Tuple[str, ...]
    observed_alignment: SCTEAlignmentFrame
    counterfactual_alignment: SCTEAlignmentFrame
    region_ids: Tuple[str, ...]
    detector_version: str
    score_schema: str
    region_types: Mapping[str, str] = field(default_factory=dict)
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60

    def __post_init__(self) -> None:
        for name in ("asset_id", "pair_id", "transform_family", "detector_version", "score_schema"):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        for name in (
            "manifest_digest",
            "reference_digest",
            "observed_digest",
            "counterfactual_digest",
            "transform_spec_digest",
        ):
            object.__setattr__(self, name, _hex_digest(name, getattr(self, name)))
        if not isinstance(self.propagation_chain, tuple) or not self.propagation_chain:
            raise ValueError("propagation_chain must be a non-empty tuple")
        chain = tuple(_text("propagation_chain_item", item) for item in self.propagation_chain)
        object.__setattr__(self, "propagation_chain", chain)
        if not isinstance(self.observed_alignment, SCTEAlignmentFrame) or not isinstance(
            self.counterfactual_alignment, SCTEAlignmentFrame
        ):
            raise ValueError("observed_alignment and counterfactual_alignment are required")
        if self.observed_alignment.role != "observed" or self.counterfactual_alignment.role != "counterfactual":
            raise ValueError("alignment frame roles must match observed/counterfactual")
        if self.observed_alignment.geometry_key() != self.counterfactual_alignment.geometry_key():
            raise ValueError("observed/counterfactual alignment geometry must match")
        if isinstance(self.region_ids, (str, bytes)) or not self.region_ids:
            raise ValueError("region_ids must be a non-empty sequence")
        region_ids = tuple(sorted(_text("region_id", item) for item in self.region_ids))
        if len(set(region_ids)) != len(region_ids):
            raise ValueError("region_ids must be unique")
        object.__setattr__(self, "region_ids", region_ids)
        if not isinstance(self.region_types, Mapping):
            raise ValueError("region_types must be a mapping")
        types = {str(key): _text("region_type", value) for key, value in self.region_types.items()}
        if set(types) != set(region_ids):
            raise ValueError("region_types must cover exactly the complete region set")
        object.__setattr__(self, "region_types", dict(sorted(types.items())))
        object.__setattr__(self, "minimum_quality", _unit("minimum_quality", self.minimum_quality))
        object.__setattr__(
            self,
            "minimum_source_match",
            _unit("minimum_source_match", self.minimum_source_match),
        )

    @property
    def alignment_digest(self) -> str:
        return _digest(
            {
                "observed": self.observed_alignment.to_dict(),
                "counterfactual": self.counterfactual_alignment.to_dict(),
            }
        )

    @property
    def binding_digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "version": VERSION,
            "schema": SCHEMA,
            "asset_id": self.asset_id,
            "pair_id": self.pair_id,
            "manifest_digest": self.manifest_digest,
            "reference_digest": self.reference_digest,
            "observed_digest": self.observed_digest,
            "counterfactual_digest": self.counterfactual_digest,
            "transform_family": self.transform_family,
            "transform_spec_digest": self.transform_spec_digest,
            "propagation_chain": list(self.propagation_chain),
            "observed_alignment": self.observed_alignment.to_dict(),
            "counterfactual_alignment": self.counterfactual_alignment.to_dict(),
            "alignment_digest": self.alignment_digest,
            "region_ids": list(self.region_ids),
            "region_types": dict(self.region_types),
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
        }
        if include_digest:
            result["binding_digest"] = self.binding_digest
        return result


@dataclass(frozen=True)
class SCTERegionEvidence:
    """One region's observed, null and source-conditioned raw evidence."""

    region_id: str
    region_type: str
    e_obs: float
    e_null: float
    e_edit: float
    quality_score: float
    source_match_score: float
    query_delta: RegionalQueryDelta

    def __post_init__(self) -> None:
        object.__setattr__(self, "region_id", _text("region_id", self.region_id))
        object.__setattr__(self, "region_type", _text("region_type", self.region_type))
        _unit("e_obs", self.e_obs)
        _unit("e_null", self.e_null)
        _signed_unit("e_edit", self.e_edit)
        _unit("quality_score", self.quality_score)
        _unit("source_match_score", self.source_match_score)
        if not isinstance(self.query_delta, RegionalQueryDelta):
            raise ValueError("query_delta must be RegionalQueryDelta")
        if self.query_delta.region_id != self.region_id or self.query_delta.region_type != self.region_type:
            raise ValueError("query_delta region identity mismatch")
        if self.query_delta.delta_raw != float(self.e_edit):
            raise ValueError("query_delta delta must equal e_edit")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region_id": self.region_id,
            "region_type": self.region_type,
            "e_obs": self.e_obs,
            "e_null": self.e_null,
            "e_edit": self.e_edit,
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "query_delta": self.query_delta.to_dict(),
        }


@dataclass(frozen=True)
class SCTEResult:
    """Fail-closed triadic adapter output."""

    accepted: bool
    route: str
    reason: str
    binding_digest: str
    alignment_digest: str
    region_set_digest: str
    evidences: Tuple[SCTERegionEvidence, ...] = ()
    query_deltas: Tuple[RegionalQueryDelta, ...] = ()
    evidence_digest: str = ""
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.route not in {ROUTE_ACCEPTED, ROUTE_INSUFFICIENT}:
            raise ValueError("invalid SCTE route")
        if self.accepted != (self.route == ROUTE_ACCEPTED):
            raise ValueError("accepted must match route")
        _text("reason", self.reason)
        for name, value in (
            ("binding_digest", self.binding_digest),
            ("alignment_digest", self.alignment_digest),
            ("region_set_digest", self.region_set_digest),
            ("evidence_digest", self.evidence_digest),
        ):
            _hex_digest(name, value)
        if self.accepted:
            if not self.evidences or len(self.evidences) != len(self.query_deltas):
                raise ValueError("accepted SCTE result requires aligned evidence and deltas")
        elif self.evidences or self.query_deltas:
            raise ValueError("insufficient SCTE result cannot contain query deltas")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "schema": SCHEMA,
            "accepted": self.accepted,
            "route": self.route,
            "reason": self.reason,
            "binding_digest": self.binding_digest,
            "alignment_digest": self.alignment_digest,
            "region_set_digest": self.region_set_digest,
            "evidences": [item.to_dict() for item in self.evidences],
            "query_deltas": [item.to_dict() for item in self.query_deltas],
            "evidence_digest": self.evidence_digest,
        }


def _region_set_digest(binding: SCTEBinding) -> str:
    return _digest(
        {
            "region_ids": list(binding.region_ids),
            "region_types": dict(binding.region_types),
            "aligned_shape": list(binding.observed_alignment.aligned_shape),
        }
    )


def _empty_result(binding: SCTEBinding, reason: str) -> SCTEResult:
    region_set_digest = _region_set_digest(binding)
    evidence_digest = _digest(
        {
            "version": VERSION,
            "binding_digest": binding.binding_digest,
            "alignment_digest": binding.alignment_digest,
            "region_set_digest": region_set_digest,
            "route": ROUTE_INSUFFICIENT,
            "reason": reason,
        }
    )
    return SCTEResult(
        accepted=False,
        route=ROUTE_INSUFFICIENT,
        reason=reason,
        binding_digest=binding.binding_digest,
        alignment_digest=binding.alignment_digest,
        region_set_digest=region_set_digest,
        evidence_digest=evidence_digest,
    )


def build_scte_query_deltas(
    observations: Iterable[RegionalObservation],
    binding: SCTEBinding,
) -> SCTEResult:
    """Validate a triadic pair and emit ordered ``RegionalQueryDelta`` values.

    The input rows must contain exactly one observed and one counterfactual
    observation for every ``binding.region_ids`` value.  All rows share one
    asset, pair, transform family, propagation chain, detector and score
    schema.  A failure returns an ``insufficient`` result with no deltas.
    """

    if not isinstance(binding, SCTEBinding):
        raise ValueError("binding must be SCTEBinding")
    if isinstance(observations, (str, bytes)):
        raise ValueError("observations must be an iterable of RegionalObservation")
    try:
        items = tuple(observations)
    except TypeError as exc:
        raise ValueError("observations must be an iterable of RegionalObservation") from exc
    if not items or any(not isinstance(item, RegionalObservation) for item in items):
        return _empty_result(binding, "invalid_observation_type")

    if any(item.asset_id != binding.asset_id for item in items):
        return _empty_result(binding, "asset_identity_mismatch")
    if any(item.pair_id != binding.pair_id for item in items):
        return _empty_result(binding, "pair_identity_mismatch")
    if any(item.transform_family != binding.transform_family for item in items):
        return _empty_result(binding, "transform_family_mismatch")
    if any(item.detector_version != binding.detector_version for item in items):
        return _empty_result(binding, "detector_version_mismatch")
    if any(item.score_schema != binding.score_schema for item in items):
        return _empty_result(binding, "score_schema_mismatch")
    if any(tuple(item.propagation_chain) != binding.propagation_chain for item in items):
        return _empty_result(binding, "propagation_chain_mismatch")
    if any(
        item.quality_score < binding.minimum_quality
        for item in items
    ):
        return _empty_result(binding, "quality_below_threshold")
    if any(
        item.source_match_score < binding.minimum_source_match
        for item in items
    ):
        return _empty_result(binding, "source_match_below_threshold")

    grouped: Dict[str, Dict[str, RegionalObservation]] = {}
    for item in items:
        region = grouped.setdefault(item.region_id, {})
        if item.kind in region:
            return _empty_result(binding, "duplicate_region_observation")
        region[item.kind] = item
    if set(grouped) != set(binding.region_ids):
        return _empty_result(binding, "region_set_mismatch")
    if any(set(values) != {"observed", "counterfactual"} for values in grouped.values()):
        return _empty_result(binding, "incomplete_region_pair")

    evidences = []
    for region_id in binding.region_ids:
        observed = grouped[region_id]["observed"]
        counterfactual = grouped[region_id]["counterfactual"]
        e_obs = float(observed.score_raw)
        e_null = float(counterfactual.score_raw)
        e_edit = e_obs - e_null
        quality = min(observed.quality_score, counterfactual.quality_score)
        source_match = min(observed.source_match_score, counterfactual.source_match_score)
        query_delta = RegionalQueryDelta(
            region_id=region_id,
            delta_raw=e_edit,
            quality_score=quality,
            source_match_score=source_match,
            transform_family=binding.transform_family,
            region_type=binding.region_types[region_id],
            detector_version=binding.detector_version,
            score_schema=binding.score_schema,
        )
        evidences.append(
            SCTERegionEvidence(
                region_id=region_id,
                region_type=binding.region_types[region_id],
                e_obs=e_obs,
                e_null=e_null,
                e_edit=e_edit,
                quality_score=quality,
                source_match_score=source_match,
                query_delta=query_delta,
            )
        )
    evidence_tuple = tuple(evidences)
    query_deltas = tuple(item.query_delta for item in evidence_tuple)
    region_set_digest = _region_set_digest(binding)
    evidence_digest = _digest(
        {
            "version": VERSION,
            "binding_digest": binding.binding_digest,
            "alignment_digest": binding.alignment_digest,
            "region_set_digest": region_set_digest,
            "evidences": [item.to_dict() for item in evidence_tuple],
        }
    )
    return SCTEResult(
        accepted=True,
        route=ROUTE_ACCEPTED,
        reason="triadic_binding_validated",
        binding_digest=binding.binding_digest,
        alignment_digest=binding.alignment_digest,
        region_set_digest=region_set_digest,
        evidences=evidence_tuple,
        query_deltas=query_deltas,
        evidence_digest=evidence_digest,
    )


__all__ = [
    "VERSION",
    "SCHEMA",
    "ROUTE_ACCEPTED",
    "ROUTE_INSUFFICIENT",
    "SCTEAlignmentFrame",
    "SCTEBinding",
    "SCTERegionEvidence",
    "SCTEResult",
    "build_scte_query_deltas",
]
