"""Offline replay of a frozen retrieval event.

This module is the small bridge between a frozen retrieval/index archive and
the existing :mod:`aigc.retrieval_aware_tree_null` raw contract.  It deliberately
does not load an index, run a detector, or make an AIGC, authorship, copyright,
or legal decision.  A replay either reconstructs the event from the archive
and returns a route-only raw sidecar, or fails closed.

The important design point is that the archive and the selection trace are
inputs to an audit, while the trace in the result is always produced by this
module.  A caller supplied final candidate list cannot silently become the
selection evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import math
from datetime import date, datetime
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union

from .retrieval_aware_tree_null import (
    MEMBERSHIP_EXACT,
    MEMBERSHIP_MATCHED,
    MEMBERSHIP_OUTSIDE,
    MEMBERSHIP_UNCERTAIN,
    OPERATION_CONTENT_EDIT,
    OPERATION_ORDINARY_PROPAGATION,
    RSCPTNConfig,
    RetrievalCandidate,
    RetrievalEvent,
    RSCPTNNullProfile,
    evaluate_retrieval_aware_tree_null,
)


VERSION = "retrieval-event-replay-v1"
SCHEMA = "retrieval-event-replay-result-v1"
# Explicit names keep package-level discovery consistent with the other
# research adapters in ``aigc.__init__``.
RETRIEVAL_EVENT_REPLAY_VERSION = VERSION
RETRIEVAL_EVENT_REPLAY_SCHEMA = SCHEMA
ARCHIVE_SCHEMA = "retrieval-archive-snapshot-v1"
SELECTION_SCHEMA = "retrieval-selection-trace-v1"
_HEX_ZERO = "0" * 64

ROUTE_CANDIDATE = "candidate"
ROUTE_NULL_CONSISTENT = "null_consistent"
ROUTE_REVIEW = "review"
ROUTE_OPEN_SET_UNKNOWN = "open_set_unknown"
ROUTE_INSUFFICIENT = "insufficient"
ROUTE_NOT_EVALUATED = "not_evaluated"

# Names used by callers that prefer the RSCPTN wording.
ROUTE_RETRIEVAL_TREE_CANDIDATE = ROUTE_CANDIDATE
ROUTE_RETRIEVAL_TREE_NULL = ROUTE_NULL_CONSISTENT
ROUTE_RETRIEVAL_CONTAMINATED = ROUTE_REVIEW

MEMBERSHIP_TIERS = {
    MEMBERSHIP_EXACT,
    MEMBERSHIP_MATCHED,
    MEMBERSHIP_UNCERTAIN,
    MEMBERSHIP_OUTSIDE,
}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _hex(name: str, value: Any) -> str:
    value = _text(name, value).lower()
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return value


def _optional_hex(name: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    return _hex(name, value)


def _finite(name: str, value: Any, *, lower: Optional[float] = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite")
    value = float(value)
    if not math.isfinite(value) or (lower is not None and value < lower):
        raise ValueError(f"{name} must be finite and >= {lower or 0}")
    return value


def _nonnegative_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be an integer >= 0")
    return value


def _positive_int(name: str, value: Any) -> int:
    value = _nonnegative_int(name, value)
    if value < 1:
        raise ValueError(f"{name} must be an integer >= 1")
    return value


def _unit(name: str, value: Any) -> float:
    value = _finite(name, value, lower=0.0)
    if value > 1.0:
        raise ValueError(f"{name} must be <= 1")
    return value


def _tuple_text(value: Any, name: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    result = tuple(_text(f"{name}[]", item) for item in value)
    return result


@dataclass(frozen=True)
class ArchiveEntry:
    """A row in a frozen retrieval/index snapshot.

    ``candidate_rank`` is the rank frozen by the index export.  Replay checks
    it against ``retrieval_score`` and the deterministic tie break, so changing
    either the rank or score cannot be hidden by a caller supplied selection
    list.  Digest fields are populated by :meth:`RetrievalArchiveSnapshot.freeze`
    when they are left at the all-zero placeholder.
    """

    candidate_id: str
    candidate_rank: int
    retrieval_score: float
    asset_id: str
    tree_id: str
    version_id: str
    parent_version_id: Optional[str]
    branch_id: str
    depth: int
    membership_tier: str
    paired_delta_raw: float
    quality_score: float
    source_match_score: float
    canonical_frame_digest: str
    detector_version: str
    score_schema: str
    operation_scope: str = OPERATION_CONTENT_EDIT
    input_digest: str = _HEX_ZERO
    evidence_digest: str = _HEX_ZERO
    membership_decision_digest: str = _HEX_ZERO
    transform_family: str = "unknown"
    quality_bucket: str = "unknown"
    transport_bucket: str = "unknown"
    time_bucket: str = "unknown"
    selection_group_id: str = "default"
    generator_family: str = "known"
    authorized_for_research: bool = True
    edit_mask_digest: Optional[str] = None
    edit_type: Optional[str] = None
    edit_steps: Tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "candidate_id", "asset_id", "tree_id", "version_id", "branch_id",
            "detector_version", "score_schema", "transform_family", "quality_bucket",
            "transport_bucket", "time_bucket", "selection_group_id", "generator_family",
        ):
            _text(name, getattr(self, name))
        _positive_int("candidate_rank", self.candidate_rank)
        _finite("retrieval_score", self.retrieval_score)
        _nonnegative_int("depth", self.depth)
        if self.parent_version_id is not None:
            _text("parent_version_id", self.parent_version_id)
        if self.membership_tier not in MEMBERSHIP_TIERS:
            raise ValueError("unsupported membership_tier")
        _finite("paired_delta_raw", self.paired_delta_raw)
        _unit("quality_score", self.quality_score)
        _unit("source_match_score", self.source_match_score)
        for name in (
            "canonical_frame_digest", "input_digest", "evidence_digest",
            "membership_decision_digest",
        ):
            _hex(name, getattr(self, name))
        if self.operation_scope not in {OPERATION_CONTENT_EDIT, OPERATION_ORDINARY_PROPAGATION}:
            raise ValueError("unsupported operation_scope")
        if not isinstance(self.authorized_for_research, bool):
            raise ValueError("authorized_for_research must be boolean")
        object.__setattr__(self, "edit_steps", tuple(self.edit_steps or ()))
        _optional_hex("edit_mask_digest", self.edit_mask_digest)
        if self.edit_type is not None:
            _text("edit_type", self.edit_type)

    @property
    def rank(self) -> int:
        return self.candidate_rank

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "retrieval-archive-entry-v1",
            "candidate_id": self.candidate_id,
            "candidate_rank": self.candidate_rank,
            "retrieval_score": float(self.retrieval_score),
            "asset_id": self.asset_id,
            "tree_id": self.tree_id,
            "version_id": self.version_id,
            "parent_version_id": self.parent_version_id,
            "branch_id": self.branch_id,
            "depth": self.depth,
            "membership_tier": self.membership_tier,
            "paired_delta_raw": float(self.paired_delta_raw),
            "quality_score": float(self.quality_score),
            "source_match_score": float(self.source_match_score),
            "canonical_frame_digest": self.canonical_frame_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "operation_scope": self.operation_scope,
            "input_digest": self.input_digest,
            "evidence_digest": self.evidence_digest,
            "membership_decision_digest": self.membership_decision_digest,
            "transform_family": self.transform_family,
            "quality_bucket": self.quality_bucket,
            "transport_bucket": self.transport_bucket,
            "time_bucket": self.time_bucket,
            "selection_group_id": self.selection_group_id,
            "generator_family": self.generator_family,
            "authorized_for_research": self.authorized_for_research,
            "edit_mask_digest": self.edit_mask_digest,
            "edit_type": self.edit_type,
            "edit_steps": list(self.edit_steps),
        }


# Friendly aliases used in research notebooks and task notes.
RetrievalArchiveEntry = ArchiveEntry
RetrievalCandidateRecord = ArchiveEntry


def _index_payload(snapshot_id: str, entries: Sequence[ArchiveEntry]) -> Dict[str, Any]:
    return {
        "schema": "retrieval-index-snapshot-v1",
        "snapshot_id": snapshot_id,
        "entries": [
            {
                "candidate_id": item.candidate_id,
                "candidate_rank": item.candidate_rank,
                "retrieval_score": float(item.retrieval_score),
            }
            for item in sorted(entries, key=lambda row: (row.candidate_rank, row.candidate_id))
        ],
    }


def _membership_digest(
    *, query_asset_id: str, membership_policy_digest: str, entry: ArchiveEntry,
) -> str:
    return _digest({
        "schema": "membership-decision-v1",
        "query_asset_id": query_asset_id,
        "candidate_id": entry.candidate_id,
        "asset_id": entry.asset_id,
        "tree_id": entry.tree_id,
        "version_id": entry.version_id,
        "membership_tier": entry.membership_tier,
        "membership_policy_digest": membership_policy_digest,
    })


def _entry_input_digest(
    *, snapshot: Mapping[str, Any], entry: ArchiveEntry, index_digest: str,
) -> str:
    return _digest({
        "schema": "retrieval-entry-input-v1",
        "query_digest": snapshot["query_digest"],
        "candidate_id": entry.candidate_id,
        "asset_id": entry.asset_id,
        "tree_id": entry.tree_id,
        "version_id": entry.version_id,
        "parent_version_id": entry.parent_version_id,
        "branch_id": entry.branch_id,
        "depth": entry.depth,
        "candidate_rank": entry.candidate_rank,
        "retrieval_score": float(entry.retrieval_score),
        "index_digest": index_digest,
        "retrieval_policy_digest": snapshot["retrieval_policy_digest"],
        "membership_policy_digest": snapshot["membership_policy_digest"],
        "manifest_digest": snapshot["manifest_digest"],
        "operation_scope": entry.operation_scope,
        "canonical_frame_digest": snapshot["canonical_frame_digest"],
        "detector_version": snapshot["detector_version"],
        "score_schema": snapshot["score_schema"],
    })


def _entry_evidence_digest(*, entry: ArchiveEntry, input_digest: str, membership_digest: str) -> str:
    return _digest({
        "schema": "retrieval-entry-evidence-v1",
        "input_digest": input_digest,
        "membership_decision_digest": membership_digest,
        "paired_delta_raw": float(entry.paired_delta_raw),
        "quality_score": float(entry.quality_score),
        "source_match_score": float(entry.source_match_score),
        "operation_scope": entry.operation_scope,
        "edit_mask_digest": entry.edit_mask_digest,
        "edit_type": entry.edit_type,
        "edit_steps": list(entry.edit_steps),
    })


@dataclass(frozen=True)
class RetrievalArchiveSnapshot:
    """Immutable archive export used as the only retrieval input."""

    snapshot_id: str
    query_asset_id: str
    query_digest: str
    entries: Tuple[ArchiveEntry, ...]
    retrieval_policy_digest: str
    membership_policy_digest: str
    manifest_digest: str
    canonical_frame_digest: str
    detector_version: str
    score_schema: str
    index_digest: str
    top_k: int
    snapshot_digest: str = ""
    archive_index_digest: Optional[str] = None
    archive_version: str = "frozen"

    def __post_init__(self) -> None:
        for name in (
            "snapshot_id", "query_asset_id", "detector_version", "score_schema", "archive_version",
        ):
            _text(name, getattr(self, name))
        for name in (
            "query_digest", "retrieval_policy_digest", "membership_policy_digest", "manifest_digest",
            "canonical_frame_digest", "index_digest",
        ):
            _hex(name, getattr(self, name))
        _nonnegative_int("top_k", self.top_k)
        entries = tuple(self.entries or ())
        if any(not isinstance(item, ArchiveEntry) for item in entries):
            raise ValueError("entries must contain ArchiveEntry values")
        object.__setattr__(self, "entries", entries)
        if self.archive_index_digest is None:
            object.__setattr__(self, "archive_index_digest", self.index_digest)
        else:
            _hex("archive_index_digest", self.archive_index_digest)
        if not self.snapshot_digest:
            object.__setattr__(self, "snapshot_digest", self.computed_digest)
        else:
            _hex("snapshot_digest", self.snapshot_digest)

    @classmethod
    def freeze(
        cls,
        entries: Iterable[ArchiveEntry],
        *,
        snapshot_id: str,
        query_asset_id: str,
        query_digest: str,
        retrieval_policy_digest: str,
        membership_policy_digest: str,
        manifest_digest: str,
        canonical_frame_digest: str,
        detector_version: str,
        score_schema: str,
        top_k: Optional[int] = None,
        index_digest: Optional[str] = None,
        archive_index_digest: Optional[str] = None,
        archive_version: str = "frozen",
        bind_placeholders: bool = True,
    ) -> "RetrievalArchiveSnapshot":
        rows = tuple(entries)
        if any(not isinstance(item, ArchiveEntry) for item in rows):
            raise ValueError("entries must contain ArchiveEntry values")
        rows = tuple(sorted(rows, key=lambda row: (row.candidate_rank, row.candidate_id)))
        query_asset_id = _text("query_asset_id", query_asset_id)
        query_digest = _hex("query_digest", query_digest)
        retrieval_policy_digest = _hex("retrieval_policy_digest", retrieval_policy_digest)
        membership_policy_digest = _hex("membership_policy_digest", membership_policy_digest)
        manifest_digest = _hex("manifest_digest", manifest_digest)
        canonical_frame_digest = _hex("canonical_frame_digest", canonical_frame_digest)
        index_digest = index_digest or _digest(_index_payload(snapshot_id, rows))
        index_digest = _hex("index_digest", index_digest)
        meta = {
            "query_digest": query_digest,
            "retrieval_policy_digest": retrieval_policy_digest,
            "membership_policy_digest": membership_policy_digest,
            "manifest_digest": manifest_digest,
            "canonical_frame_digest": canonical_frame_digest,
            "detector_version": detector_version,
            "score_schema": score_schema,
        }
        if bind_placeholders:
            bound = []
            for row in rows:
                membership = row.membership_decision_digest
                if membership == _HEX_ZERO:
                    membership = _membership_digest(
                        query_asset_id=query_asset_id,
                        membership_policy_digest=membership_policy_digest,
                        entry=row,
                    )
                input_digest = row.input_digest
                if input_digest == _HEX_ZERO:
                    input_digest = _entry_input_digest(snapshot=meta, entry=row, index_digest=index_digest)
                evidence = row.evidence_digest
                if evidence == _HEX_ZERO:
                    evidence = _entry_evidence_digest(
                        entry=row, input_digest=input_digest, membership_digest=membership,
                    )
                bound.append(replace(
                    row,
                    membership_decision_digest=membership,
                    input_digest=input_digest,
                    evidence_digest=evidence,
                ))
            rows = tuple(bound)
        top_k = len(rows) if top_k is None else top_k
        if not isinstance(top_k, int) or top_k < 0 or top_k > len(rows):
            raise ValueError("top_k must be between zero and entry count")
        result = cls(
            snapshot_id=_text("snapshot_id", snapshot_id),
            query_asset_id=query_asset_id,
            query_digest=query_digest,
            entries=rows,
            retrieval_policy_digest=retrieval_policy_digest,
            membership_policy_digest=membership_policy_digest,
            manifest_digest=manifest_digest,
            canonical_frame_digest=canonical_frame_digest,
            detector_version=_text("detector_version", detector_version),
            score_schema=_text("score_schema", score_schema),
            index_digest=index_digest,
            top_k=top_k,
            archive_index_digest=archive_index_digest or index_digest,
            archive_version=_text("archive_version", archive_version),
        )
        # __post_init__ computes the digest after all placeholders are bound.
        return result

    @property
    def archive_digest(self) -> str:
        return self.snapshot_digest

    @property
    def index_snapshot_digest(self) -> str:
        return self.index_digest

    @property
    def computed_digest(self) -> str:
        return _digest(self._payload())

    def _payload(self) -> Dict[str, Any]:
        return {
            "schema": ARCHIVE_SCHEMA,
            "snapshot_id": self.snapshot_id,
            "query_asset_id": self.query_asset_id,
            "query_digest": self.query_digest,
            "entries": [row.to_dict() for row in sorted(self.entries, key=lambda row: (row.candidate_rank, row.candidate_id))],
            "retrieval_policy_digest": self.retrieval_policy_digest,
            "membership_policy_digest": self.membership_policy_digest,
            "manifest_digest": self.manifest_digest,
            "canonical_frame_digest": self.canonical_frame_digest,
            "detector_version": self.detector_version,
            "score_schema": self.score_schema,
            "index_digest": self.index_digest,
            "archive_index_digest": self.archive_index_digest,
            "top_k": self.top_k,
            "archive_version": self.archive_version,
        }

    def validate(self) -> Tuple[str, ...]:
        """Return deterministic structural/digest errors without mutating state."""

        errors = []
        if self.snapshot_digest != self.computed_digest:
            errors.append("archive_snapshot_digest_mismatch")
        expected_index = _digest(_index_payload(self.snapshot_id, self.entries))
        if self.index_digest != expected_index:
            errors.append("index_snapshot_digest_mismatch")
        if len(self.entries) != len({row.candidate_id for row in self.entries}):
            errors.append("candidate_id_duplicate")
        ranks = tuple(row.candidate_rank for row in sorted(self.entries, key=lambda row: (row.candidate_rank, row.candidate_id)))
        if ranks != tuple(range(1, len(ranks) + 1)):
            errors.append("candidate_rank_not_contiguous")
        if self.top_k != len(self.entries):
            errors.append("top_k_snapshot_mismatch")
        expected_order = tuple(
            row.candidate_id for row in sorted(self.entries, key=lambda row: (-row.retrieval_score, row.candidate_id))
        )
        actual_order = tuple(
            row.candidate_id for row in sorted(self.entries, key=lambda row: row.candidate_rank)
        )
        if expected_order != actual_order:
            errors.append("candidate_rank_replay_mismatch")
        for row in self.entries:
            if row.authorized_for_research is not True:
                errors.append(f"candidate_unauthorized:{row.candidate_id}")
            expected_membership = _membership_digest(
                query_asset_id=self.query_asset_id,
                membership_policy_digest=self.membership_policy_digest,
                entry=row,
            )
            if row.membership_decision_digest != expected_membership:
                errors.append(f"membership_digest_mismatch:{row.candidate_id}")
            expected_input = _entry_input_digest(
                snapshot={
                    "query_digest": self.query_digest,
                    "retrieval_policy_digest": self.retrieval_policy_digest,
                    "membership_policy_digest": self.membership_policy_digest,
                    "manifest_digest": self.manifest_digest,
                    "canonical_frame_digest": self.canonical_frame_digest,
                    "detector_version": self.detector_version,
                    "score_schema": self.score_schema,
                },
                entry=row,
                index_digest=self.index_digest,
            )
            if row.input_digest != expected_input:
                errors.append(f"input_digest_mismatch:{row.candidate_id}")
            expected_evidence = _entry_evidence_digest(
                entry=row, input_digest=row.input_digest,
                membership_digest=row.membership_decision_digest,
            )
            if row.evidence_digest != expected_evidence:
                errors.append(f"evidence_digest_mismatch:{row.candidate_id}")
        return tuple(errors)

    def to_dict(self) -> Dict[str, Any]:
        payload = dict(self._payload())
        payload["snapshot_digest"] = self.snapshot_digest
        return payload


RetrievalIndexSnapshot = RetrievalArchiveSnapshot
FrozenRetrievalArchive = RetrievalArchiveSnapshot


@dataclass(frozen=True)
class ResearchAuthorization:
    authorization_id: str
    scope: str
    deletion_owner: str
    expires_at: Optional[str] = None
    authorized: bool = True
    privacy_scope: Optional[str] = None
    request_principal_digest: Optional[str] = None
    access_policy_digest: Optional[str] = None
    access_audit_digest: Optional[str] = None
    retention_policy_digest: Optional[str] = None
    deletion_tombstone_digest: Optional[str] = None
    raw_asset_return_policy: str = "no_raw_asset"
    metadata_return_policy: str = "minimal"
    deletion_tombstone_present: bool = False

    def valid(self, as_of: Optional[str] = None) -> bool:
        return self.validation_reason(as_of=as_of) is None

    def validation_reason(self, *, as_of: Optional[str] = None) -> Optional[str]:
        if not self.authorized:
            return "unauthorized_input"
        if not (
            isinstance(self.authorization_id, str) and self.authorization_id.strip()
            and isinstance(self.scope, str) and self.scope.strip()
            and isinstance(self.deletion_owner, str) and self.deletion_owner.strip()
            and isinstance(self.privacy_scope, str) and self.privacy_scope.strip()
            and self.raw_asset_return_policy in {"no_raw_asset", "metadata_only"}
            and self.metadata_return_policy in {"minimal", "no_raw_asset"}
            and isinstance(self.deletion_tombstone_present, bool)
        ):
            return "privacy_authorization_missing"
        if self.deletion_tombstone_present:
            return "privacy_deletion_tombstone"
        for name in (
            "request_principal_digest", "access_policy_digest", "access_audit_digest",
            "retention_policy_digest", "deletion_tombstone_digest",
        ):
            try:
                digest = _hex(name, getattr(self, name))
                if digest == _HEX_ZERO:
                    return f"privacy_{name}_missing"
            except ValueError:
                return f"privacy_{name}_missing"
        if self.expires_at:
            try:
                stamp = self.expires_at
                expiry = datetime.fromisoformat(stamp.replace("Z", "+00:00")).date() if "T" in stamp else date.fromisoformat(stamp)
            except (TypeError, ValueError):
                return "authorization_expiry_invalid"
            if as_of is None:
                return "authorization_expiry_check_date_missing"
            try:
                check_date = datetime.fromisoformat(as_of.replace("Z", "+00:00")).date() if "T" in as_of else date.fromisoformat(as_of)
            except (TypeError, ValueError):
                return "authorization_check_date_invalid"
            if expiry < check_date:
                return "authorization_expired"
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authorization_id": self.authorization_id,
            "scope": self.scope,
            "deletion_owner": self.deletion_owner,
            "expires_at": self.expires_at,
            "authorized": self.authorized,
            "privacy_scope": self.privacy_scope,
            "request_principal_digest": self.request_principal_digest,
            "access_policy_digest": self.access_policy_digest,
            "access_audit_digest": self.access_audit_digest,
            "retention_policy_digest": self.retention_policy_digest,
            "deletion_tombstone_digest": self.deletion_tombstone_digest,
            "raw_asset_return_policy": self.raw_asset_return_policy,
            "metadata_return_policy": self.metadata_return_policy,
            "deletion_tombstone_present": self.deletion_tombstone_present,
        }


AuthorizationEvidence = ResearchAuthorization


@dataclass(frozen=True)
class EditEvidence:
    edit_mask_digest: Optional[str] = None
    edit_type: Optional[str] = None
    steps: Tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        _optional_hex("edit_mask_digest", self.edit_mask_digest)
        if self.edit_type is not None:
            _text("edit_type", self.edit_type)
        object.__setattr__(self, "steps", tuple(self.steps or ()))

    @property
    def steps_digest(self) -> str:
        return _digest({"schema": "edit-step-lineage-v1", "steps": list(self.steps)})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edit_mask_digest": self.edit_mask_digest,
            "edit_type": self.edit_type,
            "steps": list(self.steps),
            "steps_digest": self.steps_digest,
        }


EditLineageEvidence = EditEvidence


@dataclass(frozen=True)
class SelectionAction:
    step: int
    action: str
    input_candidate_ids: Tuple[str, ...]
    output_candidate_ids: Tuple[str, ...]
    selected_candidate_id: Optional[str] = None
    budget_cost: int = 1

    def __post_init__(self) -> None:
        _positive_int("step", self.step)
        _text("action", self.action)
        object.__setattr__(self, "input_candidate_ids", _tuple_text(self.input_candidate_ids, "input_candidate_ids"))
        object.__setattr__(self, "output_candidate_ids", _tuple_text(self.output_candidate_ids, "output_candidate_ids"))
        if self.selected_candidate_id is not None:
            _text("selected_candidate_id", self.selected_candidate_id)
        _positive_int("budget_cost", self.budget_cost)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "action": self.action,
            "input_candidate_ids": list(self.input_candidate_ids),
            "output_candidate_ids": list(self.output_candidate_ids),
            "selected_candidate_id": self.selected_candidate_id,
            "budget_cost": self.budget_cost,
        }


@dataclass(frozen=True)
class SelectionTrace:
    actions: Tuple[SelectionAction, ...]
    trace_digest: str = ""

    def __post_init__(self) -> None:
        actions = tuple(self.actions or ())
        if any(not isinstance(action, SelectionAction) for action in actions):
            raise ValueError("actions must contain SelectionAction values")
        object.__setattr__(self, "actions", actions)
        if not self.trace_digest:
            object.__setattr__(self, "trace_digest", self.computed_digest)
        else:
            _hex("trace_digest", self.trace_digest)

    @property
    def computed_digest(self) -> str:
        return _digest({"schema": SELECTION_SCHEMA, "actions": [action.to_dict() for action in self.actions]})

    @property
    def total_cost(self) -> int:
        return sum(action.budget_cost for action in self.actions)

    def valid(self) -> bool:
        return (
            self.trace_digest == self.computed_digest
            and tuple(action.step for action in self.actions) == tuple(range(1, len(self.actions) + 1))
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": SELECTION_SCHEMA,
            "actions": [action.to_dict() for action in self.actions],
            "trace_digest": self.trace_digest,
            "total_cost": self.total_cost,
        }


SelectionReplayTrace = SelectionTrace


@dataclass(frozen=True)
class ReplayRequest:
    event_id: str
    snapshot: RetrievalArchiveSnapshot
    query_digest: str
    query_asset_id: str
    manifest_digest: str
    split: str
    calibration_split_digest: str
    evaluation_split_digest: str
    operation_scope: str
    authorization: Any = None
    null_profile: Optional[RSCPTNNullProfile] = None
    rscptn_config: Optional[RSCPTNConfig] = None
    action_budget: int = 3
    selection_policy: str = "max-paired-delta-then-rank-v1"
    selection_policy_digest: Optional[str] = None
    selection_trace: Optional[SelectionTrace] = None
    edit_evidence: Optional[EditEvidence] = None
    reference_route: str = "reference_specific_candidate"
    invariant_route: str = "invariant_candidate"
    open_set: bool = False
    generator_family: str = "known"
    poisoning_stress_route: str = "clean"
    poisoning_route_flip: bool = False
    decoy_injection_digest: str = _HEX_ZERO
    # A deployment may freeze one global index while each query snapshot has a
    # different candidate export.  When supplied, this digest is the global
    # archive binding used by RSCPTN profile fitting; the per-query snapshot
    # digest remains in the replay result and event input binding.
    retrieval_archive_digest: Optional[str] = None
    external_split: bool = False
    # Optional top-level aliases make JSON manifests ergonomic.  When set,
    # these values are merged into ``authorization`` before validation.
    privacy_scope: Optional[str] = None
    request_principal_digest: Optional[str] = None
    access_policy_digest: Optional[str] = None
    access_audit_digest: Optional[str] = None
    retention_policy_digest: Optional[str] = None
    deletion_tombstone_digest: Optional[str] = None
    raw_asset_return_policy: Optional[str] = None
    metadata_return_policy: Optional[str] = None
    evaluation_time: Optional[str] = None
    as_of: Optional[str] = None


@dataclass(frozen=True)
class RetrievalReplayResult:
    """Route-only replay output plus auditable binding fields."""

    route: str
    reason: str
    abstained: bool
    evaluated: bool
    event_id: str
    snapshot_digest: Optional[str]
    index_digest: Optional[str]
    event_digest: Optional[str]
    binding_digest: Optional[str]
    selection_trace_digest: Optional[str]
    selection_actions: Tuple[Dict[str, Any], ...]
    candidate_ids: Tuple[str, ...]
    selected_candidate_ids: Tuple[str, ...]
    exact_count: int
    matched_count: int
    uncertain_count: int
    outside_count: int
    tree_errors: Tuple[str, ...] = ()
    replay_errors: Tuple[str, ...] = ()
    operation_scope: Optional[str] = None
    event: Optional[RetrievalEvent] = field(default=None, repr=False, compare=False)
    trace: Optional[SelectionTrace] = field(default=None, repr=False, compare=False)

    @property
    def route_only(self) -> bool:
        return True

    @property
    def candidate_supported(self) -> bool:
        return self.route == ROUTE_CANDIDATE

    def to_dict(self) -> Dict[str, Any]:
        # Do not add probabilities, confidence, authorship, copyright, or legal
        # labels here.  This is intentionally a route/audit sidecar.
        return {
            "schema": SCHEMA,
            "version": VERSION,
            "route": self.route,
            "reason": self.reason,
            "abstained": self.abstained,
            "evaluated": self.evaluated,
            "route_only": True,
            "event_id": self.event_id,
            "snapshot_digest": self.snapshot_digest,
            "index_digest": self.index_digest,
            "event_digest": self.event_digest,
            "binding_digest": self.binding_digest,
            "selection_trace_digest": self.selection_trace_digest,
            "selection_actions": [dict(item) for item in self.selection_actions],
            "candidate_ids": list(self.candidate_ids),
            "selected_candidate_ids": list(self.selected_candidate_ids),
            "exact_count": self.exact_count,
            "matched_count": self.matched_count,
            "uncertain_count": self.uncertain_count,
            "outside_count": self.outside_count,
            "tree_errors": list(self.tree_errors),
            "replay_errors": list(self.replay_errors),
            "operation_scope": self.operation_scope,
        }


ReplayResult = RetrievalReplayResult


def _coerce_authorization(value: Any) -> Optional[ResearchAuthorization]:
    if isinstance(value, ResearchAuthorization):
        return value
    if isinstance(value, bool):
        return ResearchAuthorization("boolean-authorization", "research", "project-owner", authorized=value)
    if isinstance(value, Mapping):
        return ResearchAuthorization(
            authorization_id=str(value.get("authorization_id", value.get("id", ""))),
            scope=str(value.get("scope", "")),
            deletion_owner=str(value.get("deletion_owner", value.get("owner", ""))),
            expires_at=value.get("expires_at"),
            authorized=bool(value.get("authorized", value.get("authorized_for_research", True))),
            privacy_scope=value.get("privacy_scope"),
            request_principal_digest=value.get("request_principal_digest"),
            access_policy_digest=value.get("access_policy_digest"),
            access_audit_digest=value.get("access_audit_digest"),
            retention_policy_digest=value.get("retention_policy_digest"),
            deletion_tombstone_digest=value.get("deletion_tombstone_digest"),
            raw_asset_return_policy=value.get("raw_asset_return_policy", "no_raw_asset"),
            metadata_return_policy=value.get("metadata_return_policy", "minimal"),
            deletion_tombstone_present=bool(value.get("deletion_tombstone_present", value.get("deleted", False))),
        )
    return None


def _coerce_entry(value: Union[ArchiveEntry, Mapping[str, Any]]) -> ArchiveEntry:
    if isinstance(value, ArchiveEntry):
        return value
    data = dict(value)
    aliases = {
        "rank": "candidate_rank", "parent_id": "parent_version_id", "score": "retrieval_score",
        "mask_digest": "edit_mask_digest", "steps": "edit_steps",
    }
    for old, new in aliases.items():
        if new not in data and old in data:
            data[new] = data[old]
    data.pop("schema", None)
    data.setdefault("parent_version_id", None)
    return ArchiveEntry(**data)


def _coerce_snapshot(value: Union[RetrievalArchiveSnapshot, Mapping[str, Any]]) -> RetrievalArchiveSnapshot:
    if isinstance(value, RetrievalArchiveSnapshot):
        return value
    data = dict(value)
    rows = data.pop("entries", data.pop("candidates", ()))
    data["entries"] = tuple(_coerce_entry(item) for item in rows)
    data.pop("schema", None)
    if "archive_digest" in data and "snapshot_digest" not in data:
        data["snapshot_digest"] = data.pop("archive_digest")
    if "index_snapshot_digest" in data and "index_digest" not in data:
        data["index_digest"] = data.pop("index_snapshot_digest")
    return RetrievalArchiveSnapshot(**data)


def _coerce_edit(value: Any, kwargs: Mapping[str, Any]) -> EditEvidence:
    if isinstance(value, EditEvidence):
        return value
    if isinstance(value, Mapping):
        return EditEvidence(
            edit_mask_digest=value.get("edit_mask_digest", value.get("mask_digest")),
            edit_type=value.get("edit_type"),
            steps=tuple(value.get("steps", value.get("edit_steps", ())) or ()),
        )
    return EditEvidence(
        edit_mask_digest=kwargs.get("edit_mask_digest"),
        edit_type=kwargs.get("edit_type"),
        steps=tuple(kwargs.get("edit_steps", kwargs.get("steps", ())) or ()),
    )


def _coerce_action(value: Any) -> SelectionAction:
    if isinstance(value, SelectionAction):
        return value
    data = dict(value)
    data.pop("schema", None)
    return SelectionAction(
        step=data.get("step", data.get("action_index", 0)),
        action=data.get("action", data.get("name", "")),
        input_candidate_ids=tuple(data.get("input_candidate_ids", data.get("inputs", ())) or ()),
        output_candidate_ids=tuple(data.get("output_candidate_ids", data.get("outputs", ())) or ()),
        selected_candidate_id=data.get("selected_candidate_id"),
        budget_cost=data.get("budget_cost", data.get("cost", 1)),
    )


def _coerce_trace(value: Any) -> Optional[SelectionTrace]:
    if value is None:
        return None
    if isinstance(value, SelectionTrace):
        return value
    data = dict(value)
    actions = tuple(_coerce_action(item) for item in data.get("actions", ()))
    return SelectionTrace(actions=actions, trace_digest=data.get("trace_digest", ""))


def _coerce_request(value: Any, kwargs: Mapping[str, Any]) -> ReplayRequest:
    if isinstance(value, ReplayRequest):
        return value
    if isinstance(value, RetrievalArchiveSnapshot):
        data = dict(kwargs)
        data["snapshot"] = value
    elif isinstance(value, Mapping):
        data = dict(value)
        data.update(kwargs)
    else:
        data = dict(kwargs)
        if value is not None:
            data.setdefault("snapshot", value)
    data["snapshot"] = _coerce_snapshot(data["snapshot"])
    if "authorization" not in data and "authorized_for_research" in data:
        data["authorization"] = data["authorized_for_research"]
    data["authorization"] = _coerce_authorization(data.get("authorization"))
    alias_fields = (
        "privacy_scope", "request_principal_digest", "access_policy_digest", "access_audit_digest",
        "retention_policy_digest", "deletion_tombstone_digest", "raw_asset_return_policy",
        "metadata_return_policy",
    )
    if any(data.get(name) is not None for name in alias_fields):
        auth = data["authorization"]
        if auth is None:
            auth = ResearchAuthorization("", "", "")
        auth_updates = {name: data[name] for name in alias_fields if data.get(name) is not None}
        data["authorization"] = replace(auth, **auth_updates)
    if "edit_evidence" in data or any(key in data for key in ("edit_mask_digest", "edit_type", "edit_steps", "steps")):
        data["edit_evidence"] = _coerce_edit(data.get("edit_evidence"), data)
        for key in ("edit_mask_digest", "mask_digest", "edit_type", "edit_steps", "steps"):
            data.pop(key, None)
    data["selection_trace"] = _coerce_trace(data.get("selection_trace"))
    data.pop("authorized_for_research", None)
    data.pop("schema", None)
    return ReplayRequest(**data)


def _tree_errors(entries: Sequence[ArchiveEntry]) -> Tuple[str, ...]:
    errors = []
    by_version: Dict[str, ArchiveEntry] = {}
    for row in entries:
        if row.version_id in by_version:
            errors.append(f"version_id_duplicate:{row.version_id}")
        by_version[row.version_id] = row
    roots: Dict[Tuple[str, str], int] = {}
    for row in entries:
        key = (row.asset_id, row.tree_id)
        if row.parent_version_id is None:
            roots[key] = roots.get(key, 0) + 1
            if row.depth != 0:
                errors.append(f"root_depth_mismatch:{row.version_id}")
        else:
            parent = by_version.get(row.parent_version_id)
            if parent is None:
                errors.append(f"parent_missing:{row.version_id}")
                continue
            if parent.asset_id != row.asset_id:
                errors.append(f"parent_cross_asset:{row.version_id}")
            if parent.tree_id != row.tree_id:
                errors.append(f"parent_cross_tree:{row.version_id}")
            if parent.branch_id != row.branch_id:
                errors.append(f"branch_mismatch:{row.version_id}")
            if row.depth != parent.depth + 1:
                errors.append(f"depth_mismatch:{row.version_id}")
    for key, count in sorted(roots.items()):
        if count != 1:
            errors.append(f"root_count:{key[0]}:{key[1]}:{count}")
    # DFS detects cycles even when every parent ID exists.
    state: Dict[str, int] = {}

    def visit(version_id: str) -> None:
        mark = state.get(version_id, 0)
        if mark == 1:
            errors.append(f"cycle:{version_id}")
            return
        if mark == 2:
            return
        state[version_id] = 1
        parent = by_version[version_id].parent_version_id
        if parent in by_version:
            visit(parent)  # type: ignore[arg-type]
        state[version_id] = 2

    for version_id in sorted(by_version):
        visit(version_id)
    return tuple(dict.fromkeys(errors))


def _make_trace(entries: Sequence[ArchiveEntry]) -> SelectionTrace:
    ordered = tuple(sorted(entries, key=lambda row: row.candidate_rank))
    all_ids = tuple(row.candidate_id for row in ordered)
    supported = tuple(
        row.candidate_id for row in ordered
        if row.membership_tier in {MEMBERSHIP_EXACT, MEMBERSHIP_MATCHED}
    )
    eligible = tuple(
        row for row in ordered
        if row.membership_tier in {MEMBERSHIP_EXACT, MEMBERSHIP_MATCHED}
        and row.quality_score >= 0.35 and row.source_match_score >= 0.60
    )
    max_delta = max((row.paired_delta_raw for row in eligible), default=None)
    selected = tuple(row.candidate_id for row in eligible if row.paired_delta_raw == max_delta) if max_delta is not None else ()
    actions = (
        SelectionAction(1, "replay_ranked_candidates", (), all_ids),
        SelectionAction(2, "replay_membership_filter", all_ids, supported),
        SelectionAction(3, "replay_max_delta_then_rank", supported, selected, selected[0] if len(selected) == 1 else None),
    )
    return SelectionTrace(actions=actions)


def _selection_key_digest(policy: str) -> str:
    return _digest({"schema": "retrieval-selection-policy-v1", "policy": policy})


def _split_digest(request: ReplayRequest) -> str:
    return request.calibration_split_digest if request.split == "calibration" else request.evaluation_split_digest


def _authorization_for_request(request: ReplayRequest) -> Optional[ResearchAuthorization]:
    auth = _coerce_authorization(request.authorization)
    alias_fields = (
        "privacy_scope", "request_principal_digest", "access_policy_digest", "access_audit_digest",
        "retention_policy_digest", "deletion_tombstone_digest", "raw_asset_return_policy",
        "metadata_return_policy",
    )
    if any(getattr(request, name) is not None for name in alias_fields):
        if auth is None:
            auth = ResearchAuthorization("", "", "")
        auth = replace(auth, **{name: getattr(request, name) for name in alias_fields if getattr(request, name) is not None})
    return auth


def _empty_result(
    request: Optional[ReplayRequest], *, route: str, reason: str,
    snapshot: Optional[RetrievalArchiveSnapshot] = None,
    trace: Optional[SelectionTrace] = None,
    event: Optional[RetrievalEvent] = None,
    selected: Sequence[str] = (),
    tree_errors: Sequence[str] = (), replay_errors: Sequence[str] = (),
    evaluated: bool = False,
) -> RetrievalReplayResult:
    rows = tuple(snapshot.entries) if snapshot is not None else ()
    counts = {tier: sum(row.membership_tier == tier for row in rows) for tier in MEMBERSHIP_TIERS}
    return RetrievalReplayResult(
        route=route,
        reason=reason,
        abstained=route != ROUTE_CANDIDATE,
        evaluated=evaluated,
        event_id=request.event_id if request is not None else "unknown",
        snapshot_digest=snapshot.snapshot_digest if snapshot is not None else None,
        index_digest=snapshot.index_digest if snapshot is not None else None,
        event_digest=event.digest if event is not None else None,
        binding_digest=None,
        selection_trace_digest=trace.trace_digest if trace is not None else None,
        selection_actions=tuple(action.to_dict() for action in trace.actions) if trace is not None else (),
        candidate_ids=tuple(row.candidate_id for row in rows),
        selected_candidate_ids=tuple(selected),
        exact_count=counts[MEMBERSHIP_EXACT],
        matched_count=counts[MEMBERSHIP_MATCHED],
        uncertain_count=counts[MEMBERSHIP_UNCERTAIN],
        outside_count=counts[MEMBERSHIP_OUTSIDE],
        tree_errors=tuple(tree_errors),
        replay_errors=tuple(replay_errors),
        operation_scope=request.operation_scope if request is not None else None,
        event=event,
        trace=trace,
    )


def _build_event(request: ReplayRequest, snapshot: RetrievalArchiveSnapshot, trace: SelectionTrace) -> RetrievalEvent:
    candidates = tuple(
        RetrievalCandidate(
            candidate_id=row.candidate_id,
            candidate_rank=row.candidate_rank,
            membership_tier=row.membership_tier,
            asset_id=row.asset_id,
            tree_id=row.tree_id,
            version_id=row.version_id,
            parent_version_id=row.parent_version_id,
            branch_id=row.branch_id,
            depth=row.depth,
            paired_delta_raw=row.paired_delta_raw,
            quality_score=row.quality_score,
            source_match_score=row.source_match_score,
            canonical_frame_digest=row.canonical_frame_digest,
            detector_version=row.detector_version,
            score_schema=row.score_schema,
            input_digest=row.input_digest,
            evidence_digest=row.evidence_digest,
            transform_family=row.transform_family,
            quality_bucket=row.quality_bucket,
            transport_bucket=row.transport_bucket,
            time_bucket=row.time_bucket,
            operation_scope=row.operation_scope,
            selection_group_id=row.selection_group_id,
            generator_family=row.generator_family,
        )
        for row in snapshot.entries
    )
    selection_key_digest = _selection_key_digest(request.selection_policy)
    authorization = _authorization_for_request(request)
    authorization_binding = authorization.to_dict() if authorization is not None else None
    edit_binding = request.edit_evidence.to_dict() if request.edit_evidence is not None else None
    input_digest = _digest({
        "schema": "retrieval-event-input-v1",
        "query_digest": request.query_digest,
        "snapshot_digest": snapshot.snapshot_digest,
        "index_digest": snapshot.index_digest,
        "retrieval_archive_digest": request.retrieval_archive_digest or snapshot.archive_index_digest,
        "manifest_digest": request.manifest_digest,
        "membership_policy_digest": snapshot.membership_policy_digest,
        "split": request.split,
        "split_digest": _split_digest(request),
        "operation_scope": request.operation_scope,
        "trace_digest": trace.trace_digest,
        "authorization_binding": authorization_binding,
        "edit_binding": edit_binding,
    })
    evidence_digest = _digest({
        "schema": "retrieval-event-evidence-v1",
        "input_digest": input_digest,
        "snapshot_digest": snapshot.snapshot_digest,
        "trace_digest": trace.trace_digest,
        "authorization_binding": authorization_binding,
        "edit_binding": edit_binding,
    })
    return RetrievalEvent(
        event_id=request.event_id,
        query_digest=request.query_digest,
        retrieval_policy_digest=snapshot.retrieval_policy_digest,
        candidates=candidates,
        manifest_digest=request.manifest_digest,
        split_digest=_split_digest(request),
        calibration_split_digest=request.calibration_split_digest,
        evaluation_split_digest=request.evaluation_split_digest,
        selection_policy_digest=request.selection_policy_digest or _selection_key_digest(request.selection_policy),
        selection_key_digest=selection_key_digest,
        canonical_frame_digest=snapshot.canonical_frame_digest,
        detector_version=snapshot.detector_version,
        score_schema=snapshot.score_schema,
        action_budget=request.action_budget,
        input_digest=input_digest,
        evidence_digest=evidence_digest,
        retrieval_archive_digest=request.retrieval_archive_digest or snapshot.archive_index_digest,
        membership_policy_digest=snapshot.membership_policy_digest,
        decoy_injection_digest=request.decoy_injection_digest,
        split=request.split,
        query_asset_id=request.query_asset_id,
        operation_scope=request.operation_scope,
        candidate_count=len(candidates),
        reference_route=request.reference_route,
        invariant_route=request.invariant_route,
        open_set=request.open_set,
        authorized_for_research=True,
        poisoning_stress_route=request.poisoning_stress_route,
        poisoning_route_flip=request.poisoning_route_flip,
        transform_family=candidates[0].transform_family if candidates else "unknown",
        quality_bucket=candidates[0].quality_bucket if candidates else "unknown",
        transport_bucket=candidates[0].transport_bucket if candidates else "unknown",
        time_bucket=candidates[0].time_bucket if candidates else "unknown",
        generator_family=request.generator_family,
    )


def _replay_impl(request: ReplayRequest) -> RetrievalReplayResult:
    snapshot = request.snapshot
    # External/next-window data is a declared holdout.  Keep it visible but do
    # not allow it to silently become an evaluated route.
    if request.external_split or request.split not in {"calibration", "evaluation"}:
        return _empty_result(request, route=ROUTE_NOT_EVALUATED, reason="external_split_not_evaluated", snapshot=snapshot)
    if not isinstance(request.event_id, str) or not request.event_id.strip():
        return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="event_id_missing", snapshot=snapshot)
    auth = _authorization_for_request(request)
    check_date = request.evaluation_time or request.as_of
    if auth is None or not auth.valid(as_of=check_date):
        return _empty_result(request, route=ROUTE_INSUFFICIENT, reason=auth.validation_reason(as_of=check_date) if auth is not None else "authorization_missing", snapshot=snapshot)
    if not request.query_digest or request.query_digest != snapshot.query_digest:
        return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="query_input_digest_missing_or_mismatch", snapshot=snapshot)
    if request.query_asset_id != snapshot.query_asset_id:
        return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="query_asset_mismatch", snapshot=snapshot)
    if request.manifest_digest != snapshot.manifest_digest:
        return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="manifest_digest_mismatch", snapshot=snapshot)
    if request.retrieval_archive_digest is not None and request.retrieval_archive_digest != snapshot.archive_index_digest:
        return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="archive_index_digest_mismatch", snapshot=snapshot)
    if request.calibration_split_digest == request.evaluation_split_digest:
        return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="split_digest_not_independent", snapshot=snapshot)
    if _split_digest(request) != (request.calibration_split_digest if request.split == "calibration" else request.evaluation_split_digest):
        return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="split_digest_mismatch", snapshot=snapshot)
    snapshot_errors = snapshot.validate()
    if snapshot_errors:
        return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="archive_snapshot_invalid", snapshot=snapshot, replay_errors=snapshot_errors)
    if not snapshot.entries:
        return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="retrieval_candidates_missing", snapshot=snapshot)
    archive_families = {row.generator_family for row in snapshot.entries}
    if archive_families != {request.generator_family}:
        # The request may not relabel an unknown/open-set archive row as a
        # known family.  Preserve the open-set route when either side declares
        # unknown; other disagreements are an insufficient binding.
        mismatch_route = (
            ROUTE_OPEN_SET_UNKNOWN
            if "unknown" in archive_families or "open_set" in archive_families
            or request.generator_family in {"unknown", "open_set"}
            else ROUTE_INSUFFICIENT
        )
        return _empty_result(request, route=mismatch_route, reason="generator_family_binding_mismatch", snapshot=snapshot)
    if request.action_budget < 3:
        return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="action_budget_insufficient_for_replay", snapshot=snapshot)
    if request.operation_scope not in {OPERATION_CONTENT_EDIT, OPERATION_ORDINARY_PROPAGATION}:
        return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="operation_scope_invalid", snapshot=snapshot)
    if any(row.operation_scope != request.operation_scope for row in snapshot.entries):
        return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="operation_scope_mismatch", snapshot=snapshot)
    edit = request.edit_evidence or EditEvidence()
    if request.operation_scope == OPERATION_CONTENT_EDIT:
        if not edit.edit_mask_digest or not edit.edit_type or not edit.steps:
            return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="edit_mask_type_or_steps_missing", snapshot=snapshot)
        if edit.edit_type == OPERATION_ORDINARY_PROPAGATION:
            return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="content_edit_label_invalid", snapshot=snapshot)
        for row in snapshot.entries:
            if not row.edit_mask_digest or not row.edit_type or not row.edit_steps:
                return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="candidate_edit_evidence_missing", snapshot=snapshot)
    else:
        if edit.edit_mask_digest or edit.edit_type or edit.steps:
            return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="ordinary_propagation_edit_label", snapshot=snapshot)
        if any(row.edit_mask_digest or row.edit_type or row.edit_steps for row in snapshot.entries):
            return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="ordinary_propagation_candidate_edit_label", snapshot=snapshot)
    tree_errors = _tree_errors(snapshot.entries)
    if tree_errors:
        return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="propagation_tree_invalid", snapshot=snapshot, tree_errors=tree_errors)
    trace = _make_trace(snapshot.entries)
    if request.selection_trace is not None:
        if not request.selection_trace.valid() or request.selection_trace.to_dict() != trace.to_dict():
            return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="selection_trace_tampered", snapshot=snapshot, trace=trace, replay_errors=("selection_trace_mismatch",))
    if request.selection_policy_digest is not None and request.selection_policy_digest != _selection_key_digest(request.selection_policy):
        return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="selection_policy_digest_mismatch", snapshot=snapshot, trace=trace)
    if request.operation_scope == OPERATION_CONTENT_EDIT:
        selected_rows = {
            row.candidate_id: row for row in snapshot.entries
            if row.candidate_id in set(trace.actions[-1].output_candidate_ids)
        }
        if any(
            row.edit_mask_digest != edit.edit_mask_digest
            or row.edit_type != edit.edit_type
            or tuple(row.edit_steps) != tuple(edit.steps)
            for row in selected_rows.values()
        ):
            return _empty_result(request, route=ROUTE_INSUFFICIENT, reason="edit_evidence_binding_mismatch", snapshot=snapshot, trace=trace)
    selected = trace.actions[-1].output_candidate_ids
    event = _build_event(request, snapshot, trace)
    binding = _digest({
        "schema": VERSION,
        "event_digest": event.digest,
        "snapshot_digest": snapshot.snapshot_digest,
        "index_digest": snapshot.index_digest,
        "selection_trace_digest": trace.trace_digest,
        "selection_policy_digest": event.selection_policy_digest,
        "membership_policy_digest": snapshot.membership_policy_digest,
        "operation_scope": request.operation_scope,
        "authorization_binding": auth.to_dict() if auth is not None else None,
        "evaluation_time": check_date,
    })
    if request.null_profile is None:
        result = _empty_result(request, route=ROUTE_NOT_EVALUATED, reason="independent_null_profile_missing", snapshot=snapshot, trace=trace, event=event, selected=selected)
        return replace(result, binding_digest=binding, evaluated=False)
    if request.split != "evaluation":
        result = _empty_result(request, route=ROUTE_NOT_EVALUATED, reason="calibration_event_not_evaluated", snapshot=snapshot, trace=trace, event=event, selected=selected)
        return replace(result, binding_digest=binding, evaluated=False)
    # These are replay-level safety routes.  They must not depend on a known
    # family's null profile: an open-set query or an injected archive is never
    # promoted merely because a profile binding happened to match.
    if request.open_set or request.generator_family in {"unknown", "open_set"}:
        result = _empty_result(request, route=ROUTE_OPEN_SET_UNKNOWN, reason="open_set_or_unknown_generator", snapshot=snapshot, trace=trace, event=event, selected=selected, evaluated=True)
        return replace(result, binding_digest=binding, evaluated=True)
    if request.poisoning_route_flip or request.poisoning_stress_route in {"poisoning", "route_flip"}:
        result = _empty_result(request, route=ROUTE_REVIEW, reason="poisoning_or_route_flip", snapshot=snapshot, trace=trace, event=event, selected=selected, evaluated=True)
        return replace(result, binding_digest=binding, evaluated=True)
    if request.reference_route != "reference_specific_candidate" or request.invariant_route != "invariant_candidate":
        result = _empty_result(request, route=ROUTE_REVIEW, reason="reference_or_invariant_instability", snapshot=snapshot, trace=trace, event=event, selected=selected, evaluated=True)
        return replace(result, binding_digest=binding, evaluated=True)
    try:
        raw = evaluate_retrieval_aware_tree_null(event, request.null_profile, request.rscptn_config or RSCPTNConfig())
    except (TypeError, ValueError) as exc:
        result = _empty_result(request, route=ROUTE_INSUFFICIENT, reason=f"rscptn_contract_failed:{exc}", snapshot=snapshot, trace=trace, event=event, selected=selected)
        return replace(result, binding_digest=binding, evaluated=False)
    route_map = {
        "retrieval_tree_candidate": ROUTE_CANDIDATE,
        "retrieval_tree_null_consistent": ROUTE_NULL_CONSISTENT,
        "retrieval_contaminated_review": ROUTE_REVIEW,
        "open_set_unknown": ROUTE_OPEN_SET_UNKNOWN,
        "insufficient": ROUTE_INSUFFICIENT,
    }
    result = _empty_result(request, route=route_map.get(raw.route, ROUTE_INSUFFICIENT), reason=raw.reason, snapshot=snapshot, trace=trace, event=event, selected=selected, evaluated=True)
    return replace(result, binding_digest=binding, evaluated=True)


def replay_retrieval_event(request: Any = None, **kwargs: Any) -> RetrievalReplayResult:
    """Replay one archive event and return a route-only result.

    ``request`` may be a :class:`ReplayRequest`, a frozen snapshot (with the
    remaining fields in ``kwargs``), or a mapping.  Mapping support keeps JSON
    research manifests easy to replay without introducing a second schema.
    """

    try:
        return _replay_impl(_coerce_request(request, kwargs))
    except (TypeError, ValueError, KeyError) as exc:
        # A malformed request must still produce a serializable fail-closed
        # result rather than an accidental success or a partially trusted route.
        snapshot = None
        if isinstance(request, RetrievalArchiveSnapshot):
            snapshot = request
        elif isinstance(request, Mapping) and "snapshot" in request:
            try:
                snapshot = _coerce_snapshot(request["snapshot"])
            except Exception:
                snapshot = None
        return _empty_result(None, route=ROUTE_INSUFFICIENT, reason=f"request_contract_failed:{exc}", snapshot=snapshot)


replay_retrieval = replay_retrieval_event
replay_retrieval_event_from_snapshot = replay_retrieval_event
build_retrieval_event = replay_retrieval_event


def canonical_snapshot_digest(snapshot: Union[RetrievalArchiveSnapshot, Mapping[str, Any]]) -> str:
    return _coerce_snapshot(snapshot).computed_digest


def canonical_archive_digest(snapshot: Union[RetrievalArchiveSnapshot, Mapping[str, Any]]) -> str:
    return canonical_snapshot_digest(snapshot)


def selection_trace_digest(trace: Union[SelectionTrace, Mapping[str, Any]]) -> str:
    return _coerce_trace(trace).computed_digest  # type: ignore[union-attr]


__all__ = [
    "VERSION", "SCHEMA", "RETRIEVAL_EVENT_REPLAY_VERSION", "RETRIEVAL_EVENT_REPLAY_SCHEMA",
    "ARCHIVE_SCHEMA", "SELECTION_SCHEMA",
    "ROUTE_CANDIDATE", "ROUTE_NULL_CONSISTENT", "ROUTE_REVIEW", "ROUTE_OPEN_SET_UNKNOWN",
    "ROUTE_INSUFFICIENT", "ROUTE_NOT_EVALUATED", "ROUTE_RETRIEVAL_TREE_CANDIDATE",
    "ROUTE_RETRIEVAL_TREE_NULL", "ROUTE_RETRIEVAL_CONTAMINATED",
    "ArchiveEntry", "RetrievalArchiveEntry", "RetrievalCandidateRecord",
    "RetrievalArchiveSnapshot", "RetrievalIndexSnapshot", "FrozenRetrievalArchive",
    "ResearchAuthorization", "AuthorizationEvidence", "EditEvidence", "EditLineageEvidence",
    "SelectionAction", "SelectionTrace", "SelectionReplayTrace", "ReplayRequest",
    "RetrievalReplayResult", "ReplayResult", "canonical_snapshot_digest", "canonical_archive_digest",
    "selection_trace_digest", "replay_retrieval_event", "replay_retrieval",
    "replay_retrieval_event_from_snapshot", "build_retrieval_event",
]
