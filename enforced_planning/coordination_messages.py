#!/usr/bin/env python3
"""Durable cross-client coordination messages and append-only receipts.

Claims remain authoritative for recipient routing and write ownership. Exact
native client identity may authorize message-only send, poll, and
acknowledgement after a write claim ends; it cannot restore write authority or
route to an unclaimed recipient. This module owns only immutable message intent,
runtime/observation/acknowledgement evidence, and derived status. JSON is the
canonical storage format; human-readable projections remain outside this
boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import sys
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, NoReturn, cast

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from enforced_planning import coordination_claims


SCHEMA_VERSION: Literal["1.0"] = "1.0"
DEFAULT_TTL_SECONDS = 86_400
MAX_NOTE_LENGTH = 2_000
DEFAULT_NOTICE_BODY_LENGTH = 500
DEFAULT_NOTICE_MESSAGE_LIMIT = 20
MessageState = Literal["persisted", "runtime_accepted", "observed", "acknowledged", "expired"]


class CoordinationMessageError(RuntimeError):
    """Base class for fail-loud mailbox contract and storage errors."""


class UnknownSessionError(CoordinationMessageError):
    """Raised when no live claim or exact native client authorizes a session."""


class AmbiguousRecipientError(CoordinationMessageError):
    """Raised when a claim selector resolves to multiple recipient sessions."""


class IdentityMismatchError(CoordinationMessageError):
    """Raised when caller identity differs from the asserted sender identity."""


class RecordCollisionError(CoordinationMessageError):
    """Raised when an immutable identifier is reused for different content."""


class CorruptRecordError(CoordinationMessageError):
    """Raised after an unreadable or integrity-invalid record is quarantined."""


class MessageNotFoundError(CoordinationMessageError):
    """Raised when a requested canonical message does not exist."""


class WrongRecipientError(CoordinationMessageError):
    """Raised when a session attempts to observe or acknowledge another inbox."""


class StrictContract(BaseModel):
    """Strict immutable base for every public mailbox boundary model."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ExactSessionSelector(StrictContract):
    """Select one recipient by canonical live session identity."""

    kind: Literal["session"] = Field(description="Discriminator for exact-session routing.")
    session_id: str = Field(min_length=1, description="Canonical session ID already present in a live claim.")


class ClaimRecipientSelector(StrictContract):
    """Select one recipient through a live project claim."""

    kind: Literal["claim"] = Field(description="Discriminator for claim-backed routing.")
    project: str = Field(min_length=1, description="Project whose live claim owns the recipient session.")
    scope: str | None = Field(
        default=None,
        description="Optional exact claim scope; omission is valid only when one live session remains.",
    )


RecipientSelector = Annotated[ExactSessionSelector | ClaimRecipientSelector, Field(discriminator="kind")]


class SendMessageRequest(StrictContract):
    """Typed command for persisting one immutable coordination message."""

    caller_session_id: str = Field(min_length=1, description="Session identity supplied by the invoking adapter.")
    sender_session_id: str = Field(min_length=1, description="Sender identity asserted in the durable message.")
    recipient: RecipientSelector = Field(description="Canonical selector resolved at send time.")
    project: str = Field(min_length=1, description="Project context for the requested coordination action.")
    kind: Literal["info", "question", "review_request", "handoff", "coordination_request"] = Field(
        description="Bounded coordination intent, not an authorization to mutate recipient state."
    )
    subject: str = Field(min_length=1, max_length=500, description="Compact human-readable message subject.")
    body: str | None = Field(default=None, min_length=1, description="Inline message content when no content_ref is used.")
    content_ref: str | None = Field(
        default=None,
        min_length=1,
        description="Durable content reference used instead of inline body text.",
    )
    ttl_seconds: int = Field(
        default=DEFAULT_TTL_SECONDS,
        gt=0,
        description="Positive lifetime in seconds; expiry never deletes the audit record.",
    )
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Caller-owned retry key scoped to sender identity; not persisted verbatim.",
    )
    plan_ref: str | None = Field(default=None, min_length=1, description="Optional governing plan reference.")
    claim_ref: str | None = Field(default=None, min_length=1, description="Optional related claim scope.")
    reply_to_message_id: str | None = Field(
        default=None,
        pattern=r"^msg_[0-9a-f]{32}$",
        description="Optional canonical message ID being answered.",
    )

    @model_validator(mode="after")
    def require_exactly_one_content_source(self) -> SendMessageRequest:
        """Reject missing content and ambiguous dual inline/reference content."""

        if (self.body is None) == (self.content_ref is None):
            raise ValueError("exactly one of body or content_ref is required")
        return self


