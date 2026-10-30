import unittest

from eval.source_residual_eval import (
    DEFAULT_SEED,
    build_synthetic_dataset,
    run_synthetic_evaluation,
    score_examples,
)


class SourceResidualEvalTests(unittest.TestCase):
    def test_synthetic_protocol_is_deterministic(self):
        first = run_synthetic_evaluation()
        second = run_synthetic_evaluation()
        self.assertEqual(first["dataset_digest"], second["dataset_digest"])
        self.assertEqual(first["auroc"], second["auroc"])
        self.assertEqual(first["count"], 30)
        self.assertEqual(first["positive_roi_iou_mean"], 1.0)
        self.assertEqual(first["negative_roi_activation_rate"], 0.0)

    def test_global_brightness_is_a_hard_negative(self):
        examples = build_synthetic_dataset(seed=DEFAULT_SEED, repeats=1, size=32)
        scored = score_examples(examples)
        brightness = next(item for item in scored if item.category == "global_brightness")
        self.assertEqual(brightness.label, 0)
        self.assertLess(brightness.score, 0.01)

    def test_fixed_threshold_is_reported_as_uncalibrated(self):
        result = run_synthetic_evaluation(threshold=0.5)
        self.assertEqual(result["fixed_threshold"]["recall"], 0.0)
        self.assertIn("not calibrated", result["interpretation"])

    def test_missing_class_does_not_fabricate_auc(self):
        examples = build_synthetic_dataset(seed=DEFAULT_SEED, repeats=1, size=32)
        negatives = tuple(item for item in examples if item.label == 0)
        result = run_synthetic_evaluation(seed=DEFAULT_SEED, repeats=1, size=32)
        # The public runner has both classes; the scoring function remains
        # usable for a one-class slice, while AUROC/AP are intentionally null.
        from eval.source_residual_eval import evaluate_scored

        scored = score_examples(negatives)
        one_class = evaluate_scored(scored)
        self.assertIsNone(one_class["auroc"])
        self.assertIsNone(one_class["average_precision"])
        self.assertEqual(result["positive_count"], 4)


if __name__ == "__main__":
    unittest.main()
