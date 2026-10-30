"""Synthetic regression for source-conditioned phase/spectral evidence.

The cases exercise local-edit separation from a paired ordinary-propagation
counterfactual, global nuisance changes, malformed grids and deterministic
digests.  They are raw feature fixtures only and do not measure AIGC
accuracy, probability calibration or provenance.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

import numpy as np

from aigc.spectral_evidence import SpectralRegion, compute_spectral_evidence, score_spectral_regions


def _grids():
    yy, xx = np.mgrid[0:64, 0:64]
    reference = (0.18 + 0.003 * xx + 0.004 * yy).astype(np.float32)
    counterfactual = reference + 0.08
    edited = counterfactual.copy()
    edited[20:40, 22:42] = np.clip(edited[20:40, 22:42] + 0.25, 0.0, 1.0)
    return reference, edited, counterfactual


def _summary(result: Any) -> Dict[str, Any]:
    return {
        "accepted": result.accepted,
        "reason": result.reason,
        "paired": result.paired,
        "evidence_digest": result.evidence_digest,
        "score_raw": [score.score_raw for score in result.scores],
        "query_score_raw": [score.query_score_raw for score in result.scores],
        "counterfactual_score_raw": [score.counterfactual_score_raw for score in result.scores],
        "paired_delta_raw": [score.paired_delta_raw for score in result.scores],
        "quality_score": [score.quality_score for score in result.scores],
    }


def run_synthetic_evaluation() -> Dict[str, Any]:
    reference, edited, counterfactual = _grids()
    local = compute_spectral_evidence(reference, edited, counterfactual)
    global_change = compute_spectral_evidence(reference, counterfactual, counterfactual)
    hard_negative = compute_spectral_evidence(reference, counterfactual, counterfactual)
    regions = score_spectral_regions(
        reference,
        edited,
        counterfactual,
        regions=(
            SpectralRegion("edited", (16, 16, 48, 48)),
            SpectralRegion("background", (0, 0, 16, 16)),
        ),
    )
    bad = reference.copy()
    bad[0, 0] = np.nan
    nonfinite = compute_spectral_evidence(reference, bad, counterfactual)
    shape = compute_spectral_evidence(reference, edited[:32], counterfactual)
    repeated = compute_spectral_evidence(reference, edited, counterfactual)
    canonical = json.dumps(local.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "version": "spectral-evidence-synthetic-v1",
        "cases": {
            "local_edit": _summary(local),
            "global_change": _summary(global_change),
            "ordinary_propagation_hard_negative": _summary(hard_negative),
            "regions": _summary(regions),
            "nonfinite": _summary(nonfinite),
            "shape_mismatch": _summary(shape),
        },
        "deterministic": local.evidence_digest == repeated.evidence_digest,
        "dataset_digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "interpretation": (
            "synthetic raw spectral/phase evidence regression only; scores and digests "
            "are not AIGC probabilities, provenance or legal findings"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
