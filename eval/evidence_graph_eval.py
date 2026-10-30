"""Synthetic regression for the version-DAG evidence graph contract.

All inputs are scalar sidecars.  The runner tests topology, binding and
fail-closed routes; it is not a detector benchmark, provenance proof, or AIGC
effect estimate.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from aigc.evidence_graph import (
    GraphEdge,
    GraphNode,
    ROUTE_BRANCH_CONFLICT,
    ROUTE_GRAPH_CONSISTENT,
    ROUTE_INSUFFICIENT,
    ROUTE_PROPAGATION_LEAK,
    ROUTE_TRAJECTORY_INCONSISTENT,
    evaluate_evidence_graph,
)


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _d(char: str) -> str:
    return char * 64


def _node(node_id: str, support: float, regions=None, *, kind="version", asset="asset-1", quality=0.9):
    return GraphNode(
        node_id=node_id,
        asset_id=asset,
        node_kind=kind,
        manifest_digest=_d("a"),
        canonical_frame_digest=_d("b"),
        detector_version="source-residual-v1",
        score_schema="regional-score-v1",
        support_raw=support,
        region_support=regions or {"r1": support},
        quality_score=quality,
        source_match_score=0.9,
        evidence_digest=_d("c"),
    )


def _edge(edge_id: str, parent: str, child: str, *, scope="content_edit", regions=("r1",), mask=True, null=True):
    return GraphEdge(
        edge_id=edge_id,
        parent_id=parent,
        child_id=child,
        operation_scope=scope,
        operation_type="inpaint" if scope == "content_edit" else "jpeg_reencode",
        transform_digest=_d("d"),
        null_profile_digest=_d("e") if null else None,
        declared_mask_digest=_d("f") if mask else None,
        declared_region_ids=regions,
        upstream_evidence_digest=_d("1"),
    )


def build_cases() -> List[Dict[str, Any]]:
    return [
        {
            "case_id": "consistent_edit_path",
            "expected": ROUTE_GRAPH_CONSISTENT,
            "nodes": [_node("source", 0.05, {"r1": 0.05}, kind="registered_source"), _node("edit", 0.7, {"r1": 0.7}, kind="observed")],
            "edges": [_edge("e1", "source", "edit")],
        },
        {
            "case_id": "ordinary_propagation_leak",
            "expected": ROUTE_PROPAGATION_LEAK,
            "nodes": [_node("source", 0.05, {"r1": 0.05}, kind="registered_source"), _node("prop", 0.7, {"r1": 0.7}, kind="ordinary_null")],
            "edges": [_edge("e1", "source", "prop", scope="ordinary_propagation", regions=(), mask=False)],
        },
        {
            "case_id": "branch_conflict",
            "expected": ROUTE_BRANCH_CONFLICT,
            "nodes": [_node("source", 0.1, {"r1": 0.1}, kind="registered_source"), _node("a", 0.9), _node("b", 0.1)],
            "edges": [_edge("ea", "source", "a"), _edge("eb", "source", "b")],
        },
        {
            "case_id": "off_mask_gain",
            "expected": ROUTE_TRAJECTORY_INCONSISTENT,
            "nodes": [_node("source", 0.05, {"r1": 0.05, "r2": 0.0}, kind="registered_source"), _node("edit", 0.8, {"r1": 0.8, "r2": 0.5}, kind="observed")],
            "edges": [_edge("e1", "source", "edit", regions=("r1",))],
        },
        {
            "case_id": "unsupported_merge",
            "expected": ROUTE_INSUFFICIENT,
            "nodes": [_node("source", 0.1, {"r1": 0.1}, kind="registered_source"), _node("a", 0.5), _node("b", 0.5), _node("merge", 0.6)],
            "edges": [_edge("ea", "source", "a"), _edge("eb", "source", "b"), _edge("em", "a", "merge"), _edge("em2", "b", "merge")],
        },
        {
            "case_id": "quality_gap",
            "expected": ROUTE_INSUFFICIENT,
            "nodes": [_node("source", 0.1, {"r1": 0.1}, kind="registered_source"), _node("edit", 0.6, quality=0.1)],
            "edges": [_edge("e1", "source", "edit")],
        },
    ]


def run() -> Dict[str, Any]:
    rows = []
    for case in build_cases():
        result = evaluate_evidence_graph(case["nodes"], case["edges"])
        rows.append({
            "case_id": case["case_id"],
            "expected_route": case["expected"],
            "result": result.to_dict(),
            "expectation_met": result.route == case["expected"],
        })
    payload = {
        "version": "evidence-graph-synthetic-v1",
        "interpretation": "synthetic raw topology contract only; no route is an AIGC probability or provenance proof",
        "case_count": len(rows),
        "route_counts": {
            route: sum(row["result"]["route"] == route for row in rows)
            for route in sorted({row["result"]["route"] for row in rows})
        },
        "all_expectations_met": all(row["expectation_met"] for row in rows),
        "cases": rows,
    }
    payload["dataset_digest"] = _digest(payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True, indent=2))
