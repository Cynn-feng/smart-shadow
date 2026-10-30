"""Synthetic contract runner for source-conditioned crop consensus."""

from __future__ import annotations

import hashlib
import json

from aigc.crop_consensus import CropConsensusConfig, evaluate_crop_consensus
from tests.test_crop_consensus import make_nulls, make_views


def main() -> int:
    config = CropConsensusConfig(minimum_view_count=3, minimum_null_count=4, alpha=0.20)
    cases = {
        "consensus": evaluate_crop_consensus(
            make_views(({"r-target": 0.50, "r-other": 0.01}, {"r-target": 0.55, "r-other": 0.02}, {"r-target": 0.52, "r-other": 0.03})),
            make_nulls((0.05, 0.06, 0.07, 0.08)), config=config,
        ).to_dict(),
        "inconsistent": evaluate_crop_consensus(
            make_views(({"r-a": 0.50}, {"r-b": 0.52}, {"r-c": 0.51})),
            make_nulls((0.01, 0.02, 0.03, 0.04)), config=config,
        ).to_dict(),
        "ordinary": evaluate_crop_consensus(
            make_views(({"r-target": 0.50}, {"r-target": 0.51}, {"r-target": 0.52}, {"r-target": 0.53}, {"r-target": 0.01})),
            make_nulls((0.70, 0.71, 0.72, 0.73)), config=config,
        ).to_dict(),
    }
    digest = hashlib.sha256(json.dumps(cases, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    summary = {
        "version": "crop-consensus-eval-v1",
        "routes": {name: payload["route"] for name, payload in cases.items()},
        "p_values": {name: payload["p_value_raw"] for name, payload in cases.items()},
        "dataset_digest": digest,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    assert summary["routes"] == {
        "consensus": "consensus_candidate",
        "inconsistent": "view_inconsistent",
        "ordinary": "null_consistent",
    }
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
