import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

try:
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover - dependency gate
    Image = None

from aigc.manifest import canonical_real_manifest_digest, validate_real_manifest
from aigc.image_adapter import decode_image_bytes
from aigc.model_adapter import SourceResidualAdapter
from aigc.regional_alignment import align_gray_grids, partition_aligned_regions
from aigc.real_image_runner import run_real_image_manifest


@unittest.skipUnless(Image is not None, "Pillow is required")
class RealImagePCSCFTTests(unittest.TestCase):
    def image_bytes(self, *, edited=False, fmt="PNG"):
        image = Image.new("RGB", (64, 64))
        pixels = image.load()
        for y in range(64):
            for x in range(64):
                value = ((x * 7 + y * 3) % 256, (x * 2 + y * 11 + 31) % 256, (x * 13 + y + 73) % 256)
                if edited and 20 <= x < 42 and 18 <= y < 44:
                    value = (min(value[0] + 70, 255), max(value[1] - 50, 0), value[2])
                pixels[x, y] = value
        output = io.BytesIO()
        image.save(output, format=fmt, **({"quality": 75} if fmt == "JPEG" else {}))
        return output.getvalue()

    def records(self, files):
        common = {
            "asset_id": "asset-1",
            "pair_id": "pair-1",
            "transform_family": "identity",
            "split": "external",
            "authorization_id": "auth-1",
            "authorization_scope": "research-only",
            "authorization_expiry": "2099-12-31T23:59:59Z",
            "authorized_for_research": True,
            "origin": "synthetic_fixture",
            "generator_family": "none",
            "postprocess_chain": [],
            "resolution": [64, 64],
        }
        rows = []
        for sample_id, role, path, parent in (
            ("ref", "reference", "reference.png", None),
            ("obs", "observed", "observed.png", "ref"),
            ("cf", "counterfactual", "counterfactual.png", "ref"),
        ):
            raw = files[path]
            row = dict(common)
            row.update(
                {
                    "sample_id": sample_id,
                    "role": role,
                    "sample_path": path,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "parent_sample_id": parent,
                }
            )
            rows.append(row)
        return rows

    def test_valid_private_manifest_is_deterministic_and_abstains_without_null(self):
        files = {
            "reference.png": self.image_bytes(),
            "observed.png": self.image_bytes(edited=True),
            "counterfactual.png": self.image_bytes(fmt="JPEG"),
        }
        records = self.records(files)
        self.assertEqual(validate_real_manifest(records, now=datetime(2026, 9, 20, tzinfo=timezone.utc)), [])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in files.items():
                (root / name).write_bytes(value)
            first = run_real_image_manifest(records, root, now=datetime(2026, 9, 20, tzinfo=timezone.utc))
            second = run_real_image_manifest(records, root, now=datetime(2026, 9, 20, tzinfo=timezone.utc))
        self.assertEqual(first["manifest_errors"], [])
        self.assertEqual(first["manifest_digest"], canonical_real_manifest_digest(records))
        self.assertEqual(first["cases"][0]["status"], "insufficient")
        self.assertEqual(first["cases"][0]["reason"], "calibration_unavailable")
        self.assertNotIn(str(root), json.dumps(first))
        self.assertEqual(first, second)

    def test_unauthorized_and_hash_drift_fail_closed_without_decoding(self):
        files = {
            "reference.png": self.image_bytes(),
            "observed.png": self.image_bytes(edited=True),
            "counterfactual.png": self.image_bytes(fmt="JPEG"),
        }
        records = self.records(files)
        records[1]["authorized_for_research"] = False
        records[2]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in files.items():
                (root / name).write_bytes(value)
            result = run_real_image_manifest(records, root, now=datetime(2026, 9, 20, tzinfo=timezone.utc))
        self.assertTrue(any("unauthorized_input" in error for error in result["manifest_errors"]))
        self.assertTrue(any("hash_mismatch" in error for error in result["manifest_errors"]))
        self.assertTrue(all(case["reason"] in {"unauthorized_input", "hash_mismatch", "manifest_invalid"} for case in result["cases"]))
        self.assertNotIn("score_batches", json.dumps(result))

    def test_pair_missing_role_is_rejected(self):
        files = {"reference.png": self.image_bytes(), "observed.png": self.image_bytes(edited=True)}
        records = self.records({**files, "counterfactual.png": self.image_bytes(fmt="JPEG")})[:2]
        errors = validate_real_manifest(records, now=datetime(2026, 9, 20, tzinfo=timezone.utc))
        self.assertIn("pair_missing_role:asset-1:pair-1:counterfactual", errors)

    def test_source_residual_adapter_emits_versioned_regional_sidecar(self):
        reference = decode_image_bytes(self.image_bytes())
        query = decode_image_bytes(self.image_bytes(edited=True))
        self.assertTrue(reference.accepted)
        self.assertTrue(query.accepted)
        alignment = align_gray_grids(reference.gray, query.gray)
        regions = partition_aligned_regions(alignment)
        batch = SourceResidualAdapter().score_regions(
            sample_id="query-1",
            asset_id="asset-1",
            pair_id="pair-1",
            role="observed",
            reference_result=reference,
            query_result=query,
            regions=regions,
        )
        self.assertTrue(batch.accepted, batch.to_dict())
        self.assertEqual(len(batch.scores), 4)
        self.assertEqual(batch.to_dict()["evidence_digest"], batch.evidence_digest)
        self.assertTrue(all(0.0 <= score.score_raw <= 1.0 for score in batch.scores))
        self.assertTrue(all(len(score.input_normalized_sha256) == 64 for score in batch.scores))


if __name__ == "__main__":
    unittest.main()
