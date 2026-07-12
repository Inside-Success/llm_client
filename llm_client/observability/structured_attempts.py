"""Typed, metadata-first observability for structured-output attempts.

Each event is append-only so a successful retry cannot overwrite or conceal the
failed generation that preceded it. Raw response bodies remain outside this
metadata plane; the event carries a content hash and optional artifact reference.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

import llm_client.io_log as _io_log

AttemptEventType = Literal[
    "received", "validation_failed", "validated", "recovery_decided"
]
AttemptFailureClass = Literal["missing_required", "schema_validation"]
RecoveryDecision = Literal["retry", "exhausted"]


class StructuredValidationIssue(BaseModel):
    """One stable, bounded validation issue attached to an attempt event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    location: tuple[str | int, ...] = Field(
        description="Schema path whose value failed validation."
    )
    code: str = Field(
        description="Stable validator error code, such as `missing` or `string_type`."
    )
    message: str = Field(description="Bounded human-readable validation message.")


class StructuredAttemptEvent(BaseModel):
    """Append-only event describing one stage of one provider generation attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(
        default_factory=lambda: uuid4().hex, description="Unique event identity."
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC event timestamp.",
    )
    logical_call_id: str = Field(
        description="Stable identity shared by every attempt in one public call."
    )
    trace_id: str = Field(description="Caller trace identity.")
    task: str = Field(description="Caller task label.")
    attempt_ordinal: int = Field(
        ge=0, description="Zero-based generation attempt ordinal."
    )
    model: str = Field(description="Model used for this attempt.")
    execution_path: Literal["native_schema"] = Field(
        description="Structured runtime path."
    )
    schema_hash: str = Field(
        description="Hash of the JSON Schema sent to the provider."
    )
    event_type: AttemptEventType = Field(
        description="Lifecycle event for this attempt."
    )
    raw_sha256: str | None = Field(
        default=None, description="SHA-256 of raw content; body is not inlined."
    )
    raw_artifact_ref: str | None = Field(
        default=None, description="Optional durable raw-content artifact reference."
    )
    failure_class: AttemptFailureClass | None = Field(
        default=None, description="Typed failure family."
    )
    validation_issues: tuple[StructuredValidationIssue, ...] = Field(
        default=(), description="Typed validation issues."
    )
    recovery_decision: RecoveryDecision | None = Field(
        default=None, description="Retry policy decision."
    )

    @model_validator(mode="after")
    def _event_shape(self) -> "StructuredAttemptEvent":
        if self.event_type == "received" and self.raw_sha256 is None:
            raise ValueError("received event requires raw_sha256")
        if self.event_type == "validation_failed" and self.failure_class is None:
            raise ValueError("validation_failed event requires failure_class")
        if self.event_type == "recovery_decided" and self.recovery_decision is None:
            raise ValueError("recovery_decided event requires recovery_decision")
        if self.event_type != "validation_failed" and (
            self.failure_class or self.validation_issues
        ):
            raise ValueError(
                "failure details are only valid on validation_failed events"
            )
        if self.event_type != "recovery_decided" and self.recovery_decision is not None:
            raise ValueError(
                "recovery_decision is only valid on recovery_decided events"
            )
        return self


def record_structured_attempt_event(event: StructuredAttemptEvent) -> None:
    """Persist one event and propagate storage failures on this integrity seam."""

    _io_log.write_structured_attempt_event(event.model_dump(mode="json"))


def get_structured_attempt_events(logical_call_id: str) -> list[StructuredAttemptEvent]:
    """Return the complete ordered event history for one logical call."""

    return [
        StructuredAttemptEvent.model_validate(row)
        for row in _io_log.read_structured_attempt_events(logical_call_id)
    ]
