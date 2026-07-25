"""Tests for privacy-bounded per-attempt diagnostic persistence."""

from __future__ import annotations

import sqlite3
from uuid import uuid4

import pytest
from pydantic import ValidationError

from llm_client import io_log
from llm_client.observability.attempt_diagnostics import (
    AttemptDiagnosticEnvelope,
    exception_fingerprint,
    get_attempt_diagnosis,
    record_attempt_diagnostic,
)
from llm_client.observability.structured_attempts import (
    StructuredAttemptEvent,
    record_structured_attempt_event,
)


@pytest.fixture(autouse=True)
def _enable_observability() -> None:
    """This contract requires a real temporary SQLite write, not disabled logging."""

    previous = io_log._enabled
    io_log.configure(enabled=True)
    try:
        yield
    finally:
        io_log._enabled = previous


def _attempt() -> StructuredAttemptEvent:
    suffix = uuid4().hex
    event = StructuredAttemptEvent(
        logical_call_id=f"call-{suffix}",
        trace_id=f"trace-{suffix}",
        task="test.attempt_diagnostics",
        attempt_ordinal=0,
        model="openrouter/deepseek/deepseek-v4-flash",
        execution_path="native_schema",
        schema_hash="a" * 64,
        event_type="execution_failed",
        failure_class="timeout",
        execution_error_type="TimeoutError",
    )
    record_structured_attempt_event(event)
    return event


def _diagnostic(event: StructuredAttemptEvent, **overrides: object) -> AttemptDiagnosticEnvelope:
    values: dict[str, object] = {
        "attempt_event_id": event.event_id,
        "logical_call_id": event.logical_call_id,
        "trace_id": event.trace_id,
        "task": event.task,
        "attempt_ordinal": event.attempt_ordinal,
        "phase": "awaiting_response",
        "origin": "transport",
        "attribution": "client_observed_only",
        "exception_chain": ("APIConnectionError", "ConnectTimeout"),
        "exception_fingerprint": exception_fingerprint(("APIConnectionError", "ConnectTimeout")),
        "timeout_kind": "client_attempt_safety",
        "sanitized_summary": "client attempt safety deadline elapsed while awaiting response",
    }
    values.update(overrides)
    return AttemptDiagnosticEnvelope(**values)


def test_diagnostic_readback_binds_exact_structured_attempt() -> None:
    event = _attempt()
    diagnostic = _diagnostic(event)
    record_attempt_diagnostic(diagnostic)

    result = get_attempt_diagnosis(event.event_id)

    assert result.diagnostic_status == "available"
    assert result.logical_call_id == event.logical_call_id
    assert result.diagnostics == (diagnostic,)


def test_legacy_attempt_is_explicitly_unavailable() -> None:
    event = _attempt()

    result = get_attempt_diagnosis(event.event_id)

    assert result.diagnostic_status == "unavailable_legacy"
    assert result.diagnostics == ()


def test_diagnostic_rejects_secret_or_raw_prompt_content() -> None:
    event = _attempt()
    with pytest.raises(ValidationError, match="prohibited sensitive or raw content"):
        _diagnostic(event, sanitized_summary="Authorization: Bearer sk-secret-token")
    with pytest.raises(ValidationError, match="prohibited sensitive or raw content"):
        _diagnostic(event, sanitized_summary='{"role":"user","content":"source text"}')


def test_provider_confirmation_requires_typed_response_evidence() -> None:
    event = _attempt()
    with pytest.raises(ValidationError, match="requires typed response evidence"):
        _diagnostic(event, attribution="gateway_or_provider_confirmed")

    confirmed = _diagnostic(
        event,
        attribution="gateway_or_provider_confirmed",
        origin="gateway_or_provider_response",
        http_status=429,
        gateway_request_id="gw-123",
        retry_after_s=10.0,
    )
    record_attempt_diagnostic(confirmed)
    assert get_attempt_diagnosis(event.event_id).diagnostics == (confirmed,)


def test_writer_rejects_mismatched_attempt_identity() -> None:
    event = _attempt()
    diagnostic = _diagnostic(event, logical_call_id="wrong-call")

    with pytest.raises(ValueError, match="identity does not match"):
        record_attempt_diagnostic(diagnostic)


def test_writer_fails_loud_when_persistence_breaks(monkeypatch: pytest.MonkeyPatch) -> None:
    event = _attempt()

    def _boom(_write: object) -> None:
        raise RuntimeError("diagnostic write failed")

    monkeypatch.setattr(io_log, "_run_db_write", _boom)
    with pytest.raises(RuntimeError, match="diagnostic write failed"):
        record_attempt_diagnostic(_diagnostic(event))


def test_old_database_migrates_additive_diagnostic_table(tmp_path) -> None:
    """Databases before Plan 121 gain the new table without altering old rows."""

    old_db = tmp_path / "old-observability.db"
    previous_path, previous_conn = io_log._db_path, io_log._db_conn
    try:
        io_log._db_path = old_db
        io_log._db_conn = None
        io_log._get_db().close()
        io_log._db_conn = None
        with sqlite3.connect(old_db) as db:
            db.execute("DROP TABLE attempt_diagnostics")
        columns = {
            row[1]
            for row in io_log._get_db().execute("PRAGMA table_info(attempt_diagnostics)")
        }
    finally:
        if io_log._db_conn is not None:
            io_log._db_conn.close()
        io_log._db_path, io_log._db_conn = previous_path, previous_conn

    assert {"diagnostic_id", "attempt_event_id", "sanitized_summary"} <= columns
