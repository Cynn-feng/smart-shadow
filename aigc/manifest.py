"""Checks for leakage-resistant AIGC evaluation manifests."""

from __future__ import annotations

from collections import defaultdict
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, List, Mapping, Sequence


REQUIRED_FIELDS = (
    "sample_id",
    "group_id",
    "split",
    "origin",
    "generator_family",
    "license",
)
ALLOWED_SPLITS = {"train", "validation", "test", "external"}

REAL_MANIFEST_VERSION = "real_pc_scft_manifest_v1"
REAL_REQUIRED_FIELDS = (
    "sample_id",
    "asset_id",
    "role",
    "pair_id",
    "transform_family",
    "split",
    "sample_path",
    "sha256",
    "authorization_id",
    "authorization_scope",
    "authorization_expiry",
    "authorized_for_research",
    "origin",
    "generator_family",
    "parent_sample_id",
    "postprocess_chain",
    "resolution",
)
REAL_ROLES = {"reference", "observed", "counterfactual"}


def _real_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_real_manifest_digest(records: Sequence[Mapping[str, Any]]) -> str:
    """Return a stable digest for the full private real-image manifest."""

    if isinstance(records, (str, bytes)):
        records = [records]  # type: ignore[assignment]
    else:
        try:
            records = list(records)
        except TypeError:
            records = [records]  # type: ignore[assignment]
    canonical = []
    for record in records:
        if isinstance(record, Mapping):
            canonical.append(dict(record))
        else:
            canonical.append({"invalid_record": repr(record)})
    canonical.sort(key=lambda item: str(item.get("sample_id", "")))
    return _real_digest({"version": REAL_MANIFEST_VERSION, "records": canonical})


def _parse_expiry(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _scope_present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return bool(value) and all(isinstance(item, str) and item.strip() for item in value)
    if isinstance(value, Mapping):
        return bool(value)
    return False


def _safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    path = Path(value)
    if path.is_absolute() or value.startswith(("~", "file://", "private://")):
        return False
    return ".." not in path.parts


def validate_real_manifest(
    records: Sequence[Mapping[str, Any]],
    *,
    root: str | Path | None = None,
    now: datetime | None = None,
) -> List[str]:
    """Validate the fail-closed ``real_pc_scft_manifest_v1`` contract.

    The function only checks structure, authorization metadata and pair
    identity.  It does not trust ``license`` as authorization and does not
    infer a label from ``origin``.  File bytes are checked separately by
    :func:`verify_real_manifest_files`.
    """

    errors: List[str] = []
    if isinstance(records, (str, bytes)):
        return ["manifest:not_a_sequence"]
    try:
        records = list(records)
    except TypeError:
        return ["manifest:not_a_sequence"]
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    seen_ids: set[Any] = set()
    groups: dict[tuple[str, str], dict[str, Mapping[str, Any]]] = defaultdict(dict)
    asset_splits: dict[str, set[str]] = defaultdict(set)
    root_path = Path(root).resolve() if root is not None else None
    for index, record in enumerate(records):
        prefix = f"record[{index}]"
        if not isinstance(record, Mapping):
            errors.append(f"{prefix}:not_object")
            continue
        for field in REAL_REQUIRED_FIELDS:
            # The reference has no parent sample by definition; keep the
            # field present in the frozen schema while allowing JSON null for
            # that one role.
            if field == "parent_sample_id" and record.get("role") == "reference" and field in record:
                continue
            if field not in record or record[field] in (None, ""):
                errors.append(f"{prefix}:missing:{field}")
        sample_id = record.get("sample_id")
        try:
            sample_key = sample_id if hash(sample_id) is not None else repr(sample_id)
        except TypeError:
            sample_key = repr(sample_id)
        if sample_key in seen_ids:
            errors.append(f"{prefix}:duplicate:sample_id:{sample_id}")
        seen_ids.add(sample_key)
        role = record.get("role")
        if not isinstance(role, str) or role not in REAL_ROLES:
            errors.append(f"{prefix}:invalid:role:{role}")
        split = record.get("split")
        if not isinstance(split, str) or split not in ALLOWED_SPLITS:
            errors.append(f"{prefix}:invalid:split:{split}")
        asset_id = record.get("asset_id")
        if asset_id and split in ALLOWED_SPLITS:
            asset_splits[str(asset_id)].add(str(split))
        pair_id = record.get("pair_id")
        if asset_id and pair_id and role in REAL_ROLES:
            key = (str(asset_id), str(pair_id))
            if role in groups[key]:
                errors.append(f"{prefix}:duplicate:pair_role:{asset_id}:{pair_id}:{role}")
            groups[key][role] = record
        authorized = record.get("authorized_for_research")
        if authorized is not True:
            errors.append(f"{prefix}:unauthorized_input")
        if not _scope_present(record.get("authorization_scope")):
            errors.append(f"{prefix}:unauthorized_input:scope")
        if not isinstance(record.get("authorization_id"), str) or not record.get("authorization_id", "").strip():
            errors.append(f"{prefix}:unauthorized_input:authorization_id")
        expiry = _parse_expiry(record.get("authorization_expiry"))
        if expiry is None:
            errors.append(f"{prefix}:invalid:authorization_expiry")
        elif expiry <= current:
            errors.append(f"{prefix}:unauthorized_input:expired")
        sample_path = record.get("sample_path")
        if not _safe_relative_path(sample_path):
            errors.append(f"{prefix}:invalid:sample_path")
        elif root_path is not None:
            resolved = (root_path / str(sample_path)).resolve()
            try:
                resolved.relative_to(root_path)
            except ValueError:
                errors.append(f"{prefix}:invalid:sample_path_escape")
        sha = record.get("sha256")
        if not isinstance(sha, str) or len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha.lower()):
            errors.append(f"{prefix}:invalid:sha256")
        for optional_digest in ("parent_sha256", "transform_spec_digest"):
            value = record.get(optional_digest)
            if value not in (None, "") and (
                not isinstance(value, str)
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value.lower())
            ):
                errors.append(f"{prefix}:invalid:{optional_digest}")
        resolution = record.get("resolution")
        if not (
            isinstance(resolution, (list, tuple))
            and len(resolution) == 2
            and all(isinstance(item, int) and not isinstance(item, bool) and item > 0 for item in resolution)
        ):
            errors.append(f"{prefix}:invalid:resolution")
        if not isinstance(record.get("postprocess_chain"), list) or any(
            not isinstance(item, str) or not item.strip() for item in record.get("postprocess_chain", [])
        ):
            errors.append(f"{prefix}:invalid:postprocess_chain")
    for asset_id, splits in sorted(asset_splits.items()):
        if len(splits) > 1:
            errors.append(f"asset_leakage:{asset_id}:{','.join(sorted(splits))}")
    for (asset_id, pair_id), role_map in sorted(groups.items()):
        missing = sorted(REAL_ROLES - set(role_map))
        if missing:
            errors.append(f"pair_missing_role:{asset_id}:{pair_id}:{','.join(missing)}")
            continue
        records_for_pair = list(role_map.values())
        expected = records_for_pair[0]
        for record in records_for_pair[1:]:
            for field in ("asset_id", "pair_id", "transform_family", "split"):
                if record.get(field) != expected.get(field):
                    errors.append(f"pair_identity_mismatch:{asset_id}:{pair_id}:{field}")
        reference = role_map["reference"]
        for role in ("observed", "counterfactual"):
            parent = role_map[role].get("parent_sample_id")
            if parent not in (None, "", reference.get("sample_id")):
                errors.append(f"pair_parent_mismatch:{asset_id}:{pair_id}:{role}")
            parent_sha = role_map[role].get("parent_sha256")
            if parent_sha not in (None, "") and parent_sha != reference.get("sha256"):
                errors.append(f"pair_parent_hash_mismatch:{asset_id}:{pair_id}:{role}")
        transform_digests = {
            str(record.get("transform_spec_digest"))
            for record in records_for_pair
            if record.get("transform_spec_digest") not in (None, "")
        }
        if len(transform_digests) > 1:
            errors.append(f"pair_transform_spec_mismatch:{asset_id}:{pair_id}")
    return sorted(set(errors))


