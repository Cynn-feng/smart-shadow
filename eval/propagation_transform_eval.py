"""Synthetic regression for bounded ordinary propagation transforms.

The runner exercises the byte-level transform audit and paired source/query
contract.  It does not create AI edits, infer provenance, or evaluate AIGC
accuracy.
"""

from __future__ import annotations

import hashlib
import io
import json
from typing import Any, Dict, Iterable, List

from PIL import Image

from aigc.propagation_transforms import (
    PropagationConfig,
    TransformSpec,
    apply_propagation_transform,
    build_paired_propagation,
)


def _image_bytes(offset: int = 0) -> bytes:
    image = Image.new("RGB", (64, 48))
    pixels = image.load()
    for y in range(48):
        for x in range(64):
            pixels[x, y] = (
                (x * 7 + y * 3 + offset) % 256,
                (x * 2 + y * 11 + 31 + offset) % 256,
                (x * 13 + y + 73 + offset) % 256,
            )
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def run_synthetic_evaluation() -> Dict[str, Any]:
    source = _image_bytes(0)
    query = _image_bytes(9)
    specs = [
        TransformSpec("identity"),
        TransformSpec("jpeg_reencode", {"quality": 75}),
        TransformSpec("resize", {"scale": 0.5}),
        TransformSpec("center_crop", {"fraction": 0.8}),
        TransformSpec("blur", {"radius": 1.25}),
        TransformSpec("screenshot_sim", {"scale": 0.75, "quality": 70}),
        TransformSpec(
            "composite",
            {
                "steps": [
                    {"family": "resize", "params": {"scale": 0.75}},
                    {"family": "jpeg_reencode", "params": {"quality": 65}},
                ]
            },
        ),
    ]
    pairs = []
    for spec in specs:
        first = build_paired_propagation(source, query, spec)
        second = build_paired_propagation(source, query, spec)
        pairs.append(
            {
                "spec": spec.to_dict(),
                "accepted": first.accepted,
                "reason": first.reason,
                "pair_digest": first.pair_digest,
                "deterministic_pair_digest": first.pair_digest == second.pair_digest,
                "source": first.source.to_dict(),
                "query": first.query.to_dict(),
            }
        )
    invalid = apply_propagation_transform(source, "jpeg_reencode", params={"quality": 0})
    output_bound = apply_propagation_transform(
        source,
        "identity",
        config=PropagationConfig(max_output_bytes=len(source) - 1),
    )
    boundary = [
        {"case_id": "invalid_quality", **invalid.to_dict()},
        {"case_id": "identity_output_bound", **output_bound.to_dict()},
    ]
    all_records = pairs + boundary
    return {
        "version": "propagation-transform-synthetic-v1",
        "input_sha256": hashlib.sha256(source).hexdigest(),
        "pair_count": len(pairs),
        "accepted_pair_count": sum(item["accepted"] for item in pairs),
        "all_pairs_deterministic": all(item["deterministic_pair_digest"] for item in pairs),
        "boundary_cases": boundary,
        "dataset_digest": _digest(all_records),
        "pairs": pairs,
        "interpretation": (
            "synthetic byte-level propagation regression only; transform audits "
            "and pair digests do not establish AIGC accuracy, provenance, or legal conclusions"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
