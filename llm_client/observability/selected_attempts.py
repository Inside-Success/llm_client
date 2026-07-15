"""Strict typed reads of selected native structured-output attempts.

The reader joins the runtime's terminal call row to its complete attempt
lifecycle. It is provider-free and fails rather than guessing when persistence
is absent, incomplete, ambiguous, or contradictory.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

import llm_client.io_log as _io_log
from llm_client.observability.replay import _ReplaySnapshotV3, snapshot_fingerprint
from llm_client.observability.raw_artifacts import (
    StructuredRawArtifactError,
    read_structured_raw_artifact,
)
from llm_client.observability.structured_attempts import (
    StructuredAttemptEvent,
    get_structured_attempt_events,
)


class SelectedAttemptReceiptError(ValueError):
    """Persisted call and attempt evidence cannot identify one exact selection."""


class RuntimeSelectedAttemptReceipt(BaseModel):
    """One trusted-process receipt for a runtime-selected native-schema attempt.

    The digest is an integrity fingerprint over persisted runtime evidence, not
    independent provider attestation, source authentication, a signature, or a
    hostile-process security boundary.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: int = Field(description="SQLite identity of the terminal call row.")
    logical_call_id: str = Field(
        description="Identity shared by the public call and every attempt event."
    )
    trace_id: str = Field(description="Caller trace identity verified across stores.")
    task: str = Field(description="Caller task label verified across stores.")
    requested_model: str = Field(
        description="Model requested in the fingerprint-verified call snapshot."
    )
    resolved_model: str = Field(
        description="Model used by the selected validated attempt."
    )
    selected_attempt_ordinal: int = Field(
        ge=0, description="Zero-based ordinal of the sole validated attempt."
    )
    schema_hash: str = Field(
        description="Schema hash shared by the selected event and terminal row."
    )
    raw_sha256: str = Field(
        min_length=64,
        max_length=64,
        description="SHA-256 of the selected attempt's raw provider content.",
    )
    raw_artifact_ref: str | None = Field(
        default=None,
        description="Optional durable reference to selected raw provider content.",
    )
    call_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        description="Verified v3 call-snapshot fingerprint.",
    )
    lineage: tuple[StructuredAttemptEvent, ...] = Field(
        description="Complete ordered lifecycle, including failed attempts."
    )
    receipt_digest: str = Field(
        min_length=64,
        max_length=64,
        description="Integrity digest over the normalized joined receipt evidence.",
    )


