"""Privacy-bounded diagnostic evidence for structured-output attempts."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import llm_client.io_log as _io_log
from llm_client.observability.structured_attempts import get_structured_attempt_histories

DiagnosticPhase = Literal[
    "pre_dispatch",
    "dispatching",
    "dispatched",
    "awaiting_response",
    "response_received",
    "parsing",
    "validated",
    "finalizing",
    "cancelled",
    "interrupted_or_abandoned",
]
DiagnosticOrigin = Literal[
    "pre_dispatch",
    "client_serialization",
    "transport",
    "gateway_or_provider_response",
    "response_parse",
    "client_finalization",
    "unknown",
]
Attribution = Literal[
    "client_confirmed",
    "gateway_or_provider_confirmed",
    "client_observed_only",
    "insufficient_observation",
]
TimeoutKind = Literal[
    "provider_request",
    "client_attempt_deadline",
    "client_attempt_safety",
    "client_logical_deadline",
    "whole_call",
    "background_polling",
    "unknown",
]
ResponseOutcome = Literal["empty_content"]

_UNSAFE_SUMMARY = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|api[_-]?key\s*[:=]|authorization\s*[:=]|"
    r"sk-[a-z0-9_-]{8,}|\"role\"\s*:\s*\"(?:system|user|assistant)\")"
)


class AttemptDiagnosticEnvelope(BaseModel):
    """Typed, sanitized evidence observed at one attempt boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    diagnostic_id: str = Field(default_factory=lambda: f"diag_{uuid4().hex}")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    attempt_event_id: str = Field(min_length=1)
    logical_call_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    task: str = Field(min_length=1)
    attempt_ordinal: int = Field(ge=0)
    phase: DiagnosticPhase
    origin: DiagnosticOrigin
    attribution: Attribution
    exception_chain: tuple[str, ...] = ()
    exception_fingerprint: str | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    provider_error_code: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9._:-]{1,128}$"
    )
    provider_request_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9._:-]{1,256}$"
    )
    gateway_request_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9._:-]{1,256}$"
    )
    retry_after_s: float | None = Field(default=None, ge=0)
    timeout_kind: TimeoutKind | None = None
    response_outcome: ResponseOutcome | None = None
    sanitized_summary: str | None = Field(default=None, max_length=500)
    redaction_version: Literal["v1"] = "v1"
    artifact_ref: str | None = Field(default=None, max_length=1024)
    artifact_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @field_validator("exception_chain")
    @classmethod
    def _validate_exception_chain(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > 8 or any(not item or len(item) > 128 for item in value):
            raise ValueError("exception_chain must contain at most eight bounded class names")
        return value

    @field_validator("sanitized_summary")
    @classmethod
    def _reject_unsafe_summary(cls, value: str | None) -> str | None:
        if value is not None and _UNSAFE_SUMMARY.search(value):
            raise ValueError("sanitized_summary contains prohibited sensitive or raw content")
        return value

    @model_validator(mode="after")
    def _validate_evidence_shape(self) -> "AttemptDiagnosticEnvelope":
        if self.attribution == "gateway_or_provider_confirmed" and (
            self.http_status is None
            and self.provider_error_code is None
            and self.provider_request_id is None
            and self.gateway_request_id is None
        ):
            raise ValueError("gateway/provider confirmation requires typed response evidence")
        if (self.artifact_ref is None) != (self.artifact_sha256 is None):
            raise ValueError("artifact_ref and artifact_sha256 must be supplied together")
        return self


class AttemptDiagnosis(BaseModel):
    """Read model joining one attempt event to its retained diagnostic evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_event_id: str
    logical_call_id: str
    attempt_ordinal: int
    diagnostic_status: Literal[
        "available",
        "not_applicable_success",
        "unavailable_no_diagnostic",
    ]
    diagnostics: tuple[AttemptDiagnosticEnvelope, ...]


class TraceAttemptDiagnosis(BaseModel):
    """All structured-attempt diagnoses retained for one trace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: str
    diagnoses: tuple[AttemptDiagnosis, ...]


def exception_fingerprint(exception_chain: tuple[str, ...]) -> str | None:
    """Return an opaque stable fingerprint without retaining exception prose."""

    if not exception_chain:
        return None
    return "sha256:" + hashlib.sha256("\n".join(exception_chain).encode()).hexdigest()


def record_attempt_diagnostic(envelope: AttemptDiagnosticEnvelope) -> None:
    """Persist one diagnostic and fail loud on an unbound or failed write."""

    _io_log.write_attempt_diagnostic(envelope.model_dump(mode="json"))


def get_attempt_diagnostics(attempt_event_id: str) -> list[AttemptDiagnosticEnvelope]:
    """Return ordered diagnostic evidence for exactly one attempt event."""

    return [
        AttemptDiagnosticEnvelope.model_validate(row)
        for row in _io_log.read_attempt_diagnostics(attempt_event_id)
    ]


def get_attempt_diagnosis(attempt_event_id: str) -> AttemptDiagnosis:
    """Return retained evidence or an explicit non-diagnostic status."""

    attempt = _io_log.read_structured_attempt_event(attempt_event_id)
    if attempt is None:
        raise ValueError(f"unknown structured attempt event: {attempt_event_id}")
    diagnostics = tuple(get_attempt_diagnostics(attempt_event_id))
    diagnostic_status: Literal[
        "available",
        "not_applicable_success",
        "unavailable_no_diagnostic",
    ]
    if diagnostics:
        diagnostic_status = "available"
    elif attempt["event_type"] in {"started", "received", "validated"}:
        # Failure diagnostics are intentionally absent for a completed attempt.
        diagnostic_status = "not_applicable_success"
    else:
        diagnostic_status = "unavailable_no_diagnostic"
    return AttemptDiagnosis(
        attempt_event_id=attempt_event_id,
        logical_call_id=str(attempt["logical_call_id"]),
        attempt_ordinal=int(attempt["attempt_ordinal"]),
        diagnostic_status=diagnostic_status,
        diagnostics=diagnostics,
    )


def get_trace_attempt_diagnosis(trace_id: str) -> TraceAttemptDiagnosis:
    """Return every structured-attempt diagnosis for one trace in event order."""

    if not trace_id:
        raise ValueError("trace_id must be non-empty")
    diagnoses = tuple(
        get_attempt_diagnosis(event.event_id)
        for events in get_structured_attempt_histories(trace_id).values()
        for event in events
    )
    return TraceAttemptDiagnosis(trace_id=trace_id, diagnoses=diagnoses)
