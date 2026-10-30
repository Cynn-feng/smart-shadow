"""Offline runner for the first real-image PC-SCFT contract.

The runner is deliberately private-root based.  A manifest authorizes and
hashes every sample, then the runner decodes each file with the bounded image
adapter, aligns observed/counterfactual versions to the same reference, and
routes the resulting raw evidence through PC-SCFT.  It never emits an AIGC
probability or a four-state authorship label.

The caller may provide an independently fitted
``PairedDeltaCalibrationProfile``.  If it is absent (the normal state before
real ordinary-propagation nulls are collected), the case remains explicitly
``insufficient`` with ``calibration_unavailable``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .image_adapter import AdapterConfig, ImageAdapterResult, decode_image_file
from .manifest import (
    REAL_MANIFEST_VERSION,
    canonical_real_manifest_digest,
    validate_real_manifest,
    verify_real_manifest_files,
)
from .model_adapter import (
    ADAPTER_VERSION,
    RegionalScoreBatch,
    SourceResidualAdapter,
    SourceResidualAdapterConfig,
)
from .paired_delta_calibration import (
    PairedDeltaCalibrationConfig,
    PairedDeltaCalibrationProfile,
    PairedDeltaCalibrationResult,
    PairedDeltaGroup,
    quality_bucket,
)
from .patch_coverage import PatchCoverageConfig, PatchDelta, summarize_patch_coverage
from .pc_scft import PCSCFTConfig, PCSCFTResult, decide_pc_scft
from .regional_alignment import (
    AlignmentConfig,
    RegionalObservationBatch,
    align_gray_grids,
    partition_aligned_regions,
)
from .regional_counterfactual import (
    RegionalCounterfactualConfig,
    RegionalObservation,
    RegionalCounterfactualResult,
    fuse_regional_counterfactual,
)


RUNNER_VERSION = "real-pc-scft-runner-v1"
ROLES = ("reference", "observed", "counterfactual")


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _unavailable_calibration(query: PairedDeltaGroup, *, reason: str) -> PairedDeltaCalibrationResult:
    """Create a typed, explicitly unevaluated calibration result.

    This helper does not invent null statistics.  The digests identify the
    unavailable profile state so a downstream audit can distinguish it from
    a real profile that happened to produce a null-consistent result.
    """

    profile_digest = _digest({"version": RUNNER_VERSION, "profile": "unavailable", "reason": reason})
    config_digest = _digest({"version": RUNNER_VERSION, "calibration": "unavailable"})
    dataset_digest = _digest({"version": RUNNER_VERSION, "null_groups": []})
    return PairedDeltaCalibrationResult(
        evaluated=False,
        unknown=False,
        reason=reason,
        unknown_reason=None,
        query_group_id=query.group_id,
        transform_family=query.transform_family,
        quality_score=query.quality_score,
        quality_bucket=quality_bucket(query.quality_score),
        statistic_raw=query.statistic_raw,
        raw_p_value=None,
        alpha=0.2,
        requested_stratum=f"{query.transform_family}::{quality_bucket(query.quality_score)}",
        selected_stratum=None,
        fallback="unavailable",
        fallback_reason=reason,
        null_count=0,
        detector_version=query.detector_version,
        score_schema=query.score_schema,
        dataset_digest=dataset_digest,
        profile_digest=profile_digest,
        config_digest=config_digest,
    )


def _relative_path(root: Path, value: Any) -> Optional[Path]:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    if path.is_absolute() or value.startswith(("~", "file://", "private://")) or ".." in path.parts:
        return None
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def _sample_summary(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a result-safe record summary with no private path."""

    return {
        "sample_id": record.get("sample_id"),
        "asset_id": record.get("asset_id"),
        "pair_id": record.get("pair_id"),
        "role": record.get("role"),
        "transform_family": record.get("transform_family"),
        "split": record.get("split"),
        "sha256": record.get("sha256"),
        "resolution": list(record.get("resolution", ())) if isinstance(record.get("resolution"), (list, tuple)) else record.get("resolution"),
        "authorization_id": record.get("authorization_id"),
        "authorization_scope": record.get("authorization_scope"),
        "generator_family": record.get("generator_family"),
        "origin": record.get("origin"),
        "postprocess_chain": list(record.get("postprocess_chain", ())) if isinstance(record.get("postprocess_chain"), list) else record.get("postprocess_chain"),
    }