class PollMessagesRequest(StrictContract):
    """Typed command for reading one canonical session inbox."""

    current_session_id: str = Field(min_length=1, description="Canonical recipient session performing the poll.")
    as_of: AwareDatetime | None = Field(default=None, description="Projection time; current UTC when omitted.")
    project: str | None = Field(default=None, min_length=1, description="Optional exact project filter.")
    include_expired: bool = Field(default=False, description="Whether expired messages remain in the returned view.")
    observe: bool = Field(default=False, description="Whether returned active messages emit observation receipts.")


class AcknowledgeMessageRequest(StrictContract):
    """Typed command for appending one recipient acknowledgement."""

    current_session_id: str = Field(min_length=1, description="Canonical recipient session acknowledging the message.")
    message_id: str = Field(pattern=r"^msg_[0-9a-f]{32}$", description="Canonical message being acknowledged.")
    disposition: Literal["accepted", "declined", "deferred", "information_only"] = Field(
        description="Recipient's explicit acknowledgement disposition."
    )
    response_ref: str | None = Field(default=None, min_length=1, description="Optional durable response artifact reference.")
    note: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_NOTE_LENGTH,
        description="Optional bounded recipient note; not an authorization side effect.",
    )


class MessageStatusRequest(StrictContract):
    """Typed command for deriving status from one message and its receipt set."""

    message_id: str = Field(pattern=r"^msg_[0-9a-f]{32}$", description="Canonical message whose status is requested.")
    as_of: AwareDatetime | None = Field(default=None, description="Projection time; current UTC when omitted.")


class CoordinationMessage(StrictContract):
    """Immutable resolved coordination intent persisted by the mailbox."""

    schema_version: Literal["1.0"] = Field(description="Portable message schema version.")
    message_id: str = Field(pattern=r"^msg_[0-9a-f]{32}$", description="System-assigned globally unique message ID.")
    sender_session_id: str = Field(min_length=1, description="Canonical live sender session at creation time.")
    recipient_selector: RecipientSelector = Field(description="Original routing selector retained for audit.")
    recipient_session_id: str = Field(min_length=1, description="Exact live session resolved at creation time.")
    project: str = Field(min_length=1, description="Project context for this coordination intent.")
    kind: Literal["info", "question", "review_request", "handoff", "coordination_request"] = Field(
        description="Bounded coordination intent."
    )
    subject: str = Field(min_length=1, max_length=500, description="Compact human-readable message subject.")
    body: str | None = Field(default=None, min_length=1, description="Inline content when retained directly.")
    content_ref: str | None = Field(default=None, min_length=1, description="Durable content reference when not inline.")
    created_at: AwareDatetime = Field(description="UTC creation time chosen by the mailbox.")
    expires_at: AwareDatetime = Field(description="UTC time after which the message is inactive but auditable.")
    request_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Canonical semantic-request digest used to detect idempotency collisions.",
    )
    plan_ref: str | None = Field(default=None, min_length=1, description="Optional governing plan reference.")
    claim_ref: str | None = Field(default=None, min_length=1, description="Optional related claim scope.")
    reply_to_message_id: str | None = Field(
        default=None,
        pattern=r"^msg_[0-9a-f]{32}$",
        description="Optional canonical message being answered.",
    )

    @model_validator(mode="after")
    def validate_content_and_time(self) -> CoordinationMessage:
        """Keep persisted content exclusive and expiry strictly after creation."""

        if (self.body is None) == (self.content_ref is None):
            raise ValueError("exactly one of body or content_ref is required")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self


