"""Conservative provenance observations for image files.

This module does not claim to validate C2PA cryptography.  A caller must pass
the result of a trusted verifier as ``verification_status='valid'`` before a
manifest can become a valid provenance observation.  Ordinary image metadata
is intentionally reported as weak evidence because it can be removed or
forged.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .schema import Evidence


VALID_C2PA_STATUSES = {"missing", "unverified", "valid", "invalid"}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ProvenanceReport:
    content_sha256: str
    c2pa_status: str = "missing"
    manifest_digest: Optional[str] = None
    ai_disclosure: Optional[bool] = None
    ai_edit: Optional[bool] = None
    provider: Optional[str] = None
    user_declared_ai: Optional[bool] = None
    evidence: Tuple[Evidence, ...] = ()
    errors: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.c2pa_status not in VALID_C2PA_STATUSES:
            raise ValueError(f"unsupported c2pa_status: {self.c2pa_status}")
        if len(self.content_sha256) != 64:
            raise ValueError("content_sha256 must be a SHA-256 hex digest")
        try:
            int(self.content_sha256, 16)
        except ValueError as exc:
            raise ValueError("content_sha256 must be a SHA-256 hex digest") from exc

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content_sha256": self.content_sha256,
            "c2pa_status": self.c2pa_status,
            "manifest_digest": self.manifest_digest,
            "ai_disclosure": self.ai_disclosure,
            "ai_edit": self.ai_edit,
            "provider": self.provider,
            "user_declared_ai": self.user_declared_ai,
            "evidence": [item.to_dict() for item in self.evidence],
            "errors": list(self.errors),
        }


def _manifest_observation(
    manifest: Mapping[str, Any], verification_status: str
) -> Tuple[str, Optional[bool], Optional[bool], Optional[str], Evidence]:
    if verification_status not in VALID_C2PA_STATUSES - {"missing"}:
        raise ValueError(
            "verification_status must be valid, invalid, or unverified when a manifest is supplied"
        )

    declared = manifest.get("ai_disclosure")
    ai_disclosure = declared if isinstance(declared, bool) else None
    action = str(manifest.get("action", "")).lower()
    ai_edit = manifest.get("ai_edit")
    if not isinstance(ai_edit, bool):
        ai_edit = any(token in action for token in ("inpaint", "outpaint", "ai_edit"))
    provider = manifest.get("provider") or manifest.get("issuer")
    provider = str(provider) if provider else None
    digest = _manifest_digest(manifest)
    evidence_type = {
        "valid": "c2pa_valid",
        "invalid": "c2pa_invalid",
        "unverified": "c2pa_unverified",
    }[verification_status]
    evidence = Evidence(
        type=evidence_type,
        status=verification_status,
        provider=provider,
        details={"manifest_digest": digest},
    )
    return verification_status, ai_disclosure, ai_edit, provider, evidence


def inspect_manifest(
    manifest: Mapping[str, Any],
    verification_status: str = "unverified",
    *,
    content_sha256: Optional[str] = None,
    verifier_id: Optional[str] = None,
    binding_ok: Optional[bool] = None,
) -> ProvenanceReport:
    """Convert a manifest and an external verification result into evidence.

    ``verification_status='unverified'`` is the safe default.  A JSON object
    that merely says it is valid is not treated as cryptographic proof.  A
    content hash is required so a manifest observation cannot be detached from
    the file it is meant to describe.
    """

    if content_sha256 is None:
        raise ValueError("content_sha256 is required to bind a manifest")
    status, ai_disclosure, ai_edit, provider, evidence = _manifest_observation(
        manifest, verification_status
    )
    errors = []
    if verifier_id:
        evidence = Evidence(
            type=evidence.type,
            status=evidence.status,
            provider=evidence.provider,
            details={
                **dict(evidence.details),
                "verifier_id": verifier_id,
                "binding_ok": binding_ok,
            },
        )
    if status == "valid" and (not verifier_id or binding_ok is not True):
        # A caller-provided string is not a cryptographic verification.  The
        # trusted adapter must identify itself and confirm manifest/content
        # binding before this package records c2pa_valid.
        status = "unverified"
        evidence = Evidence(
            type="c2pa_unverified",
            status="unverified",
            provider=provider,
            details={
                "manifest_digest": evidence.details["manifest_digest"],
                "reason": "missing_verifier_or_binding",
            },
        )
        errors.append("missing_verifier_or_binding")
    return ProvenanceReport(
        content_sha256=content_sha256,
        c2pa_status=status,
        manifest_digest=evidence.details["manifest_digest"],
        ai_disclosure=ai_disclosure,
        ai_edit=ai_edit,
        provider=provider,
        evidence=(evidence,),
        errors=tuple(errors),
    )


def _weak_metadata_evidence(raw: bytes) -> Tuple[Evidence, ...]:
    text = raw.decode("latin1", errors="ignore").lower()
    observations = []
    if "parameters" in text and ("steps:" in text or "sampler:" in text):
        observations.append(
            Evidence(
                type="metadata_weak",
                status="observed",
                provider="stable-diffusion-like",
                details={"marker": "parameters/steps-or-sampler"},
            )
        )
    if "midjourney" in text or "niji" in text:
        observations.append(
            Evidence(
                type="metadata_weak",
                status="observed",
                provider="midjourney-like",
                details={"marker": "software-name"},
            )
        )
    return tuple(observations)


def inspect_file(
    path: str,
    *,
    user_declared_ai: Optional[bool] = None,
    manifest: Optional[Mapping[str, Any]] = None,
    manifest_verification: str = "missing",
    manifest_verifier_id: Optional[str] = None,
    manifest_binding_ok: Optional[bool] = None,
) -> ProvenanceReport:
    """Hash a file and collect weak metadata plus caller-supplied provenance.

    The function is dependency-free and therefore safe to use before the
    optional Pillow/C2PA adapters are installed.
    """

    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(str(file_path))
    content_sha256 = _sha256_file(file_path)
    with file_path.open("rb") as handle:
        # Metadata markers are normally near the beginning.  Avoid loading a
        # multi-gigabyte upload into memory just to collect weak evidence.
        raw = handle.read(8 * 1024 * 1024)
    evidence = list(_weak_metadata_evidence(raw))
    c2pa_status = "missing"
    manifest_digest = None
    ai_disclosure = None
    ai_edit = None
    provider = None
    errors = []

    if manifest is not None:
        # A manifest without an explicit verifier result is still an
        # observation, but it must not fail the request or become proof. The
        # safe default is an unverified manifest that the fusion layer can
        # carry into an ``unknown`` result.
        verification_status = manifest_verification
        if verification_status == "missing":
            verification_status = "unverified"
            errors.append("manifest_verification_missing")
        observed = inspect_manifest(
            manifest,
            verification_status,
            content_sha256=content_sha256,
            verifier_id=manifest_verifier_id,
            binding_ok=manifest_binding_ok,
        )
        c2pa_status = observed.c2pa_status
        manifest_digest = observed.manifest_digest
        ai_disclosure = observed.ai_disclosure
        ai_edit = observed.ai_edit
        provider = observed.provider
        evidence.extend(observed.evidence)
        errors.extend(observed.errors)
    elif manifest_verification != "missing":
        errors.append("manifest_verification_without_manifest")

    if user_declared_ai is not None:
        evidence.append(
            Evidence(
                type="user_declared_ai" if user_declared_ai else "user_declared_human",
                status="declared",
            )
        )

    return ProvenanceReport(
        content_sha256=content_sha256,
        c2pa_status=c2pa_status,
        manifest_digest=manifest_digest,
        ai_disclosure=ai_disclosure,
        ai_edit=ai_edit,
        provider=provider,
        user_declared_ai=user_declared_ai,
        evidence=tuple(evidence),
        errors=tuple(errors),
    )
