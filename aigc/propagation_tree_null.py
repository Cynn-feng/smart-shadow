"""Source-conditioned propagation-tree null calibration.

SCPTN treats one ordinary-propagation tree as the statistical unit.  It is a
small, model-free contract: callers provide already-computed paired local
delta values, while this module validates the tree, applies one registered
within-tree max selector, and calibrates that selected maximum against
independent ordinary-propagation trees.  It never emits an AIGC probability.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


VERSION = "source-conditioned-propagation-tree-null-v1"
SCHEMA = "source-conditioned-propagation-tree-null-v1"
PROFILE_SCHEMA = "source-conditioned-propagation-tree-null-profile-v1"
RESULT_SCHEMA = "source-conditioned-propagation-tree-null-result-v1"

ROUTE_TREE_CANDIDATE = "tree_specific_candidate"
ROUTE_TREE_AMBIGUOUS = "tree_selection_ambiguous"
ROUTE_TREE_NULL = "tree_null_consistent"
ROUTE_INSUFFICIENT = "insufficient"

ORDINARY_PROPAGATION = "ordinary_propagation"
CONTENT_EDIT = "content_edit"
_SCOPES = {ORDINARY_PROPAGATION, CONTENT_EDIT}


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _finite(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _unit(name: str, value: float) -> float:
    result = _finite(name, value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return result


def _positive_int(name: str, value: int, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hex(name: str, value: str) -> str:
    value = _text(name, value)
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
    return value.lower()


@dataclass(frozen=True)
class PropagationTreeConfig:
    minimum_tree_support: int = 8
    minimum_nodes_per_tree: int = 3
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    alpha: float = 0.05
    minimum_selected_delta: float = 0.15
    selection_policy: str = "max-paired-local-delta-v1"

    def __post_init__(self) -> None:
        _positive_int("minimum_tree_support", self.minimum_tree_support, minimum=2)
        _positive_int("minimum_nodes_per_tree", self.minimum_nodes_per_tree, minimum=2)
        _unit("minimum_quality", self.minimum_quality)
        _unit("minimum_source_match", self.minimum_source_match)
        alpha = _unit("alpha", self.alpha)
        if alpha <= 0.0 or alpha >= 1.0:
            raise ValueError("alpha must be strictly between 0 and 1")
        _finite("minimum_selected_delta", self.minimum_selected_delta)
        _text("selection_policy", self.selection_policy)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "minimum_tree_support": self.minimum_tree_support,
            "minimum_nodes_per_tree": self.minimum_nodes_per_tree,
            "minimum_quality": float(self.minimum_quality),
            "minimum_source_match": float(self.minimum_source_match),
            "alpha": float(self.alpha),
            "minimum_selected_delta": float(self.minimum_selected_delta),
            "selection_policy": self.selection_policy,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class PropagationTreeNode:
    version_id: str
    parent_version_id: Optional[str]
    asset_id: str
    tree_id: str
    transform_family: str
    quality_bucket: str
    time_bucket: str
    source_match_bucket: str
    operation_scope: str
    paired_delta_raw: float
    quality_score: float = 1.0
    source_match_score: float = 1.0
    node_order: int = 0
    authorized_for_research: bool = True

    def __post_init__(self) -> None:
        for name in (
            "version_id", "asset_id", "tree_id", "transform_family",
            "quality_bucket", "time_bucket", "source_match_bucket",
        ):
            _text(name, getattr(self, name))
        if self.parent_version_id is not None:
            _text("parent_version_id", self.parent_version_id)
        if self.operation_scope not in _SCOPES:
            raise ValueError("unsupported operation_scope")
        _finite("paired_delta_raw", self.paired_delta_raw)
        _unit("quality_score", self.quality_score)
        _unit("source_match_score", self.source_match_score)
        _positive_int("node_order", self.node_order, minimum=0)
        if self.authorized_for_research is not True:
            raise ValueError("propagation tree nodes must be authorised")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_id": self.version_id,
            "parent_version_id": self.parent_version_id,
            "asset_id": self.asset_id,
            "tree_id": self.tree_id,
            "transform_family": self.transform_family,
            "quality_bucket": self.quality_bucket,
            "time_bucket": self.time_bucket,
            "source_match_bucket": self.source_match_bucket,
            "operation_scope": self.operation_scope,
            "paired_delta_raw": float(self.paired_delta_raw),
            "quality_score": float(self.quality_score),
            "source_match_score": float(self.source_match_score),
            "node_order": self.node_order,
            "authorized_for_research": self.authorized_for_research,
        }


@dataclass(frozen=True)
class PropagationTree:
    tree_id: str
    asset_id: str
    manifest_digest: str
    split_digest: str
    detector_version: str
    score_schema: str
    transform_family: str
    quality_bucket: str
    time_bucket: str
    source_match_bucket: str
    nodes: Tuple[PropagationTreeNode, ...]
    split: str = "calibration"
    authorized_for_research: bool = True

    def __post_init__(self) -> None:
        for name in (
            "tree_id", "asset_id", "detector_version", "score_schema",
            "transform_family", "quality_bucket", "time_bucket", "source_match_bucket",
        ):
            _text(name, getattr(self, name))
        _hex("manifest_digest", self.manifest_digest)
        _hex("split_digest", self.split_digest)
        _text("split", self.split)
        if self.split not in {"calibration", "evaluation"}:
            raise ValueError("split must be calibration or evaluation")
        if self.authorized_for_research is not True:
            raise ValueError("propagation trees must be authorised")
        if isinstance(self.nodes, (str, bytes)) or not self.nodes:
            raise ValueError("nodes must be a non-empty sequence")
        nodes = tuple(self.nodes)
        if any(not isinstance(node, PropagationTreeNode) for node in nodes):
            raise ValueError("nodes must contain PropagationTreeNode values")
        ids = [node.version_id for node in nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("version IDs must be unique within a tree")
        if any(node.tree_id != self.tree_id or node.asset_id != self.asset_id for node in nodes):
            raise ValueError("node tree/asset binding mismatch")
        if any(
            node.transform_family != self.transform_family
            or node.quality_bucket != self.quality_bucket
            or node.time_bucket != self.time_bucket
            or node.source_match_bucket != self.source_match_bucket
            for node in nodes
        ):
            raise ValueError("tree nodes must share the declared calibration stratum")
        orders = [node.node_order for node in nodes]
        if len(orders) != len(set(orders)):
            raise ValueError("node_order values must be unique")
        if sorted(orders) != list(range(len(nodes))):
            raise ValueError("node_order must form a contiguous topological order")
        node_map = {node.version_id: node for node in nodes}
        roots = [node for node in nodes if node.parent_version_id is None]
        if len(roots) != 1:
            raise ValueError("propagation tree must have exactly one root")
        for node in nodes:
            if node.parent_version_id is not None:
                parent = node_map.get(node.parent_version_id)
                if parent is None:
                    raise ValueError("parent version is missing")
                if parent.node_order >= node.node_order:
                    raise ValueError("parent must precede child")

    @property
    def stratum_key(self) -> Tuple[str, str, str, str]:
        return (self.transform_family, self.quality_bucket, self.time_bucket, self.source_match_bucket)

    @property
    def operation_scopes(self) -> Tuple[str, ...]:
        return tuple(sorted({node.operation_scope for node in self.nodes}))

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tree_id": self.tree_id,
            "asset_id": self.asset_id,
            "manifest_digest": self.manifest_digest,
            "split_digest": self.split_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "transform_family": self.transform_family,
            "quality_bucket": self.quality_bucket,
            "time_bucket": self.time_bucket,
            "source_match_bucket": self.source_match_bucket,
            "nodes": [node.to_dict() for node in sorted(self.nodes, key=lambda item: item.node_order)],
            "split": self.split,
            "authorized_for_research": self.authorized_for_research,
        }

    def eligible_nodes(self, config: PropagationTreeConfig) -> Tuple[PropagationTreeNode, ...]:
        return tuple(
            node for node in self.nodes
            if node.quality_score >= config.minimum_quality
            and node.source_match_score >= config.minimum_source_match
        )

    def selected_max(self, config: PropagationTreeConfig) -> Tuple[Optional[float], Tuple[str, ...]]:
        eligible = self.eligible_nodes(config)
        if not eligible:
            return None, ()
        maximum = max(node.paired_delta_raw for node in eligible)
        selected = tuple(sorted(node.version_id for node in eligible if node.paired_delta_raw == maximum))
        return float(maximum), selected


@dataclass(frozen=True)
class PropagationTreeNullProfile:
    manifest_digest: str
    split_digest: str
    detector_version: str
    score_schema: str
    stratum_key: Tuple[str, str, str, str]
    null_max_statistics_raw: Tuple[float, ...]
    support_tree_ids: Tuple[str, ...]
    dataset_digest: str
    config_digest: str
    profile_digest: str
    schema: str = PROFILE_SCHEMA

    def __post_init__(self) -> None:
        _hex("manifest_digest", self.manifest_digest)
        _hex("split_digest", self.split_digest)
        _text("detector_version", self.detector_version)
        _text("score_schema", self.score_schema)
        if len(self.stratum_key) != 4 or any(not isinstance(value, str) or not value.strip() for value in self.stratum_key):
            raise ValueError("stratum_key must contain four non-empty strings")
        if not self.null_max_statistics_raw:
            raise ValueError("null profile needs support")
        for value in self.null_max_statistics_raw:
            _finite("null_max_statistics_raw", value)
        if len(self.support_tree_ids) != len(self.null_max_statistics_raw):
            raise ValueError("support IDs and statistics must have equal length")
        if len(set(self.support_tree_ids)) != len(self.support_tree_ids):
            raise ValueError("support tree IDs must be unique")
        _hex("dataset_digest", self.dataset_digest)
        _hex("config_digest", self.config_digest)
        _hex("profile_digest", self.profile_digest)
        if self.schema != PROFILE_SCHEMA:
            raise ValueError("unsupported profile schema")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "manifest_digest": self.manifest_digest,
            "split_digest": self.split_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "stratum_key": list(self.stratum_key),
            "null_max_statistics_raw": [float(value) for value in self.null_max_statistics_raw],
            "support_tree_ids": list(self.support_tree_ids),
            "dataset_digest": self.dataset_digest,
            "config_digest": self.config_digest,
            "profile_digest": self.profile_digest,
        }


@dataclass(frozen=True)
class SCPTNResult:
    route: str
    abstained: bool
    reason: str
    tree_id: str
    asset_id: str
    tree_digest: Optional[str]
    binding_digest: Optional[str]
    config_digest: str
    profile_digest: Optional[str]
    selected_max_raw: Optional[float]
    selected_version_ids: Tuple[str, ...]
    p_value_raw: Optional[float]
    null_support: int
    operation_scopes: Tuple[str, ...]
    stratum_key: Optional[Tuple[str, str, str, str]]
    schema: str = RESULT_SCHEMA

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "route": self.route,
            "abstained": self.abstained,
            "reason": self.reason,
            "tree_id": self.tree_id,
            "asset_id": self.asset_id,
            "tree_digest": self.tree_digest,
            "binding_digest": self.binding_digest,
            "config_digest": self.config_digest,
            "profile_digest": self.profile_digest,
            "selected_max_raw": self.selected_max_raw,
            "selected_version_ids": list(self.selected_version_ids),
            "p_value_raw": self.p_value_raw,
            "null_support": self.null_support,
            "operation_scopes": list(self.operation_scopes),
            "stratum_key": list(self.stratum_key) if self.stratum_key is not None else None,
        }


def _tree_digest_payload(tree: PropagationTree, config: PropagationTreeConfig) -> Dict[str, Any]:
    selected_max, selected_ids = tree.selected_max(config)
    return {
        "tree_digest": tree.digest,
        "selected_max_raw": selected_max,
        "selected_version_ids": list(selected_ids),
        "selection_policy": config.selection_policy,
    }


def fit_propagation_tree_null_profile(
    trees: Iterable[PropagationTree],
    config: Optional[PropagationTreeConfig] = None,
) -> PropagationTreeNullProfile:
    config = config or PropagationTreeConfig()
    ordered = tuple(sorted(tuple(trees), key=lambda tree: tree.tree_id))
    if len(ordered) < config.minimum_tree_support:
        raise ValueError("ordinary-propagation tree support is insufficient")
    if any(not isinstance(tree, PropagationTree) for tree in ordered):
        raise ValueError("trees must contain PropagationTree values")
    if len({tree.tree_id for tree in ordered}) != len(ordered):
        raise ValueError("tree IDs must be unique")
    if len({tree.asset_id for tree in ordered}) != len(ordered):
        raise ValueError("calibration trees must use independent assets")
    if any(tree.split != "calibration" for tree in ordered):
        raise ValueError("null profile requires calibration trees")
    if any(tree.operation_scopes != (ORDINARY_PROPAGATION,) for tree in ordered):
        raise ValueError("null profile only accepts ordinary-propagation trees")
    first = ordered[0]
    if any(
        tree.manifest_digest != first.manifest_digest
        or tree.split_digest != first.split_digest
        or tree.detector_version != first.detector_version
        or tree.score_schema != first.score_schema
        or tree.stratum_key != first.stratum_key
        for tree in ordered
    ):
        raise ValueError("calibration trees must share binding and stratum")
    selected: List[float] = []
    for tree in ordered:
        if len(tree.nodes) < config.minimum_nodes_per_tree:
            raise ValueError("tree node support is insufficient")
        value, _ = tree.selected_max(config)
        if value is None:
            raise ValueError("tree has no quality/source-matched nodes")
        selected.append(value)
    payload = {
        "version": VERSION,
        "manifest_digest": first.manifest_digest,
        "split_digest": first.split_digest,
        "detector_version": first.detector_version,
        "score_schema": first.score_schema,
        "stratum_key": list(first.stratum_key),
        "null_max_statistics_raw": selected,
        "support_tree_ids": [tree.tree_id for tree in ordered],
        "tree_digests": [tree.digest for tree in ordered],
        "config_digest": config.digest,
    }
    dataset_digest = _digest({"trees": [tree.to_dict() for tree in ordered], "config": config.to_dict()})
    profile_digest = _digest(payload)
    return PropagationTreeNullProfile(
        manifest_digest=first.manifest_digest,
        split_digest=first.split_digest,
        detector_version=first.detector_version,
        score_schema=first.score_schema,
        stratum_key=first.stratum_key,
        null_max_statistics_raw=tuple(selected),
        support_tree_ids=tuple(tree.tree_id for tree in ordered),
        dataset_digest=dataset_digest,
        config_digest=config.digest,
        profile_digest=profile_digest,
    )


def _result(
    *,
    route: str,
    abstained: bool,
    reason: str,
    tree: Optional[PropagationTree],
    config: PropagationTreeConfig,
    profile: Optional[PropagationTreeNullProfile] = None,
    selected_max: Optional[float] = None,
    selected_ids: Tuple[str, ...] = (),
    p_value: Optional[float] = None,
    binding_digest: Optional[str] = None,
) -> SCPTNResult:
    return SCPTNResult(
        route=route,
        abstained=abstained,
        reason=reason,
        tree_id=tree.tree_id if tree is not None else "unknown",
        asset_id=tree.asset_id if tree is not None else "unknown",
        tree_digest=tree.digest if tree is not None else None,
        binding_digest=binding_digest,
        config_digest=config.digest,
        profile_digest=profile.profile_digest if profile is not None else None,
        selected_max_raw=selected_max,
        selected_version_ids=selected_ids,
        p_value_raw=p_value,
        null_support=len(profile.null_max_statistics_raw) if profile is not None else 0,
        operation_scopes=tree.operation_scopes if tree is not None else (),
        stratum_key=tree.stratum_key if tree is not None else None,
    )


def evaluate_propagation_tree_null(
    tree: PropagationTree,
    profile: PropagationTreeNullProfile,
    config: Optional[PropagationTreeConfig] = None,
) -> SCPTNResult:
    config = config or PropagationTreeConfig()
    try:
        if not isinstance(tree, PropagationTree) or not isinstance(profile, PropagationTreeNullProfile):
            raise ValueError("tree and profile types are required")
        if tree.split != "evaluation":
            raise ValueError("query tree must use split=evaluation")
        if len(tree.nodes) < config.minimum_nodes_per_tree:
            raise ValueError("query tree node support is insufficient")
        if profile.config_digest != config.digest:
            raise ValueError("config digest mismatch")
        if tree.manifest_digest != profile.manifest_digest:
            raise ValueError("manifest digest mismatch")
        if tree.split_digest == profile.split_digest:
            raise ValueError("calibration/evaluation split leakage")
        if tree.detector_version != profile.detector_version or tree.score_schema != profile.score_schema:
            raise ValueError("detector or score schema mismatch")
        if tree.stratum_key != profile.stratum_key:
            raise ValueError("calibration stratum mismatch")
        selected_max, selected_ids = tree.selected_max(config)
        if selected_max is None:
            raise ValueError("query tree has no quality/source-matched nodes")
        binding_digest = _digest({
            "tree_digest": tree.digest,
            "profile_digest": profile.profile_digest,
            "config_digest": config.digest,
            "selection_policy": config.selection_policy,
        })
        if tree.operation_scopes == (ORDINARY_PROPAGATION,):
            return _result(
                route=ROUTE_TREE_NULL,
                abstained=False,
                reason="ordinary_propagation_scope",
                tree=tree,
                config=config,
                profile=profile,
                selected_max=selected_max,
                selected_ids=selected_ids,
                binding_digest=binding_digest,
            )
        if selected_max < config.minimum_selected_delta:
            return _result(
                route=ROUTE_TREE_NULL,
                abstained=False,
                reason="selected_delta_below_gate",
                tree=tree,
                config=config,
                profile=profile,
                selected_max=selected_max,
                selected_ids=selected_ids,
                binding_digest=binding_digest,
            )
        exceedances = sum(value >= selected_max for value in profile.null_max_statistics_raw)
        p_value = (1.0 + exceedances) / (1.0 + len(profile.null_max_statistics_raw))
        if p_value <= config.alpha:
            return _result(
                route=ROUTE_TREE_CANDIDATE,
                abstained=False,
                reason="tree_selected_delta_exceeds_null",
                tree=tree,
                config=config,
                profile=profile,
                selected_max=selected_max,
                selected_ids=selected_ids,
                p_value=p_value,
                binding_digest=binding_digest,
            )
        return _result(
            route=ROUTE_TREE_AMBIGUOUS,
            abstained=True,
            reason="tree_selection_p_value_not_supported",
            tree=tree,
            config=config,
            profile=profile,
            selected_max=selected_max,
            selected_ids=selected_ids,
            p_value=p_value,
            binding_digest=binding_digest,
        )
    except (TypeError, ValueError):
        return _result(
            route=ROUTE_INSUFFICIENT,
            abstained=True,
            reason="tree_or_profile_contract_failed",
            tree=tree if isinstance(tree, PropagationTree) else None,
            config=config,
            profile=profile if isinstance(profile, PropagationTreeNullProfile) else None,
        )


__all__ = [
    "VERSION", "SCHEMA", "PROFILE_SCHEMA", "RESULT_SCHEMA",
    "ROUTE_TREE_CANDIDATE", "ROUTE_TREE_AMBIGUOUS", "ROUTE_TREE_NULL", "ROUTE_INSUFFICIENT",
    "ORDINARY_PROPAGATION", "CONTENT_EDIT",
    "PropagationTreeConfig", "PropagationTreeNode", "PropagationTree",
    "PropagationTreeNullProfile", "SCPTNResult",
    "fit_propagation_tree_null_profile", "evaluate_propagation_tree_null",
]
