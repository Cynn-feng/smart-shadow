import hashlib
import json
import unittest

from aigc.multistream import EvidenceStreamObservation, ROUTE_CANDIDATE, ROUTE_CONFLICT_REVIEW, ROUTE_INSUFFICIENT, ROUTE_NULL_CONSISTENT
from aigc.multistream_calibration import (
    MultiStreamCalibrationConfig,
    StreamNullExample,
    evaluate_calibrated_multistream,
    fit_stream_null_profiles,
)


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _stream(
    stream_id,
    score=None,
    *,
    accepted=True,
    quality=0.9,
    paired=True,
    reason=None,
    score_schema=None,
):
    return EvidenceStreamObservation(
        stream_id=stream_id,
        accepted=accepted,
        paired=paired,
        score_raw=score if accepted else None,
        quality_score=quality if accepted else None,
        reason=reason if not accepted else None,
        detector_version=f"{stream_id}-detector-v1",
        score_schema=score_schema or f"{stream_id}-score-v1",
        config_digest=_digest({"stream": stream_id, "config": 1}),
        input_digests=(_digest({"input": stream_id}),) if accepted else (),
        evidence_digest=_digest({"stream": stream_id, "score": score, "accepted": accepted}),
    )


def _profiles(count=60):
    examples = []
    for stream_id in ("pixel_residual", "spectral"):
        for index in range(count):
            examples.append(
                StreamNullExample(
                    stream_id=stream_id,
                    score_raw=0.05,
                    group_id=f"{stream_id}-null-{index}",
                    detector_version=f"{stream_id}-detector-v1",
                    score_schema=f"{stream_id}-score-v1",
                    transform_family="jpeg_q75",
                )
            )
    return fit_stream_null_profiles(examples)


class MultiStreamCalibrationTests(unittest.TestCase):
    def test_candidate_requires_concordant_calibrated_null_rejection(self):
        result = evaluate_calibrated_multistream(
            (_stream("pixel_residual", 0.9), _stream("spectral", 0.85)),
            _profiles(),
        )
        self.assertEqual(result.route, ROUTE_CANDIDATE)
        self.assertFalse(result.abstained)
        self.assertTrue(all(item.reject_null for item in result.stream_results))
        self.assertEqual(len(result.profile_digests), 2)

    def test_ordinary_propagation_is_null_consistent_without_claiming_human(self):
        result = evaluate_calibrated_multistream(
            (_stream("pixel_residual", 0.05), _stream("spectral", 0.05)),
            _profiles(),
        )
        self.assertEqual(result.route, ROUTE_NULL_CONSISTENT)
        self.assertFalse(result.abstained)
        self.assertTrue(all(not item.reject_null for item in result.stream_results))
        self.assertNotIn("human", json.dumps(result.to_dict(), ensure_ascii=False))

    def test_partial_rejection_is_review_without_score_averaging(self):
        result = evaluate_calibrated_multistream(
            (_stream("pixel_residual", 0.05), _stream("spectral", 0.85)),
            _profiles(),
        )
        self.assertEqual(result.route, ROUTE_CONFLICT_REVIEW)
        self.assertTrue(result.abstained)
        self.assertEqual([item.score_raw for item in result.stream_results], [0.05, 0.85])

    def test_missing_stream_keeps_missing_score_as_none_and_abstains(self):
        unavailable = _stream("spectral", accepted=False, reason="detector_unavailable")
        result = evaluate_calibrated_multistream(
            (_stream("pixel_residual", 0.9), unavailable),
            _profiles(),
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertTrue(result.abstained)
        records = {item.stream_id: item for item in result.stream_results}
        self.assertEqual(records["spectral"].score_raw, None)
        self.assertEqual(records["spectral"].reason, "detector_unavailable")

    def test_schema_and_null_support_mismatch_fail_closed(self):
        result = evaluate_calibrated_multistream(
            (_stream("pixel_residual", 0.9), _stream("spectral", 0.9)),
            _profiles(count=3),
            config=MultiStreamCalibrationConfig(minimum_null_count=20),
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "null_support_below_minimum")

        bad_schema = _stream("spectral", 0.9, score_schema="wrong-score-v1")
        result = evaluate_calibrated_multistream(
            (_stream("pixel_residual", 0.9), bad_schema),
            _profiles(),
        )
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertEqual(result.reason, "detector_or_schema_mismatch")

    def test_config_and_profile_digests_are_reproducible(self):
        profiles_a = _profiles()
        profiles_b = _profiles()
        self.assertEqual(
            [profile.profile_digest for profile in profiles_a],
            [profile.profile_digest for profile in profiles_b],
        )
        result_a = evaluate_calibrated_multistream(
            (_stream("pixel_residual", 0.9), _stream("spectral", 0.9)),
            profiles_a,
        )
        result_b = evaluate_calibrated_multistream(
            (_stream("pixel_residual", 0.9), _stream("spectral", 0.9)),
            profiles_b,
        )
        self.assertEqual(result_a.evidence_digest, result_b.evidence_digest)


if __name__ == "__main__":
    unittest.main()