@dataclass(frozen=True)
class RealImageRunnerConfig:
    """All gates used by one deterministic runner invocation."""

    adapter_config: AdapterConfig = field(default_factory=AdapterConfig)
    model_adapter_config: SourceResidualAdapterConfig = field(default_factory=SourceResidualAdapterConfig)
    alignment_config: AlignmentConfig = field(default_factory=AlignmentConfig)
    regional_config: RegionalCounterfactualConfig = field(default_factory=RegionalCounterfactualConfig)
    patch_config: PatchCoverageConfig = field(default_factory=PatchCoverageConfig)
    pc_scft_config: PCSCFTConfig = field(default_factory=PCSCFTConfig)
    calibration_config: PairedDeltaCalibrationConfig = field(default_factory=PairedDeltaCalibrationConfig)

    @property
    def digest(self) -> str:
        return _digest(
            {
                "runner_version": RUNNER_VERSION,
                "adapter_config": self.adapter_config.to_dict(),
                "model_adapter_config": self.model_adapter_config.to_dict(),
                "alignment_config": self.alignment_config.to_dict(),
                "regional_config": self.regional_config.to_dict(),
                "patch_config": self.patch_config.to_dict(),
                "pc_scft_config": self.pc_scft_config.to_dict(),
                "calibration_config": self.calibration_config.to_dict(),
            }
        )


def _alignment_summary(result: Any) -> Dict[str, Any]:
    return result.to_dict()


def _batch_failure(
    *,
    sample: Mapping[str, Any],
    adapter: SourceResidualAdapter,
    reason: str,
) -> RegionalScoreBatch:
    return RegionalScoreBatch(
        accepted=False,
        reason=reason,
        sample_id=str(sample.get("sample_id")),
        asset_id=str(sample.get("asset_id")),
        pair_id=str(sample.get("pair_id")),
        role=str(sample.get("role")),
        input_normalized_sha256=None,
        adapter_config_digest=adapter.config.digest,
        model_digest=adapter.config.resolved_model_digest,
        detector_version=adapter.detector_version,
        score_schema=adapter.score_schema,
    )


def _to_observations(
    observed: RegionalScoreBatch,
    counterfactual: RegionalScoreBatch,
    *,
    transform_family: str,
) -> Tuple[RegionalObservation, ...]:
    if not observed.accepted or not counterfactual.accepted:
        raise ValueError("cannot build observations from a rejected score batch")
    observed_by_id = {score.region_id: score for score in observed.scores}
    counterfactual_by_id = {score.region_id: score for score in counterfactual.scores}
    if set(observed_by_id) != set(counterfactual_by_id):
        raise ValueError("observed and counterfactual region IDs must agree")
    rows: List[RegionalObservation] = []
    for region_id in sorted(observed_by_id):
        obs = observed_by_id[region_id]
        cf = counterfactual_by_id[region_id]
        if obs.detector_version != cf.detector_version or obs.score_schema != cf.score_schema:
            raise ValueError("observed/counterfactual detector identity mismatch")
        rows.extend(
            (
                RegionalObservation(
                    asset_id=obs.asset_id,
                    pair_id=obs.pair_id,
                    region_id=region_id,
                    version_id=f"{obs.sample_id}:{region_id}",
                    transform_family=transform_family,
                    score_raw=obs.score_raw,
                    quality_score=obs.quality_score,
                    source_match_score=obs.source_match_score,
                    kind="observed",
                    detector_version=obs.detector_version,
                    score_schema=obs.score_schema,
                    propagation_chain=(transform_family,),
                ),
                RegionalObservation(
                    asset_id=cf.asset_id,
                    pair_id=cf.pair_id,
                    region_id=region_id,
                    version_id=f"{cf.sample_id}:{region_id}",
                    transform_family=transform_family,
                    score_raw=cf.score_raw,
                    quality_score=cf.quality_score,
                    source_match_score=cf.source_match_score,
                    kind="counterfactual",
                    detector_version=cf.detector_version,
                    score_schema=cf.score_schema,
                    propagation_chain=(transform_family,),
                ),
            )
        )
    return tuple(rows)


def _region_type_map(record: Mapping[str, Any]) -> Mapping[str, str]:
    raw = record.get("region_type_map")
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(key): str(value)
        for key, value in raw.items()
        if isinstance(value, str) and value.strip()
    }