def verify_real_manifest_files(
    records: Sequence[Mapping[str, Any]],
    root: str | Path,
) -> List[str]:
    """Verify bytes and declared geometry for an already structurally valid manifest."""

    errors: List[str] = []
    try:
        records = list(records)
    except TypeError:
        return ["manifest:not_a_sequence"]
    root_path = Path(root).resolve()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            errors.append(f"record[{index}]:not_object")
            continue
        path_value = record.get("sample_path")
        if not _safe_relative_path(path_value):
            errors.append(f"record[{index}]:invalid:sample_path")
            continue
        path = (root_path / str(path_value)).resolve()
        try:
            path.relative_to(root_path)
        except ValueError:
            errors.append(f"record[{index}]:invalid:sample_path_escape")
            continue
        if not path.is_file():
            errors.append(f"record[{index}]:missing:file")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != str(record.get("sha256", "")).lower():
            errors.append(f"record[{index}]:hash_mismatch")
    return sorted(set(errors))


def validate_manifest(records: Sequence[Mapping[str, Any]]) -> List[str]:
    """Return deterministic errors; an empty list means structural validity."""

    errors: List[str] = []
    seen_ids = set()
    groups = defaultdict(set)
    for index, record in enumerate(records):
        prefix = f"record[{index}]"
        for field in REQUIRED_FIELDS:
            if field not in record or record[field] in (None, ""):
                errors.append(f"{prefix}:missing:{field}")
        sample_id = record.get("sample_id")
        if sample_id in seen_ids:
            errors.append(f"{prefix}:duplicate:sample_id:{sample_id}")
        seen_ids.add(sample_id)
        split = record.get("split")
        if split not in ALLOWED_SPLITS:
            errors.append(f"{prefix}:invalid:split:{split}")
        group_id = record.get("group_id")
        if group_id and split in ALLOWED_SPLITS:
            groups[group_id].add(split)

    for group_id, splits in sorted(groups.items(), key=lambda item: str(item[0])):
        if len(splits) > 1:
            errors.append(f"group_leakage:{group_id}:{','.join(sorted(splits))}")
    return errors


def load_jsonl(path: str) -> List[Mapping[str, Any]]:
    records = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"line {line_number}: record must be an object")
            records.append(record)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Smart Shadow AIGC JSONL manifest")
    parser.add_argument("manifest", help="path to JSONL manifest")
    args = parser.parse_args()
    errors = validate_manifest(load_jsonl(args.manifest))
    if errors:
        print("\n".join(errors))
        return 1
    print("manifest: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
