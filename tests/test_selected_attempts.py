"""Provider-free contract tests for trusted-process selected-attempt receipts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from llm_client import io_log
from llm_client import acall_llm_structured
from llm_client import call_llm_structured
from llm_client.core.data_types import LLMCallResult
from llm_client.observability.replay import build_call_snapshot, snapshot_fingerprint
from llm_client.observability.selected_attempts import (
    SelectedAttemptReceiptError,
    get_runtime_selected_attempt_receipt,
    diagnose_runtime_selected_attempt_receipt_for_trace,
)
from llm_client.observability.structured_attempts import (
    StructuredAttemptEvent,
    record_structured_attempt_event,
)


class _Decision(BaseModel):
    """Minimal structured result used to build a real v3 snapshot."""

    action: str


def _native_response(content: str) -> MagicMock:
    """Build one provider-shaped response for the real structured runtime."""

    response = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = "stop"
    response.choices = [choice]
    response.usage.prompt_tokens = 1
    response.usage.completion_tokens = 1
    response.usage.total_tokens = 2
    return response


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
    execution_path: str = "native_schema",
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
            "execution_path": execution_path,
            "schema_hash": schema_hash,
            "event_type": event_type,
            "raw_sha256": raw_sha256,
            "recovery_decision": recovery_decision,
            "failure_class": failure_class,
            "execution_error_type": execution_error_type,
        }
    )


def _record_success_events(
    *,
    ordinal: int = 0,
    model: str = "openrouter/requested",
    execution_path: str = "native_schema",
) -> None:
    """Persist one complete selected attempt."""

    record_structured_attempt_event(
        _event(
            "started",
            ordinal=ordinal,
            model=model,
            execution_path=execution_path,
        )
    )
    record_structured_attempt_event(
        _event(
            "received",
            ordinal=ordinal,
            model=model,
            execution_path=execution_path,
            raw_sha256="a" * 64,
        )
    )
    record_structured_attempt_event(
        _event(
            "validated",
            ordinal=ordinal,
            model=model,
            execution_path=execution_path,
        )
    )


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

    receipt = get_runtime_selected_attempt_receipt("logical-1")

    assert receipt.requested_model == "openrouter/requested"
    assert receipt.resolved_model == "openrouter/requested"
    assert receipt.selected_attempt_ordinal == 0
    assert receipt.raw_sha256 == "a" * 64
    assert [event.event_type for event in receipt.lineage] == [
        "started",
        "received",
        "validated",
    ]
    assert len(receipt.receipt_digest) == 64
    assert diagnose_runtime_selected_attempt_receipt_for_trace("trace-1") == receipt


def test_reads_responses_attempt_when_terminal_path_agrees() -> None:
    """Responses custody is eligible only under its matching terminal contract."""

    _record_success_events(execution_path="responses_api")
    _record_terminal(
        execution_path="responses_api",
        response_format_type="responses_api",
    )

    receipt = get_runtime_selected_attempt_receipt("logical-1")

    assert all(event.execution_path == "responses_api" for event in receipt.lineage)


# mock-ok: provider transport is controlled; the public runtime, lifecycle, and real SQLite join are under test.
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.completion")
def test_public_runtime_produces_readable_selected_receipt(
    mock_completion: MagicMock,
    _mock_cost: MagicMock,
) -> None:
    """The actual public structured runtime persists both halves of the join."""

    mock_completion.return_value = _native_response('{"action":"accept"}')

    parsed, _result = call_llm_structured(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "Choose"}],
        response_model=_Decision,
        task="semantic-map",
        trace_id="trace-runtime",
        max_budget=0,
        num_retries=0,
    )

    assert _result.logical_call_id is not None
    receipt = get_runtime_selected_attempt_receipt(_result.logical_call_id)
    assert parsed.action == "accept"
    assert receipt.requested_model == "deepseek/deepseek-chat"
    assert receipt.resolved_model == "openrouter/deepseek/deepseek-chat"
    assert receipt.selected_attempt_ordinal == 0
    assert receipt.raw_sha256 == "627da2fea5adc2f0ef2aa36b76829fee34e563859a9e3472a2e5522904495b35"
    with pytest.raises(SelectedAttemptReceiptError, match="terminal call row"):
        get_runtime_selected_attempt_receipt(f"substituted-{_result.logical_call_id}")


# mock-ok: provider responses are controlled; retry/fallback, returned identity, lifecycle, and SQLite are real.
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.completion")
def test_public_runtime_retry_receipt_pins_returned_logical_call_id(
    mock_completion: MagicMock,
    _mock_cost: MagicMock,
) -> None:
    """A real validation retry returns the exact ID selecting attempt one."""

    mock_completion.side_effect = [
        _native_response("{}"),
        _native_response('{"action":"accept"}'),
    ]
    _parsed, result = call_llm_structured(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "Choose"}],
        response_model=_Decision,
        task="semantic-map",
        trace_id="trace-runtime-retry",
        max_budget=0,
        num_retries=1,
        base_delay=0,
    )

    assert result.logical_call_id is not None
    receipt = get_runtime_selected_attempt_receipt(result.logical_call_id)
    assert receipt.selected_attempt_ordinal == 1
    assert receipt.logical_call_id == result.logical_call_id
    assert receipt.lineage[3].recovery_decision == "retry"


# mock-ok: provider failure/success are controlled; model fallback and persisted lifecycle are real.
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.completion")
def test_public_runtime_fallback_receipt_preserves_model_transition(
    mock_completion: MagicMock,
    _mock_cost: MagicMock,
) -> None:
    """A real fallback changes model and returns the exact selected receipt ID."""

    mock_completion.side_effect = [
        TimeoutError("provider timeout"),
        _native_response('{"action":"accept"}'),
    ]
    _parsed, result = call_llm_structured(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "Choose"}],
        response_model=_Decision,
        task="semantic-map",
        trace_id="trace-runtime-fallback",
        max_budget=0,
        num_retries=0,
        fallback_models=["gemini/gemini-2.5-flash"],
    )

    assert result.logical_call_id is not None
    receipt = get_runtime_selected_attempt_receipt(result.logical_call_id)
    assert receipt.selected_attempt_ordinal == 1
    assert receipt.requested_model == "deepseek/deepseek-chat"
    assert receipt.resolved_model != receipt.lineage[0].model
    assert receipt.lineage[2].recovery_decision == "fallback"


# mock-ok: async provider transport is controlled; public async runtime and SQLite receipt are real.
@pytest.mark.asyncio
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
async def test_public_async_runtime_returns_receipt_identity(
    mock_completion: AsyncMock,
    _mock_cost: MagicMock,
) -> None:
    """The async public path returns the same logical identity persisted in SQLite."""

    mock_completion.return_value = _native_response('{"action":"accept"}')
    _parsed, result = await acall_llm_structured(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "Choose"}],
        response_model=_Decision,
        task="semantic-map",
        trace_id="trace-runtime-async",
        max_budget=0,
        num_retries=0,
    )

    assert result.logical_call_id is not None
    receipt = get_runtime_selected_attempt_receipt(result.logical_call_id)
    assert receipt.logical_call_id == result.logical_call_id
    assert receipt.selected_attempt_ordinal == 0


# mock-ok: async provider responses are controlled; public retry lifecycle and SQLite are real.
@pytest.mark.asyncio
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
async def test_public_async_retry_receipt_pins_returned_identity(
    mock_completion: AsyncMock,
    _mock_cost: MagicMock,
) -> None:
    """The async retry path returns the ID selecting its second attempt."""

    mock_completion.side_effect = [
        _native_response("{}"),
        _native_response('{"action":"accept"}'),
    ]
    _parsed, result = await acall_llm_structured(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "Choose"}],
        response_model=_Decision,
        task="semantic-map",
        trace_id="trace-runtime-async-retry",
        max_budget=0,
        num_retries=1,
        base_delay=0,
    )

    assert result.logical_call_id is not None
    receipt = get_runtime_selected_attempt_receipt(result.logical_call_id)
    assert receipt.selected_attempt_ordinal == 1
    assert receipt.lineage[3].recovery_decision == "retry"


# mock-ok: async provider failure/success are controlled; fallback lifecycle and SQLite are real.
@pytest.mark.asyncio
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
async def test_public_async_fallback_receipt_preserves_model_transition(
    mock_completion: AsyncMock,
    _mock_cost: MagicMock,
) -> None:
    """The async fallback path returns the selected different-model receipt ID."""

    mock_completion.side_effect = [
        TimeoutError("provider timeout"),
        _native_response('{"action":"accept"}'),
    ]
    _parsed, result = await acall_llm_structured(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "Choose"}],
        response_model=_Decision,
        task="semantic-map",
        trace_id="trace-runtime-async-fallback",
        max_budget=0,
        num_retries=0,
        fallback_models=["gemini/gemini-2.5-flash"],
    )

    assert result.logical_call_id is not None
    receipt = get_runtime_selected_attempt_receipt(result.logical_call_id)
    assert receipt.selected_attempt_ordinal == 1
    assert receipt.resolved_model != receipt.lineage[0].model
    assert receipt.lineage[2].recovery_decision == "fallback"


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

    receipt = get_runtime_selected_attempt_receipt("logical-1")

    assert receipt.requested_model == "openrouter/requested"
    assert receipt.resolved_model == "openrouter/fallback"
    assert receipt.selected_attempt_ordinal == 1
    assert receipt.raw_sha256 == "a" * 64
    assert len(receipt.lineage) == 7
    assert receipt.lineage[3].recovery_decision == "fallback"


@pytest.mark.parametrize(
    ("recovery", "first_model", "second_model", "message"),
    [
        ("exhausted", "model-a", "model-b", "exhausted"),
        ("retry", "model-a", "model-b", "retry changed model"),
        ("fallback", "model-a", "model-a", "fallback kept"),
    ],
)
def test_contradictory_recovery_transition_rejects(
    recovery: str,
    first_model: str,
    second_model: str,
    message: str,
) -> None:
    """Recovery disposition constrains whether the next attempt may change model."""

    record_structured_attempt_event(_event("started", model=first_model))
    record_structured_attempt_event(
        _event("execution_failed", model=first_model, failure_class="timeout", execution_error_type="TimeoutError")
    )
    record_structured_attempt_event(
        _event("recovery_decided", model=first_model, recovery_decision=recovery)
    )
    _record_success_events(ordinal=1, model=second_model)
    _record_terminal(model=second_model)

    with pytest.raises(SelectedAttemptReceiptError, match=message):
        get_runtime_selected_attempt_receipt("logical-1")


def test_one_attempt_with_inconsistent_models_rejects() -> None:
    """Every event within one attempt ordinal must name the same model."""

    record_structured_attempt_event(_event("started", model="model-a"))
    record_structured_attempt_event(
        _event("received", model="model-b", raw_sha256="b" * 64)
    )
    record_structured_attempt_event(
        _event("validation_failed", model="model-c", failure_class="schema_validation")
    )
    record_structured_attempt_event(
        _event("recovery_decided", model="model-d", recovery_decision="fallback")
    )
    _record_success_events(ordinal=1, model="model-e")
    _record_terminal(model="model-e")

    with pytest.raises(SelectedAttemptReceiptError, match="inconsistent model"):
        get_runtime_selected_attempt_receipt("logical-1")


def test_one_attempt_with_inconsistent_execution_paths_rejects() -> None:
    """One provider attempt cannot switch runtime paths between lifecycle events."""

    record_structured_attempt_event(_event("started"))
    record_structured_attempt_event(
        _event(
            "received",
            execution_path="responses_api",
            raw_sha256="b" * 64,
        )
    )
    record_structured_attempt_event(_event("validated"))
    _record_terminal()

    with pytest.raises(SelectedAttemptReceiptError, match="execution paths"):
        get_runtime_selected_attempt_receipt("logical-1")


def test_public_events_without_terminal_row_have_no_receipt() -> None:
    """Caller-writable lifecycle events alone cannot become a selected receipt."""

    _record_success_events()

    with pytest.raises(SelectedAttemptReceiptError, match="terminal call row"):
        get_runtime_selected_attempt_receipt("logical-1")


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

    with pytest.raises(SelectedAttemptReceiptError):
        get_runtime_selected_attempt_receipt("logical-1")


def test_duplicate_terminal_rows_and_validations_reject() -> None:
    """Ambiguous terminal state is never resolved by row order."""

    _record_success_events()
    _record_terminal()
    _record_terminal()
    with pytest.raises(SelectedAttemptReceiptError, match="exactly one terminal"):
        get_runtime_selected_attempt_receipt("logical-1")

    io_log._get_db().execute("DELETE FROM llm_calls")
    io_log._get_db().commit()
    _record_terminal()
    record_structured_attempt_event(_event("validated", ordinal=1))
    with pytest.raises(SelectedAttemptReceiptError, match="exactly one validated"):
        get_runtime_selected_attempt_receipt("logical-1")


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

    with pytest.raises(SelectedAttemptReceiptError, match=message):
        get_runtime_selected_attempt_receipt("logical-1")


@pytest.mark.parametrize(
    ("terminal_updates", "message"),
    [
        ({"error": RuntimeError("failed")}, "successful"),
        ({"execution_path": "instructor"}, "execution_path"),
        ({"response_format_type": "instructor"}, "response format"),
    ],
)
def test_noneligible_terminal_row_rejects(
    terminal_updates: dict[str, object], message: str
) -> None:
    """Only matching successful provider-native calls have receipt evidence."""

    _record_success_events()
    _record_terminal(**terminal_updates)  # type: ignore[arg-type]

    with pytest.raises(SelectedAttemptReceiptError, match=message):
        get_runtime_selected_attempt_receipt("logical-1")


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

    with pytest.raises(SelectedAttemptReceiptError, match="fingerprint"):
        get_runtime_selected_attempt_receipt("logical-1")


def test_matching_fingerprint_does_not_legitimize_malformed_v3_snapshot() -> None:
    """Receipt identity requires the full closed v3 contract, not a hash alone."""

    _record_success_events()
    malformed = _snapshot()
    del malformed["replay"]
    _record_terminal(snapshot=malformed)

    with pytest.raises(SelectedAttemptReceiptError, match="valid v3"):
        get_runtime_selected_attempt_receipt("logical-1")


def test_nonhex_raw_digest_rejects() -> None:
    """A length-shaped value cannot masquerade as selected raw-content SHA-256."""

    record_structured_attempt_event(_event("started"))
    record_structured_attempt_event(_event("received", raw_sha256="z" * 64))
    record_structured_attempt_event(_event("validated"))
    _record_terminal()

    with pytest.raises(SelectedAttemptReceiptError, match="SHA-256"):
        get_runtime_selected_attempt_receipt("logical-1")


def test_trace_helper_rejects_zero_or_multiple_logical_calls() -> None:
    """Trace lookup never chooses among multiple structured public calls."""

    with pytest.raises(SelectedAttemptReceiptError, match="exactly one logical call"):
        diagnose_runtime_selected_attempt_receipt_for_trace("trace-1")

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

    with pytest.raises(SelectedAttemptReceiptError, match="exactly one logical call"):
        diagnose_runtime_selected_attempt_receipt_for_trace("trace-1")