def _patches(
    observed: RegionalScoreBatch,
    counterfactual: RegionalScoreBatch,
    *,
    region_types: Mapping[str, str],
) -> Tuple[PatchDelta, ...]:
    obs = {score.region_id: score for score in observed.scores}
    cf = {score.region_id: score for score in counterfactual.scores}
    if set(obs) != set(cf):
        raise ValueError("observed and counterfactual score IDs must agree")
    count = max(1, len(obs))
    return tuple(
        PatchDelta(
            region_id=region_id,
            delta_raw=obs[region_id].score_raw - cf[region_id].score_raw,
            quality_score=min(obs[region_id].quality_score, cf[region_id].quality_score),
            source_match_score=min(obs[region_id].source_match_score, cf[region_id].source_match_score),
            area_fraction=1.0 / count,
            detector_version=obs[region_id].detector_version,
            score_schema=obs[region_id].score_schema,
            region_type=region_types.get(region_id, "unknown"),
        )
        for region_id in sorted(obs)
    )


class RealImageRunner:
    """Execute one manifest under a private root."""

    def __init__(
        self,
        root: str | Path,
        *,
        config: Optional[RealImageRunnerConfig] = None,
        calibration_profile: Optional[PairedDeltaCalibrationProfile] = None,
        now: Optional[datetime] = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.config = config or RealImageRunnerConfig()
        self.adapter = SourceResidualAdapter(self.config.model_adapter_config)
        self.calibration_profile = calibration_profile
        self.now = now or datetime.now(timezone.utc)
        if self.now.tzinfo is None:
            self.now = self.now.replace(tzinfo=timezone.utc)
        else:
            self.now = self.now.astimezone(timezone.utc)

    def _decode(self, record: Mapping[str, Any]) -> Tuple[Optional[ImageAdapterResult], Optional[str]]:
        path = _relative_path(self.root, record.get("sample_path"))
        if path is None:
            return None, "invalid_sample_path"
        try:
            result = decode_image_file(path, self.config.adapter_config)
        except (OSError, RuntimeError, ValueError) as exc:
            return None, f"adapter_failed:{type(exc).__name__}"
        if not result.accepted:
            return result, f"adapter:{result.reason}"
        return result, None

    def _pair_case(
        self,
        records: Mapping[str, Mapping[str, Any]],
        *,
        manifest_digest: str,
    ) -> Dict[str, Any]:
        reference_record = records["reference"]
        observed_record = records["observed"]
        counterfactual_record = records["counterfactual"]
        case: Dict[str, Any] = {
            "sample_id": observed_record.get("sample_id"),
            "asset_id": observed_record.get("asset_id"),
            "pair_id": observed_record.get("pair_id"),
            "transform_family": observed_record.get("transform_family"),
            "manifest_digest": manifest_digest,
            "record_summaries": {
                role: _sample_summary(records[role]) for role in ROLES
            },
            "runner_version": RUNNER_VERSION,
            "adapter_version": ADAPTER_VERSION,
            "config_digest": self.config.digest,
        }
        decoded: Dict[str, ImageAdapterResult] = {}
        for role, record in records.items():
            result, reason = self._decode(record)
            if reason is not None or result is None or not result.accepted:
                case.update({"status": "insufficient", "reason": reason or "adapter_failed", "decoded_roles": sorted(decoded)})
                return case
            declared = record.get("resolution")
            actual = result.audit.original_size
            if (
                isinstance(declared, (list, tuple))
                and actual is not None
                and tuple(int(item) for item in declared) != tuple(int(item) for item in actual)
            ):
                case.update({"status": "insufficient", "reason": "resolution_mismatch", "decoded_roles": sorted(decoded)})
                return case
            decoded[role] = result
        case["decode_audits"] = {
            role: result.to_dict() for role, result in decoded.items()
        }
        ref = decoded["reference"]
        obs = decoded["observed"]
        cf = decoded["counterfactual"]
        assert ref.gray is not None and obs.gray is not None and cf.gray is not None
        observed_alignment = align_gray_grids(ref.gray, obs.gray, config=self.config.alignment_config)
        counterfactual_alignment = align_gray_grids(ref.gray, cf.gray, config=self.config.alignment_config)
        case["alignment"] = {
            "observed": _alignment_summary(observed_alignment),
            "counterfactual": _alignment_summary(counterfactual_alignment),
        }
        if not observed_alignment.accepted:
            case.update({"status": "insufficient", "reason": f"observed_{observed_alignment.reason}"})
            return case
        if not counterfactual_alignment.accepted:
            case.update({"status": "insufficient", "reason": f"counterfactual_{counterfactual_alignment.reason}"})
            return case
        if (
            observed_alignment.aligned_shape != counterfactual_alignment.aligned_shape
            or observed_alignment.reference_offset != counterfactual_alignment.reference_offset
            or observed_alignment.alignment_version != counterfactual_alignment.alignment_version
        ):
            case.update({"status": "insufficient", "reason": "paired_coordinate_frame_mismatch"})
            return case
        try:
            observed_regions = partition_aligned_regions(observed_alignment, config=self.config.alignment_config)
            counterfactual_regions = partition_aligned_regions(counterfactual_alignment, config=self.config.alignment_config)
        except ValueError as exc:
            case.update({"status": "insufficient", "reason": f"region_partition_failed:{str(exc)}"})
            return case
        if [region.region_id for region in observed_regions] != [region.region_id for region in counterfactual_regions]:
            case.update({"status": "insufficient", "reason": "paired_region_set_mismatch"})
            return case
        observed_batch = self.adapter.score_regions(
            sample_id=str(observed_record["sample_id"]),
            asset_id=str(observed_record["asset_id"]),
            pair_id=str(observed_record["pair_id"]),
            role="observed",
            reference_result=ref,
            query_result=obs,
            regions=observed_regions,
        )
        counterfactual_batch = self.adapter.score_regions(
            sample_id=str(counterfactual_record["sample_id"]),
            asset_id=str(counterfactual_record["asset_id"]),
            pair_id=str(counterfactual_record["pair_id"]),
            role="counterfactual",
            reference_result=ref,
            query_result=cf,
            regions=counterfactual_regions,
        )
        case["score_batches"] = {
            "observed": observed_batch.to_dict(),
            "counterfactual": counterfactual_batch.to_dict(),
        }
        if not observed_batch.accepted:
            case.update({"status": "insufficient", "reason": f"observed_{observed_batch.reason}"})
            return case
        if not counterfactual_batch.accepted:
            case.update({"status": "insufficient", "reason": f"counterfactual_{counterfactual_batch.reason}"})
            return case
        try:
            rows = _to_observations(observed_batch, counterfactual_batch, transform_family=str(observed_record["transform_family"]))
            regional = fuse_regional_counterfactual(rows, config=self.config.regional_config)
            patches = _patches(observed_batch, counterfactual_batch, region_types=_region_type_map(observed_record))
            coverage = summarize_patch_coverage(patches, config=self.config.patch_config)
            deltas = tuple(max(-1.0, min(1.0, item.delta_raw)) for item in patches)
            quality = min(item.quality_score for item in patches)
            query = PairedDeltaGroup(
                group_id=f"{observed_record['pair_id']}:query",
                transform_family=str(observed_record["transform_family"]),
                quality_score=quality,
                region_deltas=deltas,
                detector_version=observed_batch.detector_version,
                score_schema=observed_batch.score_schema,
                region_ids=tuple(item.region_id for item in patches),
            )
            if self.calibration_profile is None:
                calibration = _unavailable_calibration(query, reason="no_independent_null_profile")
            else:
                try:
                    calibration = self.calibration_profile.evaluate(query)
                except ValueError:
                    case.update({"status": "insufficient", "reason": "calibration_schema_mismatch"})
                    return case
            decision = decide_pc_scft(
                regional,
                calibration,
                coverage,
                config=self.config.pc_scft_config,
            )
        except (TypeError, ValueError, OverflowError) as exc:
            case.update({"status": "insufficient", "reason": f"evidence_failed:{type(exc).__name__}"})
            return case
        case.update(
            {
                "status": decision.status,
                "reason": decision.reason,
                "regional": regional.to_dict(),
                "calibration": calibration.to_dict(),
                "coverage": coverage.to_dict(),
                "decision": decision.to_dict(),
            }
        )
        return case

    def run(self, records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        if isinstance(records, Mapping) or isinstance(records, (str, bytes)):
            records = [records]  # type: ignore[assignment]
        else:
            try:
                records = list(records)
            except TypeError:
                records = [records]  # type: ignore[assignment]
        manifest_digest = canonical_real_manifest_digest(records)
        errors = validate_real_manifest(records, root=self.root, now=self.now)
        # Verify hashes even when authorization metadata is invalid.  This
        # preserves every fail-closed reason in the audit rather than hiding
        # a byte mismatch behind an earlier structural error.
        file_errors = verify_real_manifest_files(records, self.root)
        all_errors = sorted(set(errors + file_errors))
        base: Dict[str, Any] = {
            "version": RUNNER_VERSION,
            "manifest_version": REAL_MANIFEST_VERSION,
            "manifest_digest": manifest_digest,
            "config_digest": self.config.digest,
            "adapter_digest": self.adapter.config.digest,
            "model_digest": self.adapter.config.resolved_model_digest,
            "record_count": len(records),
            "manifest_errors": all_errors,
            "interpretation": (
                "authorized private-image raw PC-SCFT contract only; statuses are evidence-routing states, "
                "not AIGC probabilities, authorship, provenance or legal findings"
            ),
        }
        if all_errors:
            cases = []
            for index, record in enumerate(records):
                if not isinstance(record, Mapping):
                    cases.append(
                        {
                            "status": "insufficient",
                            "reason": "manifest_invalid",
                            "record_index": index,
                        }
                    )
                    continue
                sample_id = record.get("sample_id")
                related = [error for error in all_errors if error.startswith(f"record[{index}]:")]
                reason = "manifest_invalid"
                if any("unauthorized_input" in error for error in related):
                    reason = "unauthorized_input"
                elif any("hash_mismatch" in error for error in related):
                    reason = "hash_mismatch"
                cases.append(
                    {
                        "sample_id": sample_id,
                        "asset_id": record.get("asset_id"),
                        "pair_id": record.get("pair_id"),
                        "role": record.get("role"),
                        "status": "insufficient",
                        "reason": reason,
                        "record_summary": _sample_summary(record),
                    }
                )
            base["cases"] = cases
            base["status_counts"] = {"insufficient": len(cases)}
            return base
        by_pair: Dict[Tuple[str, str], Dict[str, Mapping[str, Any]]] = defaultdict(dict)
        for record in records:
            by_pair[(str(record["asset_id"]), str(record["pair_id"]))][str(record["role"])] = record
        cases = []
        for key in sorted(by_pair):
            role_map = by_pair[key]
            if set(role_map) != set(ROLES):
                # Structural validation normally catches this.  Keep a
                # second fail-closed guard close to the execution boundary.
                cases.append(
                    {
                        "asset_id": key[0],
                        "pair_id": key[1],
                        "status": "insufficient",
                        "reason": "pair_missing_role",
                    }
                )
                continue
            cases.append(self._pair_case(role_map, manifest_digest=manifest_digest))
        status_counts: Dict[str, int] = {}
        for case in cases:
            status = str(case.get("status", "insufficient"))
            status_counts[status] = status_counts.get(status, 0) + 1
        base["cases"] = cases
        base["pair_count"] = len(cases)
        base["status_counts"] = status_counts
        return base


def run_real_image_manifest(
    records: Sequence[Mapping[str, Any]],
    root: str | Path,
    *,
    config: Optional[RealImageRunnerConfig] = None,
    calibration_profile: Optional[PairedDeltaCalibrationProfile] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Functional entry point used by tests and the evaluation runner."""

    return RealImageRunner(
        root,
        config=config,
        calibration_profile=calibration_profile,
        now=now,
    ).run(records)


run_real_manifest = run_real_image_manifest


def load_manifest(path: str | Path) -> List[Mapping[str, Any]]:
    from .manifest import load_jsonl

    return load_jsonl(str(path))


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run private real-image PC-SCFT raw evidence")
    parser.add_argument("manifest", help="JSONL real_pc_scft_manifest_v1")
    parser.add_argument("--root", required=True, help="private root containing relative sample paths")
    parser.add_argument("--output", help="optional JSON output path")
    args = parser.parse_args()
    result = run_real_image_manifest(load_manifest(args.manifest), args.root)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    return 0 if not result.get("manifest_errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RUNNER_VERSION",
    "RealImageRunnerConfig",
    "RealImageRunner",
    "run_real_image_manifest",
    "run_real_manifest",
    "load_manifest",
]
