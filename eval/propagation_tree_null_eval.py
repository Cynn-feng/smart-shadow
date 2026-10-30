"""Synthetic SCPTN contract runner; no model or image data is loaded."""

from __future__ import annotations

import hashlib
import json
from typing import Dict, Iterable, List

from aigc.propagation_tree_null import (
    CONTENT_EDIT,
    ORDINARY_PROPAGATION,
    PropagationTree,
    PropagationTreeConfig,
    PropagationTreeNode,
    evaluate_propagation_tree_null,
    fit_propagation_tree_null_profile,
)


def _digest(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _tree(tree_id: str, *, split: str, split_digest: str, scope: str, deltas: Iterable[float],
          asset_id: str | None = None, transform: str = "jpeg") -> PropagationTree:
    asset_id = asset_id or f"asset-{tree_id}"
    values = tuple(float(value) for value in deltas)
    nodes = tuple(
        PropagationTreeNode(
            version_id=f"{tree_id}-v{index}",
            parent_version_id=None if index == 0 else f"{tree_id}-v{index - 1}",
            asset_id=asset_id,
            tree_id=tree_id,
            transform_family=transform,
            quality_bucket="high",
            time_bucket="t0",
            source_match_bucket="matched",
            operation_scope=scope,
            paired_delta_raw=value,
            quality_score=0.95,
            source_match_score=0.95,
            node_order=index,
        )
        for index, value in enumerate(values)
    )
    return PropagationTree(
        tree_id=tree_id,
        asset_id=asset_id,
        manifest_digest="a" * 64,
        split_digest=split_digest,
        detector_version="detector-v1",
        score_schema="paired-delta-v1",
        transform_family=transform,
        quality_bucket="high",
        time_bucket="t0",
        source_match_bucket="matched",
        nodes=nodes,
        split=split,
    )


def main() -> None:
    config = PropagationTreeConfig(
        minimum_tree_support=8,
        minimum_nodes_per_tree=3,
        alpha=0.20,
        minimum_selected_delta=0.01,
    )
    calibration = [
        _tree(f"null-{index}", split="calibration", split_digest="b" * 64,
              scope=ORDINARY_PROPAGATION, deltas=(0.01, 0.02, 0.03))
        for index in range(8)
    ]
    profile = fit_propagation_tree_null_profile(calibration, config)
    cases = [
        ("edited_tree_candidate", _tree("candidate", split="evaluation", split_digest="c" * 64,
                                         scope=CONTENT_EDIT, deltas=(0.70, 0.80, 0.75))),
        ("ordinary_tree_null", _tree("ordinary", split="evaluation", split_digest="c" * 64,
                                      scope=ORDINARY_PROPAGATION, deltas=(0.80, 0.70, 0.60))),
        ("selection_tie", _tree("tie", split="evaluation", split_digest="c" * 64,
                                 scope=CONTENT_EDIT, deltas=(0.03, 0.025, 0.02))),
        ("low_selected_delta", _tree("low", split="evaluation", split_digest="c" * 64,
                                      scope=CONTENT_EDIT, deltas=(0.001, 0.002, 0.003))),
        ("stratum_mismatch", _tree("mismatch", split="evaluation", split_digest="c" * 64,
                                   scope=CONTENT_EDIT, deltas=(0.80, 0.70, 0.60), transform="resize")),
    ]
    rows: List[Dict[str, object]] = []
    for case_id, tree in cases:
        result = evaluate_propagation_tree_null(tree, profile, config)
        rows.append({"case_id": case_id, "result": result.to_dict()})
    route_counts: Dict[str, int] = {}
    for row in rows:
        route = row["result"]["route"]
        route_counts[route] = route_counts.get(route, 0) + 1
    dataset_digest = _digest({"cases": rows, "profile": profile.to_dict(), "config": config.to_dict()})
    print(json.dumps({
        "version": "source-conditioned-propagation-tree-null-synthetic-v1",
        "count": len(rows),
        "route_counts": dict(sorted(route_counts.items())),
        "config_digest": config.digest,
        "profile_digest": profile.profile_digest,
        "dataset_digest": dataset_digest,
        "cases": rows,
        "interpretation": "synthetic raw contract only; tree routes are not AIGC probabilities or legal findings",
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
