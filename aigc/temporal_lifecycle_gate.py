"""Fail-closed temporal/lifecycle replay gate for evidence sidecars.

This module does not score images and never promotes an AIGC candidate.  It
checks that an upstream raw route was evaluated against an as-of-consistent
version/event ledger: no future snapshot, stale index head, deleted version,
invalid restore chain, or stale calibration profile may silently pass through.
The contract is intentionally dependency-light and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


VERSION = "temporal-lifecycle-gate-v1"
SCHEMA = "temporal-lifecycle-gate-result-v1"
EVENT_SCHEMA = "temporal-lifecycle-event-v1"
CONFIG_SCHEMA = "temporal-lifecycle-gate-config-v1"

ROUTE_LIFECYCLE_CONSISTENT = "lifecycle_consistent"
ROUTE_FUTURE_EVENT_LEAK = "future_event_leak"
ROUTE_STALE_SNAPSHOT_REVIEW = "stale_snapshot_review"
ROUTE_TOMBSTONED_INSUFFICIENT = "tombstoned_insufficient"
ROUTE_DELETION_REPLAY_MISMATCH = "deletion_replay_mismatch"
ROUTE_PROFILE_STALE = "profile_stale"
ROUTE_INSUFFICIENT = "insufficient"
ROUTE_NOT_EVALUATED = "not_evaluated"

EVENT_CREATE = "create"
EVENT_UPDATE = "update"
EVENT_DELETE = "delete"
EVENT_RESTORE = "restore"
EVENT_EXPIRE = "expire"
EVENT_TYPES = {EVENT_CREATE, EVENT_UPDATE, EVENT_DELETE, EVENT_RESTORE, EVENT_EXPIRE}

OPERATION_CONTENT_EDIT = "content_edit"
OPERATION_ORDINARY_PROPAGATION = "ordinary_propagation"
OPERATION_SCOPES = {OPERATION_CONTENT_EDIT, OPERATION_ORDINARY_PROPAGATION}

# TLEG is upstream-neutral, but it must not turn a terminal raw route into a
# downstream candidate.  These names cover current sidecars without importing
# their modules (which keeps this contract dependency-light).
_BLOCKED_UPSTREAM_ROUTES = {
    "review",
    "conflict_review",
    "open_set_unknown",
    "insufficient",
    "not_evaluated",
    "unknown",
    "future_event_leak",
    "stale_snapshot_review",
    "tombstoned_insufficient",
    "deletion_replay_mismatch",
    "profile_stale",
}
_CANDIDATE_UPSTREAM_ROUTES = {
    "candidate",
    "candidate_edit",
    "consensus_candidate",
    "persistent_candidate",
    "reference_specific_candidate",
    "retrieval_tree_candidate",
    "holdout_consistent",
    "attack_stable_candidate",
}

_ZERO_DIGEST = "0" * 64


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _hex(name: str, value: Any, *, allow_zero: bool = True) -> str:
    value = _text(name, value)
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
    if not allow_zero and value == _ZERO_DIGEST:
        raise ValueError(f"{name} cannot be zero digest")
    return value


def _optional_hex(name: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    return _hex(name, value)


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonnegative_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _timestamp(name: str, value: Any) -> str:
    value = _text(name, value)
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parsed_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _finite_nonnegative(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite non-negative number")
    value = float(value)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return value


@dataclass(frozen=True)
class TemporalLifecycleConfig:
    """Frozen policy for as-of replay and profile freshness."""

    maximum_profile_age_days: int = 30
    minimum_event_count: int = 1
    require_previous_digest_chain: bool = True

    def __post_init__(self) -> None:
        _nonnegative_int("maximum_profile_age_days", self.maximum_profile_age_days)
        _positive_int("minimum_event_count", self.minimum_event_count)
        if not isinstance(self.require_previous_digest_chain, bool):
            raise ValueError("require_previous_digest_chain must be boolean")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": CONFIG_SCHEMA,
            "version": VERSION,
            "maximum_profile_age_days": self.maximum_profile_age_days,
            "minimum_event_count": self.minimum_event_count,
            "require_previous_digest_chain": self.require_previous_digest_chain,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class TemporalLifecycleEvent:
    """One immutable ledger event for an asset/version lineage."""

    event_id: str
    asset_id: str
    version_id: str
    sequence: int
    event_time: str
    event_type: str
    content_digest: str
    manifest_digest: str
    authorization_digest: str
    retention_policy_digest: str
    access_policy_digest: str
    snapshot_id: str
    parent_version_id: Optional[str] = None
    previous_event_digest: Optional[str] = None
    deletion_tombstone_digest: Optional[str] = None
    restores_event_id: Optional[str] = None
    tenant_id: str = "tenant-1"
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None

    def __post_init__(self) -> None:
        for name in (
            "event_id", "asset_id", "version_id", "snapshot_id",
        ):
            _text(name, getattr(self, name))
        _text("tenant_id", self.tenant_id)
        _positive_int("sequence", self.sequence)
        object.__setattr__(self, "event_time", _timestamp("event_time", self.event_time))
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported event_type: {self.event_type}")
        for name in (
            "content_digest", "manifest_digest", "authorization_digest",
            "retention_policy_digest", "access_policy_digest",
        ):
            object.__setattr__(self, name, _hex(name, getattr(self, name), allow_zero=False))
        if self.parent_version_id is not None:
            _text("parent_version_id", self.parent_version_id)
        object.__setattr__(self, "previous_event_digest", _optional_hex("previous_event_digest", self.previous_event_digest))
        object.__setattr__(self, "deletion_tombstone_digest", _optional_hex("deletion_tombstone_digest", self.deletion_tombstone_digest))
        if self.restores_event_id is not None:
            _text("restores_event_id", self.restores_event_id)
        if self.effective_from is not None:
            object.__setattr__(self, "effective_from", _timestamp("effective_from", self.effective_from))
        if self.effective_to is not None:
            object.__setattr__(self, "effective_to", _timestamp("effective_to", self.effective_to))
        if self.effective_from is not None and self.effective_to is not None:
            if _parsed_timestamp(self.effective_to) < _parsed_timestamp(self.effective_from):
                raise ValueError("effective_to must not precede effective_from")
        if self.event_type in {EVENT_DELETE, EVENT_EXPIRE} and self.deletion_tombstone_digest is None:
            raise ValueError("delete/expire events require deletion_tombstone_digest")
        if self.event_type != EVENT_RESTORE and self.restores_event_id is not None:
            raise ValueError("only restore events may set restores_event_id")

    @property
    def computed_digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "schema": EVENT_SCHEMA,
            "event_id": self.event_id,
            "tenant_id": self.tenant_id,
            "asset_id": self.asset_id,
            "version_id": self.version_id,
            "sequence": self.sequence,
            "event_time": self.event_time,
            "event_type": self.event_type,
            "content_digest": self.content_digest,
            "manifest_digest": self.manifest_digest,
            "authorization_digest": self.authorization_digest,
            "retention_policy_digest": self.retention_policy_digest,
            "access_policy_digest": self.access_policy_digest,
            "snapshot_id": self.snapshot_id,
            "parent_version_id": self.parent_version_id,
            "previous_event_digest": self.previous_event_digest,
            "deletion_tombstone_digest": self.deletion_tombstone_digest,
            "restores_event_id": self.restores_event_id,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
        }
        if include_digest:
            payload["event_digest"] = self.computed_digest
        return payload


@dataclass(frozen=True)
class TemporalLifecycleRequest:
    """A query against a frozen lifecycle/index snapshot."""

    event_id: str
    asset_id: str
    query_as_of: str
    snapshot_id: str
    snapshot_created_at: str
    snapshot_sequence: int
    ledger_head_sequence: int
    index_epoch: str
    events: Tuple[TemporalLifecycleEvent, ...]
    selected_version_id: Optional[str]
    manifest_digest: str
    authorization_digest: str
    retention_policy_digest: str
    access_policy_digest: str
    profile_digest: str
    profile_fitted_through: str
    split: str
    operation_scope: str
    upstream_route: str
    upstream_evidence_digest: str
    ledger_head_event_time: Optional[str] = None
    expected_snapshot_digest: Optional[str] = None
    profile_max_age_days: Optional[int] = None
    tenant_id: str = "tenant-1"
    time_window: str = "unspecified"

    def __post_init__(self) -> None:
        for name in ("event_id", "tenant_id", "asset_id", "snapshot_id", "index_epoch", "upstream_route"):
            _text(name, getattr(self, name))
        _text("time_window", self.time_window)
        object.__setattr__(self, "query_as_of", _timestamp("query_as_of", self.query_as_of))
        object.__setattr__(self, "snapshot_created_at", _timestamp("snapshot_created_at", self.snapshot_created_at))
        object.__setattr__(self, "profile_fitted_through", _timestamp("profile_fitted_through", self.profile_fitted_through))
        if self.ledger_head_event_time is not None:
            object.__setattr__(self, "ledger_head_event_time", _timestamp("ledger_head_event_time", self.ledger_head_event_time))
        _positive_int("snapshot_sequence", self.snapshot_sequence)
        _positive_int("ledger_head_sequence", self.ledger_head_sequence)
        if self.split not in {"calibration", "evaluation", "external"}:
            raise ValueError("split must be calibration, evaluation, or external")
        if self.operation_scope not in OPERATION_SCOPES:
            raise ValueError("unsupported operation_scope")
        rows = tuple(self.events or ())
        if any(not isinstance(item, TemporalLifecycleEvent) for item in rows):
            raise ValueError("events must contain TemporalLifecycleEvent values")
        object.__setattr__(self, "events", rows)
        for name in (
            "manifest_digest", "authorization_digest", "retention_policy_digest",
            "access_policy_digest", "profile_digest", "upstream_evidence_digest",
        ):
            object.__setattr__(self, name, _hex(name, getattr(self, name), allow_zero=False))
        if self.selected_version_id is not None:
            _text("selected_version_id", self.selected_version_id)
        object.__setattr__(self, "expected_snapshot_digest", _optional_hex("expected_snapshot_digest", self.expected_snapshot_digest))
        if self.profile_max_age_days is not None:
            _nonnegative_int("profile_max_age_days", self.profile_max_age_days)

    @property
    def snapshot_digest(self) -> str:
        return _digest(self.snapshot_payload())

    def snapshot_payload(self) -> Dict[str, Any]:
        return {
            "schema": "temporal-lifecycle-snapshot-v1",
            "snapshot_id": self.snapshot_id,
            "tenant_id": self.tenant_id,
            "asset_id": self.asset_id,
            "snapshot_created_at": self.snapshot_created_at,
            "snapshot_sequence": self.snapshot_sequence,
            "ledger_head_sequence": self.ledger_head_sequence,
            "ledger_head_event_time": self.ledger_head_event_time,
            "index_epoch": self.index_epoch,
            "manifest_digest": self.manifest_digest,
            "authorization_digest": self.authorization_digest,
            "retention_policy_digest": self.retention_policy_digest,
            "access_policy_digest": self.access_policy_digest,
            "events": [row.to_dict() for row in sorted(self.events, key=lambda item: item.sequence)],
            "time_window": self.time_window,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "temporal-lifecycle-request-v1",
            "event_id": self.event_id,
            "tenant_id": self.tenant_id,
            "asset_id": self.asset_id,
            "query_as_of": self.query_as_of,
            "snapshot_id": self.snapshot_id,
            "snapshot_created_at": self.snapshot_created_at,
            "snapshot_sequence": self.snapshot_sequence,
            "ledger_head_sequence": self.ledger_head_sequence,
            "ledger_head_event_time": self.ledger_head_event_time,
            "index_epoch": self.index_epoch,
            "time_window": self.time_window,
            "events": [row.to_dict() for row in sorted(self.events, key=lambda item: item.sequence)],
            "selected_version_id": self.selected_version_id,
            "manifest_digest": self.manifest_digest,
            "authorization_digest": self.authorization_digest,
            "retention_policy_digest": self.retention_policy_digest,
            "access_policy_digest": self.access_policy_digest,
            "profile_digest": self.profile_digest,
            "profile_fitted_through": self.profile_fitted_through,
            "profile_max_age_days": self.profile_max_age_days,
            "split": self.split,
            "operation_scope": self.operation_scope,
            "upstream_route": self.upstream_route,
            "upstream_evidence_digest": self.upstream_evidence_digest,
            "expected_snapshot_digest": self.expected_snapshot_digest,
        }


@dataclass(frozen=True)
class TemporalLifecycleResult:
    route: str
    reason: str
    abstained: bool
    evaluated: bool
    event_id: str
    asset_id: str
    selected_version_id: Optional[str]
    query_as_of: str
    snapshot_id: str
    snapshot_sequence: int
    visible_sequence: int
    active_version_ids: Tuple[str, ...]
    deletion_seen: bool
    downstream_eligible: bool
    upstream_route: str
    snapshot_digest: str
    profile_digest: str
    config_digest: str
    lifecycle_digest: str
    replay_errors: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        routes = {
            ROUTE_LIFECYCLE_CONSISTENT,
            ROUTE_FUTURE_EVENT_LEAK,
            ROUTE_STALE_SNAPSHOT_REVIEW,
            ROUTE_TOMBSTONED_INSUFFICIENT,
            ROUTE_DELETION_REPLAY_MISMATCH,
            ROUTE_PROFILE_STALE,
            ROUTE_INSUFFICIENT,
            ROUTE_NOT_EVALUATED,
        }
        if self.route not in routes:
            raise ValueError(f"unsupported route: {self.route}")
        if self.abstained != (self.route != ROUTE_LIFECYCLE_CONSISTENT):
            raise ValueError("abstained must match route")
        if self.route != ROUTE_LIFECYCLE_CONSISTENT and self.downstream_eligible:
            raise ValueError("failed lifecycle route cannot be downstream eligible")
        for name in ("snapshot_digest", "profile_digest", "config_digest", "lifecycle_digest"):
            _hex(name, getattr(self, name))
        _timestamp("query_as_of", self.query_as_of)
        _positive_int("snapshot_sequence", self.snapshot_sequence)
        _nonnegative_int("visible_sequence", self.visible_sequence)
        if not isinstance(self.deletion_seen, bool) or not isinstance(self.downstream_eligible, bool):
            raise ValueError("boolean result fields must be boolean")

    @property
    def route_only(self) -> bool:
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": SCHEMA,
            "version": VERSION,
            "route": self.route,
            "reason": self.reason,
            "abstained": self.abstained,
            "evaluated": self.evaluated,
            "route_only": True,
            "event_id": self.event_id,
            "asset_id": self.asset_id,
            "selected_version_id": self.selected_version_id,
            "query_as_of": self.query_as_of,
            "snapshot_id": self.snapshot_id,
            "snapshot_sequence": self.snapshot_sequence,
            "visible_sequence": self.visible_sequence,
            "active_version_ids": list(self.active_version_ids),
            "deletion_seen": self.deletion_seen,
            "downstream_eligible": self.downstream_eligible,
            "upstream_route": self.upstream_route,
            "snapshot_digest": self.snapshot_digest,
            "profile_digest": self.profile_digest,
            "config_digest": self.config_digest,
            "lifecycle_digest": self.lifecycle_digest,
            "replay_errors": list(self.replay_errors),
        }


def _result(
    request: TemporalLifecycleRequest,
    config: TemporalLifecycleConfig,
    *,
    route: str,
    reason: str,
    evaluated: bool,
    visible_sequence: int = 0,
    active_version_ids: Sequence[str] = (),
    deletion_seen: bool = False,
    replay_errors: Sequence[str] = (),
    downstream_eligible: bool = False,
) -> TemporalLifecycleResult:
    payload = {
        "schema": SCHEMA,
        "request": request.to_dict(),
        "config_digest": config.digest,
        "route": route,
        "reason": reason,
        "visible_sequence": visible_sequence,
        "active_version_ids": sorted(active_version_ids),
        "deletion_seen": deletion_seen,
        "replay_errors": list(replay_errors),
    }
    return TemporalLifecycleResult(
        route=route,
        reason=reason,
        abstained=route != ROUTE_LIFECYCLE_CONSISTENT,
        evaluated=evaluated,
        event_id=request.event_id,
        asset_id=request.asset_id,
        selected_version_id=request.selected_version_id,
        query_as_of=request.query_as_of,
        snapshot_id=request.snapshot_id,
        snapshot_sequence=request.snapshot_sequence,
        visible_sequence=visible_sequence,
        active_version_ids=tuple(sorted(active_version_ids)),
        deletion_seen=deletion_seen,
        downstream_eligible=downstream_eligible,
        upstream_route=request.upstream_route,
        snapshot_digest=request.snapshot_digest,
        profile_digest=request.profile_digest,
        config_digest=config.digest,
        lifecycle_digest=_digest(payload),
        replay_errors=tuple(replay_errors),
    )


def _common_binding_errors(request: TemporalLifecycleRequest) -> Tuple[str, ...]:
    errors = []
    for row in request.events:
        if row.asset_id != request.asset_id:
            errors.append(f"asset_mismatch:{row.event_id}")
        if row.tenant_id != request.tenant_id:
            errors.append(f"tenant_mismatch:{row.event_id}")
        if row.snapshot_id != request.snapshot_id:
            errors.append(f"snapshot_mismatch:{row.event_id}")
        if row.manifest_digest != request.manifest_digest:
            errors.append(f"manifest_digest_mismatch:{row.event_id}")
        if row.authorization_digest != request.authorization_digest:
            errors.append(f"authorization_digest_mismatch:{row.event_id}")
        if row.retention_policy_digest != request.retention_policy_digest:
            errors.append(f"retention_policy_digest_mismatch:{row.event_id}")
        if row.access_policy_digest != request.access_policy_digest:
            errors.append(f"access_policy_digest_mismatch:{row.event_id}")
    return tuple(errors)


def _event_chain_errors(request: TemporalLifecycleRequest, config: TemporalLifecycleConfig) -> Tuple[str, ...]:
    rows = tuple(sorted(request.events, key=lambda item: item.sequence))
    errors = []
    expected_sequences = tuple(range(1, len(rows) + 1))
    actual_sequences = tuple(row.sequence for row in rows)
    if actual_sequences != expected_sequences:
        errors.append("event_sequence_not_contiguous")
    previous: Optional[TemporalLifecycleEvent] = None
    for row in rows:
        event_time = _parsed_timestamp(row.event_time)
        if row.effective_from is not None and _parsed_timestamp(row.effective_from) > event_time:
            errors.append(f"effective_from_after_event:{row.event_id}")
        if row.effective_to is not None and _parsed_timestamp(row.effective_to) < event_time:
            errors.append(f"effective_to_before_event:{row.event_id}")
        if previous is not None:
            if event_time < _parsed_timestamp(previous.event_time):
                errors.append("event_time_not_monotonic")
            if config.require_previous_digest_chain and row.previous_event_digest != previous.computed_digest:
                errors.append(f"previous_event_digest_mismatch:{row.event_id}")
        elif config.require_previous_digest_chain and row.previous_event_digest is not None:
            errors.append("first_event_previous_digest_present")
        previous = row
    return tuple(errors)


def _lifecycle_state(
    request: TemporalLifecycleRequest,
) -> Tuple[Optional[str], Dict[str, str], bool, Tuple[str, ...]]:
    """Apply visible events and validate delete/restore transitions."""

    rows = tuple(sorted(request.events, key=lambda item: item.sequence))
    query_time = _parsed_timestamp(request.query_as_of)
    states: Dict[str, str] = {}
    deleted_by_event: Dict[str, TemporalLifecycleEvent] = {}
    errors = []
    deletion_seen = False
    for row in rows:
        event_time = _parsed_timestamp(row.event_time)
        if event_time > query_time:
            continue
        current = states.get(row.version_id)
        if row.event_type == EVENT_CREATE:
            if current is not None:
                errors.append(f"duplicate_create:{row.version_id}")
            elif row.parent_version_id is not None and row.parent_version_id not in states:
                errors.append(f"missing_parent:{row.event_id}")
            else:
                states[row.version_id] = "active"
        elif row.event_type == EVENT_UPDATE:
            if current != "active":
                errors.append(f"update_requires_active_version:{row.event_id}")
            else:
                states[row.version_id] = "active"
        elif row.event_type in {EVENT_DELETE, EVENT_EXPIRE}:
            deletion_seen = True
            if current != "active":
                errors.append(f"delete_requires_active_version:{row.event_id}")
            else:
                states[row.version_id] = "deleted" if row.event_type == EVENT_DELETE else "expired"
                deleted_by_event[row.event_id] = row
        elif row.event_type == EVENT_RESTORE:
            if not row.restores_event_id or row.restores_event_id not in deleted_by_event:
                errors.append(f"restore_target_missing:{row.event_id}")
                continue
            deleted = deleted_by_event[row.restores_event_id]
            if row.version_id == deleted.version_id or row.parent_version_id != deleted.version_id:
                errors.append(f"restore_version_binding_mismatch:{row.event_id}")
                continue
            if row.version_id in states:
                errors.append(f"restore_version_already_exists:{row.event_id}")
                continue
            states[row.version_id] = "active"
    return None, states, deletion_seen, tuple(errors)


def evaluate_temporal_lifecycle(
    request: TemporalLifecycleRequest,
    config: Optional[TemporalLifecycleConfig] = None,
) -> TemporalLifecycleResult:
    """Evaluate one as-of lifecycle snapshot with fail-closed routes."""

    if not isinstance(request, TemporalLifecycleRequest):
        raise TypeError("request must be TemporalLifecycleRequest")
    config = config or TemporalLifecycleConfig()
    if request.split == "external":
        return _result(request, config, route=ROUTE_NOT_EVALUATED, reason="external_split_not_evaluated", evaluated=False)
    if len(request.events) < config.minimum_event_count:
        return _result(request, config, route=ROUTE_INSUFFICIENT, reason="event_support_insufficient", evaluated=False)
    if request.expected_snapshot_digest is not None and request.expected_snapshot_digest != request.snapshot_digest:
        return _result(request, config, route=ROUTE_INSUFFICIENT, reason="snapshot_digest_mismatch", evaluated=False, replay_errors=("snapshot_digest_mismatch",))
    if _parsed_timestamp(request.snapshot_created_at) > _parsed_timestamp(request.query_as_of):
        return _result(request, config, route=ROUTE_FUTURE_EVENT_LEAK, reason="snapshot_created_after_query_as_of", evaluated=True)
    if request.ledger_head_sequence < request.snapshot_sequence:
        return _result(request, config, route=ROUTE_INSUFFICIENT, reason="ledger_head_before_snapshot", evaluated=False)
    if request.ledger_head_sequence > request.snapshot_sequence:
        if request.ledger_head_event_time is None:
            return _result(request, config, route=ROUTE_INSUFFICIENT, reason="ledger_head_time_missing", evaluated=False)
        if _parsed_timestamp(request.ledger_head_event_time) <= _parsed_timestamp(request.query_as_of):
            return _result(request, config, route=ROUTE_STALE_SNAPSHOT_REVIEW, reason="snapshot_behind_visible_ledger_head", evaluated=True)
        return _result(request, config, route=ROUTE_FUTURE_EVENT_LEAK, reason="ledger_head_after_query_as_of", evaluated=True)
    if _parsed_timestamp(request.profile_fitted_through) > _parsed_timestamp(request.query_as_of):
        return _result(request, config, route=ROUTE_FUTURE_EVENT_LEAK, reason="profile_fitted_after_query_as_of", evaluated=True)
    max_age = config.maximum_profile_age_days if request.profile_max_age_days is None else request.profile_max_age_days
    age = _parsed_timestamp(request.query_as_of) - _parsed_timestamp(request.profile_fitted_through)
    if age > timedelta(days=max_age):
        return _result(request, config, route=ROUTE_PROFILE_STALE, reason="profile_older_than_maximum_age", evaluated=True)
    for row in request.events:
        event_time = _parsed_timestamp(row.event_time)
        if event_time > _parsed_timestamp(request.query_as_of):
            return _result(request, config, route=ROUTE_FUTURE_EVENT_LEAK, reason="event_after_query_as_of", evaluated=True)
        if row.effective_from is not None and _parsed_timestamp(row.effective_from) > _parsed_timestamp(request.query_as_of):
            return _result(request, config, route=ROUTE_FUTURE_EVENT_LEAK, reason="effective_interval_after_query_as_of", evaluated=True)
    binding_errors = _common_binding_errors(request)
    if binding_errors:
        return _result(request, config, route=ROUTE_INSUFFICIENT, reason="lifecycle_binding_mismatch", evaluated=False, replay_errors=binding_errors)
    chain_errors = _event_chain_errors(request, config)
    if chain_errors:
        return _result(request, config, route=ROUTE_INSUFFICIENT, reason="event_chain_invalid", evaluated=False, replay_errors=chain_errors)
    _, states, deletion_seen, transition_errors = _lifecycle_state(request)
    if transition_errors:
        return _result(request, config, route=ROUTE_DELETION_REPLAY_MISMATCH, reason="deletion_restore_transition_invalid", evaluated=True, visible_sequence=request.snapshot_sequence, active_version_ids=tuple(version for version, state in states.items() if state == "active"), deletion_seen=deletion_seen, replay_errors=transition_errors)
    if request.selected_version_id is not None:
        selected_state = states.get(request.selected_version_id)
        if selected_state in {"deleted", "expired"}:
            return _result(request, config, route=ROUTE_TOMBSTONED_INSUFFICIENT, reason="selected_version_tombstoned_as_of_query", evaluated=True, visible_sequence=request.snapshot_sequence, active_version_ids=tuple(version for version, state in states.items() if state == "active"), deletion_seen=deletion_seen)
        if selected_state is None:
            return _result(request, config, route=ROUTE_INSUFFICIENT, reason="selected_version_missing_as_of_query", evaluated=False, visible_sequence=request.snapshot_sequence, active_version_ids=tuple(version for version, state in states.items() if state == "active"), deletion_seen=deletion_seen)
    if request.upstream_route in _BLOCKED_UPSTREAM_ROUTES or request.upstream_route not in _CANDIDATE_UPSTREAM_ROUTES | {"null_consistent", "ordinary_propagation_consistent"}:
        return _result(request, config, route=ROUTE_INSUFFICIENT, reason="upstream_route_blocked", evaluated=True, visible_sequence=request.snapshot_sequence, active_version_ids=tuple(version for version, state in states.items() if state == "active"), deletion_seen=deletion_seen, replay_errors=(f"upstream_route:{request.upstream_route}",))
    active = tuple(version for version, state in states.items() if state == "active")
    downstream_eligible = (
        request.operation_scope == OPERATION_CONTENT_EDIT
        and request.upstream_route in _CANDIDATE_UPSTREAM_ROUTES
        and request.selected_version_id is not None
    )
    return _result(request, config, route=ROUTE_LIFECYCLE_CONSISTENT, reason="as_of_lifecycle_consistent", evaluated=True, visible_sequence=request.snapshot_sequence, active_version_ids=active, deletion_seen=deletion_seen, downstream_eligible=downstream_eligible)


def replay_temporal_lifecycle(request: TemporalLifecycleRequest, config: Optional[TemporalLifecycleConfig] = None) -> TemporalLifecycleResult:
    """Alias emphasizing that the function replays, rather than predicts."""

    return evaluate_temporal_lifecycle(request, config)


__all__ = [
    "VERSION", "SCHEMA", "EVENT_SCHEMA", "CONFIG_SCHEMA",
    "ROUTE_LIFECYCLE_CONSISTENT", "ROUTE_FUTURE_EVENT_LEAK", "ROUTE_STALE_SNAPSHOT_REVIEW",
    "ROUTE_TOMBSTONED_INSUFFICIENT", "ROUTE_DELETION_REPLAY_MISMATCH", "ROUTE_PROFILE_STALE",
    "ROUTE_INSUFFICIENT", "ROUTE_NOT_EVALUATED",
    "EVENT_CREATE", "EVENT_UPDATE", "EVENT_DELETE", "EVENT_RESTORE", "EVENT_EXPIRE",
    "OPERATION_CONTENT_EDIT", "OPERATION_ORDINARY_PROPAGATION",
    "TemporalLifecycleConfig", "TemporalLifecycleEvent", "TemporalLifecycleRequest",
    "TemporalLifecycleResult", "evaluate_temporal_lifecycle", "replay_temporal_lifecycle",
]
