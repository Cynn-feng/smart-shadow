import io
import unittest

try:
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover - skipped in the base runtime
    Image = None

from aigc import image_adapter as adapter


@unittest.skipUnless(Image is not None and adapter.np is not None, "Pillow and NumPy are required")
class ImageAdapterTests(unittest.TestCase):
    def image_bytes(self, fmt="PNG", *, size=(64, 48), mode="RGB", exif_orientation=None):
        np = adapter.np
        yy, xx = np.mgrid[0 : size[1], 0 : size[0]]
        rgb = np.stack(
            [
                (xx * 5 + yy * 3) % 256,
                (xx * 2 + yy * 7 + 31) % 256,
                (xx * 11 + yy + 73) % 256,
            ],
            axis=-1,
        ).astype("uint8")
        image = Image.fromarray(rgb, "RGB")
        if mode == "RGBA":
            image = image.convert("RGBA")
            alpha = Image.new("L", size, 180)
            image.putalpha(alpha)
        output = io.BytesIO()
        save_kwargs = {}
        if exif_orientation is not None:
            exif = Image.Exif()
            exif[274] = exif_orientation
            save_kwargs["exif"] = exif
        image.save(output, format=fmt, **save_kwargs)
        return output.getvalue()

    def test_supported_formats_are_decoded_and_digests_are_stable(self):
        for fmt in ("PNG", "JPEG", "WEBP", "TIFF", "BMP"):
            with self.subTest(fmt=fmt):
                first = adapter.decode_image_bytes(self.image_bytes(fmt))
                second = adapter.decode_image_bytes(self.image_bytes(fmt))
                self.assertTrue(first.accepted, first.to_dict())
                self.assertIsNone(first.reason)
                self.assertEqual(first.audit.raw_sha256, second.audit.raw_sha256)
                self.assertEqual(first.audit.normalized_sha256, second.audit.normalized_sha256)
                self.assertEqual(first.gray.shape, (48, 64))
                self.assertGreaterEqual(first.quality.quality_score, 0.15)

    def test_invalid_and_truncated_bytes_have_explicit_reasons(self):
        invalid = adapter.decode_image_bytes(b"not-an-image")
        self.assertFalse(invalid.accepted)
        self.assertIn(invalid.reason, {"decode_failed", "truncated_or_corrupt"})
        truncated = adapter.decode_image_bytes(self.image_bytes("PNG")[:20])
        self.assertFalse(truncated.accepted)
        self.assertIn(truncated.reason, {"decode_failed", "truncated_or_corrupt"})

    def test_size_geometry_and_pixel_limits_are_hard_gates(self):
        raw = self.image_bytes("PNG")
        too_small = adapter.decode_image_bytes(raw, adapter.AdapterConfig(min_side=100))
        self.assertEqual(too_small.reason, "min_side_too_small")
        too_wide = adapter.decode_image_bytes(
            self.image_bytes("PNG", size=(512, 16)),
            adapter.AdapterConfig(max_aspect_ratio=10),
        )
        self.assertEqual(too_wide.reason, "aspect_ratio_exceeded")
        too_many = adapter.decode_image_bytes(
            self.image_bytes("PNG", size=(64, 48)),
            adapter.AdapterConfig(max_pixels=100),
        )
        self.assertEqual(too_many.reason, "pixel_limit_exceeded")
        too_large = adapter.decode_image_bytes(raw, adapter.AdapterConfig(max_bytes=10))
        self.assertEqual(too_large.reason, "bytes_too_large")

    def test_alpha_policy_is_explicit(self):
        raw = self.image_bytes("PNG", mode="RGBA")
        rejected = adapter.decode_image_bytes(raw)
        self.assertEqual(rejected.reason, "alpha_policy_rejected")
        composited = adapter.decode_image_bytes(raw, adapter.AdapterConfig(alpha_policy="composite"))
        self.assertTrue(composited.accepted, composited.to_dict())
        self.assertIn("alpha_composited", composited.audit.warnings)

    def test_flat_and_clipped_content_does_not_become_forensic_ready(self):
        flat = Image.new("RGB", (64, 48), (128, 128, 128))
        out = io.BytesIO()
        flat.save(out, format="PNG")
        result = adapter.decode_image_bytes(out.getvalue())
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "flat_region")
        clipped = Image.new("RGB", (64, 48), (255, 255, 255))
        out = io.BytesIO()
        clipped.save(out, format="PNG")
        result = adapter.decode_image_bytes(out.getvalue())
        self.assertFalse(result.accepted)
        self.assertIn(result.reason, {"flat_region", "clipping_excessive"})

    def test_exif_orientation_is_applied_and_audit_kept(self):
        raw = self.image_bytes("JPEG", size=(64, 48), exif_orientation=6)
        result = adapter.decode_image_bytes(raw)
        self.assertTrue(result.accepted, result.to_dict())
        self.assertEqual(result.audit.exif_orientation, 6)
        self.assertEqual(result.audit.normalized_size, (48, 64))
        self.assertEqual(tuple(result.gray.shape), (64, 48))

    def test_multipage_tiff_is_rejected(self):
        first = Image.new("RGB", (64, 48), (10, 20, 30))
        second = Image.new("RGB", (64, 48), (30, 20, 10))
        out = io.BytesIO()
        first.save(out, format="TIFF", save_all=True, append_images=[second])
        result = adapter.decode_image_bytes(out.getvalue())
        self.assertEqual(result.reason, "animated_or_multipage")

    def test_file_entrypoint_uses_same_contract(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.png"
            path.write_bytes(self.image_bytes("PNG"))
            result = adapter.decode_image_file(path)
            self.assertTrue(result.accepted)
            self.assertEqual(result.audit.raw_sha256, adapter._digest(path.read_bytes()))


if __name__ == "__main__":
    unittest.main()