class MessageReceipt(StrictContract):
    """Immutable evidence of runtime acceptance, observation, or acknowledgement."""

    schema_version: Literal["1.0"] = Field(description="Portable receipt schema version.")
    receipt_id: str = Field(pattern=r"^rcpt_[0-9a-f]{32}$", description="System-assigned deterministic receipt ID.")
    message_id: str = Field(pattern=r"^msg_[0-9a-f]{32}$", description="Message evidenced by this receipt.")
    recipient_session_id: str = Field(min_length=1, description="Canonical recipient session producing the evidence.")
    event: Literal["runtime_accepted", "observed", "acknowledged"] = Field(
        description="Evidence class; no event implies a stronger class by storage alone."
    )
    recorded_at: AwareDatetime = Field(description="UTC time at which the immutable receipt was appended.")
    disposition: Literal["accepted", "declined", "deferred", "information_only"] | None = Field(
        default=None,
        description="Required only for acknowledgement receipts.",
    )
    response_ref: str | None = Field(default=None, min_length=1, description="Optional durable response artifact reference.")
    note: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_NOTE_LENGTH,
        description="Optional bounded recipient note.",
    )

    @model_validator(mode="after")
    def validate_acknowledgement_fields(self) -> MessageReceipt:
        """Prevent weaker receipt classes from carrying acknowledgement claims."""

        if self.event == "acknowledged" and self.disposition is None:
            raise ValueError("acknowledged receipts require disposition")
        if self.event != "acknowledged" and any(
            value is not None for value in (self.disposition, self.response_ref, self.note)
        ):
            raise ValueError("only acknowledged receipts may carry disposition, response_ref, or note")
        return self


class StoredMessageRecord(StrictContract):
    """Integrity envelope for one canonical message file."""

    record_type: Literal["coordination_message"] = Field(description="Discriminator for message storage records.")
    payload: CoordinationMessage = Field(description="Strict canonical message payload.")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="Digest of canonical payload JSON.")

    @model_validator(mode="after")
    def validate_digest(self) -> StoredMessageRecord:
        """Reject storage bytes whose payload no longer matches its digest."""

        if self.payload_sha256 != _model_digest(self.payload):
            raise ValueError("message payload_sha256 mismatch")
        return self


class StoredReceiptRecord(StrictContract):
    """Integrity envelope for one canonical receipt file."""

    record_type: Literal["message_receipt"] = Field(description="Discriminator for receipt storage records.")
    payload: MessageReceipt = Field(description="Strict canonical receipt payload.")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="Digest of canonical payload JSON.")

    @model_validator(mode="after")
    def validate_digest(self) -> StoredReceiptRecord:
        """Reject storage bytes whose payload no longer matches its digest."""

        if self.payload_sha256 != _model_digest(self.payload):
            raise ValueError("receipt payload_sha256 mismatch")
        return self


class MessageStatusView(StrictContract):
    """Derived lifecycle view computed from immutable message and receipts."""

    message: CoordinationMessage = Field(description="Canonical immutable message being projected.")
    state: MessageState = Field(
        description="Strongest active lifecycle state at the requested projection time."
    )
    runtime_accepted: bool = Field(description="Whether runtime acceptance evidence exists.")
    observed: bool = Field(description="Whether observation or acknowledgement evidence exists.")
    acknowledged: bool = Field(description="Whether explicit acknowledgement evidence exists.")
    expired: bool = Field(description="Whether the message is inactive at the projection time.")
    receipts: tuple[MessageReceipt, ...] = Field(description="Exact ordered receipt set used for this projection.")
    receipt_paths: tuple[str, ...] = Field(
        description="Evidence paths aligned one-to-one with the ordered receipt set."
    )
    receipt_set_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Digest watermark of ordered canonical receipt payloads.",
    )
    message_path: str = Field(min_length=1, description="Evidence path to the canonical stored message.")


class PersistedMessageResult(StrictContract):
    """Result of one successful or idempotently replayed send operation."""

    message: CoordinationMessage = Field(description="Canonical persisted message.")
    message_path: str = Field(min_length=1, description="Evidence path to the canonical message record.")
    idempotent_replay: bool = Field(description="Whether an identical existing message satisfied this request.")


class MessagePollResult(StrictContract):
    """Ordered inbox views and any observation receipts appended by polling."""

    current_session_id: str = Field(min_length=1, description="Canonical session whose inbox was polled.")
    messages: tuple[MessageStatusView, ...] = Field(description="Creation-ordered message views for the recipient.")
    observation_receipts: tuple[MessageReceipt, ...] = Field(
        description="Observation receipts created or idempotently reused by this poll."
    )
    observation_receipt_paths: tuple[str, ...] = Field(
        description="Evidence paths aligned one-to-one with observation_receipts."
    )


