"""Provider-free contract tests for authoritative selected-attempt reads."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from llm_client import io_log
from llm_client import call_llm_structured
from llm_client.core.data_types import LLMCallResult
from llm_client.observability.replay import build_call_snapshot, snapshot_fingerprint
from llm_client.observability.selected_attempts import (
    SelectedAttemptIntegrityError,
    get_authoritative_selected_attempt,
    get_authoritative_selected_attempt_for_trace,
)
from llm_client.observability.structured_attempts import (
    StructuredAttemptEvent,
    record_structured_attempt_event,
)


class _Decision(BaseModel):
    """Minimal structured result used to build a real v3 snapshot."""

    action: str


@pytest.fixture(autouse=True)
def _isolated_observability(tmp_path: Path) -> Generator[None, None, None]:
    """Use the real SQLite writers against one temporary database."""

    old = (
        io_log._enabled,
        io_log._data_root,
        io_log._project,
        io_log._db_path,
        io_log._db_conn,
    )
    io_log._enabled = True
    io_log._data_root = tmp_path
    io_log._project = "selected-attempt-test"
    io_log._db_path = tmp_path / "attempts.db"
    io_log._db_conn = None
    yield
    if io_log._db_conn is not None:
        io_log._db_conn.close()
    (
        io_log._enabled,
        io_log._data_root,
        io_log._project,
        io_log._db_path,
        io_log._db_conn,
    ) = old


def _snapshot(
    *, requested_model: str = "openrouter/requested", fallback_models: list[str] | None = None
) -> dict[str, Any]:
    """Build a production-shaped structured v3 snapshot without a provider call."""

    return build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model=requested_model,
        messages=[{"role": "user", "content": "Choose"}],
        prompt_ref=None,
        max_budget=0,
        timeout=60,
        num_retries=2,
        reasoning_effort=None,
        api_base=None,
        base_delay=1,
        max_delay=30,
        retry_on=None,
        fallback_models=fallback_models,
        public_kwargs={},
        structured_output_mode="require_native_json_schema",
        response_model=_Decision,
    )


def _event(
    event_type: str,
    *,
    ordinal: int = 0,
    model: str = "openrouter/requested",
    logical_call_id: str = "logical-1",
    trace_id: str = "trace-1",
    task: str = "semantic-map",
    schema_hash: str = "schema-1",
    raw_sha256: str | None = None,
    recovery_decision: str | None = None,
    failure_class: str | None = None,
    execution_error_type: str | None = None,
) -> StructuredAttemptEvent:
    """Build one typed lifecycle event with stable fixture identity."""

    return StructuredAttemptEvent.model_validate(
        {
            "logical_call_id": logical_call_id,
            "trace_id": trace_id,
            "task": task,
            "attempt_ordinal": ordinal,
            "model": model,
            "execution_path": "native_schema",
            "schema_hash": schema_hash,
            "event_type": event_type,
            "raw_sha256": raw_sha256,
            "recovery_decision": recovery_decision,
            "failure_class": failure_class,
            "execution_error_type": execution_error_type,
        }
    )


def _record_success_events(
    *, ordinal: int = 0, model: str = "openrouter/requested"
) -> None:
    """Persist one complete selected attempt."""

    record_structured_attempt_event(_event("started", ordinal=ordinal, model=model))
    record_structured_attempt_event(
        _event("received", ordinal=ordinal, model=model, raw_sha256="a" * 64)
    )
    record_structured_attempt_event(_event("validated", ordinal=ordinal, model=model))


def _record_terminal(
    *,
    model: str = "openrouter/requested",
    logical_call_id: str = "logical-1",
    trace_id: str = "trace-1",
    task: str = "semantic-map",
    schema_hash: str = "schema-1",
    snapshot: dict[str, object] | None = None,
    error: Exception | None = None,
    execution_path: str = "native_schema",
    response_format_type: str = "json_schema",
) -> None:
    """Persist one production-shaped terminal call row through the real writer."""

    captured = snapshot or _snapshot()
    result = None if error else LLMCallResult(
        content='{"action":"accept"}',
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        cost=0,
        model=model,
        resolved_model=model,
    )
    io_log.log_call(
        model=model,
        messages=[{"role": "user", "content": "Choose"}],
        result=result,
        error=error,
        caller="call_llm_structured",
        task=task,
        trace_id=trace_id,
        call_snapshot=captured,
        call_fingerprint=snapshot_fingerprint(captured),
        execution_path=execution_path,
        schema_hash=schema_hash,
        response_format_type=response_format_type,
        logical_call_id=logical_call_id,
    )


def test_reads_exact_selected_attempt_and_complete_lineage() -> None:
    """One joined terminal lifecycle yields a typed evidence-bearing receipt."""

    _record_success_events()
    _record_terminal()

    receipt = get_authoritative_selected_attempt("logical-1")

    assert receipt.requested_model == "openrouter/requested"
    assert receipt.resolved_model == "openrouter/requested"
    assert receipt.selected_attempt_ordinal == 0
    assert receipt.raw_sha256 == "a" * 64
    assert [event.event_type for event in receipt.lineage] == [
        "started",
        "received",
        "validated",
    ]
    assert len(receipt.authority_digest) == 64
    assert get_authoritative_selected_attempt_for_trace("trace-1") == receipt


# mock-ok: provider transport is controlled; the public runtime, lifecycle, and real SQLite join are under test.
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.completion")
def test_public_runtime_produces_readable_selected_receipt(
    mock_completion: MagicMock,
    _mock_cost: MagicMock,
) -> None:
    """The actual public structured runtime persists both halves of the join."""

    response = MagicMock()
    choice = MagicMock()
    choice.message.content = '{"action":"accept"}'
    choice.finish_reason = "stop"
    response.choices = [choice]
    response.usage.prompt_tokens = 1
    response.usage.completion_tokens = 1
    response.usage.total_tokens = 2
    mock_completion.return_value = response

    parsed, _result = call_llm_structured(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "Choose"}],
        response_model=_Decision,
        task="semantic-map",
        trace_id="trace-runtime",
        max_budget=0,
        num_retries=0,
    )

    receipt = get_authoritative_selected_attempt_for_trace("trace-runtime")
    assert parsed.action == "accept"
    assert receipt.requested_model == "deepseek/deepseek-chat"
    assert receipt.resolved_model == "openrouter/deepseek/deepseek-chat"
    assert receipt.selected_attempt_ordinal == 0
    assert receipt.raw_sha256 == "627da2fea5adc2f0ef2aa36b76829fee34e563859a9e3472a2e5522904495b35"


def test_retry_and_fallback_lineage_selects_only_validated_attempt() -> None:
    """Failed source-model evidence remains visible beside the fallback selection."""

    record_structured_attempt_event(_event("started"))
    record_structured_attempt_event(
        _event("received", raw_sha256="b" * 64)
    )
    record_structured_attempt_event(
        _event("validation_failed", failure_class="schema_validation")
    )
    record_structured_attempt_event(
        _event("recovery_decided", recovery_decision="fallback")
    )
    _record_success_events(ordinal=1, model="openrouter/fallback")
    _record_terminal(
        model="openrouter/fallback",
        snapshot=_snapshot(fallback_models=["openrouter/fallback"]),
    )

    receipt = get_authoritative_selected_attempt("logical-1")

    assert receipt.requested_model == "openrouter/requested"
    assert receipt.resolved_model == "openrouter/fallback"
    assert receipt.selected_attempt_ordinal == 1
    assert receipt.raw_sha256 == "a" * 64
    assert len(receipt.lineage) == 7
    assert receipt.lineage[3].recovery_decision == "fallback"


def test_public_events_without_terminal_row_have_no_authority() -> None:
    """Caller-writable lifecycle events alone cannot become a selected receipt."""

    _record_success_events()

    with pytest.raises(SelectedAttemptIntegrityError, match="terminal call row"):
        get_authoritative_selected_attempt("logical-1")


@pytest.mark.parametrize("missing", ["events", "validated", "received"])
def test_incomplete_lifecycle_rejects(missing: str) -> None:
    """Neither a terminal-only nor a partial lifecycle is projected as success."""

    if missing != "events":
        record_structured_attempt_event(_event("started"))
        if missing != "received":
            record_structured_attempt_event(
                _event("received", raw_sha256="a" * 64)
            )
        if missing != "validated":
            record_structured_attempt_event(_event("validated"))
    _record_terminal()

    with pytest.raises(SelectedAttemptIntegrityError):
        get_authoritative_selected_attempt("logical-1")


def test_duplicate_terminal_rows_and_validations_reject() -> None:
    """Ambiguous terminal state is never resolved by row order."""

    _record_success_events()
    _record_terminal()
    _record_terminal()
    with pytest.raises(SelectedAttemptIntegrityError, match="exactly one terminal"):
        get_authoritative_selected_attempt("logical-1")

    io_log._get_db().execute("DELETE FROM llm_calls")
    io_log._get_db().commit()
    _record_terminal()
    record_structured_attempt_event(_event("validated", ordinal=1))
    with pytest.raises(SelectedAttemptIntegrityError, match="exactly one validated"):
        get_authoritative_selected_attempt("logical-1")


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("trace_id", "other-trace", "trace"),
        ("task", "other-task", "task"),
        ("model", "other-model", "model"),
        ("schema_hash", "other-schema", "schema"),
    ],
)
def test_cross_record_identity_mismatch_rejects(
    column: str, value: str, message: str
) -> None:
    """The terminal row must describe the selected lifecycle exactly."""

    _record_success_events()
    _record_terminal()
    io_log._get_db().execute(
        f"UPDATE llm_calls SET {column} = ? WHERE logical_call_id = ?",  # noqa: S608 - fixed test-only column parameter
        (value, "logical-1"),
    )
    io_log._get_db().commit()

    with pytest.raises(SelectedAttemptIntegrityError, match=message):
        get_authoritative_selected_attempt("logical-1")


@pytest.mark.parametrize(
    ("terminal_updates", "message"),
    [
        ({"error": RuntimeError("failed")}, "successful"),
        ({"execution_path": "instructor"}, "native_schema"),
        ({"response_format_type": "instructor"}, "json_schema"),
    ],
)
def test_noneligible_terminal_row_rejects(
    terminal_updates: dict[str, object], message: str
) -> None:
    """Only successful native JSON-schema calls have lossless receipt evidence."""

    _record_success_events()
    _record_terminal(**terminal_updates)  # type: ignore[arg-type]

    with pytest.raises(SelectedAttemptIntegrityError, match=message):
        get_authoritative_selected_attempt("logical-1")


def test_tampered_snapshot_or_fingerprint_rejects() -> None:
    """Requested identity is accepted only from a fingerprint-verified v3 snapshot."""

    _record_success_events()
    _record_terminal()
    row = io_log._get_db().execute(
        "SELECT call_snapshot FROM llm_calls WHERE logical_call_id = ?",
        ("logical-1",),
    ).fetchone()
    assert row is not None
    tampered = row[0].replace("openrouter/requested", "openrouter/tampered")
    io_log._get_db().execute(
        "UPDATE llm_calls SET call_snapshot = ? WHERE logical_call_id = ?",
        (tampered, "logical-1"),
    )
    io_log._get_db().commit()

    with pytest.raises(SelectedAttemptIntegrityError, match="fingerprint"):
        get_authoritative_selected_attempt("logical-1")


def test_matching_fingerprint_does_not_legitimize_malformed_v3_snapshot() -> None:
    """Receipt identity requires the full closed v3 contract, not a hash alone."""

    _record_success_events()
    malformed = _snapshot()
    del malformed["replay"]
    _record_terminal(snapshot=malformed)

    with pytest.raises(SelectedAttemptIntegrityError, match="valid v3"):
        get_authoritative_selected_attempt("logical-1")


def test_nonhex_raw_digest_rejects() -> None:
    """A length-shaped value cannot masquerade as selected raw-content SHA-256."""

    record_structured_attempt_event(_event("started"))
    record_structured_attempt_event(_event("received", raw_sha256="z" * 64))
    record_structured_attempt_event(_event("validated"))
    _record_terminal()

    with pytest.raises(SelectedAttemptIntegrityError, match="SHA-256"):
        get_authoritative_selected_attempt("logical-1")


def test_trace_helper_rejects_zero_or_multiple_logical_calls() -> None:
    """Trace lookup never chooses among multiple structured public calls."""

    with pytest.raises(SelectedAttemptIntegrityError, match="exactly one logical call"):
        get_authoritative_selected_attempt_for_trace("trace-1")

    _record_success_events()
    _record_terminal()
    for event_type in ("started", "received", "validated"):
        record_structured_attempt_event(
            _event(
                event_type,
                logical_call_id="logical-2",
                raw_sha256="c" * 64 if event_type == "received" else None,
            )
        )
    _record_terminal(logical_call_id="logical-2")

    with pytest.raises(SelectedAttemptIntegrityError, match="exactly one logical call"):
        get_authoritative_selected_attempt_for_trace("trace-1")
