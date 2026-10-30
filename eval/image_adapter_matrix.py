"""Deterministic adapter matrix; synthetic only until an authorized manifest exists."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence

from PIL import Image

from aigc.image_adapter import AdapterConfig, decode_image_bytes


def _image_bytes(fmt: str, *, size=(64, 48), mode="RGB") -> bytes:
    image = Image.new("RGB", size)
    pixels = image.load()
    for y in range(size[1]):
        for x in range(size[0]):
            pixels[x, y] = ((x * 5 + y * 3) % 256, (x * 2 + y * 7 + 31) % 256, (x * 11 + y + 73) % 256)
    if mode == "RGBA":
        image = image.convert("RGBA")
        image.putalpha(Image.new("L", size, 180))
    output = io.BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


def _fixtures() -> Iterable[Mapping[str, object]]:
    yield {"sample_id": "png", "payload": _image_bytes("PNG"), "config": AdapterConfig()}
    yield {"sample_id": "jpeg", "payload": _image_bytes("JPEG"), "config": AdapterConfig()}
    yield {"sample_id": "webp", "payload": _image_bytes("WEBP"), "config": AdapterConfig()}
    yield {"sample_id": "tiff", "payload": _image_bytes("TIFF"), "config": AdapterConfig()}
    yield {"sample_id": "bmp", "payload": _image_bytes("BMP"), "config": AdapterConfig()}
    yield {"sample_id": "invalid", "payload": b"not-an-image", "config": AdapterConfig()}
    yield {"sample_id": "truncated", "payload": _image_bytes("PNG")[:20], "config": AdapterConfig()}
    yield {"sample_id": "alpha-rejected", "payload": _image_bytes("PNG", mode="RGBA"), "config": AdapterConfig()}
    yield {"sample_id": "pixel-limit", "payload": _image_bytes("PNG"), "config": AdapterConfig(max_pixels=100)}


def run_synthetic_matrix() -> Dict[str, object]:
    reports: List[Mapping[str, object]] = []
    for item in _fixtures():
        result = decode_image_bytes(item["payload"], item["config"])
        reports.append(
            {
                "sample_id": item["sample_id"],
                "accepted": result.accepted,
                "reason": result.reason,
                "audit_digest": result.audit.digest,
                "raw_sha256": result.audit.raw_sha256,
                "detected_format": result.audit.detected_format,
                "quality": result.quality.to_dict() if result.quality else None,
            }
        )
    canonical = json.dumps(reports, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    reasons: Dict[str, int] = {}
    for report in reports:
        reason = report["reason"] or "accepted"
        reasons[reason] = reasons.get(reason, 0) + 1
    return {
        "version": "image-adapter-matrix-synthetic-v1",
        "synthetic_only": True,
        "count": len(reports),
        "accepted_count": sum(1 for report in reports if report["accepted"]),
        "reason_counts": dict(sorted(reasons.items())),
        "dataset_digest": hashlib.sha256(canonical).hexdigest(),
        "reports": reports,
        "interpretation": "synthetic adapter regression only; no real-image quality or AIGC claim",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, help="reserved for an authorized image manifest")
    args = parser.parse_args(argv)
    if args.manifest is not None:
        raise SystemExit("real manifest adapter evaluation is not enabled in this synthetic-only runner")
    print(json.dumps(run_synthetic_matrix(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
