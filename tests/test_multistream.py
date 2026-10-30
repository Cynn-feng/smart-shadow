import hashlib
import json
import unittest

from aigc.multistream import (
    EvidenceStreamObservation,
    MultiStreamRouteConfig,
    ROUTE_CANDIDATE,
    ROUTE_CONFLICT_REVIEW,
    ROUTE_INSUFFICIENT,
    ROUTE_NULL_CONSISTENT,
    route_multistream_evidence,
)


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _observation(stream_id, score, *, paired=True, quality=0.9, accepted=True, reason=None):
    marker = _digest({"stream": stream_id, "score": score, "accepted": accepted})
    return EvidenceStreamObservation(
        stream_id=stream_id,
        accepted=accepted,
        paired=paired,
        score_raw=score if accepted else None,
        quality_score=quality if accepted else None,
        reason=reason if not accepted else None,
        detector_version=f"{stream_id}-detector-v1",
        score_schema=f"{stream_id}-score-v1",
        config_digest=_digest({"stream": stream_id, "config": 1}),
        input_digests=(_digest({"input": stream_id}),) if accepted else (),
        evidence_digest=marker,
        details={"fixture": True},
    )


class MultiStreamRouterTests(unittest.TestCase):
    def test_concordant_positive_preserves_independent_stream_records(self):
        result = route_multistream_evidence(
            (_observation("pixel_residual", 0.82), _observation("spectral", 0.71))
        )
        self.assertEqual(result.route, ROUTE_CANDIDATE)
        self.assertFalse(result.abstained)
        self.assertEqual(result.positive_streams, ("pixel_residual", "spectral"))
        self.assertEqual(len(result.streams), 2)
        self.assertEqual(result.streams[0]["score_raw"], 0.82)
        self.assertIn("detector_version", result.streams[1])
        self.assertIn("score_schema", result.streams[1])
        self.assertIn("config_digest", result.streams[1])
        self.assertIn("input_digests", result.streams[1])
        self.assertEqual(result.evidence_digest, result.to_dict()["evidence_digest"])

    def test_concordant_ordinary_propagation_is_null_consistent(self):
        result = route_multistream_evidence(
            (_observation("pixel_residual", 0.02), _observation("spectral", 0.01))
        )
        self.assertEqual(result.route, ROUTE_NULL_CONSISTENT)
        self.assertFalse(result.abstained)
        self.assertEqual(result.negative_streams, ("pixel_residual", "spectral"))

    def test_score_conflict_abstains_without_averaging(self):
        result = route_multistream_evidence(
            (_observation("pixel_residual", 0.92), _observation("spectral", 0.08))
        )
        self.assertEqual(result.route, ROUTE_CONFLICT_REVIEW)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "raw_score_conflict")
        self.assertEqual(result.streams[0]["score_raw"], 0.92)
        self.assertEqual(result.streams[1]["score_raw"], 0.08)

    def test_missing_or_unpaired_stream_fails_closed(self):
        unavailable = _observation(
            "spectral", None, accepted=False, reason="detector_unavailable"
        )
        result = route_multistream_evidence((_observation("pixel_residual", 0.8), unavailable))
        self.assertEqual(result.route, ROUTE_INSUFFICIENT)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "accepted_stream_count_below_minimum")
        unpaired = route_multistream_evidence(
            (_observation("pixel_residual", 0.8, paired=False), _observation("spectral", 0.8))
        )
        self.assertEqual(unpaired.route, ROUTE_INSUFFICIENT)
        self.assertEqual(unpaired.reason, "paired_counterfactual_required")

    def test_quality_gate_and_duplicate_ids_are_explicit(self):
        low_quality = route_multistream_evidence(
            (_observation("pixel_residual", 0.8, quality=0.1), _observation("spectral", 0.8))
        )
        self.assertEqual(low_quality.route, ROUTE_INSUFFICIENT)
        self.assertEqual(low_quality.reason, "quality_below_threshold")
        with self.assertRaises(ValueError):
            route_multistream_evidence((_observation("same", 0.7), _observation("same", 0.6)))

    def test_config_digest_changes_route_digest(self):
        streams = (_observation("pixel_residual", 0.2), _observation("spectral", 0.2))
        default = route_multistream_evidence(streams)
        changed = route_multistream_evidence(
            streams,
            config=MultiStreamRouteConfig(raw_positive_threshold=0.1),
        )
        self.assertNotEqual(default.router_config_digest, changed.router_config_digest)
        self.assertNotEqual(default.evidence_digest, changed.evidence_digest)


if __name__ == "__main__":
    unittest.main()
