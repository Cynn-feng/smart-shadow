"""Retrieval- and selection-calibrated source-conditioned tree null.

This module is a deliberately small, model-free research contract.  The
caller supplies a frozen retrieval event and already-computed paired local
effects.  The contract validates candidate membership, tree bindings,
selection keys, split/authorization boundaries, and two independent ordinary
propagation null profiles.  It emits raw ranks and an auditable route only;
the result is never an AIGC probability, confidence, authorship statement,
copyright conclusion, or legal finding.

RSCPTN uses two statistics:

``tree_statistic``
    The maximum paired local delta among exact/matched candidates.  This is
    calibrated at the propagation-tree level, so correlated versions are not
    counted as independent rows.

``retrieval_statistic``
    The maximum paired local delta selected by the complete retrieval event,
    including uncertain/outside candidates for *diagnostic replay*.  Those
    candidates are never soft-weighted and cannot unlock a candidate route.
    Replaying this statistic on an independent ordinary-propagation placebo
    profile exposes retrieval/selection contamination.

The implementation is offline-only.  It does not load images, run a model,
touch the HTTP service, or modify ``aigc_result_v1``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple


VERSION = "retrieval-aware-tree-null-v1"
SCHEMA = "retrieval-aware-tree-null-result-v1"
PROFILE_SCHEMA = "retrieval-aware-tree-null-profile-v1"

ROUTE_RETRIEVAL_TREE_CANDIDATE = "retrieval_tree_candidate"
ROUTE_RETRIEVAL_TREE_NULL = "retrieval_tree_null_consistent"
ROUTE_RETRIEVAL_CONTAMINATED = "retrieval_contaminated_review"
ROUTE_OPEN_SET_UNKNOWN = "open_set_unknown"
ROUTE_INSUFFICIENT = "insufficient"

ROUTE_CANDIDATE = ROUTE_RETRIEVAL_TREE_CANDIDATE
ROUTE_NULL_CONSISTENT = ROUTE_RETRIEVAL_TREE_NULL
ROUTE_CONTAMINATED_REVIEW = ROUTE_RETRIEVAL_CONTAMINATED

MEMBERSHIP_EXACT = "exact"
MEMBERSHIP_MATCHED = "matched"
MEMBERSHIP_UNCERTAIN = "uncertain"
MEMBERSHIP_OUTSIDE = "outside"
MEMBERSHIP_TIERS = {
    MEMBERSHIP_EXACT,
    MEMBERSHIP_MATCHED,
    MEMBERSHIP_UNCERTAIN,
    MEMBERSHIP_OUTSIDE,
}
SUPPORTED_MEMBERSHIP = {MEMBERSHIP_EXACT, MEMBERSHIP_MATCHED}

OPERATION_CONTENT_EDIT = "content_edit"
OPERATION_ORDINARY_PROPAGATION = "ordinary_propagation"
OPERATION_SCOPES = {OPERATION_CONTENT_EDIT, OPERATION_ORDINARY_PROPAGATION}

_HEX_ZERO = "0" * 64


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _hex(name: str, value: str) -> str:
    value = _text(name, value).lower()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return value


def _finite(name: str, value: float, *, lower: Optional[float] = None,
            upper: Optional[float] = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if lower is not None and value < lower:
        raise ValueError(f"{name} is below its lower bound")
    if upper is not None and value > upper:
        raise ValueError(f"{name} is above its upper bound")
    return value


def _unit(name: str, value: float) -> float:
    return _finite(name, value, lower=0.0, upper=1.0)


def _positive_int(name: str, value: int, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _nonnegative_int(name: str, value: int) -> int:
    return _positive_int(name, value, minimum=0)


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class RSCPTNConfig:
    """Frozen gates for both raw null profiles."""

    minimum_profile_support: int = 8
    minimum_exact_matched_candidates: int = 1
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    minimum_selected_delta: float = 0.15
    alpha: float = 0.05
    maximum_contamination_fraction: float = 0.0
    minimum_action_budget: int = 1
    selection_policy: str = "max-paired-local-delta-then-rank-v1"
    required_reference_route: str = "reference_specific_candidate"
    required_invariant_route: str = "invariant_candidate"

    def __post_init__(self) -> None:
        _positive_int("minimum_profile_support", self.minimum_profile_support, minimum=2)
        _positive_int("minimum_exact_matched_candidates", self.minimum_exact_matched_candidates)
        _unit("minimum_quality", self.minimum_quality)
        _unit("minimum_source_match", self.minimum_source_match)
        _finite("minimum_selected_delta", self.minimum_selected_delta, lower=0.0)
        alpha = _unit("alpha", self.alpha)
        if alpha <= 0.0 or alpha >= 1.0:
            raise ValueError("alpha must be strictly between 0 and 1")
        _unit("maximum_contamination_fraction", self.maximum_contamination_fraction)
        _positive_int("minimum_action_budget", self.minimum_action_budget)
        _text("selection_policy", self.selection_policy)
        _text("required_reference_route", self.required_reference_route)
        _text("required_invariant_route", self.required_invariant_route)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "minimum_profile_support": self.minimum_profile_support,
            "minimum_exact_matched_candidates": self.minimum_exact_matched_candidates,
            "minimum_quality": float(self.minimum_quality),
            "minimum_source_match": float(self.minimum_source_match),
            "minimum_selected_delta": float(self.minimum_selected_delta),
            "alpha": float(self.alpha),
            "maximum_contamination_fraction": float(self.maximum_contamination_fraction),
            "minimum_action_budget": self.minimum_action_budget,
            "selection_policy": self.selection_policy,
            "required_reference_route": self.required_reference_route,
            "required_invariant_route": self.required_invariant_route,
        }

    @property
    def config_digest(self) -> str:
        return _digest(self.to_dict())

    @property
    def digest(self) -> str:
        return self.config_digest


@dataclass(frozen=True)
class RetrievalCandidate:
    """One ranked retrieval result and its already-computed raw evidence."""

    candidate_id: str
    candidate_rank: int
    membership_tier: str
    asset_id: str
    tree_id: str
    version_id: str
    parent_version_id: Optional[str]
    branch_id: str
    depth: int
    paired_delta_raw: float
    quality_score: float
    source_match_score: float
    canonical_frame_digest: str
    detector_version: str
    score_schema: str
    input_digest: str
    evidence_digest: str
    transform_family: str = "unknown"
    quality_bucket: str = "unknown"
    transport_bucket: str = "unknown"
    time_bucket: str = "unknown"
    operation_scope: str = OPERATION_CONTENT_EDIT
    selection_group_id: str = "default"
    generator_family: str = "known"
    authorized_for_research: bool = True

    def __post_init__(self) -> None:
        for name in (
            "candidate_id", "asset_id", "tree_id", "version_id", "branch_id",
            "detector_version", "score_schema", "transform_family", "quality_bucket",
            "transport_bucket", "time_bucket", "selection_group_id", "generator_family",
        ):
            _text(name, getattr(self, name))
        _positive_int("candidate_rank", self.candidate_rank)
        if self.membership_tier not in MEMBERSHIP_TIERS:
            raise ValueError("unsupported membership_tier")
        if self.parent_version_id is not None:
            _text("parent_version_id", self.parent_version_id)
        _nonnegative_int("depth", self.depth)
        _finite("paired_delta_raw", self.paired_delta_raw)
        _unit("quality_score", self.quality_score)
        _unit("source_match_score", self.source_match_score)
        for name in ("canonical_frame_digest", "input_digest", "evidence_digest"):
            object.__setattr__(self, name, _hex(name, getattr(self, name)))
        if self.operation_scope not in OPERATION_SCOPES:
            raise ValueError("unsupported operation_scope")
        if self.authorized_for_research is not True:
            raise ValueError("retrieval candidates must be authorised")

    @property
    def rank(self) -> int:
        """Alias used by callers that call the field simply ``rank``."""

        return self.candidate_rank

    @property
    def eligible_for_tree(self) -> bool:
        return self.membership_tier in SUPPORTED_MEMBERSHIP

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_rank": self.candidate_rank,
            "membership_tier": self.membership_tier,
            "asset_id": self.asset_id,
            "tree_id": self.tree_id,
            "version_id": self.version_id,
            "parent_version_id": self.parent_version_id,
            "branch_id": self.branch_id,
            "depth": self.depth,
            "paired_delta_raw": float(self.paired_delta_raw),
            "quality_score": float(self.quality_score),
            "source_match_score": float(self.source_match_score),
            "canonical_frame_digest": self.canonical_frame_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "input_digest": self.input_digest,
            "evidence_digest": self.evidence_digest,
            "transform_family": self.transform_family,
            "quality_bucket": self.quality_bucket,
            "transport_bucket": self.transport_bucket,
            "time_bucket": self.time_bucket,
            "operation_scope": self.operation_scope,
            "selection_group_id": self.selection_group_id,
            "generator_family": self.generator_family,
            "authorized_for_research": self.authorized_for_research,
        }


@dataclass(frozen=True)
class RetrievalEvent:
    """One complete retrieval → membership → tree → selection event."""

    event_id: str
    query_digest: str
    retrieval_policy_digest: str
    candidates: Tuple[RetrievalCandidate, ...]
    manifest_digest: str
    split_digest: str
    calibration_split_digest: str
    evaluation_split_digest: str
    selection_policy_digest: str
    selection_key_digest: str
    canonical_frame_digest: str
    detector_version: str
    score_schema: str
    action_budget: int
    input_digest: str
    evidence_digest: str
    retrieval_archive_digest: str
    membership_policy_digest: str
    decoy_injection_digest: str
    split: str = "evaluation"
    query_asset_id: str = "query-asset"
    operation_scope: str = OPERATION_CONTENT_EDIT
    candidate_count: Optional[int] = None
    reference_route: str = "reference_specific_candidate"
    invariant_route: str = "invariant_candidate"
    open_set: bool = False
    authorization_expired: bool = False
    authorized_for_research: bool = True
    poisoning_stress_route: str = "clean"
    poisoning_route_flip: bool = False
    retrieval_source_bucket: str = "unknown"
    platform_bucket: str = "unknown"
    transform_family: str = "unknown"
    quality_bucket: str = "unknown"
    transport_bucket: str = "unknown"
    time_bucket: str = "unknown"
    generator_family: str = "known"

    def __post_init__(self) -> None:
        _text("event_id", self.event_id)
        _text("query_asset_id", self.query_asset_id)
        for name in (
            "query_digest", "retrieval_policy_digest", "manifest_digest", "split_digest",
            "calibration_split_digest", "evaluation_split_digest", "selection_policy_digest",
            "selection_key_digest", "canonical_frame_digest", "input_digest", "evidence_digest",
            "retrieval_archive_digest", "membership_policy_digest", "decoy_injection_digest",
        ):
            object.__setattr__(self, name, _hex(name, getattr(self, name)))
        for name in (
            "detector_version", "score_schema", "reference_route", "invariant_route",
            "poisoning_stress_route", "retrieval_source_bucket", "platform_bucket",
            "transform_family", "quality_bucket", "transport_bucket", "time_bucket",
            "generator_family",
        ):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        if self.split not in {"calibration", "evaluation"}:
            raise ValueError("split must be calibration or evaluation")
        if self.operation_scope not in OPERATION_SCOPES:
            raise ValueError("unsupported operation_scope")
        _positive_int("action_budget", self.action_budget)
        if self.action_budget < 1:
            raise ValueError("action_budget must be positive")
        # ``split_digest`` is intentionally equal to the digest for the
        # event's own split.  The two *partition* digests must be distinct;
        # requiring all three values to differ would make every valid event
        # impossible to construct.
        if self.calibration_split_digest == self.evaluation_split_digest:
            raise ValueError("calibration and evaluation split digests must be distinct")
        expected_split = self.calibration_split_digest if self.split == "calibration" else self.evaluation_split_digest
        if self.split_digest != expected_split:
            raise ValueError("split_digest does not match split")
        if self.authorized_for_research is not True:
            raise ValueError("retrieval events must be authorised")
        if self.poisoning_stress_route not in {"clean", "false_positive", "missing", "poisoning", "route_flip"}:
            raise ValueError("unsupported poisoning_stress_route")
        if not isinstance(self.open_set, bool) or not isinstance(self.authorization_expired, bool):
            raise ValueError("open_set and authorization_expired must be booleans")
        if not isinstance(self.poisoning_route_flip, bool):
            raise ValueError("poisoning_route_flip must be boolean")
        if isinstance(self.candidates, (str, bytes)):
            raise ValueError("candidates must be a sequence")
        ordered = tuple(sorted(tuple(self.candidates), key=lambda item: (item.candidate_rank, item.candidate_id)))
        if not ordered or any(not isinstance(item, RetrievalCandidate) for item in ordered):
            raise ValueError("candidates must contain RetrievalCandidate values")
        if tuple(item.candidate_rank for item in ordered) != tuple(range(1, len(ordered) + 1)):
            raise ValueError("candidate ranks must be unique and contiguous from one")
        if len({item.candidate_id for item in ordered}) != len(ordered):
            raise ValueError("candidate IDs must be unique")
        if self.candidate_count is not None:
            _positive_int("candidate_count", self.candidate_count)
            if self.candidate_count != len(ordered):
                raise ValueError("candidate_count does not match candidates")
        object.__setattr__(self, "candidates", ordered)
        if any(item.canonical_frame_digest != self.canonical_frame_digest for item in ordered):
            raise ValueError("candidate canonical frame mismatch")
        if any(item.detector_version != self.detector_version or item.score_schema != self.score_schema for item in ordered):
            raise ValueError("candidate detector/schema mismatch")
        if any(item.operation_scope != self.operation_scope for item in ordered):
            raise ValueError("candidate operation scope mismatch")

    @property
    def candidate_count_value(self) -> int:
        return len(self.candidates)

    @property
    def candidate_rank_digest(self) -> str:
        return _digest([
            {
                "candidate_id": item.candidate_id,
                "candidate_rank": item.candidate_rank,
                "membership_tier": item.membership_tier,
            }
            for item in self.candidates
        ])

    @property
    def membership_tier_histogram(self) -> Tuple[int, int, int, int]:
        return tuple(sum(item.membership_tier == tier for item in self.candidates) for tier in (
            MEMBERSHIP_EXACT, MEMBERSHIP_MATCHED, MEMBERSHIP_UNCERTAIN, MEMBERSHIP_OUTSIDE,
        ))

    @property
    def uncertain_fraction_raw(self) -> float:
        return sum(item.membership_tier == MEMBERSHIP_UNCERTAIN for item in self.candidates) / len(self.candidates)

    @property
    def outside_fraction_raw(self) -> float:
        return sum(item.membership_tier == MEMBERSHIP_OUTSIDE for item in self.candidates) / len(self.candidates)

    @property
    def contamination_fraction_raw(self) -> float:
        return (sum(item.membership_tier in {MEMBERSHIP_UNCERTAIN, MEMBERSHIP_OUTSIDE} for item in self.candidates)
                / len(self.candidates))

    @property
    def tree_component_count(self) -> int:
        return len({item.tree_id for item in self.candidates if item.membership_tier in SUPPORTED_MEMBERSHIP})

    @property
    def branch_count(self) -> int:
        return len({(item.tree_id, item.branch_id) for item in self.candidates if item.membership_tier in SUPPORTED_MEMBERSHIP})

    @property
    def max_depth(self) -> int:
        return max((item.depth for item in self.candidates), default=0)

    @property
    def unresolved_parent_count(self) -> int:
        version_ids = {item.version_id for item in self.candidates}
        return sum(
            item.parent_version_id is not None and item.parent_version_id not in version_ids
            for item in self.candidates if item.membership_tier in SUPPORTED_MEMBERSHIP
        )

    @property
    def tree_shape_bucket(self) -> str:
        return f"components={self.tree_component_count};branches={self.branch_count};depth={self.max_depth}"

    @property
    def rank_profile_bucket(self) -> str:
        return f"top={len(self.candidates)}"

    @property
    def stratum_key(self) -> Tuple[str, ...]:
        tiers = ",".join(str(value) for value in self.membership_tier_histogram)
        return (
            self.retrieval_source_bucket, self.platform_bucket, self.transform_family,
            self.quality_bucket, self.transport_bucket, self.time_bucket,
            self.generator_family, str(self.action_budget), str(len(self.candidates)),
            self.rank_profile_bucket, tiers, self.tree_shape_bucket,
        )

    @property
    def binding_digest(self) -> str:
        return _digest({
            "version": VERSION,
            "retrieval_policy_digest": self.retrieval_policy_digest,
            "membership_policy_digest": self.membership_policy_digest,
            "selection_policy_digest": self.selection_policy_digest,
            "selection_key_digest": self.selection_key_digest,
            "candidate_rank_digest": self.candidate_rank_digest,
            "manifest_digest": self.manifest_digest,
            "canonical_frame_digest": self.canonical_frame_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "action_budget": self.action_budget,
            "split": self.split,
            "split_digest": self.split_digest,
            "stratum_key": list(self.stratum_key),
        })

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "retrieval-aware-tree-null-event-v1",
            "event_id": self.event_id,
            "query_digest": self.query_digest,
            "query_asset_id": self.query_asset_id,
            "retrieval_policy_digest": self.retrieval_policy_digest,
            "candidate_count": len(self.candidates),
            "candidate_rank_digest": self.candidate_rank_digest,
            "candidates": [item.to_dict() for item in self.candidates],
            "manifest_digest": self.manifest_digest,
            "split": self.split,
            "split_digest": self.split_digest,
            "calibration_split_digest": self.calibration_split_digest,
            "evaluation_split_digest": self.evaluation_split_digest,
            "selection_policy_digest": self.selection_policy_digest,
            "selection_key_digest": self.selection_key_digest,
            "canonical_frame_digest": self.canonical_frame_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "action_budget": self.action_budget,
            "input_digest": self.input_digest,
            "evidence_digest": self.evidence_digest,
            "retrieval_archive_digest": self.retrieval_archive_digest,
            "membership_policy_digest": self.membership_policy_digest,
            "decoy_injection_digest": self.decoy_injection_digest,
            "operation_scope": self.operation_scope,
            "reference_route": self.reference_route,
            "invariant_route": self.invariant_route,
            "open_set": self.open_set,
            "authorization_expired": self.authorization_expired,
            "authorized_for_research": self.authorized_for_research,
            "poisoning_stress_route": self.poisoning_stress_route,
            "poisoning_route_flip": self.poisoning_route_flip,
            "retrieval_source_bucket": self.retrieval_source_bucket,
            "platform_bucket": self.platform_bucket,
            "transform_family": self.transform_family,
            "quality_bucket": self.quality_bucket,
            "transport_bucket": self.transport_bucket,
            "time_bucket": self.time_bucket,
            "generator_family": self.generator_family,
            "stratum_key": list(self.stratum_key),
        }


@dataclass(frozen=True)
class RSCPTNNullProfile:
    """Independent ordinary-propagation profile for both selection paths."""

    manifest_digest: str
    calibration_split_digest: str
    evaluation_split_digest: str
    retrieval_policy_digest: str
    membership_policy_digest: str
    retrieval_archive_digest: str
    decoy_injection_digest: str
    selection_policy_digest: str
    selection_key_digest: str
    canonical_frame_digest: str
    detector_version: str
    score_schema: str
    action_budget: int
    stratum_key: Tuple[str, ...]
    tree_statistics_raw: Tuple[float, ...]
    retrieval_statistics_raw: Tuple[float, ...]
    tree_support_ids: Tuple[str, ...]
    retrieval_support_ids: Tuple[str, ...]
    support_asset_ids: Tuple[str, ...]
    support_selection_group_ids: Tuple[str, ...]
    dataset_digest: str
    config_digest: str
    profile_digest: str
    schema: str = PROFILE_SCHEMA

    def __post_init__(self) -> None:
        for name in (
            "manifest_digest", "calibration_split_digest", "evaluation_split_digest",
            "retrieval_policy_digest", "membership_policy_digest", "retrieval_archive_digest",
            "decoy_injection_digest", "selection_policy_digest",
            "selection_key_digest", "canonical_frame_digest", "dataset_digest", "config_digest",
            "profile_digest",
        ):
            object.__setattr__(self, name, _hex(name, getattr(self, name)))
        for name in ("detector_version", "score_schema"):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        _positive_int("action_budget", self.action_budget)
        if not self.stratum_key or any(not isinstance(value, str) or not value for value in self.stratum_key):
            raise ValueError("stratum_key must contain non-empty strings")
        if not self.tree_statistics_raw or len(self.tree_statistics_raw) != len(self.retrieval_statistics_raw):
            raise ValueError("tree and retrieval profiles need equal non-empty support")
        for value in (*self.tree_statistics_raw, *self.retrieval_statistics_raw):
            _finite("null statistic", value)
        for name, values in (("tree_support_ids", self.tree_support_ids),
                             ("retrieval_support_ids", self.retrieval_support_ids),
                             ("support_asset_ids", self.support_asset_ids),
                             ("support_selection_group_ids", self.support_selection_group_ids)):
            if len(values) != len(self.tree_statistics_raw):
                raise ValueError(f"{name} and support statistics must have equal length")
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"{name} must contain non-empty strings")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must be unique")
        if self.schema != PROFILE_SCHEMA:
            raise ValueError("unsupported profile schema")

    @property
    def tree_null_statistics_raw(self) -> Tuple[float, ...]:
        return self.tree_statistics_raw

    @property
    def retrieval_null_statistics_raw(self) -> Tuple[float, ...]:
        return self.retrieval_statistics_raw

    @property
    def support_event_ids(self) -> Tuple[str, ...]:
        return self.retrieval_support_ids

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "manifest_digest": self.manifest_digest,
            "calibration_split_digest": self.calibration_split_digest,
            "evaluation_split_digest": self.evaluation_split_digest,
            "retrieval_policy_digest": self.retrieval_policy_digest,
            "membership_policy_digest": self.membership_policy_digest,
            "retrieval_archive_digest": self.retrieval_archive_digest,
            "decoy_injection_digest": self.decoy_injection_digest,
            "selection_policy_digest": self.selection_policy_digest,
            "selection_key_digest": self.selection_key_digest,
            "canonical_frame_digest": self.canonical_frame_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "action_budget": self.action_budget,
            "stratum_key": list(self.stratum_key),
            "tree_statistics_raw": [float(value) for value in self.tree_statistics_raw],
            "retrieval_statistics_raw": [float(value) for value in self.retrieval_statistics_raw],
            "tree_support_ids": list(self.tree_support_ids),
            "retrieval_support_ids": list(self.retrieval_support_ids),
            "support_asset_ids": list(self.support_asset_ids),
            "support_selection_group_ids": list(self.support_selection_group_ids),
            "dataset_digest": self.dataset_digest,
            "config_digest": self.config_digest,
            "profile_digest": self.profile_digest,
        }


@dataclass(frozen=True)
class RSCPTNResult:
    """Raw route and diagnostic sidecar; no semantic verdict is included."""

    route: str
    abstained: bool
    reason: str
    event_id: str
    query_digest: Optional[str]
    event_digest: Optional[str]
    binding_digest: Optional[str]
    config_digest: str
    profile_digest: Optional[str]
    tree_statistic_raw: Optional[float]
    retrieval_statistic_raw: Optional[float]
    p_tree_raw: Optional[float]
    p_retrieval_raw: Optional[float]
    p_joint_raw: Optional[float]
    selected_candidate_ids: Tuple[str, ...]
    selected_tree_ids: Tuple[str, ...]
    exact_count: int
    matched_count: int
    uncertain_count: int
    outside_count: int
    uncertain_fraction_raw: float
    outside_fraction_raw: float
    contamination_fraction_raw: float
    unresolved_parent_count: int
    tree_component_count: int
    branch_count: int
    max_depth: int
    poisoning_route_flip: bool
    null_support_tree: int
    null_support_retrieval: int
    schema: str = SCHEMA

    @property
    def tree_max_statistic_raw(self) -> Optional[float]:
        return self.tree_statistic_raw

    @property
    def retrieval_max_statistic_raw(self) -> Optional[float]:
        return self.retrieval_statistic_raw

    @property
    def candidate_supported(self) -> bool:
        return self.route == ROUTE_RETRIEVAL_TREE_CANDIDATE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "version": VERSION,
            "route": self.route,
            "abstained": self.abstained,
            "candidate_supported": self.candidate_supported,
            "reason": self.reason,
            "event_id": self.event_id,
            "query_digest": self.query_digest,
            "event_digest": self.event_digest,
            "binding_digest": self.binding_digest,
            "config_digest": self.config_digest,
            "profile_digest": self.profile_digest,
            "tree_statistic_raw": self.tree_statistic_raw,
            "retrieval_statistic_raw": self.retrieval_statistic_raw,
            "p_tree_raw": self.p_tree_raw,
            "p_retrieval_raw": self.p_retrieval_raw,
            "p_joint_raw": self.p_joint_raw,
            "selected_candidate_ids": list(self.selected_candidate_ids),
            "selected_tree_ids": list(self.selected_tree_ids),
            "exact_count": self.exact_count,
            "matched_count": self.matched_count,
            "uncertain_count": self.uncertain_count,
            "outside_count": self.outside_count,
            "uncertain_fraction_raw": self.uncertain_fraction_raw,
            "outside_fraction_raw": self.outside_fraction_raw,
            "contamination_fraction_raw": self.contamination_fraction_raw,
            "unresolved_parent_count": self.unresolved_parent_count,
            "tree_component_count": self.tree_component_count,
            "branch_count": self.branch_count,
            "max_depth": self.max_depth,
            "poisoning_route_flip": self.poisoning_route_flip,
            "null_support_tree": self.null_support_tree,
            "null_support_retrieval": self.null_support_retrieval,
        }


def _stats(event: RetrievalEvent, config: RSCPTNConfig) -> Dict[str, Any]:
    exact = tuple(item for item in event.candidates if item.membership_tier == MEMBERSHIP_EXACT)
    matched = tuple(item for item in event.candidates if item.membership_tier == MEMBERSHIP_MATCHED)
    supported = tuple(item for item in event.candidates if item.membership_tier in SUPPORTED_MEMBERSHIP)
    quality_supported = tuple(item for item in supported if item.quality_score >= config.minimum_quality
                              and item.source_match_score >= config.minimum_source_match)
    retrieval_quality_supported = tuple(item for item in event.candidates
                                        if item.quality_score >= config.minimum_quality
                                        and item.source_match_score >= config.minimum_source_match)
    if quality_supported:
        tree_stat = max(item.paired_delta_raw for item in quality_supported)
        selected = tuple(sorted(item.candidate_id for item in quality_supported if item.paired_delta_raw == tree_stat))
        selected_trees = tuple(sorted({item.tree_id for item in quality_supported if item.paired_delta_raw == tree_stat}))
    else:
        tree_stat = None
        selected = ()
        selected_trees = ()
    retrieval_stat = max((item.paired_delta_raw for item in retrieval_quality_supported), default=None)
    return {
        "exact_count": len(exact),
        "matched_count": len(matched),
        "uncertain_count": sum(item.membership_tier == MEMBERSHIP_UNCERTAIN for item in event.candidates),
        "outside_count": sum(item.membership_tier == MEMBERSHIP_OUTSIDE for item in event.candidates),
        "tree_statistic_raw": tree_stat,
        "retrieval_statistic_raw": retrieval_stat,
        "selected_candidate_ids": selected,
        "selected_tree_ids": selected_trees,
    }


def _p_value(statistic: Optional[float], null_values: Sequence[float]) -> Optional[float]:
    if statistic is None or not null_values:
        return None
    exceedances = sum(value >= statistic for value in null_values)
    return (1.0 + exceedances) / (1.0 + len(null_values))


def _event_asset_id(event: RetrievalEvent) -> str:
    supported = [item.asset_id for item in event.candidates if item.membership_tier in SUPPORTED_MEMBERSHIP]
    return sorted(supported)[0] if supported else event.query_asset_id


def _profile_binding(event: RetrievalEvent) -> Tuple[Any, ...]:
    return (
        event.manifest_digest, event.calibration_split_digest, event.evaluation_split_digest,
        event.retrieval_policy_digest, event.membership_policy_digest, event.retrieval_archive_digest,
        event.decoy_injection_digest, event.selection_policy_digest,
        event.selection_key_digest, event.canonical_frame_digest, event.detector_version,
        event.score_schema, event.action_budget, event.stratum_key,
    )


def fit_rscptn_null_profile(events: Iterable[RetrievalEvent], config: Optional[RSCPTNConfig] = None) -> RSCPTNNullProfile:
    """Fit tree and retrieval raw nulls from independent ordinary events."""

    config = config or RSCPTNConfig()
    try:
        ordered = tuple(sorted(tuple(events), key=lambda item: item.event_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("events must be a sequence") from exc
    if len(ordered) < config.minimum_profile_support:
        raise ValueError("ordinary-propagation profile support is insufficient")
    if any(not isinstance(event, RetrievalEvent) for event in ordered):
        raise ValueError("events must contain RetrievalEvent values")
    if any(event.split != "calibration" for event in ordered):
        raise ValueError("null profile requires calibration events")
    if any(event.operation_scope != OPERATION_ORDINARY_PROPAGATION for event in ordered):
        raise ValueError("null profile accepts ordinary-propagation events only")
    if any(event.authorization_expired or event.poisoning_route_flip for event in ordered):
        raise ValueError("null profile cannot include expired or poisoning-flipped events")
    if len({event.event_id for event in ordered}) != len(ordered):
        raise ValueError("event IDs must be unique")
    asset_ids = tuple(_event_asset_id(event) for event in ordered)
    groups = tuple(event.query_asset_id for event in ordered)
    if len(set(asset_ids)) != len(asset_ids) or len(set(groups)) != len(groups):
        raise ValueError("calibration events must use independent assets and selection groups")
    first = ordered[0]
    binding = _profile_binding(first)
    if any(_profile_binding(event) != binding for event in ordered):
        raise ValueError("calibration events must share retrieval/tree selection binding")
    stats = [_stats(event, config) for event in ordered]
    if any(item["tree_statistic_raw"] is None or item["retrieval_statistic_raw"] is None for item in stats):
        raise ValueError("calibration event lacks quality/source-supported statistic")
    payload = {
        "version": VERSION,
        "binding": {
            "manifest_digest": first.manifest_digest,
            "calibration_split_digest": first.calibration_split_digest,
            "evaluation_split_digest": first.evaluation_split_digest,
            "retrieval_policy_digest": first.retrieval_policy_digest,
            "membership_policy_digest": first.membership_policy_digest,
            "retrieval_archive_digest": first.retrieval_archive_digest,
            "decoy_injection_digest": first.decoy_injection_digest,
            "selection_policy_digest": first.selection_policy_digest,
            "selection_key_digest": first.selection_key_digest,
            "canonical_frame_digest": first.canonical_frame_digest,
            "detector_version": first.detector_version,
            "score_schema": first.score_schema,
            "action_budget": first.action_budget,
            "stratum_key": list(first.stratum_key),
        },
        "tree_statistics_raw": [item["tree_statistic_raw"] for item in stats],
        "retrieval_statistics_raw": [item["retrieval_statistic_raw"] for item in stats],
        "tree_support_ids": [event.event_id for event in ordered],
        "retrieval_support_ids": [event.event_id for event in ordered],
        "support_asset_ids": list(asset_ids),
        "support_selection_group_ids": list(groups),
        "config_digest": config.config_digest,
    }
    dataset_digest = _digest({
        "events": [event.to_dict() for event in ordered],
        "config": config.to_dict(),
    })
    profile_digest = _digest(payload)
    return RSCPTNNullProfile(
        manifest_digest=first.manifest_digest,
        calibration_split_digest=first.calibration_split_digest,
        evaluation_split_digest=first.evaluation_split_digest,
        retrieval_policy_digest=first.retrieval_policy_digest,
        membership_policy_digest=first.membership_policy_digest,
        retrieval_archive_digest=first.retrieval_archive_digest,
        decoy_injection_digest=first.decoy_injection_digest,
        selection_policy_digest=first.selection_policy_digest,
        selection_key_digest=first.selection_key_digest,
        canonical_frame_digest=first.canonical_frame_digest,
        detector_version=first.detector_version,
        score_schema=first.score_schema,
        action_budget=first.action_budget,
        stratum_key=first.stratum_key,
        tree_statistics_raw=tuple(item["tree_statistic_raw"] for item in stats),
        retrieval_statistics_raw=tuple(item["retrieval_statistic_raw"] for item in stats),
        tree_support_ids=tuple(event.event_id for event in ordered),
        retrieval_support_ids=tuple(event.event_id for event in ordered),
        support_asset_ids=asset_ids,
        support_selection_group_ids=groups,
        dataset_digest=dataset_digest,
        config_digest=config.config_digest,
        profile_digest=profile_digest,
    )


def _empty_result(*, config: RSCPTNConfig, event: Optional[RetrievalEvent],
                  profile: Optional[RSCPTNNullProfile], reason: str,
                  route: str = ROUTE_INSUFFICIENT, stats: Optional[Dict[str, Any]] = None,
                  p_tree: Optional[float] = None, p_retrieval: Optional[float] = None,
                  binding_digest: Optional[str] = None) -> RSCPTNResult:
    stats = stats or {
        "exact_count": 0, "matched_count": 0, "uncertain_count": 0, "outside_count": 0,
        "tree_statistic_raw": None, "retrieval_statistic_raw": None,
        "selected_candidate_ids": (), "selected_tree_ids": (),
    }
    joint = max(p_tree, p_retrieval) if p_tree is not None and p_retrieval is not None else None
    return RSCPTNResult(
        route=route,
        abstained=route in {ROUTE_RETRIEVAL_CONTAMINATED, ROUTE_OPEN_SET_UNKNOWN, ROUTE_INSUFFICIENT},
        reason=reason,
        event_id=event.event_id if event is not None else "unknown",
        query_digest=event.query_digest if event is not None else None,
        event_digest=event.digest if event is not None else None,
        binding_digest=binding_digest,
        config_digest=config.config_digest,
        profile_digest=profile.profile_digest if profile is not None else None,
        tree_statistic_raw=stats["tree_statistic_raw"],
        retrieval_statistic_raw=stats["retrieval_statistic_raw"],
        p_tree_raw=p_tree,
        p_retrieval_raw=p_retrieval,
        p_joint_raw=joint,
        selected_candidate_ids=tuple(stats["selected_candidate_ids"]),
        selected_tree_ids=tuple(stats["selected_tree_ids"]),
        exact_count=stats["exact_count"],
        matched_count=stats["matched_count"],
        uncertain_count=stats["uncertain_count"],
        outside_count=stats["outside_count"],
        uncertain_fraction_raw=event.uncertain_fraction_raw if event is not None else 0.0,
        outside_fraction_raw=event.outside_fraction_raw if event is not None else 0.0,
        contamination_fraction_raw=event.contamination_fraction_raw if event is not None else 0.0,
        unresolved_parent_count=event.unresolved_parent_count if event is not None else 0,
        tree_component_count=event.tree_component_count if event is not None else 0,
        branch_count=event.branch_count if event is not None else 0,
        max_depth=event.max_depth if event is not None else 0,
        poisoning_route_flip=event.poisoning_route_flip if event is not None else False,
        null_support_tree=len(profile.tree_statistics_raw) if profile is not None else 0,
        null_support_retrieval=len(profile.retrieval_statistics_raw) if profile is not None else 0,
    )


def evaluate_retrieval_aware_tree_null(
    event: RetrievalEvent,
    profile: RSCPTNNullProfile,
    config: Optional[RSCPTNConfig] = None,
) -> RSCPTNResult:
    """Replay a frozen event against both independent raw null profiles."""

    config = config or RSCPTNConfig()
    if not isinstance(event, RetrievalEvent) or not isinstance(profile, RSCPTNNullProfile):
        return _empty_result(config=config, event=event if isinstance(event, RetrievalEvent) else None,
                             profile=profile if isinstance(profile, RSCPTNNullProfile) else None,
                             reason="event_or_profile_contract_failed")
    try:
        if event.split != "evaluation":
            raise ValueError("query event must use split=evaluation")
        if event.authorization_expired or not event.authorized_for_research:
            raise ValueError("authorization_expired")
        if profile.config_digest != config.config_digest:
            raise ValueError("config_digest_mismatch")
        if len(profile.tree_statistics_raw) < config.minimum_profile_support:
            raise ValueError("null_profile_support_insufficient")
        if _profile_binding(event) != (
            profile.manifest_digest, profile.calibration_split_digest, profile.evaluation_split_digest,
            profile.retrieval_policy_digest, profile.membership_policy_digest, profile.retrieval_archive_digest,
            profile.decoy_injection_digest, profile.selection_policy_digest,
            profile.selection_key_digest, profile.canonical_frame_digest, profile.detector_version,
            profile.score_schema, profile.action_budget, profile.stratum_key,
        ):
            raise ValueError("retrieval_tree_selection_binding_mismatch")
        if event.split_digest != profile.evaluation_split_digest:
            raise ValueError("evaluation_split_mismatch")
        if event.query_asset_id in set(profile.support_asset_ids):
            raise ValueError("asset_leaks_into_calibration")
        if event.query_asset_id in set(profile.support_selection_group_ids):
            raise ValueError("selection_group_leaks_into_calibration")
        if event.action_budget < config.minimum_action_budget:
            raise ValueError("action_budget_below_minimum")
        stats = _stats(event, config)
        p_tree = _p_value(stats["tree_statistic_raw"], profile.tree_statistics_raw)
        p_retrieval = _p_value(stats["retrieval_statistic_raw"], profile.retrieval_statistics_raw)
        binding_digest = _digest({
            "event_digest": event.digest,
            "profile_digest": profile.profile_digest,
            "config_digest": config.config_digest,
            "candidate_rank_digest": event.candidate_rank_digest,
            "selection_policy_digest": event.selection_policy_digest,
            "selection_key_digest": event.selection_key_digest,
        })
        if stats["exact_count"] + stats["matched_count"] == 0:
            return _empty_result(config=config, event=event, profile=profile, stats=stats,
                                 p_tree=p_tree, p_retrieval=p_retrieval, binding_digest=binding_digest,
                                 route=ROUTE_OPEN_SET_UNKNOWN, reason="no_exact_or_matched_membership")
        if event.open_set or event.generator_family in {"unknown", "open_set"}:
            return _empty_result(config=config, event=event, profile=profile, stats=stats,
                                 p_tree=p_tree, p_retrieval=p_retrieval, binding_digest=binding_digest,
                                 route=ROUTE_OPEN_SET_UNKNOWN, reason="open_set_or_unknown_generator")
        if stats["exact_count"] + stats["matched_count"] < config.minimum_exact_matched_candidates:
            return _empty_result(config=config, event=event, profile=profile, stats=stats,
                                 p_tree=p_tree, p_retrieval=p_retrieval, binding_digest=binding_digest,
                                 reason="exact_matched_support_insufficient")
        if stats["tree_statistic_raw"] is None or stats["retrieval_statistic_raw"] is None:
            return _empty_result(config=config, event=event, profile=profile, stats=stats,
                                 p_tree=p_tree, p_retrieval=p_retrieval, binding_digest=binding_digest,
                                 reason="selected_statistic_unavailable")
        if event.operation_scope == OPERATION_ORDINARY_PROPAGATION:
            return _empty_result(config=config, event=event, profile=profile, stats=stats,
                                 p_tree=p_tree, p_retrieval=p_retrieval, binding_digest=binding_digest,
                                 route=ROUTE_RETRIEVAL_TREE_NULL, reason="ordinary_propagation_scope")
        if event.poisoning_route_flip or event.poisoning_stress_route in {"poisoning", "route_flip"}:
            return _empty_result(config=config, event=event, profile=profile, stats=stats,
                                 p_tree=p_tree, p_retrieval=p_retrieval, binding_digest=binding_digest,
                                 route=ROUTE_RETRIEVAL_CONTAMINATED, reason="poisoning_or_route_flip")
        if event.reference_route != config.required_reference_route or event.invariant_route != config.required_invariant_route:
            return _empty_result(config=config, event=event, profile=profile, stats=stats,
                                 p_tree=p_tree, p_retrieval=p_retrieval, binding_digest=binding_digest,
                                 route=ROUTE_RETRIEVAL_CONTAMINATED, reason="reference_or_invariant_instability")
        if event.contamination_fraction_raw > config.maximum_contamination_fraction or event.unresolved_parent_count > 0:
            return _empty_result(config=config, event=event, profile=profile, stats=stats,
                                 p_tree=p_tree, p_retrieval=p_retrieval, binding_digest=binding_digest,
                                 route=ROUTE_RETRIEVAL_CONTAMINATED, reason="retrieval_contamination_detected")
        if len(stats["selected_tree_ids"]) != 1 or len(stats["selected_candidate_ids"]) != 1:
            return _empty_result(config=config, event=event, profile=profile, stats=stats,
                                 p_tree=p_tree, p_retrieval=p_retrieval, binding_digest=binding_digest,
                                 route=ROUTE_RETRIEVAL_CONTAMINATED,
                                 reason="tree_selection_tie_or_multiple_components")
        if stats["tree_statistic_raw"] < config.minimum_selected_delta:
            return _empty_result(config=config, event=event, profile=profile, stats=stats,
                                 p_tree=p_tree, p_retrieval=p_retrieval, binding_digest=binding_digest,
                                 route=ROUTE_RETRIEVAL_TREE_NULL, reason="selected_delta_below_gate")
        if p_tree is not None and p_retrieval is not None and p_tree <= config.alpha and p_retrieval <= config.alpha:
            return _empty_result(config=config, event=event, profile=profile, stats=stats,
                                 p_tree=p_tree, p_retrieval=p_retrieval, binding_digest=binding_digest,
                                 route=ROUTE_RETRIEVAL_TREE_CANDIDATE, reason="dual_null_gate_passed")
        return _empty_result(config=config, event=event, profile=profile, stats=stats,
                             p_tree=p_tree, p_retrieval=p_retrieval, binding_digest=binding_digest,
                             route=ROUTE_RETRIEVAL_TREE_NULL, reason="dual_null_gate_not_supported")
    except (TypeError, ValueError) as exc:
        return _empty_result(config=config, event=event, profile=profile,
                             reason=str(exc) or "event_or_profile_contract_failed")


# Explicit aliases make the contract easy to discover without creating a
# second implementation or changing the historical SCPTN module.
fit_retrieval_aware_null_profile = fit_rscptn_null_profile
evaluate_rscptn = evaluate_retrieval_aware_tree_null
evaluate_retrieval_aware_null = evaluate_retrieval_aware_tree_null
RetrievalAwareTreeNullConfig = RSCPTNConfig
RetrievalAwareCandidate = RetrievalCandidate
RetrievalAwareEvent = RetrievalEvent
RetrievalAwareTreeNullProfile = RSCPTNNullProfile
RetrievalAwareTreeNullResult = RSCPTNResult


__all__ = [
    "VERSION", "SCHEMA", "PROFILE_SCHEMA",
    "ROUTE_RETRIEVAL_TREE_CANDIDATE", "ROUTE_RETRIEVAL_TREE_NULL",
    "ROUTE_RETRIEVAL_CONTAMINATED", "ROUTE_OPEN_SET_UNKNOWN", "ROUTE_INSUFFICIENT",
    "ROUTE_CANDIDATE", "ROUTE_NULL_CONSISTENT", "ROUTE_CONTAMINATED_REVIEW",
    "MEMBERSHIP_EXACT", "MEMBERSHIP_MATCHED", "MEMBERSHIP_UNCERTAIN", "MEMBERSHIP_OUTSIDE",
    "OPERATION_CONTENT_EDIT", "OPERATION_ORDINARY_PROPAGATION",
    "RSCPTNConfig", "RetrievalCandidate", "RetrievalEvent", "RSCPTNNullProfile", "RSCPTNResult",
    "fit_rscptn_null_profile", "fit_retrieval_aware_null_profile",
    "evaluate_retrieval_aware_tree_null", "evaluate_rscptn", "evaluate_retrieval_aware_null",
    "RetrievalAwareTreeNullConfig", "RetrievalAwareCandidate", "RetrievalAwareEvent",
    "RetrievalAwareTreeNullProfile", "RetrievalAwareTreeNullResult",
]
