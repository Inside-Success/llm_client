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
    get_trace_attempt_diagnosis,
    record_attempt_diagnostic,
)
from llm_client.observability.structured_attempts import (
    StructuredAttemptEvent,
    get_structured_attempt_histories,
    record_structured_attempt_event,
)
from llm_client.execution.structured_runtime import _record_execution_failure


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


def test_failed_attempt_without_diagnostic_is_explicitly_unavailable() -> None:
    event = _attempt()

    result = get_attempt_diagnosis(event.event_id)

    assert result.diagnostic_status == "unavailable_no_diagnostic"
    assert result.diagnostics == ()


def test_successful_attempt_is_not_mislabeled_as_legacy() -> None:
    suffix = uuid4().hex
    event = StructuredAttemptEvent(
        logical_call_id=f"success-{suffix}",
        trace_id=f"success-trace-{suffix}",
        task="test.attempt_diagnostics.success",
        attempt_ordinal=0,
        model="openrouter/deepseek/deepseek-v4-flash",
        execution_path="native_schema",
        schema_hash="s" * 64,
        event_type="validated",
    )
    record_structured_attempt_event(event)

    result = get_attempt_diagnosis(event.event_id)

    assert result.diagnostic_status == "not_applicable_success"
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


def test_runtime_records_confirmed_gateway_response_diagnostic() -> None:
    class GatewayError(Exception):
        status_code = 429
        code = "rate_limit"
        retry_after = 4

        class response:
            status_code = 429
            headers = {
                "x-request-id": "gw-request-123",
                "x-provider-request-id": "provider-request-456",
            }

    trace_id = f"runtime-gateway-trace-{uuid4().hex}"
    _record_execution_failure(
        error=GatewayError(), logical_call_id="runtime-gateway-call",
        trace_id=trace_id, task="test.runtime_gateway",
        attempt=0, model="openrouter/deepseek/deepseek-v4-flash", schema_hash="b" * 64,
    )
    event = next(iter(get_structured_attempt_histories(trace_id).values()))[0]
    diagnostic = get_attempt_diagnosis(event.event_id).diagnostics[0]
    assert diagnostic.attribution == "gateway_or_provider_confirmed"
    assert diagnostic.http_status == 429
    assert diagnostic.gateway_request_id == "gw-request-123"
    assert diagnostic.provider_request_id == "provider-request-456"
    assert diagnostic.provider_error_code == "rate_limit"
    assert diagnostic.retry_after_s == 4


def test_runtime_timeout_without_response_does_not_blame_provider() -> None:
    trace_id = f"runtime-timeout-trace-{uuid4().hex}"
    _record_execution_failure(
        error=TimeoutError("client attempt safety deadline elapsed"),
        logical_call_id="runtime-timeout-call", trace_id=trace_id,
        task="test.runtime_timeout", attempt=0,
        model="openrouter/deepseek/deepseek-v4-flash", schema_hash="c" * 64,
    )
    event = next(iter(get_structured_attempt_histories(trace_id).values()))[0]
    diagnostic = get_attempt_diagnosis(event.event_id).diagnostics[0]
    assert diagnostic.attribution == "client_observed_only"
    assert diagnostic.timeout_kind == "client_attempt_safety"


def test_runtime_client_attempt_deadline_is_classified() -> None:
    trace_id = f"runtime-client-deadline-trace-{uuid4().hex}"
    _record_execution_failure(
        error=TimeoutError("structured provider attempt exceeded 300s client deadline"),
        logical_call_id="runtime-client-deadline-call", trace_id=trace_id,
        task="test.runtime_client_deadline", attempt=0,
        model="openrouter/deepseek/deepseek-v4-flash", schema_hash="e" * 64,
    )
    event = next(iter(get_structured_attempt_histories(trace_id).values()))[0]
    diagnostic = get_attempt_diagnosis(event.event_id).diagnostics[0]
    assert diagnostic.attribution == "client_observed_only"
    assert diagnostic.timeout_kind == "client_attempt_deadline"


def test_runtime_unknown_timeout_remains_unknown() -> None:
    trace_id = f"runtime-unknown-timeout-trace-{uuid4().hex}"
    _record_execution_failure(
        error=TimeoutError("upstream deadline elapsed"),
        logical_call_id="runtime-unknown-timeout-call", trace_id=trace_id,
        task="test.runtime_unknown_timeout", attempt=0,
        model="openrouter/deepseek/deepseek-v4-flash", schema_hash="f" * 64,
    )
    event = next(iter(get_structured_attempt_histories(trace_id).values()))[0]
    diagnostic = get_attempt_diagnosis(event.event_id).diagnostics[0]
    assert diagnostic.timeout_kind == "unknown"


def test_trace_query_returns_all_attempt_statuses() -> None:
    event = _attempt()
    record_attempt_diagnostic(_diagnostic(event))

    result = get_trace_attempt_diagnosis(event.trace_id)

    assert result.trace_id == event.trace_id
    assert [(diagnosis.attempt_event_id, diagnosis.diagnostic_status) for diagnosis in result.diagnoses] == [
        (event.event_id, "available")
    ]


def test_trace_query_does_not_leak_reused_logical_call_id() -> None:
    first_trace, second_trace = f"trace-a-{uuid4().hex}", f"trace-b-{uuid4().hex}"
    first = StructuredAttemptEvent(
        logical_call_id="reused-logical-call", trace_id=first_trace,
        task="test.trace_isolation", attempt_ordinal=0,
        model="openrouter/deepseek/deepseek-v4-flash", execution_path="native_schema",
        schema_hash="d" * 64, event_type="execution_failed", failure_class="timeout",
        execution_error_type="TimeoutError",
    )
    second = first.model_copy(update={"event_id": uuid4().hex, "trace_id": second_trace})
    record_structured_attempt_event(first)
    record_structured_attempt_event(second)

    result = get_trace_attempt_diagnosis(second_trace)

    assert [diagnosis.attempt_event_id for diagnosis in result.diagnoses] == [second.event_id]
