"""Version-DAG evidence consistency audit for source-conditioned evidence.

This module consumes already-bound raw sidecars.  It does not run a detector,
fit a null profile, or infer a missing provenance edge.  The graph is an
auditable topology view over registered versions, ordinary-propagation nulls,
and claimed content edits.  A result is a raw audit route, never an AIGC
probability, source/author finding, or legal conclusion.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


VERSION = "evidence-graph-v1"
SCHEMA = "evidence-graph-result-v1"

ROUTE_GRAPH_CONSISTENT = "graph_consistent"
ROUTE_PROPAGATION_LEAK = "propagation_leak"
ROUTE_BRANCH_CONFLICT = "branch_conflict"
ROUTE_TRAJECTORY_INCONSISTENT = "trajectory_inconsistent"
ROUTE_INSUFFICIENT = "insufficient"

NODE_KINDS = frozenset(
    {"registered_source", "version", "ordinary_null", "observed", "decoy", "wrong_reference", "counterfactual"}
)
EDGE_SCOPES = frozenset({"content_edit", "ordinary_propagation"})


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _sha256(name: str, value: Optional[str], *, allow_none: bool = False) -> Optional[str]:
    if value is None and allow_none:
        return None
    normalized = _text(name, value or "").lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return normalized


def _finite(name: str, value: float, *, lower: float, upper: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < lower or normalized > upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")
    return normalized


def _unit(name: str, value: float) -> float:
    return _finite(name, value, lower=0.0, upper=1.0)


def _ids(name: str, values: Iterable[str]) -> Tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    result = tuple(_text(name, value) for value in values)
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
class GraphNode:
    """A version or control view with already-computed raw support."""

    node_id: str
    asset_id: str
    node_kind: str
    manifest_digest: str
    canonical_frame_digest: str
    detector_version: str
    score_schema: str
    support_raw: float
    region_support: Mapping[str, float]
    quality_score: float
    source_match_score: float
    evidence_digest: str
    metadata: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        for name in ("node_id", "asset_id", "detector_version", "score_schema"):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        kind = _text("node_kind", self.node_kind).lower().replace("-", "_")
        if kind not in NODE_KINDS:
            raise ValueError(f"unsupported node_kind: {kind}")
        object.__setattr__(self, "node_kind", kind)
        for name in ("manifest_digest", "canonical_frame_digest", "evidence_digest"):
            object.__setattr__(self, name, _sha256(name, getattr(self, name)))
        object.__setattr__(self, "support_raw", _unit("support_raw", self.support_raw))
        object.__setattr__(self, "quality_score", _unit("quality_score", self.quality_score))
        object.__setattr__(self, "source_match_score", _unit("source_match_score", self.source_match_score))
        if not isinstance(self.region_support, Mapping) or not self.region_support:
            raise ValueError("region_support must be a non-empty mapping")
        normalised: Dict[str, float] = {}
        for region_id, value in self.region_support.items():
            key = _text("region_id", region_id)
            if key in normalised:
                raise ValueError("region_support must not contain duplicate region IDs")
            normalised[key] = _unit(f"region_support[{key}]", value)
        object.__setattr__(self, "region_support", dict(sorted(normalised.items())))
        object.__setattr__(self, "metadata", _json_mapping("metadata", self.metadata))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "node_id": self.node_id,
            "asset_id": self.asset_id,
            "node_kind": self.node_kind,
            "manifest_digest": self.manifest_digest,
            "canonical_frame_digest": self.canonical_frame_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "support_raw": self.support_raw,
            "region_support": dict(self.region_support),
            "quality_score": self.quality_score,
            "source_match_score": self.source_match_score,
            "evidence_digest": self.evidence_digest,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GraphEdge:
    """A declared parent-to-child version transition."""

    edge_id: str
    parent_id: str
    child_id: str
    operation_scope: str
    operation_type: str
    transform_digest: str
    null_profile_digest: Optional[str] = None
    declared_mask_digest: Optional[str] = None
    declared_region_ids: Tuple[str, ...] = ()
    upstream_evidence_digest: Optional[str] = None
    metadata: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        for name in ("edge_id", "parent_id", "child_id"):
            object.__setattr__(self, name, _text(name, getattr(self, name)))
        object.__setattr__(self, "operation_type", _text("operation_type", self.operation_type).lower().replace("-", "_"))
        scope = _text("operation_scope", self.operation_scope).lower().replace("-", "_")
        if scope not in EDGE_SCOPES:
            raise ValueError("operation_scope must be content_edit or ordinary_propagation")
        object.__setattr__(self, "operation_scope", scope)
        object.__setattr__(self, "transform_digest", _sha256("transform_digest", self.transform_digest))
        object.__setattr__(self, "null_profile_digest", _sha256("null_profile_digest", self.null_profile_digest, allow_none=True))
        object.__setattr__(self, "declared_mask_digest", _sha256("declared_mask_digest", self.declared_mask_digest, allow_none=True))
        object.__setattr__(self, "upstream_evidence_digest", _sha256("upstream_evidence_digest", self.upstream_evidence_digest, allow_none=True))
        object.__setattr__(self, "declared_region_ids", _ids("declared_region_ids", self.declared_region_ids))
        object.__setattr__(self, "metadata", _json_mapping("metadata", self.metadata))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "edge_id": self.edge_id,
            "parent_id": self.parent_id,
            "child_id": self.child_id,
            "operation_scope": self.operation_scope,
            "operation_type": self.operation_type,
            "transform_digest": self.transform_digest,
            "null_profile_digest": self.null_profile_digest,
            "declared_mask_digest": self.declared_mask_digest,
            "declared_region_ids": list(self.declared_region_ids),
            "upstream_evidence_digest": self.upstream_evidence_digest,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EvidenceGraphConfig:
    minimum_quality: float = 0.35
    minimum_source_match: float = 0.60
    minimum_support_for_persistence: float = 0.20
    maximum_propagation_leak: float = 0.20
    maximum_off_mask_gain: float = 0.20
    maximum_branch_disagreement: float = 0.50
    minimum_path_persistence: float = 0.50
    require_null_profile_for_propagation: bool = True

    def __post_init__(self) -> None:
        for name in (
            "minimum_quality",
            "minimum_source_match",
            "minimum_support_for_persistence",
            "maximum_propagation_leak",
            "maximum_off_mask_gain",
            "maximum_branch_disagreement",
            "minimum_path_persistence",
        ):
            object.__setattr__(self, name, _unit(name, getattr(self, name)))
        if not isinstance(self.require_null_profile_for_propagation, bool):
            raise ValueError("require_null_profile_for_propagation must be bool")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "minimum_quality": self.minimum_quality,
            "minimum_source_match": self.minimum_source_match,
            "minimum_support_for_persistence": self.minimum_support_for_persistence,
            "maximum_propagation_leak": self.maximum_propagation_leak,
            "maximum_off_mask_gain": self.maximum_off_mask_gain,
            "maximum_branch_disagreement": self.maximum_branch_disagreement,
            "minimum_path_persistence": self.minimum_path_persistence,
            "require_null_profile_for_propagation": self.require_null_profile_for_propagation,
        }

    @property
    def config_digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class GraphEdgeAudit:
    edge_id: str
    parent_id: str
    child_id: str
    new_support_raw: float
    off_mask_gain_raw: float
    accepted: bool
    reasons: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "parent_id": self.parent_id,
            "child_id": self.child_id,
            "new_support_raw": self.new_support_raw,
            "off_mask_gain_raw": self.off_mask_gain_raw,
            "accepted": self.accepted,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class EvidenceGraphResult:
    route: str
    schema: str
    version: str
    graph_digest: str
    config_digest: str
    node_count: int
    edge_count: int
    root_ids: Tuple[str, ...]
    leaf_ids: Tuple[str, ...]
    propagation_leak_raw: float
    off_mask_gain_raw: float
    branch_disagreement_raw: float
    path_persistence_raw: float
    edge_audits: Tuple[GraphEdgeAudit, ...]
    reasons: Tuple[str, ...] = ()

    @property
    def abstained(self) -> bool:
        return self.route != ROUTE_GRAPH_CONSISTENT

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "route": self.route,
            "abstained": self.abstained,
            "graph_digest": self.graph_digest,
            "config_digest": self.config_digest,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "root_ids": list(self.root_ids),
            "leaf_ids": list(self.leaf_ids),
            "propagation_leak_raw": self.propagation_leak_raw,
            "off_mask_gain_raw": self.off_mask_gain_raw,
            "branch_disagreement_raw": self.branch_disagreement_raw,
            "path_persistence_raw": self.path_persistence_raw,
            "edge_audits": [item.to_dict() for item in self.edge_audits],
            "reasons": list(self.reasons),
        }


def _topological_order(node_ids: Sequence[str], edges: Sequence[GraphEdge]) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    children: Dict[str, list[str]] = defaultdict(list)
    indegree = {node_id: 0 for node_id in node_ids}
    for edge in edges:
        children[edge.parent_id].append(edge.child_id)
        indegree[edge.child_id] += 1
    queue = deque(sorted(node_id for node_id, count in indegree.items() if count == 0))
    ordered = []
    while queue:
        node_id = queue.popleft()
        ordered.append(node_id)
        for child_id in sorted(children[node_id]):
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                queue.append(child_id)
    roots = tuple(sorted(node_id for node_id, count in {key: 0 for key in node_ids}.items() if node_id not in {edge.child_id for edge in edges}))
    return tuple(ordered), roots


def _path_persistence(nodes: Mapping[str, GraphNode], edges: Sequence[GraphEdge], config: EvidenceGraphConfig) -> float:
    content_children = {edge.child_id for edge in edges if edge.operation_scope == "content_edit"}
    if not content_children:
        return 1.0
    children: Dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        children[edge.parent_id].append(edge.child_id)
    values = []
    for onset in sorted(content_children):
        seen = {onset}
        queue = deque([onset])
        while queue:
            current = queue.popleft()
            for child in children[current]:
                if child not in seen:
                    seen.add(child)
                    queue.append(child)
        values.append(sum(nodes[node_id].support_raw >= config.minimum_support_for_persistence for node_id in seen) / len(seen))
    return min(values) if values else 0.0


def evaluate_evidence_graph(
    nodes: Sequence[GraphNode],
    edges: Sequence[GraphEdge],
    *,
    config: EvidenceGraphConfig = EvidenceGraphConfig(),
) -> EvidenceGraphResult:
    """Validate a version DAG and summarize only topology-aware raw evidence."""

    node_list = tuple(nodes)
    edge_list = tuple(edges)
    reasons: list[str] = []
    node_map: Dict[str, GraphNode] = {}
    for node in node_list:
        if not isinstance(node, GraphNode):
            reasons.append("invalid_node_type")
            continue
        if node.node_id in node_map:
            reasons.append("duplicate_node_id")
        node_map[node.node_id] = node
    edge_ids = set()
    for edge in edge_list:
        if not isinstance(edge, GraphEdge):
            reasons.append("invalid_edge_type")
            continue
        if edge.edge_id in edge_ids:
            reasons.append("duplicate_edge_id")
        edge_ids.add(edge.edge_id)
        if edge.parent_id not in node_map or edge.child_id not in node_map:
            reasons.append("missing_parent_or_child")
        if edge.parent_id == edge.child_id:
            reasons.append("self_loop")

    parent_counts: Dict[str, int] = defaultdict(int)
    for edge in edge_list:
        parent_counts[edge.child_id] += 1
    if any(count > 1 for count in parent_counts.values()):
        reasons.append("merge_not_supported")

    contexts = {
        (node.asset_id, node.manifest_digest, node.canonical_frame_digest, node.detector_version, node.score_schema)
        for node in node_map.values()
    }
    if len(contexts) > 1:
        reasons.append("binding_context_mismatch")
    if any(node.quality_score < config.minimum_quality for node in node_map.values()):
        reasons.append("quality_below_gate")
    if any(node.source_match_score < config.minimum_source_match for node in node_map.values()):
        reasons.append("source_match_below_gate")

    valid_edges = [edge for edge in edge_list if edge.parent_id in node_map and edge.child_id in node_map]
    for edge in valid_edges:
        if edge.operation_scope == "content_edit" and (edge.declared_mask_digest is None or not edge.declared_region_ids):
            reasons.append(f"content_edge_missing_declared_mask:{edge.edge_id}")
        if edge.operation_scope == "ordinary_propagation" and config.require_null_profile_for_propagation and edge.null_profile_digest is None:
            reasons.append(f"propagation_edge_missing_null_profile:{edge.edge_id}")

    ordered, root_ids = _topological_order(tuple(sorted(node_map)), valid_edges)
    if len(ordered) != len(node_map):
        reasons.append("cycle_detected")
    child_ids = {edge.child_id for edge in valid_edges}
    leaf_ids = tuple(sorted(node_id for node_id in node_map if node_id not in {edge.parent_id for edge in valid_edges}))
    if not root_ids and node_map:
        reasons.append("no_root")

    edge_audits = []
    propagation_leak = 0.0
    off_mask_gain = 0.0
    for edge in sorted(valid_edges, key=lambda item: item.edge_id):
        parent = node_map[edge.parent_id]
        child = node_map[edge.child_id]
        region_ids = set(parent.region_support) | set(child.region_support)
        gains = {region_id: max(0.0, child.region_support.get(region_id, 0.0) - parent.region_support.get(region_id, 0.0)) for region_id in region_ids}
        new_support = max(0.0, child.support_raw - parent.support_raw)
        if edge.operation_scope == "ordinary_propagation":
            edge_off_mask = max(gains.values(), default=0.0)
            propagation_leak = max(propagation_leak, new_support, edge_off_mask)
        else:
            edge_off_mask = max((gain for region_id, gain in gains.items() if region_id not in set(edge.declared_region_ids)), default=0.0)
            off_mask_gain = max(off_mask_gain, edge_off_mask)
        accepted = not (
            new_support > config.maximum_propagation_leak and edge.operation_scope == "ordinary_propagation"
        ) and not (edge_off_mask > config.maximum_off_mask_gain and edge.operation_scope == "content_edit")
        edge_reasons = []
        if edge.operation_scope == "ordinary_propagation" and new_support > config.maximum_propagation_leak:
            edge_reasons.append("new_support_on_ordinary_propagation")
        if edge.operation_scope == "content_edit" and edge_off_mask > config.maximum_off_mask_gain:
            edge_reasons.append("support_outside_declared_mask")
        edge_audits.append(GraphEdgeAudit(edge.edge_id, edge.parent_id, edge.child_id, new_support, edge_off_mask, accepted, tuple(edge_reasons)))

    siblings: Dict[str, list[str]] = defaultdict(list)
    for edge in valid_edges:
        siblings[edge.parent_id].append(edge.child_id)
    branch_disagreement = 0.0
    for child_group in siblings.values():
        if len(child_group) < 2:
            continue
        values = [node_map[node_id].support_raw for node_id in child_group]
        branch_disagreement = max(branch_disagreement, max(values) - min(values))

    path_persistence = _path_persistence(node_map, valid_edges, config) if node_map else 0.0
    if branch_disagreement > config.maximum_branch_disagreement:
        reasons.append("sibling_support_disagreement")
    if path_persistence < config.minimum_path_persistence and any(edge.operation_scope == "content_edit" for edge in valid_edges):
        reasons.append("edit_trajectory_not_persistent")
    if propagation_leak > config.maximum_propagation_leak:
        reasons.append("propagation_leak_above_gate")
    if off_mask_gain > config.maximum_off_mask_gain:
        reasons.append("off_mask_gain_above_gate")

    if any(reason.startswith("propagation_edge_missing_null_profile") or reason.startswith("content_edge_missing_declared_mask") for reason in reasons):
        route = ROUTE_INSUFFICIENT
    elif any(reason in {"duplicate_node_id", "duplicate_edge_id", "missing_parent_or_child", "self_loop", "merge_not_supported", "cycle_detected", "no_root", "binding_context_mismatch", "quality_below_gate", "source_match_below_gate", "invalid_node_type", "invalid_edge_type"} for reason in reasons):
        route = ROUTE_INSUFFICIENT
    elif branch_disagreement > config.maximum_branch_disagreement:
        route = ROUTE_BRANCH_CONFLICT
    elif propagation_leak > config.maximum_propagation_leak:
        route = ROUTE_PROPAGATION_LEAK
    elif off_mask_gain > config.maximum_off_mask_gain or path_persistence < config.minimum_path_persistence:
        route = ROUTE_TRAJECTORY_INCONSISTENT
    else:
        route = ROUTE_GRAPH_CONSISTENT

    graph_payload = {
        "version": VERSION,
        "nodes": [node.to_dict() for node in sorted(node_map.values(), key=lambda item: item.node_id)],
        "edges": [edge.to_dict() for edge in sorted(valid_edges, key=lambda item: item.edge_id)],
    }
    return EvidenceGraphResult(
        route=route,
        schema=SCHEMA,
        version=VERSION,
        graph_digest=_digest(graph_payload),
        config_digest=config.config_digest,
        node_count=len(node_map),
        edge_count=len(valid_edges),
        root_ids=tuple(root_ids),
        leaf_ids=leaf_ids,
        propagation_leak_raw=propagation_leak,
        off_mask_gain_raw=off_mask_gain,
        branch_disagreement_raw=branch_disagreement,
        path_persistence_raw=path_persistence,
        edge_audits=tuple(edge_audits),
        reasons=tuple(sorted(set(reasons))),
    )


__all__ = [
    "VERSION",
    "SCHEMA",
    "ROUTE_GRAPH_CONSISTENT",
    "ROUTE_PROPAGATION_LEAK",
    "ROUTE_BRANCH_CONFLICT",
    "ROUTE_TRAJECTORY_INCONSISTENT",
    "ROUTE_INSUFFICIENT",
    "GraphNode",
    "GraphEdge",
    "EvidenceGraphConfig",
    "GraphEdgeAudit",
    "EvidenceGraphResult",
    "evaluate_evidence_graph",
]