class RuntimeSelectedRawContent(BaseModel):
    """Exact selected structured bytes verified by trusted-process evidence.

    This is not provider attestation, a signature, or a semantic-correctness
    judgment. It proves only what the configured local runtime retained.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    logical_call_id: str = Field(description="Exact runtime-returned call identity.")
    selected_attempt_ordinal: int = Field(
        ge=0, description="Ordinal selected by the strict Plan 101 receipt."
    )
    raw_content: str = Field(description="Exact retained provider content decoded as UTF-8.")
    raw_sha256: str = Field(
        min_length=64,
        max_length=64,
        description="SHA-256 verified against both reference and retained bytes.",
    )
    raw_artifact_ref: str = Field(
        description="Verified versioned reference beneath the configured private root."
    )
    selected_attempt_receipt_digest: str = Field(
        min_length=64,
        max_length=64,
        description="Digest of the Plan 101 selected-attempt receipt used for this join.",
    )


def _fail(logical_call_id: str, detail: str) -> SelectedAttemptReceiptError:
    """Build one contextual fail-loud integrity error."""

    return SelectedAttemptReceiptError(f"Logical call {logical_call_id}: {detail}")


def _require_text(
    row: dict[str, Any], key: str, logical_call_id: str
) -> str:
    """Read one required nonblank terminal-row string."""

    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _fail(logical_call_id, f"terminal row is missing {key}.")
    return value


def _validate_history(
    logical_call_id: str,
    events: list[StructuredAttemptEvent],
) -> tuple[StructuredAttemptEvent, StructuredAttemptEvent]:
    """Validate the complete lifecycle and return selected receive/validation."""

    if not events:
        raise _fail(logical_call_id, "attempt lifecycle is absent.")
    validated = [event for event in events if event.event_type == "validated"]
    if len(validated) != 1:
        raise _fail(
            logical_call_id,
            f"expected exactly one validated attempt; found {len(validated)}.",
        )
    selected = validated[0]
    ordinals = [event.attempt_ordinal for event in events]
    if ordinals != sorted(ordinals):
        raise _fail(logical_call_id, "attempt ordinals are interleaved or decreasing.")
    distinct_ordinals = sorted(set(ordinals))
    if distinct_ordinals != list(range(selected.attempt_ordinal + 1)):
        raise _fail(logical_call_id, "attempt ordinals are non-contiguous.")
    if events[-1] != selected:
        raise _fail(logical_call_id, "events exist after the selected validation.")

    selected_events = [
        event for event in events if event.attempt_ordinal == selected.attempt_ordinal
    ]
    if [event.event_type for event in selected_events] != [
        "started",
        "received",
        "validated",
    ]:
        raise _fail(
            logical_call_id,
            "selected lifecycle must be started -> received -> validated.",
        )
    received = selected_events[1]
    if received.raw_sha256 is None or re.fullmatch(
        r"[0-9a-f]{64}", received.raw_sha256
    ) is None:
        raise _fail(logical_call_id, "selected received event lacks a SHA-256 hash.")

    for ordinal in range(selected.attempt_ordinal):
        attempt = [event for event in events if event.attempt_ordinal == ordinal]
        event_types = [event.event_type for event in attempt]
        valid_failure_shapes = (
            ["started", "received", "validation_failed", "recovery_decided"],
            ["started", "execution_failed", "recovery_decided"],
        )
        if event_types not in valid_failure_shapes:
            raise _fail(
                logical_call_id,
                f"attempt {ordinal} has incomplete failure/recovery lifecycle.",
            )
        attempt_models = {event.model for event in attempt}
        if len(attempt_models) != 1:
            raise _fail(
                logical_call_id,
                f"attempt {ordinal} contains inconsistent model identity.",
            )
        next_attempt = [
            event for event in events if event.attempt_ordinal == ordinal + 1
        ]
        current_model = attempt[0].model
        next_model = next_attempt[0].model
        recovery = attempt[-1].recovery_decision
        if recovery == "retry" and next_model != current_model:
            raise _fail(logical_call_id, f"attempt {ordinal} retry changed model.")
        if recovery == "fallback" and next_model == current_model:
            raise _fail(logical_call_id, f"attempt {ordinal} fallback kept the same model.")
        if recovery == "exhausted":
            raise _fail(
                logical_call_id,
                f"attempt {ordinal} is exhausted but a later success exists.",
            )
    selected_models = {event.model for event in selected_events}
    if len(selected_models) != 1:
        raise _fail(logical_call_id, "selected attempt contains inconsistent model identity.")
    return received, selected


def _receipt_digest(payload: dict[str, Any]) -> str:
    """Hash normalized joined evidence without implying a signature."""

    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def get_runtime_selected_attempt_receipt(
    logical_call_id: str,
) -> RuntimeSelectedAttemptReceipt:
    """Return the sole exact selected attempt for one logical structured call.

    The function performs no model call. It rejects unsupported runtime paths
    and every incomplete or ambiguous join instead of choosing by row order.
    """

    if not logical_call_id.strip():
        raise SelectedAttemptReceiptError("logical_call_id must be nonblank.")
    try:
        rows = _io_log.read_structured_terminal_calls(logical_call_id)
    except ValueError as error:
        raise _fail(logical_call_id, str(error)) from error
    if not rows:
        raise _fail(logical_call_id, "terminal call row is absent.")
    if len(rows) != 1:
        raise _fail(
            logical_call_id,
            f"expected exactly one terminal call row; found {len(rows)}.",
        )
    row = rows[0]
    if row.get("error") is not None:
        raise _fail(logical_call_id, "terminal call row is not successful.")
    if row.get("caller") not in {"call_llm_structured", "acall_llm_structured"}:
        raise _fail(logical_call_id, "terminal row is not a structured public call.")
    if row.get("execution_path") != "native_schema":
        raise _fail(logical_call_id, "terminal execution_path is not native_schema.")
    if row.get("response_format_type") != "json_schema":
        raise _fail(logical_call_id, "terminal response format is not json_schema.")

    trace_id = _require_text(row, "trace_id", logical_call_id)
    task = _require_text(row, "task", logical_call_id)
    resolved_model = _require_text(row, "model", logical_call_id)
    schema_hash = _require_text(row, "schema_hash", logical_call_id)
    stored_fingerprint = _require_text(row, "call_fingerprint", logical_call_id)
    snapshot = row.get("call_snapshot")
    if not isinstance(snapshot, dict):
        raise _fail(logical_call_id, "terminal row lacks a structured call snapshot.")
    try:
        validated_snapshot = _ReplaySnapshotV3.model_validate(snapshot)
    except ValidationError as error:
        raise _fail(logical_call_id, "terminal call snapshot is not valid v3.") from error
    if validated_snapshot.call_kind != "structured":
        raise _fail(logical_call_id, "terminal call snapshot is not structured.")
    if validated_snapshot.public_api != row.get("caller"):
        raise _fail(logical_call_id, "snapshot public API does not match terminal caller.")
    try:
        recomputed_fingerprint = snapshot_fingerprint(snapshot)
    except (TypeError, ValueError) as error:
        raise _fail(logical_call_id, "terminal call snapshot is malformed.") from error
    if recomputed_fingerprint != stored_fingerprint:
        raise _fail(logical_call_id, "call snapshot fingerprint mismatch.")
    requested_model = validated_snapshot.request.requested_model

    events = get_structured_attempt_events(logical_call_id)
    received, selected = _validate_history(logical_call_id, events)
    for event in events:
        if event.logical_call_id != logical_call_id:
            raise _fail(logical_call_id, "event logical-call identity mismatch.")
        if event.trace_id != trace_id:
            raise _fail(logical_call_id, "event trace identity mismatch.")
        if event.task != task:
            raise _fail(logical_call_id, "event task identity mismatch.")
        if event.schema_hash != schema_hash:
            raise _fail(logical_call_id, "event schema identity mismatch.")
    if selected.model != resolved_model:
        raise _fail(logical_call_id, "selected model does not match terminal model.")
    if received.model != selected.model or received.schema_hash != selected.schema_hash:
        raise _fail(logical_call_id, "selected received evidence identity mismatch.")

    evidence = {
        "call_id": row["call_id"],
        "logical_call_id": logical_call_id,
        "trace_id": trace_id,
        "task": task,
        "requested_model": requested_model,
        "resolved_model": resolved_model,
        "selected_attempt_ordinal": selected.attempt_ordinal,
        "schema_hash": schema_hash,
        "raw_sha256": received.raw_sha256,
        "raw_artifact_ref": received.raw_artifact_ref,
        "call_fingerprint": stored_fingerprint,
        "lineage": [event.model_dump(mode="json") for event in events],
    }
    return RuntimeSelectedAttemptReceipt.model_validate(
        {**evidence, "receipt_digest": _receipt_digest(evidence)}
    )


def get_runtime_selected_raw_content(
    logical_call_id: str,
) -> RuntimeSelectedRawContent:
    """Return exact retained bytes for the strict selected native-schema attempt."""

    receipt = get_runtime_selected_attempt_receipt(logical_call_id)
    if receipt.raw_artifact_ref is None:
        raise StructuredRawArtifactError(
            f"Logical call {logical_call_id}: selected attempt has no raw artifact reference."
        )
    raw_bytes = read_structured_raw_artifact(
        artifact_ref=receipt.raw_artifact_ref,
        logical_call_id=receipt.logical_call_id,
        attempt_ordinal=receipt.selected_attempt_ordinal,
        expected_sha256=receipt.raw_sha256,
    )
    try:
        raw_content = raw_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise StructuredRawArtifactError(
            f"Logical call {logical_call_id}: selected raw artifact is not valid UTF-8."
        ) from error
    return RuntimeSelectedRawContent(
        logical_call_id=receipt.logical_call_id,
        selected_attempt_ordinal=receipt.selected_attempt_ordinal,
        raw_content=raw_content,
        raw_sha256=receipt.raw_sha256,
        raw_artifact_ref=receipt.raw_artifact_ref,
        selected_attempt_receipt_digest=receipt.receipt_digest,
    )


def diagnose_runtime_selected_attempt_receipt_for_trace(
    trace_id: str,
) -> RuntimeSelectedAttemptReceipt:
    """Diagnose a trace only when it maps to exactly one logical call.

    Trusted consumers must pin the ``logical_call_id`` returned on the actual
    ``LLMCallResult`` and call ``get_runtime_selected_attempt_receipt``.
    """

    if not trace_id.strip():
        raise SelectedAttemptReceiptError("trace_id must be nonblank.")
    logical_call_ids = _io_log.read_structured_attempt_call_ids(trace_id)
    if len(logical_call_ids) != 1:
        raise SelectedAttemptReceiptError(
            f"Trace {trace_id}: expected exactly one logical call; "
            f"found {len(logical_call_ids)}."
        )
    return get_runtime_selected_attempt_receipt(logical_call_ids[0])
