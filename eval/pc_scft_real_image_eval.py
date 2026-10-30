"""Contract regression for the private real-image PC-SCFT runner.

The fixture is generated at runtime and is intentionally labelled synthetic.
It checks authorization, byte hashes, deterministic normalized digests and the
fail-closed ``calibration_unavailable`` route.  It does not claim real-image
AIGC accuracy and does not fit a production null profile.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
from typing import Any, Dict, List

from PIL import Image

from aigc.real_image_runner import run_real_image_manifest


def _image_bytes(*, edited: bool = False, quality: int | None = None) -> bytes:
    image = Image.new("RGB", (64, 64))
    pixels = image.load()
    for y in range(64):
        for x in range(64):
            red = (x * 7 + y * 3 + 17) % 256
            green = (x * 2 + y * 11 + 31) % 256
            blue = (x * 13 + y + 73) % 256
            if edited and 20 <= x < 42 and 18 <= y < 44:
                red, green, blue = min(255, red + 65), max(0, green - 45), blue
            pixels[x, y] = (red, green, blue)
    output = io.BytesIO()
    kwargs = {"quality": quality} if quality is not None else {}
    image.save(output, format="JPEG" if quality is not None else "PNG", **kwargs)
    return output.getvalue()


def _record(
    *,
    sample_id: str,
    role: str,
    path: str,
    data: bytes,
    parent_sample_id: str | None,
    pair_id: str = "pair-001",
) -> Dict[str, Any]:
    return {
        "sample_id": sample_id,
        "asset_id": "asset-001",
        "role": role,
        "pair_id": pair_id,
        "transform_family": "jpeg_q75",
        "split": "external",
        "sample_path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "authorization_id": "auth-synthetic-001",
        "authorization_scope": "research-only",
        "authorization_expiry": "2099-12-31T23:59:59Z",
        "authorized_for_research": True,
        "origin": "synthetic_fixture",
        "generator_family": "none",
        "parent_sample_id": parent_sample_id,
        "postprocess_chain": ["synthetic-fixture"],
        "resolution": [64, 64],
        "c2pa_status": "absent",
        "region_type_map": {
            "g0c0": "object",
            "g0c1": "stuff",
            "g1c0": "background",
            "g1c1": "object",
        },
    }


def run_synthetic_evaluation() -> Dict[str, Any]:
    reference = _image_bytes()
    observed = _image_bytes(edited=True)
    counterfactual = _image_bytes(quality=75)
    with tempfile.TemporaryDirectory(prefix="smart-shadow-real-pc-scft-") as directory:
        root = Path(directory)
        (root / "reference.jpg").write_bytes(reference)
        (root / "observed.jpg").write_bytes(observed)
        (root / "counterfactual.jpg").write_bytes(counterfactual)
        records: List[Dict[str, Any]] = [
            _record(sample_id="sample-ref-001", role="reference", path="reference.jpg", data=reference, parent_sample_id=None),
            _record(sample_id="sample-obs-001", role="observed", path="observed.jpg", data=observed, parent_sample_id="sample-ref-001"),
            _record(sample_id="sample-cf-001", role="counterfactual", path="counterfactual.jpg", data=counterfactual, parent_sample_id="sample-ref-001"),
        ]
        first = run_real_image_manifest(
            records,
            root,
            now=datetime(2026, 9, 20, tzinfo=timezone.utc),
        )
        second = run_real_image_manifest(
            records,
            root,
            now=datetime(2026, 9, 20, tzinfo=timezone.utc),
        )
    first_case = first["cases"][0] if first.get("cases") else {}
    second_case = second["cases"][0] if second.get("cases") else {}
    canonical_first = json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    canonical_second = json.dumps(second, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "version": "pc-scft-real-image-synthetic-contract-v1",
        "manifest_digest": first.get("manifest_digest"),
        "manifest_errors": first.get("manifest_errors"),
        "deterministic_result_digest": hashlib.sha256(canonical_first.encode("utf-8")).hexdigest(),
        "repeat_digest_equal": canonical_first == canonical_second,
        "status_counts": first.get("status_counts"),
        "first_case_status": first_case.get("status"),
        "first_case_reason": first_case.get("reason"),
        "score_batches_present": "score_batches" in first_case,
        "normalized_digest_present": bool(first_case.get("decode_audits")),
        "interpretation": (
            "synthetic contract regression only; this exercises private file authorization, "
            "hash/audit replay and calibration fail-closed behavior, not AIGC accuracy"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
