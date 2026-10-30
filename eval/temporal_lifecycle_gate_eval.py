"""Synthetic runner for the TLEG-v1 temporal/lifecycle replay contract.

The runner exercises as-of snapshot ordering, event-chain integrity,
delete/restore replay, profile freshness, authorization binding and upstream
fail-closed behavior.  It uses no images or models and never reports AIGC
accuracy, probability or legal conclusions.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from typing import Any, Dict, Iterable, List, Sequence

from aigc.temporal_lifecycle_gate import (
    EVENT_CREATE,
    EVENT_DELETE,
    EVENT_RESTORE,
    OPERATION_CONTENT_EDIT,
    OPERATION_ORDINARY_PROPAGATION,
    TemporalLifecycleConfig,
    TemporalLifecycleEvent,
    TemporalLifecycleRequest,
    evaluate_temporal_lifecycle,
)


MANIFEST = hashlib.sha256(b"tleg-manifest").hexdigest()
AUTHORIZATION = hashlib.sha256(b"tleg-authorization").hexdigest()
RETENTION = hashlib.sha256(b"tleg-retention").hexdigest()
ACCESS = hashlib.sha256(b"tleg-access").hexdigest()
PROFILE = hashlib.sha256(b"tleg-profile").hexdigest()
UPSTREAM = hashlib.sha256(b"tleg-upstream").hexdigest()


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _events(specs: Sequence[Dict[str, Any]], *, snapshot_id: str = "snapshot-1", asset_id: str = "asset-1") -> tuple[TemporalLifecycleEvent, ...]:
    rows: List[TemporalLifecycleEvent] = []
    previous = None
    for number, spec in enumerate(specs, 1):
        event_id = spec.get("event_id", f"event-{number}")
        event_type = spec["event_type"]
        row = TemporalLifecycleEvent(
            event_id=event_id,
            asset_id=asset_id,
            version_id=spec["version_id"],
            sequence=number,
            event_time=spec.get("event_time", f"2026-09-20T0{number}:00:00Z"),
            event_type=event_type,
            content_digest=_h(spec.get("content", f"content-{number}")),
            manifest_digest=MANIFEST,
            authorization_digest=AUTHORIZATION,
            retention_policy_digest=RETENTION,
            access_policy_digest=ACCESS,
            snapshot_id=snapshot_id,
            parent_version_id=spec.get("parent_version_id"),
            previous_event_digest=previous,
            deletion_tombstone_digest=_h(event_id + "-tombstone") if event_type == EVENT_DELETE else None,
            restores_event_id=spec.get("restores_event_id"),
        )
        rows.append(row)
        previous = row.computed_digest
    return tuple(rows)


def _request(
    rows: Iterable[TemporalLifecycleEvent] | None = None,
    *,
    query_as_of: str = "2026-09-20T12:00:00Z",
    snapshot_created_at: str = "2026-09-20T10:00:00Z",
    snapshot_sequence: int | None = None,
    ledger_head_sequence: int | None = None,
    ledger_head_event_time: str | None = None,
    selected_version_id: str | None = "v1",
    split: str = "evaluation",
    operation_scope: str = OPERATION_CONTENT_EDIT,
    upstream_route: str = "candidate_edit",
    profile_fitted_through: str = "2026-09-19T12:00:00Z",
    profile_max_age_days: int | None = None,
    expected_snapshot_digest: str | None = None,
    authorization_digest: str = AUTHORIZATION,
) -> TemporalLifecycleRequest:
    rows = tuple(rows if rows is not None else _events([{"version_id": "v1", "event_type": EVENT_CREATE}]))
    snapshot_sequence = len(rows) if snapshot_sequence is None else snapshot_sequence
    ledger_head_sequence = snapshot_sequence if ledger_head_sequence is None else ledger_head_sequence
    return TemporalLifecycleRequest(
        event_id="query-event",
        asset_id="asset-1",
        query_as_of=query_as_of,
        snapshot_id="snapshot-1",
        snapshot_created_at=snapshot_created_at,
        snapshot_sequence=snapshot_sequence,
        ledger_head_sequence=ledger_head_sequence,
        ledger_head_event_time=ledger_head_event_time,
        index_epoch="epoch-1",
        events=rows,
        selected_version_id=selected_version_id,
        manifest_digest=MANIFEST,
        authorization_digest=authorization_digest,
        retention_policy_digest=RETENTION,
        access_policy_digest=ACCESS,
        profile_digest=PROFILE,
        profile_fitted_through=profile_fitted_through,
        profile_max_age_days=profile_max_age_days,
        split=split,
        operation_scope=operation_scope,
        upstream_route=upstream_route,
        upstream_evidence_digest=UPSTREAM,
        expected_snapshot_digest=expected_snapshot_digest,
    )


def build_synthetic_cases() -> List[Dict[str, Any]]:
    clean = _events([{"version_id": "v1", "event_type": EVENT_CREATE}])
    deleted = _events([
        {"version_id": "v1", "event_type": EVENT_CREATE},
        {"version_id": "v1", "event_type": EVENT_DELETE, "event_time": "2026-09-20T02:00:00Z"},
    ])
    restored = _events([
        {"version_id": "v1", "event_type": EVENT_CREATE},
        {"version_id": "v1", "event_type": EVENT_DELETE, "event_time": "2026-09-20T02:00:00Z"},
        {"version_id": "v2", "event_type": EVENT_RESTORE, "parent_version_id": "v1", "restores_event_id": "event-2", "event_time": "2026-09-20T03:00:00Z"},
    ])
    chain = _events([{"version_id": "v1", "event_type": EVENT_CREATE}])
    chain_tampered = (replace(chain[0], previous_event_digest=_h("unexpected")),)
    gap = _events([
        {"version_id": "v1", "event_type": EVENT_CREATE},
        {"version_id": "v1", "event_type": "update"},
    ])
    gap_tampered = (gap[0], replace(gap[1], sequence=3, previous_event_digest=gap[0].computed_digest))
    restore_bad = _events([
        {"version_id": "v1", "event_type": EVENT_CREATE},
        {"version_id": "v1", "event_type": EVENT_DELETE, "event_time": "2026-09-20T02:00:00Z"},
        {"version_id": "v1", "event_type": EVENT_RESTORE, "parent_version_id": "wrong", "restores_event_id": "event-2", "event_time": "2026-09-20T03:00:00Z"},
    ])
    return [
        {"case_id": "clean_active", "request": _request(clean)},
        {"case_id": "ordinary_propagation", "request": _request(clean, operation_scope=OPERATION_ORDINARY_PROPAGATION)},
        {"case_id": "null_upstream", "request": _request(clean, upstream_route="null_consistent")},
        {"case_id": "future_event", "request": _request(_events([{"version_id": "v1", "event_type": EVENT_CREATE, "event_time": "2026-09-20T13:00:00Z"}]), snapshot_created_at="2026-09-20T09:00:00Z")},
        {"case_id": "future_snapshot", "request": _request(clean, snapshot_created_at="2026-09-20T13:00:00Z")},
        {"case_id": "stale_snapshot", "request": _request(clean, snapshot_sequence=1, ledger_head_sequence=2, ledger_head_event_time="2026-09-20T11:00:00Z")},
        {"case_id": "future_ledger_head", "request": _request(clean, snapshot_sequence=1, ledger_head_sequence=2, ledger_head_event_time="2026-09-20T13:00:00Z")},
        {"case_id": "stale_profile", "request": _request(clean, profile_fitted_through="2026-07-01T00:00:00Z", profile_max_age_days=7)},
        {"case_id": "deleted_version", "request": _request(deleted)},
        {"case_id": "valid_restore", "request": _request(restored, selected_version_id="v2")},
        {"case_id": "restore_binding_mismatch", "request": _request(restore_bad)},
        {"case_id": "binding_mismatch", "request": _request(clean, authorization_digest=_h("wrong"))},
        {"case_id": "chain_mismatch", "request": _request(chain_tampered)},
        {"case_id": "sequence_gap", "request": _request(gap_tampered, snapshot_sequence=3)},
        {"case_id": "external_split", "request": _request(clean, split="external")},
        {"case_id": "open_set_upstream", "request": _request(clean, upstream_route="open_set_unknown")},
        {"case_id": "snapshot_digest_tamper", "request": _request(clean, expected_snapshot_digest=_h("wrong"))},
        {"case_id": "selected_version_missing", "request": _request(clean, selected_version_id="missing")},
    ]


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def run_synthetic_evaluation() -> Dict[str, Any]:
    config = TemporalLifecycleConfig(maximum_profile_age_days=30)
    outputs = []
    for case in build_synthetic_cases():
        result = evaluate_temporal_lifecycle(case["request"], config)
        outputs.append({"case_id": case["case_id"], "result": result.to_dict()})
    counts: Dict[str, int] = {}
    for row in outputs:
        route = row["result"]["route"]
        counts[route] = counts.get(route, 0) + 1
    return {
        "version": "temporal-lifecycle-gate-synthetic-v1",
        "count": len(outputs),
        "config_digest": config.digest,
        "dataset_digest": _digest(outputs),
        "route_counts": dict(sorted(counts.items())),
        "cases": outputs,
        "real_data_status": "not_evaluated",
        "interpretation": (
            "synthetic lifecycle replay contract only; no real archive, image, model, "
            "temporal generalization, probability, customer, or legal metric"
        ),
    }


def main() -> None:
    print(json.dumps(run_synthetic_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
