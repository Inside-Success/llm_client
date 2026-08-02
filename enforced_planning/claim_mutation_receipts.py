"""Durable, typed evidence for sanctioned claim-registry mutations."""

from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
import yaml  # type: ignore[import-untyped]


DEFAULT_EVENTS_PATH = Path.home() / ".claude" / "coordination" / "claim-mutation-events-v1.jsonl"
DEFAULT_COMPLETED_CLAIM_ARCHIVE_PATH = (
    Path.home() / ".claude" / "coordination" / "completed-claim-archive-v1.jsonl"
)
MutationOperation = Literal[
    "create",
    "session_upsert",
    "heartbeat",
    "release",
    "prune",
    "session_end",
    "closeout",
]
MutationResult = Literal["applied_projection_current", "applied_projection_stale", "not_applied"]
CompletedClaimSourceKind = Literal["live_prune", "legacy_reconciliation"]
CompletedClaimStatus = Literal["complete", "completed"]
CompletedClaimPruneBindingKind = Literal["live_prune_transaction", "legacy_prune_event"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompletedClaimPruneBindingV1(_StrictModel):
    """Bind one archived completed claim to its sanctioned prune provenance."""

    kind: CompletedClaimPruneBindingKind
    transaction_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    mutation_event_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _require_exact_binding_identity(self) -> "CompletedClaimPruneBindingV1":
        """Each binding kind owns exactly one provenance identifier."""

        if self.kind == "live_prune_transaction":
            if self.transaction_id is None or self.mutation_event_id is not None:
                raise ValueError(
                    "live_prune_transaction requires transaction_id and forbids mutation_event_id"
                )
            return self
        if self.mutation_event_id is None or self.transaction_id is not None:
            raise ValueError(
                "legacy_prune_event requires mutation_event_id and forbids transaction_id"
            )
        return self


def _decode_source_yaml_bytes(encoded: str) -> bytes:
    """Decode a strict base64 source payload."""

    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("source_yaml_bytes is not valid canonical base64") from exc


def _completed_claim_identity(
    source_bytes: bytes,
) -> tuple[str, str, str, str | None, CompletedClaimStatus]:
    """Parse the exact identity needed by the completed-claim archive."""

    try:
        decoded = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("completed claim source is not valid UTF-8") from exc
    try:
        payload = yaml.safe_load(decoded)
    except yaml.YAMLError as exc:
        raise ValueError(f"completed claim source is malformed YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("completed claim source must decode to a YAML mapping")

    agent = payload.get("agent")
    scope = payload.get("scope")
    session_id = payload.get("session_id")
    status_value = payload.get("status")
    project_value = payload.get("project")
    projects_value = payload.get("projects")

    if not isinstance(agent, str) or not agent.strip():
        raise ValueError("completed claim source requires a non-empty agent")
    if not isinstance(scope, str) or not scope.strip():
        raise ValueError("completed claim source requires a non-empty scope")
    if session_id is not None and (
        not isinstance(session_id, str) or not session_id.strip()
    ):
        raise ValueError("completed claim source session_id must be null or non-empty")
    if isinstance(project_value, str) and project_value.strip():
        project = project_value.strip()
    elif (
        isinstance(projects_value, list)
        and projects_value
        and isinstance(projects_value[0], str)
        and projects_value[0].strip()
    ):
        project = projects_value[0].strip()
    else:
        raise ValueError("completed claim source requires project or non-empty projects")
    if not isinstance(status_value, str):
        raise ValueError("completed claim source requires an explicit completed status")
    normalized_status = status_value.strip().lower()
    if normalized_status not in {"complete", "completed"}:
        raise ValueError(
            f"completed claim source has non-completed status {status_value!r}"
        )
    status: CompletedClaimStatus = (
        "complete" if normalized_status == "complete" else "completed"
    )
    return (
        agent.strip(),
        project,
        scope.strip(),
        session_id.strip() if isinstance(session_id, str) else None,
        status,
    )


class CompletedClaimArchiveReceiptV1(_StrictModel):
    """One exact-byte, intrinsically validated completed-claim archive record."""

    schema_version: Literal["1.0"] = "1.0"
    archive_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_kind: CompletedClaimSourceKind
    source_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_yaml_bytes: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    project: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    session_id: str | None
    status: CompletedClaimStatus
    prune_binding: CompletedClaimPruneBindingV1
    archived_at: datetime
    writer_source_path: str = Field(min_length=1)
    writer_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    writer_repo_root: str = Field(min_length=1)
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_exact_source_and_receipt(self) -> "CompletedClaimArchiveReceiptV1":
        """Reject any drift in source bytes, identity, binding, or receipt digest."""

        source_bytes = _decode_source_yaml_bytes(self.source_yaml_bytes)
        actual_source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        if actual_source_sha256 != self.source_sha256:
            raise ValueError(
                "completed claim source SHA-256 does not match source_yaml_bytes"
            )
        agent, project, scope, session_id, status = _completed_claim_identity(
            source_bytes
        )
        expected_identity = (agent, project, scope, session_id, status)
        observed_identity = (
            self.agent,
            self.project,
            self.scope,
            self.session_id,
            self.status,
        )
        if observed_identity != expected_identity:
            raise ValueError(
                "completed claim parsed identity does not match archive receipt fields"
            )
        expected_archive_id = completed_claim_archive_id(
            source_path=self.source_path,
            source_sha256=self.source_sha256,
        )
        if self.archive_id != expected_archive_id:
            raise ValueError("completed claim archive_id does not match source identity")
        expected_binding_kind = (
            "live_prune_transaction"
            if self.source_kind == "live_prune"
            else "legacy_prune_event"
        )
        if self.prune_binding.kind != expected_binding_kind:
            raise ValueError(
                "completed claim source_kind does not match prune_binding kind"
            )
        if self.archived_at.tzinfo is None:
            raise ValueError("completed claim archived_at must be timezone-aware")
        expected_receipt_sha256 = completed_claim_archive_receipt_sha256(self)
        if self.receipt_sha256 != expected_receipt_sha256:
            raise ValueError("completed claim receipt_sha256 does not match canonical content")
        return self


class ClaimMutationReceiptV1(_StrictModel):
    """One terminal audit record for one sanctioned claim mutation."""

    schema_version: Literal["1.0"] = "1.0"
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    operation: MutationOperation
    result: MutationResult
    writer_source_path: str
    writer_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    writer_repo_root: str
    process_id: int = Field(ge=1)
    session_id: str | None
    target_project: str | None
    target_scope: str | None
    target_claim_path: str | None
    registry_digest_before: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    registry_digest_after: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    projection_digest_after: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    projection_current_after: bool | None
    archive_transaction_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    error_code: str | None = None

    @model_validator(mode="after")
    def _require_outcome_details_when_applied(self) -> "ClaimMutationReceiptV1":
        """Applied mutations must retain the complete authority outcome."""

        if self.archive_transaction_id is not None and (
            self.operation != "prune" or self.result == "not_applied"
        ):
            raise ValueError(
                "archive_transaction_id is valid only for an applied prune mutation"
            )
        if self.result == "not_applied":
            return self
        missing = [
            field
            for field, value in (
                ("registry_digest_before", self.registry_digest_before),
                ("registry_digest_after", self.registry_digest_after),
                ("projection_digest_after", self.projection_digest_after),
                ("projection_current_after", self.projection_current_after),
            )
            if value is None
        ]
        if missing:
            raise ValueError(
                "Applied mutation receipts require non-null authority outcome fields: "
                + ", ".join(missing)
            )
        return self


class MutationAuditError(ValueError):
    """A mutation completed, but its durable provenance receipt could not persist."""

    error_code = "mutation_applied_audit_failed"

    def __init__(
        self,
        *,
        operation: MutationOperation,
        target_project: str | None,
        target_scope: str | None,
        registry_digest_after: str | None,
        projection_digest_after: str | None,
        projection_current_after: bool | None,
        cause: OSError,
    ) -> None:
        self.operation = operation
        self.target_project = target_project
        self.target_scope = target_scope
        self.registry_digest_after = registry_digest_after
        self.projection_digest_after = projection_digest_after
        self.projection_current_after = projection_current_after
        self.cause = cause
        super().__init__(
            f"{self.error_code}: operation={operation} target="
            f"{target_project or '<unknown>'}:{target_scope or '<unknown>'} "
            f"registry_digest_after={registry_digest_after or '<none>'} "
            f"projection_digest_after={projection_digest_after or '<none>'} "
            f"projection_current_after={projection_current_after!r}; cause={cause}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "error_code": self.error_code,
            "mutation_applied": True,
            "operation": self.operation,
            "target_project": self.target_project,
            "target_scope": self.target_scope,
            "registry_digest_after": self.registry_digest_after,
            "projection_digest_after": self.projection_digest_after,
            "projection_current_after": self.projection_current_after,
            "cause": str(self.cause),
        }


class CompletedClaimArchiveError(ValueError):
    """Archive validation or persistence failed before claim-registry mutation."""

    def __init__(
        self,
        *,
        error_code: str,
        source_path: str | None,
        cause: Exception,
    ) -> None:
        self.error_code = error_code
        self.source_path = source_path
        self.cause = cause
        super().__init__(
            f"{error_code}: source_path={source_path or '<unknown>'}; cause={cause}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "error_code": self.error_code,
            "mutation_applied": False,
            "source_path": self.source_path,
            "cause": str(self.cause),
        }


def writer_identity(source_path: Path) -> tuple[str, str, str]:
    """Return the loaded runtime source identity without relying on cwd or repo names."""

    resolved = source_path.resolve()
    source_bytes = resolved.read_bytes()
    return (
        str(resolved),
        hashlib.sha256(source_bytes).hexdigest(),
        str(resolved.parents[1]),
    )


def completed_claim_archive_id(*, source_path: str, source_sha256: str) -> str:
    """Return the deterministic identity for one exact claim source artifact."""

    payload = (
        "completed-claim-archive-v1\0"
        + source_path
        + "\0"
        + source_sha256
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def completed_claim_archive_transaction_id(archive_id: str) -> str:
    """Return the deterministic live-prune transaction for one archive identity."""

    return hashlib.sha256(
        ("completed-claim-prune-v1\0" + archive_id).encode("utf-8")
    ).hexdigest()


def _canonical_json_value(value: Any) -> Any:
    """Normalize Pydantic and datetime values for a stable canonical digest."""

    if isinstance(value, BaseModel):
        return _canonical_json_value(value.model_dump(mode="python"))
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("canonical receipt datetime must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical_json_value(item) for item in value]
    return value


def completed_claim_archive_receipt_sha256(
    receipt: CompletedClaimArchiveReceiptV1 | dict[str, Any],
) -> str:
    """Hash canonical receipt content while excluding its self-digest field."""

    if isinstance(receipt, CompletedClaimArchiveReceiptV1):
        payload = receipt.model_dump(mode="python")
    else:
        payload = dict(receipt)
    payload.pop("receipt_sha256", None)
    archived_at = payload.get("archived_at")
    if isinstance(archived_at, str):
        try:
            payload["archived_at"] = datetime.fromisoformat(
                archived_at.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError("completed claim archived_at is invalid") from exc
    canonical = json.dumps(
        _canonical_json_value(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_completed_claim_archive_receipt(
    *,
    source_kind: CompletedClaimSourceKind,
    source_path: Path | str,
    source_bytes: bytes,
    prune_event_id: str | None = None,
    writer: tuple[str, str, str] | None = None,
    archived_at: datetime | None = None,
) -> CompletedClaimArchiveReceiptV1:
    """Build and fully validate one deterministic exact-byte archive receipt."""

    normalized_source_path = str(Path(source_path).expanduser().resolve())
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    archive_id = completed_claim_archive_id(
        source_path=normalized_source_path,
        source_sha256=source_sha256,
    )
    if source_kind == "live_prune":
        if prune_event_id is not None:
            raise ValueError("live_prune does not accept a historical prune_event_id")
        prune_binding = CompletedClaimPruneBindingV1(
            kind="live_prune_transaction",
            transaction_id=completed_claim_archive_transaction_id(archive_id),
            mutation_event_id=None,
        )
    else:
        if not prune_event_id or not prune_event_id.strip():
            raise ValueError("legacy_reconciliation requires a prune_event_id")
        prune_binding = CompletedClaimPruneBindingV1(
            kind="legacy_prune_event",
            transaction_id=None,
            mutation_event_id=prune_event_id.strip(),
        )
    agent, project, scope, session_id, status = _completed_claim_identity(source_bytes)
    writer_source_path, writer_source_sha256, writer_repo_root = (
        writer or writer_identity(Path(__file__))
    )
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "archive_id": archive_id,
        "source_kind": source_kind,
        "source_path": normalized_source_path,
        "source_sha256": source_sha256,
        "source_yaml_bytes": base64.b64encode(source_bytes).decode("ascii"),
        "agent": agent,
        "project": project,
        "scope": scope,
        "session_id": session_id,
        "status": status,
        "prune_binding": prune_binding.model_dump(mode="python"),
        "archived_at": archived_at or datetime.now(timezone.utc),
        "writer_source_path": writer_source_path,
        "writer_source_sha256": writer_source_sha256,
        "writer_repo_root": writer_repo_root,
    }
    payload["receipt_sha256"] = completed_claim_archive_receipt_sha256(payload)
    return CompletedClaimArchiveReceiptV1.model_validate(payload)


def _completed_claim_archive_semantic_payload(
    receipt: CompletedClaimArchiveReceiptV1,
) -> dict[str, Any]:
    """Return immutable source and prune fields used for duplicate comparison."""

    return {
        "schema_version": receipt.schema_version,
        "archive_id": receipt.archive_id,
        "source_kind": receipt.source_kind,
        "source_path": receipt.source_path,
        "source_sha256": receipt.source_sha256,
        "source_yaml_bytes": receipt.source_yaml_bytes,
        "agent": receipt.agent,
        "project": receipt.project,
        "scope": receipt.scope,
        "session_id": receipt.session_id,
        "status": receipt.status,
        "prune_binding": receipt.prune_binding.model_dump(mode="python"),
    }


def _parse_completed_claim_archive(
    text: str,
    *,
    archive_path: Path,
) -> list[CompletedClaimArchiveReceiptV1]:
    """Parse an intrinsic archive ledger and reject conflicting duplicate IDs."""

    receipts: list[CompletedClaimArchiveReceiptV1] = []
    by_id: dict[str, CompletedClaimArchiveReceiptV1] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            receipt = CompletedClaimArchiveReceiptV1.model_validate_json(line)
        except ValueError as exc:
            raise ValueError(
                f"Invalid completed-claim archive receipt at {archive_path}:{number}: {exc}"
            ) from exc
        existing = by_id.get(receipt.archive_id)
        if existing is not None:
            if _completed_claim_archive_semantic_payload(
                existing
            ) != _completed_claim_archive_semantic_payload(receipt):
                raise ValueError(
                    "conflicting completed-claim archive records share archive_id "
                    f"{receipt.archive_id}"
                )
            continue
        by_id[receipt.archive_id] = receipt
        receipts.append(receipt)
    return receipts


def append_completed_claim_archive_receipt(
    receipt: CompletedClaimArchiveReceiptV1,
    *,
    archive_path: Path | None = None,
) -> tuple[Path, bool]:
    """Append and fsync one receipt, with idempotent exact-identity replay."""

    validated = CompletedClaimArchiveReceiptV1.model_validate(
        receipt.model_dump(mode="python")
    )
    resolved = (
        archive_path or DEFAULT_COMPLETED_CLAIM_ARCHIVE_PATH
    ).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with resolved.open("a+", encoding="utf-8") as handle:
        resolved.chmod(0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            existing_receipts = _parse_completed_claim_archive(
                handle.read(),
                archive_path=resolved,
            )
            for existing in existing_receipts:
                if existing.archive_id != validated.archive_id:
                    continue
                if _completed_claim_archive_semantic_payload(
                    existing
                ) == _completed_claim_archive_semantic_payload(validated):
                    return resolved, False
                raise ValueError(
                    "conflicting completed-claim archive receipt for archive_id "
                    f"{validated.archive_id}"
                )
            handle.seek(0, os.SEEK_END)
            handle.write(validated.model_dump_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return resolved, True


def validate_completed_claim_archive_prune_binding(
    receipt: CompletedClaimArchiveReceiptV1,
    *,
    mutation_receipts: list[ClaimMutationReceiptV1],
) -> ClaimMutationReceiptV1:
    """Require one applied prune mutation matching the archived claim exactly."""

    if receipt.prune_binding.kind == "live_prune_transaction":
        matches = [
            event
            for event in mutation_receipts
            if event.archive_transaction_id
            == receipt.prune_binding.transaction_id
        ]
        binding_label = (
            "transaction " + str(receipt.prune_binding.transaction_id)
        )
    else:
        matches = [
            event
            for event in mutation_receipts
            if event.event_id == receipt.prune_binding.mutation_event_id
        ]
        binding_label = (
            "mutation event " + str(receipt.prune_binding.mutation_event_id)
        )
    if len(matches) != 1:
        raise ValueError(
            f"completed-claim archive {binding_label} must match exactly one mutation receipt"
        )
    event = matches[0]
    if event.operation != "prune" or event.result == "not_applied":
        raise ValueError(
            f"completed-claim archive {binding_label} does not identify an applied prune"
        )
    observed_path = (
        str(Path(event.target_claim_path).expanduser().resolve())
        if event.target_claim_path
        else None
    )
    expected = (
        receipt.project,
        receipt.scope,
        receipt.source_path,
        receipt.session_id,
    )
    observed = (
        event.target_project,
        event.target_scope,
        observed_path,
        event.session_id,
    )
    if observed != expected:
        raise ValueError(
            "completed-claim archive prune receipt identity/path/session mismatch: "
            f"expected={expected!r} observed={observed!r}"
        )
    return event


def load_completed_claim_archive_receipts(
    *,
    archive_path: Path | None = None,
    mutation_events_path: Path | None = None,
) -> list[CompletedClaimArchiveReceiptV1]:
    """Load the archive and require every record's applied prune binding."""

    resolved = (
        archive_path or DEFAULT_COMPLETED_CLAIM_ARCHIVE_PATH
    ).expanduser().resolve()
    if not resolved.exists():
        return []
    receipts = _parse_completed_claim_archive(
        resolved.read_text(encoding="utf-8"),
        archive_path=resolved,
    )
    mutation_receipts = load_receipts(events_path=mutation_events_path)
    for receipt in receipts:
        validate_completed_claim_archive_prune_binding(
            receipt,
            mutation_receipts=mutation_receipts,
        )
    return receipts


def append_receipt(receipt: ClaimMutationReceiptV1, *, events_path: Path | None = None) -> Path:
    """Append and fsync one receipt while preserving JSONL record boundaries."""

    resolved = (events_path or DEFAULT_EVENTS_PATH).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = receipt.model_dump_json() + "\n"
    with resolved.open("a", encoding="utf-8") as handle:
        resolved.chmod(0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return resolved


def load_receipts(*, events_path: Path | None = None) -> list[ClaimMutationReceiptV1]:
    """Load a complete JSONL ledger, rejecting malformed or unknown fields."""

    resolved = (events_path or DEFAULT_EVENTS_PATH).expanduser().resolve()
    if not resolved.exists():
        return []
    receipts: list[ClaimMutationReceiptV1] = []
    for number, line in enumerate(resolved.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            receipts.append(ClaimMutationReceiptV1.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"Invalid claim mutation receipt at {resolved}:{number}: {exc}") from exc
    return receipts


__all__ = [
    "CompletedClaimArchiveError",
    "CompletedClaimArchiveReceiptV1",
    "CompletedClaimPruneBindingV1",
    "CompletedClaimPruneBindingKind",
    "CompletedClaimSourceKind",
    "CompletedClaimStatus",
    "ClaimMutationReceiptV1",
    "DEFAULT_COMPLETED_CLAIM_ARCHIVE_PATH",
    "DEFAULT_EVENTS_PATH",
    "MutationAuditError",
    "MutationOperation",
    "MutationResult",
    "append_completed_claim_archive_receipt",
    "append_receipt",
    "build_completed_claim_archive_receipt",
    "completed_claim_archive_id",
    "completed_claim_archive_receipt_sha256",
    "completed_claim_archive_transaction_id",
    "load_completed_claim_archive_receipts",
    "load_receipts",
    "validate_completed_claim_archive_prune_binding",
    "writer_identity",
]
