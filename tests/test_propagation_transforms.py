import io
import unittest

from aigc.propagation_transforms import (
    PropagationConfig,
    TransformSpec,
    apply_propagation_transform,
    build_paired_propagation,
)

try:
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover - dependency gate
    Image = None


@unittest.skipUnless(Image is not None, "Pillow is required")
class PropagationTransformTests(unittest.TestCase):
    @staticmethod
    def image_bytes(*, fmt="PNG", size=(64, 48), offset=0):
        image = Image.new("RGB", size)
        pixels = image.load()
        for y in range(size[1]):
            for x in range(size[0]):
                pixels[x, y] = (
                    (x * 7 + y * 3 + offset) % 256,
                    (x * 2 + y * 11 + 31 + offset) % 256,
                    (x * 13 + y + 73 + offset) % 256,
                )
        output = io.BytesIO()
        image.save(output, format=fmt)
        return output.getvalue()

    def setUp(self):
        self.source = self.image_bytes(offset=0)
        self.query = self.image_bytes(offset=9)

    def test_identity_is_audited_and_enforces_output_bound(self):
        accepted = apply_propagation_transform(self.source, "identity")
        self.assertTrue(accepted.accepted, accepted.to_dict())
        self.assertEqual(accepted.data, self.source)
        self.assertEqual(accepted.audit.parent_sha256, accepted.audit.output_sha256)
        self.assertEqual(accepted.audit.input_format, "PNG")
        self.assertEqual(accepted.audit.output_format, "PNG")

        rejected = apply_propagation_transform(
            self.source,
            "identity",
            config=PropagationConfig(max_output_bytes=len(self.source) - 1),
        )
        self.assertFalse(rejected.accepted)
        self.assertEqual(rejected.reason, "output_too_large")

    def test_supported_transform_families_record_shape_and_format(self):
        cases = [
            ("jpeg_reencode", {"quality": 70}, (64, 48), "JPEG"),
            ("resize", {"scale": 0.5}, (32, 24), "PNG"),
            ("center_crop", {"fraction": 0.5}, (32, 24), "PNG"),
            ("blur", {"radius": 1.5}, (64, 48), "PNG"),
            ("screenshot_sim", {"scale": 0.5, "quality": 70}, (32, 24), "JPEG"),
        ]
        for family, params, expected_size, expected_format in cases:
            with self.subTest(family=family):
                result = apply_propagation_transform(self.source, family, params=params)
                self.assertTrue(result.accepted, result.to_dict())
                self.assertEqual(result.audit.output_size, expected_size)
                self.assertEqual(result.audit.output_format, expected_format)
                self.assertEqual(result.audit.transform_family, family)
                self.assertEqual(result.audit.operation_chain, (family,))

    def test_composite_and_paired_outputs_are_deterministic(self):
        spec = TransformSpec(
            "composite",
            {
                "steps": [
                    {"family": "resize", "params": {"scale": 0.5}},
                    {"family": "jpeg_reencode", "params": {"quality": 70}},
                ]
            },
        )
        first = apply_propagation_transform(self.source, spec)
        second = apply_propagation_transform(self.source, spec)
        self.assertTrue(first.accepted, first.to_dict())
        self.assertEqual(first.data, second.data)
        self.assertEqual(first.audit.to_dict(), second.audit.to_dict())
        self.assertEqual(first.audit.operation_chain, ("resize", "jpeg_reencode"))

        pair = build_paired_propagation(self.source, self.query, spec)
        pair_again = build_paired_propagation(self.source, self.query, spec)
        self.assertTrue(pair.accepted, pair.to_dict())
        self.assertEqual(pair.pair_digest, pair_again.pair_digest)
        self.assertEqual(pair.source.audit.transform_family, "composite")
        self.assertEqual(pair.query.audit.transform_family, "composite")

    def test_invalid_params_and_chain_shapes_fail_closed(self):
        invalid_quality = apply_propagation_transform(
            self.source, "jpeg_reencode", params={"quality": 0}
        )
        self.assertFalse(invalid_quality.accepted)
        self.assertEqual(invalid_quality.reason, "invalid_params")
        unknown_family = apply_propagation_transform(self.source, "unknown_family")
        self.assertFalse(unknown_family.accepted)
        self.assertEqual(unknown_family.reason, "invalid_params")
        malformed_chain = apply_propagation_transform(
            self.source,
            TransformSpec("composite", {"steps": [{"params": {}}]}),
        )
        self.assertFalse(malformed_chain.accepted)
        self.assertEqual(malformed_chain.reason, "chain_invalid")
        too_many = apply_propagation_transform(
            self.source,
            TransformSpec(
                "composite",
                {"steps": [{"family": "blur", "params": {"radius": 0.1}}] * 7},
            ),
        )
        self.assertFalse(too_many.accepted)
        self.assertEqual(too_many.reason, "chain_invalid")

    def test_decode_and_resource_limits_are_explicit(self):
        invalid = apply_propagation_transform(b"not-an-image", "identity")
        self.assertFalse(invalid.accepted)
        self.assertEqual(invalid.reason, "decode_failed")
        too_large = apply_propagation_transform(
            self.source,
            "identity",
            config=PropagationConfig(max_input_bytes=len(self.source) - 1),
        )
        self.assertFalse(too_large.accepted)
        self.assertEqual(too_large.reason, "input_too_large")
        too_many_pixels = apply_propagation_transform(
            self.source,
            "identity",
            config=PropagationConfig(max_pixels=100),
        )
        self.assertFalse(too_many_pixels.accepted)
        self.assertEqual(too_many_pixels.reason, "pixel_limit_exceeded")
        too_wide = apply_propagation_transform(
            self.source,
            "identity",
            config=PropagationConfig(max_dimension=32),
        )
        self.assertFalse(too_wide.accepted)
        self.assertEqual(too_wide.reason, "pixel_limit_exceeded")

    def test_multipage_and_pair_failures_keep_reason_context(self):
        first = Image.new("RGB", (64, 48), (20, 30, 40))
        second = Image.new("RGB", (64, 48), (40, 30, 20))
        output = io.BytesIO()
        first.save(output, format="TIFF", save_all=True, append_images=[second])
        multipage = apply_propagation_transform(output.getvalue(), "identity")
        self.assertFalse(multipage.accepted)
        self.assertEqual(multipage.reason, "animated_or_multipage")

        pair = build_paired_propagation(self.source, b"bad", "identity")
        self.assertFalse(pair.accepted)
        self.assertEqual(pair.reason, "query:decode_failed")
        self.assertTrue(pair.source.accepted)
        self.assertFalse(pair.query.accepted)

    def test_specs_canonicalize_mapping_order_and_non_bytes_reject(self):
        first = TransformSpec("jpeg_reencode", {"quality": 70, "progressive": False})
        second = TransformSpec("jpeg_reencode", {"progressive": False, "quality": 70})
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.digest, second.digest)
        non_bytes = apply_propagation_transform(bytearray(self.source), first)
        self.assertFalse(non_bytes.accepted)
        self.assertEqual(non_bytes.reason, "invalid_params")


if __name__ == "__main__":
    unittest.main()
