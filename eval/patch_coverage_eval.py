"""Synthetic regression for patch-coverage evidence shape.

The cases are scalar regional deltas.  They test the routing contract used by
the PC-SCFT research path; they are not labeled AIGC data and do not estimate
detector accuracy.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional

from aigc.patch_coverage import PatchCoverageConfig, PatchDelta, summarize_patch_coverage


def _case(
    case_id: str,
    deltas: Iterable[float],
    *,
    quality: float = 0.90,
    region_types: Optional[Iterable[str]] = None,
    config: Optional[PatchCoverageConfig] = None,
) -> Dict[str, Any]:
    values = tuple(deltas)
    types = tuple(region_types or ("unknown",) * len(values))
    if len(types) != len(values):
        raise ValueError("region_types must match deltas")
    return {
        "case_id": case_id,
        "config": config or PatchCoverageConfig(),
        "patches": [
            PatchDelta(
                region_id=f"r{index}",
                delta_raw=value,
                quality_score=quality,
                source_match_score=0.90,
                detector_version="synthetic-detector-v1",
                score_schema="synthetic-delta-v1",
                region_type=types[index],
            )
            for index, value in enumerate(values)
        ],
    }


def build_synthetic_cases() -> List[Dict[str, Any]]:
    return [
        _case("distributed", (0.45, 0.42, 0.48, 0.44)),
        _case("localized", (0.82, 0.04, 0.02, 0.01)),
        _case("mixed", (0.80, 0.78, 0.03, 0.02)),
        _case("ordinary_propagation", (0.04, 0.06, 0.02, 0.05)),
        _case("low_quality", (0.80, 0.80, 0.80), quality=0.20),
        _case(
            "typed_distributed",
            (0.45, 0.42, 0.48, 0.44),
            region_types=("object", "stuff", "background", "object"),
            config=PatchCoverageConfig(require_region_type_diversity=True),
        ),
        _case(
            "typed_object_shortcut",
            (0.45, 0.42, 0.48, 0.44),
            region_types=("object", "object", "object", "object"),
            config=PatchCoverageConfig(require_region_type_diversity=True),
        ),
    ]


def _digest(cases: Iterable[Dict[str, Any]]) -> str:
    payload = [
        {
            "case_id": case["case_id"],
            "config": case["config"].to_dict(),
            "patches": [item.to_dict() for item in case["patches"]],
        }
        for case in cases
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def run_synthetic_evaluation() -> Dict[str, Any]:
    cases = build_synthetic_cases()
    outputs = []
    for case in cases:
        result = summarize_patch_coverage(case["patches"], config=case["config"])
        outputs.append({"case_id": case["case_id"], "result": result.to_dict()})
    status_counts: Dict[str, int] = {}
    for item in outputs:
        status = item["result"]["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "version": "patch-coverage-synthetic-v1",
        "count": len(outputs),
        "dataset_digest": _digest(cases),
        "status_counts": status_counts,
        "cases": outputs,
        "interpretation": (
            "synthetic regression only; patch coverage is raw routing evidence, "
            "not an AIGC probability, human/AI conclusion, or legal finding"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