class AcknowledgementResult(StrictContract):
    """Acknowledgement receipt plus the resulting derived message status."""

    receipt: MessageReceipt = Field(description="Canonical acknowledgement receipt.")
    receipt_path: str = Field(min_length=1, description="Evidence path to the canonical acknowledgement receipt.")
    status: MessageStatusView = Field(description="Status projected after appending the receipt.")
    idempotent_replay: bool = Field(description="Whether an identical receipt already existed.")


class SessionInboxNotice(StrictContract):
    """Compact agent-facing projection of one lifecycle mailbox poll."""

    session_id: str = Field(min_length=1, description="Canonical session identity whose inbox was polled.")
    project: str = Field(min_length=1, description="Project filter applied to the poll.")
    active_count: int = Field(ge=0, description="Number of non-expired messages visible to the session.")
    message_ids: tuple[str, ...] = Field(description="Canonical active message IDs in creation order.")
    summary: str = Field(description="Bounded text suitable for injection into an agent lifecycle response.")


def _canonical_json(value: Any) -> bytes:
    """Serialize one JSON-compatible value deterministically for identity and storage."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _model_digest(model: BaseModel) -> str:
    """Hash one strict model in JSON mode using canonical ordering."""

    return hashlib.sha256(_canonical_json(model.model_dump(mode="json"))).hexdigest()


def _receipt_set_digest(receipts: list[MessageReceipt]) -> str:
    """Hash the exact ordered receipt payload set used by a status projection."""

    payloads = [receipt.model_dump(mode="json") for receipt in receipts]
    return hashlib.sha256(_canonical_json(payloads)).hexdigest()


def _utc_now() -> datetime:
    """Return an aware UTC timestamp for default runtime operations."""

    return datetime.now(UTC)


def _fsync_directory(path: Path) -> None:
    """Durably commit a directory-entry change before reporting success."""

    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stable_id(prefix: str, *parts: str) -> str:
    """Build a collision-resistant deterministic ID from a namespaced tuple."""

    digest = hashlib.sha256("\0".join((prefix, *parts)).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}_{digest}"


class CoordinationMessageStore:
    """Filesystem authority for immutable messages, receipts, and derived views."""

    def __init__(self, *, root: Path, claims_dir: Path) -> None:
        self.root = root.expanduser().resolve()
        self.claims_dir = claims_dir.expanduser().resolve()
        self.messages_dir = self.root / "messages"
        self.receipts_dir = self.root / "receipts"
        self.quarantine_dir = self.root / "quarantine"

    def _live_claims(self, project: str | None = None) -> list[coordination_claims.ClaimRecord]:
        """Read canonical live identity records without introducing another registry."""
        check_claims = cast(
            "Callable[..., list[coordination_claims.ClaimRecord]]",
            coordination_claims.check_claims,
        )
        parameters = inspect.signature(check_claims).parameters
        if "claims_dir" in parameters:
            return check_claims(project, claims_dir=self.claims_dir)
        canonical_claims_dir = Path(coordination_claims.CLAIMS_DIR).expanduser().resolve()
        if self.claims_dir != canonical_claims_dir:
            raise CoordinationMessageError(
                "Installed claim registry cannot read a custom claims directory; "
                "upgrade enforced_planning.coordination_claims before overriding claims_dir"
            )
        return check_claims(project)

    def _require_live_session(self, session_id: str) -> None:
        """Fail when a caller or exact recipient is absent from live claims."""

        if not any(claim.session_id == session_id for claim in self._live_claims()):
            raise UnknownSessionError(f"No live claim owns session {session_id!r}")

    def resolve_recipient(self, selector: RecipientSelector) -> str:
        """Resolve an exact or claim-backed selector to one canonical session."""

        if isinstance(selector, ExactSessionSelector):
            self._require_live_session(selector.session_id)
            return selector.session_id
        claims = self._live_claims(selector.project)
        if selector.scope is not None:
            claims = [claim for claim in claims if claim.scope == selector.scope]
        sessions = sorted({claim.session_id for claim in claims if claim.session_id})
        if not sessions:
            raise UnknownSessionError(
                f"No live recipient session matches project={selector.project!r}, scope={selector.scope!r}"
            )
        if len(sessions) > 1:
            raise AmbiguousRecipientError(
                f"Recipient selector matched {len(sessions)} sessions: {', '.join(sessions)}"
            )
        return sessions[0]

    def _quarantine(self, path: Path, reason: str) -> NoReturn:
        """Move one corrupt record out of the canonical scan path and retain its evidence."""

        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        suffix = f".{_utc_now().strftime('%Y%m%dT%H%M%S%fZ')}.{uuid.uuid4().hex[:8]}.corrupt"
        destination = self.quarantine_dir / f"{path.name}{suffix}"
        try:
            os.replace(path, destination)
            _fsync_directory(self.quarantine_dir)
            if path.parent != self.quarantine_dir:
                _fsync_directory(path.parent)
        except OSError as exc:
            raise CorruptRecordError(f"Corrupt record {path} could not be quarantined: {reason}; {exc}") from exc
        raise CorruptRecordError(f"Quarantined corrupt record {path} at {destination}: {reason}")

    def _read_message_path(self, path: Path) -> CoordinationMessage:
        """Validate one message record, quarantining malformed or digest-invalid content."""

        try:
            record = StoredMessageRecord.model_validate_json(path.read_bytes())
        except (OSError, ValidationError, ValueError) as exc:
            return self._quarantine(path, str(exc))
        return record.payload

    def _read_receipt_path(self, path: Path) -> MessageReceipt:
        """Validate one receipt record, quarantining malformed or digest-invalid content."""

        try:
            record = StoredReceiptRecord.model_validate_json(path.read_bytes())
        except (OSError, ValidationError, ValueError) as exc:
            return self._quarantine(path, str(exc))
        return record.payload

    def _write_immutable(self, path: Path, payload: bytes) -> bool:
        """Atomically publish immutable bytes without overwriting an existing identifier."""

        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
                temp_path = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp_path, path)
            except FileExistsError:
                return False
            _fsync_directory(path.parent)
            return True
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _store_message(self, message: CoordinationMessage) -> tuple[Path, bool]:
        """Persist one integrity-wrapped message or verify an idempotent replay."""

        path = self.messages_dir / f"{message.message_id}.json"
        record = StoredMessageRecord(
            record_type="coordination_message",
            payload=message,
            payload_sha256=_model_digest(message),
        )
        encoded = _canonical_json(record.model_dump(mode="json")) + b"\n"
        if self._write_immutable(path, encoded):
            return path, False
        existing = self._read_message_path(path)
        if existing.request_sha256 != message.request_sha256:
            raise RecordCollisionError(f"Message ID {message.message_id} already contains different content")
        return path, True

    def _store_receipt(self, receipt: MessageReceipt) -> tuple[Path, bool]:
        """Append one integrity-wrapped receipt or verify an idempotent replay."""

        path = self.receipts_dir / f"{receipt.receipt_id}.json"
        record = StoredReceiptRecord(
            record_type="message_receipt",
            payload=receipt,
            payload_sha256=_model_digest(receipt),
        )
        encoded = _canonical_json(record.model_dump(mode="json")) + b"\n"
        if self._write_immutable(path, encoded):
            return path, False
        existing = self._read_receipt_path(path)
        comparable_existing = existing.model_copy(update={"recorded_at": receipt.recorded_at})
        if comparable_existing != receipt:
            raise RecordCollisionError(f"Receipt ID {receipt.receipt_id} already contains different content")
        return path, True

    def _message(self, message_id: str) -> tuple[CoordinationMessage, Path]:
        """Load one canonical message or fail when it is absent."""

        path = self.messages_dir / f"{message_id}.json"
        if not path.is_file():
            raise MessageNotFoundError(f"Message {message_id} does not exist")
        return self._read_message_path(path), path

    def _all_messages(self) -> list[tuple[CoordinationMessage, Path]]:
        """Load every canonical message in deterministic creation order."""

        if not self.messages_dir.exists():
            return []
        messages = [(self._read_message_path(path), path) for path in sorted(self.messages_dir.glob("*.json"))]
        return sorted(messages, key=lambda item: (item[0].created_at, item[0].message_id))

    def _receipts_for(self, message_id: str) -> list[MessageReceipt]:
        """Load and order every receipt, then select the requested message set."""

        if not self.receipts_dir.exists():
            return []
        receipts = [self._read_receipt_path(path) for path in sorted(self.receipts_dir.glob("*.json"))]
        matching = [receipt for receipt in receipts if receipt.message_id == message_id]
        return sorted(matching, key=lambda receipt: (receipt.recorded_at, receipt.receipt_id))

    def send(
        self,
        request: SendMessageRequest,
        *,
        now: datetime | None = None,
        require_live_claim: bool = True,
    ) -> PersistedMessageResult:
        """Resolve identities and persist one immutable coordination message.

        Native client adapters may set ``require_live_claim=False`` only after
        verifying that their current client session exactly matches the caller
        and sender IDs. Recipient routing remains claim-backed.
        """

        if request.caller_session_id != request.sender_session_id:
            raise IdentityMismatchError(
                f"Caller {request.caller_session_id!r} cannot assert sender {request.sender_session_id!r}"
            )
        if require_live_claim:
            self._require_live_session(request.caller_session_id)
        semantic_request = request.model_dump(mode="json", exclude={"idempotency_key"})
        request_sha256 = hashlib.sha256(_canonical_json(semantic_request)).hexdigest()
        if request.idempotency_key is None:
            message_id = f"msg_{uuid.uuid4().hex}"
        else:
            message_id = _stable_id("msg", request.sender_session_id, request.idempotency_key)
            existing_path = self.messages_dir / f"{message_id}.json"
            if existing_path.is_file():
                existing = self._read_message_path(existing_path)
                if existing.request_sha256 != request_sha256:
                    raise RecordCollisionError(f"Message ID {message_id} already contains different content")
                return PersistedMessageResult(
                    message=existing,
                    message_path=str(existing_path),
                    idempotent_replay=True,
                )
        recipient_session_id = self.resolve_recipient(request.recipient)
        created_at = now or _utc_now()
        if created_at.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        message = CoordinationMessage(
            schema_version=SCHEMA_VERSION,
            message_id=message_id,
            sender_session_id=request.sender_session_id,
            recipient_selector=request.recipient,
            recipient_session_id=recipient_session_id,
            project=request.project,
            kind=request.kind,
            subject=request.subject,
            body=request.body,
            content_ref=request.content_ref,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=request.ttl_seconds),
            request_sha256=request_sha256,
            plan_ref=request.plan_ref,
            claim_ref=request.claim_ref,
            reply_to_message_id=request.reply_to_message_id,
        )
        path, idempotent = self._store_message(message)
        if idempotent:
            message = self._read_message_path(path)
        return PersistedMessageResult(message=message, message_path=str(path), idempotent_replay=idempotent)

    def _append_observation(self, message: CoordinationMessage, *, now: datetime) -> tuple[MessageReceipt, Path]:
        """Append or reuse one observation receipt for the exact recipient."""

        receipt = MessageReceipt(
            schema_version=SCHEMA_VERSION,
            receipt_id=_stable_id("rcpt", message.message_id, message.recipient_session_id, "observed"),
            message_id=message.message_id,
            recipient_session_id=message.recipient_session_id,
            event="observed",
            recorded_at=now,
        )
        path, idempotent = self._store_receipt(receipt)
        return (self._read_receipt_path(path) if idempotent else receipt), path

    def status(self, request: MessageStatusRequest) -> MessageStatusView:
        """Derive lifecycle state from one immutable message and exact receipt set."""

        message, path = self._message(request.message_id)
        receipts = self._receipts_for(message.message_id)
        as_of = request.as_of or _utc_now()
        relevant = [receipt for receipt in receipts if receipt.recorded_at <= as_of]
        runtime_accepted = any(receipt.event == "runtime_accepted" for receipt in relevant)
        acknowledgements = [receipt for receipt in relevant if receipt.event == "acknowledged"]
        observed = bool(acknowledgements) or any(receipt.event == "observed" for receipt in relevant)
        acknowledged = bool(acknowledgements)
        expired = as_of >= message.expires_at and not any(
            receipt.recorded_at <= message.expires_at for receipt in acknowledgements
        )
        state: MessageState
        if expired:
            state = "expired"
        elif acknowledged:
            state = "acknowledged"
        elif observed:
            state = "observed"
        elif runtime_accepted:
            state = "runtime_accepted"
        else:
            state = "persisted"
        return MessageStatusView(
            message=message,
            state=state,
            runtime_accepted=runtime_accepted,
            observed=observed,
            acknowledged=acknowledged,
            expired=expired,
            receipts=tuple(relevant),
            receipt_paths=tuple(str(self.receipts_dir / f"{receipt.receipt_id}.json") for receipt in relevant),
            receipt_set_sha256=_receipt_set_digest(relevant),
            message_path=str(path),
        )

    def poll(
        self,
        request: PollMessagesRequest,
        *,
        now: datetime | None = None,
        require_live_claim: bool = True,
    ) -> MessagePollResult:
        """Read one session inbox and optionally append observation receipts.

        ``require_live_claim=False`` is reserved for a native client lifecycle
        adapter that receives the current session ID from the client itself.
        Write claims remain mandatory for message routing and sender identity;
        completing a write claim must not make the still-running client's
        read-only inbox unavailable.
        """

        if require_live_claim:
            self._require_live_session(request.current_session_id)
        as_of = request.as_of or now or _utc_now()
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        selected = [
            message
            for message, _path in self._all_messages()
            if message.recipient_session_id == request.current_session_id
            and (request.project is None or message.project == request.project)
        ]
        observations: list[MessageReceipt] = []
        observation_paths: list[str] = []
        views: list[MessageStatusView] = []
        for message in selected:
            before = self.status(MessageStatusRequest(message_id=message.message_id, as_of=as_of))
            if before.expired and not request.include_expired:
                continue
            if request.observe and not before.expired and not before.observed:
                observation, observation_path = self._append_observation(message, now=as_of)
                observations.append(observation)
                observation_paths.append(str(observation_path))
            views.append(self.status(MessageStatusRequest(message_id=message.message_id, as_of=as_of)))
        return MessagePollResult(
            current_session_id=request.current_session_id,
            messages=tuple(views),
            observation_receipts=tuple(observations),
            observation_receipt_paths=tuple(observation_paths),
        )

    def acknowledge(
        self,
        request: AcknowledgeMessageRequest,
        *,
        now: datetime | None = None,
        require_live_claim: bool = True,
    ) -> AcknowledgementResult:
        """Append one recipient acknowledgement without mutating message state.

        A native client adapter may bypass claim liveness after proving the
        current client session exactly matches ``current_session_id``.
        """

        if require_live_claim:
            self._require_live_session(request.current_session_id)
        message, _path = self._message(request.message_id)
        if message.recipient_session_id != request.current_session_id:
            raise WrongRecipientError(
                f"Session {request.current_session_id!r} is not recipient {message.recipient_session_id!r}"
            )
        recorded_at = now or _utc_now()
        receipt = MessageReceipt(
            schema_version=SCHEMA_VERSION,
            receipt_id=_stable_id("rcpt", message.message_id, request.current_session_id, "acknowledged"),
            message_id=message.message_id,
            recipient_session_id=request.current_session_id,
            event="acknowledged",
            recorded_at=recorded_at,
            disposition=request.disposition,
            response_ref=request.response_ref,
            note=request.note,
        )
        path, idempotent = self._store_receipt(receipt)
        if idempotent:
            receipt = self._read_receipt_path(path)
        status = self.status(MessageStatusRequest(message_id=message.message_id, as_of=recorded_at))
        return AcknowledgementResult(
            receipt=receipt,
            receipt_path=str(path),
            status=status,
            idempotent_replay=idempotent,
        )


def default_message_root(claims_dir: Path | None = None) -> Path:
    """Derive the mailbox authority beside the configured canonical claims directory."""

    return (claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve().parent / "messages-v1"


def poll_session_inbox(
    *,
    agent: str,
    project: str,
    session_id: str | None = None,
    observe: bool = True,
    claims_dir: Path | None = None,
    root: Path | None = None,
    max_body_chars: int = DEFAULT_NOTICE_BODY_LENGTH,
    max_messages: int = DEFAULT_NOTICE_MESSAGE_LIMIT,
    require_live_claim: bool = True,
) -> SessionInboxNotice:
    """Resolve one live agent session and return an agent-visible mailbox notice.

    Native lifecycle adapters may set ``require_live_claim=False`` because the
    client event supplies the exact current session identity. Observation
    evidence still means the notice reached an agent-facing command result, not
    merely that a background process scanned storage.
    """

    if max_body_chars < 1 or max_messages < 1:
        raise ValueError("max_body_chars and max_messages must be positive")
    resolved_session_id = coordination_claims.resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise UnknownSessionError(
            f"Unable to resolve a canonical session ID for agent {agent!r}; "
            "pass session_id or run from a supported client runtime"
        )
    resolved_claims_dir = (claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve()
    store = CoordinationMessageStore(
        root=root or default_message_root(resolved_claims_dir),
        claims_dir=resolved_claims_dir,
    )
    result = store.poll(
        PollMessagesRequest(
            current_session_id=resolved_session_id,
            project=project,
            observe=observe,
        ),
        require_live_claim=require_live_claim,
    )
    active = tuple(
        view for view in result.messages if not view.expired and not view.acknowledged
    )
    if active:
        displayed = active[:max_messages]
        rendered_messages: list[str] = []
        for view in displayed:
            content = view.message.body or f"content_ref={view.message.content_ref}"
            compact_content = " ".join(content.split())
            if len(compact_content) > max_body_chars:
                compact_content = compact_content[: max_body_chars - 1] + "…"
            rendered_messages.append(
                f"{view.message.message_id} [{view.message.kind}] "
                f"{view.message.subject}: {compact_content}"
            )
        details = "; ".join(rendered_messages)
        remainder = len(active) - len(displayed)
        suffix = f"; {remainder} more not shown" if remainder else ""
        summary = f"coordination mailbox: {len(active)} active message(s): {details}{suffix}"
    else:
        summary = "coordination mailbox: no active messages"
    return SessionInboxNotice(
        session_id=resolved_session_id,
        project=project,
        active_count=len(active),
        message_ids=tuple(view.message.message_id for view in active[:max_messages]),
        summary=summary,
    )


def _request_json(raw: str) -> str:
    """Read a request from an inline JSON string or stdin marker."""

    return sys.stdin.read() if raw == "-" else raw


def _is_current_native_session(session_id: str) -> bool:
    """Return whether ambient client identity exactly matches one canonical ID."""

    return any(
        coordination_claims.resolve_session_id(agent) == session_id
        for agent in coordination_claims.SESSION_ENV_KEYS
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the agent-drivable JSON request CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Override canonical mailbox root.")
    parser.add_argument("--claims-dir", type=Path, help="Override canonical claims registry.")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for operation in ("send", "poll", "status", "acknowledge"):
        command = subparsers.add_parser(operation)
        command.add_argument(
            "--request-json",
            default="-",
            help="Strict request JSON, or '-' to read one object from stdin.",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute one typed mailbox operation and print a strict JSON result."""

    args = build_parser().parse_args(argv)
    claims_dir = (args.claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve()
    store = CoordinationMessageStore(root=args.root or default_message_root(claims_dir), claims_dir=claims_dir)
    raw = _request_json(args.request_json)
    try:
        if args.operation == "send":
            send_request = SendMessageRequest.model_validate_json(raw)
            result: BaseModel = store.send(
                send_request,
                require_live_claim=not _is_current_native_session(send_request.caller_session_id),
            )
        elif args.operation == "poll":
            poll_request = PollMessagesRequest.model_validate_json(raw)
            result = store.poll(
                poll_request,
                require_live_claim=not _is_current_native_session(poll_request.current_session_id),
            )
        elif args.operation == "status":
            result = store.status(MessageStatusRequest.model_validate_json(raw))
        else:
            acknowledge_request = AcknowledgeMessageRequest.model_validate_json(raw)
            result = store.acknowledge(
                acknowledge_request,
                require_live_claim=not _is_current_native_session(
                    acknowledge_request.current_session_id
                ),
            )
    except (ValidationError, CoordinationMessageError, ValueError) as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__, "error": str(exc)}, sort_keys=True))
        return 2
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
