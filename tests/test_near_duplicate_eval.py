import unittest

from eval.near_duplicate_eval import run_synthetic_evaluation


class NearDuplicateEvalTests(unittest.TestCase):
    def test_synthetic_runner_is_deterministic_and_reports_three_aggregates(self):
        first = run_synthetic_evaluation()
        second = run_synthetic_evaluation()
        self.assertEqual(first["dataset_digest"], second["dataset_digest"])
        self.assertEqual(first["dataset_digest"], "74f56c7edfe4a77e936d01d3b31b07965d85fe1af9e6d0a2521fdd360d18fb67")
        self.assertEqual(len(first["assets"]), 4)
        self.assertIn("single_original_mean_raw", first["summary"])
        self.assertIn("simple_mean_of_versions_raw", first["summary"])
        self.assertIn("quality_weighted_mean_raw", first["summary"])
        self.assertLess(
            first["summary"]["quality_weighted_mean_raw"],
            first["summary"]["simple_mean_of_versions_raw"],
        )
        self.assertEqual(first["interpretation"].split(";", 1)[0], "synthetic regression only")

    def test_runner_keeps_low_quality_version_in_audit(self):
        result = run_synthetic_evaluation(asset_count=1)
        aggregate = result["assets"][0]["quality_weighted"]
        self.assertEqual(aggregate["rejected_version_ids"], ["synthetic-asset-000-low-quality"])
        self.assertEqual(aggregate["version_audit"][-1]["accepted"], False)
        self.assertEqual(aggregate["version_audit"][-1]["rejection_reason"], "quality_below_threshold")


if __name__ == "__main__":
    unittest.main()
