"""Offline regression evaluation for ``source-residual-v1``.

The runner deliberately uses only the Python standard library and synthetic
normalized grayscale grids.  It is a protocol smoke test for the raw feature
adapter, not a claim about real images or a calibrated AIGC detector.  The
synthetic set contains ordinary global transforms as hard negatives and local
region edits as positives.  Every input is generated from an explicit seed so
the score distribution and digest can be reproduced in a clean checkout.

Run from the repository root::

    python3 -m eval.source_residual_eval

The output includes AUROC, average precision, a transparent fixed-threshold
diagnostic, per-category score distributions, and a digest of the scored
examples.  The fixed threshold is useful for regression detection only; it
must not be used as a production AIGC probability or legal conclusion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from aigc.forensic_features import (
    ResidualConfig,
    compare_aligned_regions,
    extract_residual_roi,
)
from aigc.calibration import fit_conservative_ai_threshold


PROTOCOL_VERSION = "source-residual-synthetic-v1"
DEFAULT_SEED = 20260920
DEFAULT_SIZE = 32
DEFAULT_REPEATS = 3
DEFAULT_THRESHOLD = 0.50
DEFAULT_ROI_THRESHOLD = 0.12

Grid = Tuple[Tuple[float, ...], ...]
Transform = Callable[[Grid, random.Random, int], Tuple[Grid, Optional[Tuple[int, int, int, int]]]]


def _clip(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _copy_grid(grid: Sequence[Sequence[float]]) -> Grid:
    return tuple(tuple(float(value) for value in row) for row in grid)


def _make_reference(index: int, size: int, rng: random.Random) -> Grid:
    """Create a textured source image without relying on an image library."""

    phase_x = rng.uniform(-math.pi, math.pi) + index * 0.17
    phase_y = rng.uniform(-math.pi, math.pi) - index * 0.11
    freq_x = 0.13 + (index % 5) * 0.017
    freq_y = 0.16 + (index % 7) * 0.013
    rows: List[Tuple[float, ...]] = []
    for y in range(size):
        values = []
        for x in range(size):
            value = (
                0.50
                + 0.17 * math.sin(freq_x * x + phase_x)
                + 0.14 * math.cos(freq_y * y + phase_y)
                + 0.09 * math.sin(0.08 * (x + y) + phase_x - phase_y)
                + 0.025 * rng.uniform(-1.0, 1.0)
            )
            values.append(_clip(value))
        rows.append(tuple(values))
    return tuple(rows)


def _rectangle(rng: random.Random, size: int) -> Tuple[int, int, int, int]:
    span = max(4, size // 4)
    # Keep a small margin so the edit is not confused with a boundary effect.
    max_start = max(1, size - span - 1)
    x0 = rng.randint(1, max_start)
    y0 = rng.randint(1, max_start)
    return x0, y0, x0 + span, y0 + span


def _global_brightness(reference: Grid, _rng: random.Random, _size: int):
    return tuple(tuple(_clip(value + 0.08) for value in row) for row in reference), None


def _global_contrast(reference: Grid, _rng: random.Random, _size: int):
    return (
        tuple(tuple(_clip(0.5 + 0.86 * (value - 0.5)) for value in row) for row in reference),
        None,
    )


def _global_gamma(reference: Grid, _rng: random.Random, _size: int):
    return tuple(tuple(_clip(value**0.92) for value in row) for row in reference), None


def _quantized(reference: Grid, _rng: random.Random, _size: int):
    # A coarse codec-like quantization is a deterministic proxy for ordinary
    # re-encoding.  It is not a JPEG implementation and is labelled as such.
    levels = 32.0
    return (
        tuple(tuple(_clip(round(value * levels) / levels) for value in row) for row in reference),
        None,
    )


def _tone_curve(reference: Grid, _rng: random.Random, _size: int):
    return (
        tuple(tuple(_clip(0.06 + 0.88 * value) for value in row) for row in reference),
        None,
    )


def _local_bright(reference: Grid, rng: random.Random, size: int):
    rect = _rectangle(rng, size)
    x0, y0, x1, y1 = rect
    result = [list(row) for row in reference]
    for y in range(y0, y1):
        for x in range(x0, x1):
            result[y][x] = _clip(result[y][x] + 0.45)
    return _copy_grid(result), rect


def _local_dark(reference: Grid, rng: random.Random, size: int):
    rect = _rectangle(rng, size)
    x0, y0, x1, y1 = rect
    result = [list(row) for row in reference]
    for y in range(y0, y1):
        for x in range(x0, x1):
            result[y][x] = _clip(result[y][x] - 0.45)
    return _copy_grid(result), rect


def _local_patch(reference: Grid, rng: random.Random, size: int):
    rect = _rectangle(rng, size)
    x0, y0, x1, y1 = rect
    result = [list(row) for row in reference]
    # Use an unrelated, deterministic patch-shaped signal to represent a
    # local inpaint/img2img result without loading a generative model.
    phase = rng.uniform(-math.pi, math.pi)
    for y in range(y0, y1):
        for x in range(x0, x1):
            patch = 0.5 + 0.26 * math.sin(0.65 * (x - x0) + phase)
            patch += 0.18 * math.cos(0.43 * (y - y0) - phase)
            result[y][x] = _clip(patch)
    return _copy_grid(result), rect


def _local_noise(reference: Grid, rng: random.Random, size: int):
    rect = _rectangle(rng, size)
    x0, y0, x1, y1 = rect
    result = [list(row) for row in reference]
    for y in range(y0, y1):
        for x in range(x0, x1):
            result[y][x] = _clip(result[y][x] + rng.uniform(-0.28, 0.28))
    return _copy_grid(result), rect


_CASES: Tuple[Tuple[str, int, Transform], ...] = (
    ("identity", 0, lambda reference, rng, size: (_copy_grid(reference), None)),
    ("global_brightness", 0, _global_brightness),
    ("global_contrast", 0, _global_contrast),
    ("global_gamma", 0, _global_gamma),
    ("codec_like_quantization", 0, _quantized),
    ("global_tone_curve", 0, _tone_curve),
    ("local_bright_edit", 1, _local_bright),
    ("local_dark_edit", 1, _local_dark),
    ("local_patch_edit", 1, _local_patch),
    ("local_noise_edit", 1, _local_noise),
)


@dataclass(frozen=True)
class SyntheticExample:
    sample_id: str
    category: str
    label: int
    reference: Grid
    query: Grid
    edit_region: Optional[Tuple[int, int, int, int]] = None


@dataclass(frozen=True)
class ScoredExample:
    sample_id: str
    category: str
    label: int
    score: float
    quality: float
    global_shift: float
    residual_coverage: float
    roi_selected_fraction: float
    roi_iou: Optional[float]
    edit_region: Optional[Tuple[int, int, int, int]] = None

    def compact_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "sample_id": self.sample_id,
            "category": self.category,
            "label": self.label,
            "score": round(self.score, 12),
            "quality": round(self.quality, 12),
            "global_shift": round(self.global_shift, 12),
            "residual_coverage": round(self.residual_coverage, 12),
            "roi_selected_fraction": round(self.roi_selected_fraction, 12),
            "roi_iou": round(self.roi_iou, 12) if self.roi_iou is not None else None,
        }
        if self.edit_region is not None:
            result["edit_region"] = list(self.edit_region)
        return result


def _box_iou(
    left: Optional[Tuple[int, int, int, int]],
    right: Optional[Tuple[int, int, int, int]],
) -> Optional[float]:
    if left is None or right is None:
        return None
    lx0, ly0, lx1, ly1 = left
    rx0, ry0, rx1, ry1 = right
    ix0, iy0 = max(lx0, rx0), max(ly0, ry0)
    ix1, iy1 = min(lx1, rx1), min(ly1, ry1)
    intersection = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    left_area = max(0, lx1 - lx0) * max(0, ly1 - ly0)
    right_area = max(0, rx1 - rx0) * max(0, ry1 - ry0)
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def build_synthetic_dataset(
    *, seed: int = DEFAULT_SEED, repeats: int = DEFAULT_REPEATS, size: int = DEFAULT_SIZE
) -> Tuple[SyntheticExample, ...]:
    """Build the frozen synthetic protocol input for one seed and resolution."""

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    if isinstance(size, bool) or not isinstance(size, int) or size < 8:
        raise ValueError("size must be an integer >= 8")

    examples: List[SyntheticExample] = []
    for index in range(repeats):
        source_rng = random.Random(seed + index * 1_000_003)
        reference = _make_reference(index, size, source_rng)
        for case_index, (category, label, transform) in enumerate(_CASES):
            transform_rng = random.Random(seed + index * 1_000_003 + case_index * 9_973 + 17)
            query, edit_region = transform(reference, transform_rng, size)
            examples.append(
                SyntheticExample(
                    sample_id=f"synthetic-{index:03d}-{category}",
                    category=category,
                    label=label,
                    reference=reference,
                    query=query,
                    edit_region=edit_region,
                )
            )
    return tuple(examples)


def _validate_threshold(threshold: float) -> float:
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("threshold must be a finite number between 0 and 1")
    threshold = float(threshold)
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be a finite number between 0 and 1")
    return threshold


def _roc_auc(labels: Sequence[int], scores: Sequence[float]) -> Optional[float]:
    positives = sum(label == 1 for label in labels)
    negatives = sum(label == 0 for label in labels)
    if positives == 0 or negatives == 0:
        return None
    # Rank-sum form with average ranks for ties, ascending score order.
    ordered = sorted(zip(scores, labels), key=lambda item: item[0])
    rank_sum_positive = 0.0
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][0] == ordered[cursor][0]:
            end += 1
        average_rank = (cursor + 1 + end) / 2.0
        rank_sum_positive += average_rank * sum(label == 1 for _, label in ordered[cursor:end])
        cursor = end
    return (rank_sum_positive - positives * (positives + 1) / 2.0) / (positives * negatives)


def _average_precision(labels: Sequence[int], scores: Sequence[float]) -> Optional[float]:
    positives = sum(label == 1 for label in labels)
    if positives == 0:
        return None
    ordered = sorted(zip(scores, labels), key=lambda item: item[0], reverse=True)
    true_positive = 0
    false_positive = 0
    previous_recall = 0.0
    area = 0.0
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][0] == ordered[cursor][0]:
            end += 1
        true_positive += sum(label == 1 for _, label in ordered[cursor:end])
        false_positive += sum(label == 0 for _, label in ordered[cursor:end])
        recall = true_positive / positives
        precision = true_positive / (true_positive + false_positive)
        area += (recall - previous_recall) * precision
        previous_recall = recall
        cursor = end
    return area


def _threshold_metrics(labels: Sequence[int], scores: Sequence[float], threshold: float) -> Dict[str, Any]:
    predictions = [score >= threshold for score in scores]
    true_positive = sum(prediction and label == 1 for prediction, label in zip(predictions, labels))
    false_positive = sum(prediction and label == 0 for prediction, label in zip(predictions, labels))
    true_negative = sum(not prediction and label == 0 for prediction, label in zip(predictions, labels))
    false_negative = sum(not prediction and label == 1 for prediction, label in zip(predictions, labels))
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    fpr = false_positive / (false_positive + true_negative) if false_positive + true_negative else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": threshold,
        "tp": true_positive,
        "fp": false_positive,
        "tn": true_negative,
        "fn": false_negative,
        "precision": precision,
        "recall": recall,
        "fpr": fpr,
        "f1": f1,
    }


def _category_metrics(scored: Sequence[ScoredExample], threshold: float) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[ScoredExample]] = {}
    for item in scored:
        grouped.setdefault(item.category, []).append(item)
    output: Dict[str, Dict[str, Any]] = {}
    for category in sorted(grouped):
        items = grouped[category]
        labels = [item.label for item in items]
        scores = [item.score for item in items]
        output[category] = {
            "count": len(items),
            "label": labels[0] if len(set(labels)) == 1 else "mixed",
            "score_mean": mean(scores),
            "score_min": min(scores),
            "score_max": max(scores),
            "quality_mean": mean(item.quality for item in items),
            "positive_rate_at_threshold": mean(score >= threshold for score in scores),
        }
    return output


def score_examples(
    examples: Iterable[SyntheticExample],
    *,
    config: Optional[ResidualConfig] = None,
    roi_threshold: float = DEFAULT_ROI_THRESHOLD,
) -> Tuple[ScoredExample, ...]:
    """Extract only raw source-residual observations from synthetic examples."""

    scored: List[ScoredExample] = []
    seen_ids = set()
    for example in examples:
        if example.sample_id in seen_ids:
            raise ValueError(f"duplicate sample_id: {example.sample_id}")
        seen_ids.add(example.sample_id)
        if example.label not in (0, 1):
            raise ValueError(f"label must be 0 or 1: {example.sample_id}")
        evidence = compare_aligned_regions(example.reference, example.query, config=config)
        roi = extract_residual_roi(
            example.reference,
            example.query,
            threshold=roi_threshold,
            config=config,
        )
        scored.append(
            ScoredExample(
                sample_id=example.sample_id,
                category=example.category,
                label=example.label,
                score=evidence.edit_score,
                quality=evidence.quality_score,
                global_shift=evidence.global_shift,
                residual_coverage=evidence.residual_coverage,
                roi_selected_fraction=roi.selected_fraction,
                roi_iou=_box_iou(roi.bbox, example.edit_region),
                edit_region=example.edit_region,
            )
        )
    return tuple(scored)


def evaluate_scored(
    scored: Sequence[ScoredExample],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    include_records: bool = False,
    protocol: str = PROTOCOL_VERSION,
    dataset_identity: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute deterministic ranking and fixed-threshold diagnostics."""

    threshold = _validate_threshold(threshold)
    if not scored:
        raise ValueError("scored examples must not be empty")
    labels = [item.label for item in scored]
    scores = [item.score for item in scored]
    if any(not math.isfinite(score) or not 0.0 <= score <= 1.0 for score in scores):
        raise ValueError("scores must be finite and between 0 and 1")
    compact_records = [item.compact_dict() for item in scored]
    digest_payload = {
        "protocol": protocol,
        "dataset_identity": dict(dataset_identity or {}),
        "records": compact_records,
    }
    canonical = json.dumps(digest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    dataset_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    threshold_result = _threshold_metrics(labels, scores, threshold)
    negative = [item for item in scored if item.label == 0]
    positive = [item for item in scored if item.label == 1]
    operating_point = None
    if negative and positive:
        operating_point = fit_conservative_ai_threshold(
            scores,
            labels,
            detector_version=ResidualConfig().detector_version,
            score_schema=ResidualConfig().score_schema,
            target_fpr=0.0,
        )
    result: Dict[str, Any] = {
        "protocol": protocol,
        "detector_version": ResidualConfig().detector_version,
        "score_schema": ResidualConfig().score_schema,
        "dataset_identity": dict(dataset_identity or {}),
        "dataset_digest": dataset_digest,
        "count": len(scored),
        "positive_count": len(positive),
        "negative_count": len(negative),
        "auroc": _roc_auc(labels, scores),
        "average_precision": _average_precision(labels, scores),
        "fixed_threshold": threshold_result,
        "conservative_operating_point": (
            operating_point.to_dict() if operating_point is not None else None
        ),
        "hard_negative_fpr_at_threshold": (
            mean(item.score >= threshold for item in negative) if negative else None
        ),
        "positive_recall_at_threshold": (
            mean(item.score >= threshold for item in positive) if positive else None
        ),
        "positive_score_mean": mean(item.score for item in positive) if positive else None,
        "negative_score_mean": mean(item.score for item in negative) if negative else None,
        "positive_roi_iou_mean": (
            mean(item.roi_iou for item in positive if item.roi_iou is not None)
            if any(item.roi_iou is not None for item in positive)
            else None
        ),
        "negative_roi_activation_rate": (
            mean(item.roi_selected_fraction > 0.0 for item in negative)
            if negative
            else None
        ),
        "category_metrics": _category_metrics(scored, threshold),
        "interpretation": (
            "synthetic regression only; edit_score_raw is not calibrated, not an AIGC probability, "
            "and not a legal conclusion"
        ),
    }
    if include_records:
        result["records"] = compact_records
    return result


def run_synthetic_evaluation(
    *,
    seed: int = DEFAULT_SEED,
    repeats: int = DEFAULT_REPEATS,
    size: int = DEFAULT_SIZE,
    threshold: float = DEFAULT_THRESHOLD,
    roi_threshold: float = DEFAULT_ROI_THRESHOLD,
    include_records: bool = False,
) -> Dict[str, Any]:
    examples = build_synthetic_dataset(seed=seed, repeats=repeats, size=size)
    scored = score_examples(examples, roi_threshold=roi_threshold)
    return evaluate_scored(
        scored,
        threshold=threshold,
        include_records=include_records,
        dataset_identity={
            "seed": seed,
            "repeats": repeats,
            "size": size,
            "roi_threshold": roi_threshold,
        },
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate source-residual-v1 on a synthetic hard-negative protocol")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--roi-threshold", type=float, default=DEFAULT_ROI_THRESHOLD)
    parser.add_argument("--include-records", action="store_true")
    parser.add_argument("--output", type=Path, help="write JSON to this path instead of stdout")
    args = parser.parse_args(argv)
    payload = run_synthetic_evaluation(
        seed=args.seed,
        repeats=args.repeats,
        size=args.size,
        threshold=args.threshold,
        roi_threshold=args.roi_threshold,
        include_records=args.include_records,
    )
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
