"""Contract tests for lossless structured-output attempt events."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from llm_client import io_log
from llm_client import acall_llm_structured, call_llm_structured
from pydantic import BaseModel
from llm_client.observability.structured_attempts import (
    StructuredAttemptEvent,
    get_structured_attempt_events,
    record_structured_attempt_event,
)


@pytest.fixture(autouse=True)
def _isolated_observability(tmp_path: Path):
    """Use a real temporary SQLite store for every attempt-ledger test."""

    old = (
        io_log._enabled,
        io_log._data_root,
        io_log._project,
        io_log._db_path,
        io_log._db_conn,
    )
    io_log._enabled = True
    io_log._data_root = tmp_path
    io_log._project = "attempt-test"
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


def _event(
    *, event_type: str, ordinal: int = 0, **updates: object
) -> StructuredAttemptEvent:
    """Build one typed attempt event with stable fixture identity."""

    payload = {
        "logical_call_id": "call-1",
        "trace_id": "trace-1",
        "task": "planner",
        "attempt_ordinal": ordinal,
        "model": "openrouter/example",
        "execution_path": "native_schema",
        "schema_hash": "schema-hash",
        "event_type": event_type,
        **updates,
    }
    return StructuredAttemptEvent.model_validate(payload)


def test_failed_attempt_survives_successful_retry_in_order() -> None:
    """A later success must not erase the received/failed first attempt."""

    events = [
        _event(event_type="received", raw_sha256="a" * 64),
        _event(
            event_type="validation_failed",
            failure_class="missing_required",
            validation_issues=[
                {
                    "location": ["decision", "rationale"],
                    "code": "missing",
                    "message": "Field required",
                }
            ],
        ),
        _event(event_type="recovery_decided", recovery_decision="retry"),
        _event(event_type="received", ordinal=1, raw_sha256="b" * 64),
        _event(event_type="validated", ordinal=1),
    ]
    for event in events:
        record_structured_attempt_event(event)

    observed = get_structured_attempt_events("call-1")
    assert [(event.attempt_ordinal, event.event_type) for event in observed] == [
        (0, "received"),
        (0, "validation_failed"),
        (0, "recovery_decided"),
        (1, "received"),
        (1, "validated"),
    ]
    assert observed[1].failure_class == "missing_required"
    assert observed[0].raw_sha256 == "a" * 64
    assert not hasattr(observed[0], "raw_content")


def test_attempt_event_rejects_unknown_taxonomy() -> None:
    """Unknown event/failure/recovery values fail before persistence."""

    with pytest.raises(ValidationError):
        _event(event_type="papered_over")
    with pytest.raises(ValidationError):
        _event(event_type="validation_failed", failure_class="mystery")


def test_attempt_persistence_failure_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The integrity ledger fails loud when its database write fails."""

    def _boom(_write_fn: object) -> None:
        raise RuntimeError("write failed")

    monkeypatch.setattr(io_log, "_run_db_write", _boom)
    with pytest.raises(RuntimeError, match="write failed"):
        record_structured_attempt_event(
            _event(event_type="received", raw_sha256="a" * 64)
        )


# mock-ok: provider responses are controlled; the real retry runtime and SQLite ledger are under test.
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.completion")
def test_native_schema_runtime_persists_failed_attempt_before_retry_success(
    mock_completion: MagicMock,
    _mock_cost: MagicMock,
) -> None:
    """The real retry closure emits received/failure/recovery/received/success."""

    class Decision(BaseModel):
        action: str
        rationale: str

    def _response(content: str) -> MagicMock:
        response = MagicMock()
        choice = MagicMock()
        choice.message.content = content
        choice.finish_reason = "stop"
        response.choices = [choice]
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        return response

    mock_completion.side_effect = [
        _response('{"action":"answer"}'),
        _response('{"action":"answer","rationale":"Enough evidence."}'),
    ]
    parsed, _result = call_llm_structured(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "Choose"}],
        response_model=Decision,
        task="planner",
        trace_id="trace-runtime-retry",
        max_budget=0,
        num_retries=1,
        base_delay=0,
    )

    assert parsed.rationale == "Enough evidence."
    rows = (
        io_log._get_db()
        .execute(
            "SELECT logical_call_id FROM structured_attempt_events WHERE trace_id=? LIMIT 1",
            ("trace-runtime-retry",),
        )
        .fetchone()
    )
    assert rows is not None
    history = get_structured_attempt_events(rows[0])
    assert [(event.attempt_ordinal, event.event_type) for event in history] == [
        (0, "received"),
        (0, "validation_failed"),
        (0, "recovery_decided"),
        (1, "received"),
        (1, "validated"),
    ]
    assert history[1].failure_class == "missing_required"
    final_call = io_log._get_db().execute(
        "SELECT logical_call_id FROM llm_calls WHERE trace_id=? ORDER BY id DESC LIMIT 1",
        ("trace-runtime-retry",),
    ).fetchone()
    assert final_call == (rows[0],)


@pytest.mark.asyncio
# mock-ok: provider responses are controlled; the real async retry runtime and SQLite ledger are under test.
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
async def test_async_native_schema_runtime_preserves_failed_attempt(
    mock_completion: AsyncMock,
    _mock_cost: MagicMock,
) -> None:
    """The async public path preserves the same lossless attempt history."""

    class Decision(BaseModel):
        action: str
        rationale: str

    def _response(content: str) -> MagicMock:
        response = MagicMock()
        choice = MagicMock()
        choice.message.content = content
        choice.finish_reason = "stop"
        response.choices = [choice]
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        return response

    mock_completion.side_effect = [
        _response('{"action":"answer"}'),
        _response('{"action":"answer","rationale":"Enough evidence."}'),
    ]
    parsed, _result = await acall_llm_structured(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "Choose"}],
        response_model=Decision,
        task="planner",
        trace_id="trace-async-runtime-retry",
        max_budget=0,
        num_retries=1,
        base_delay=0,
    )

    assert parsed.rationale == "Enough evidence."
    logical_call_id = (
        io_log._get_db()
        .execute(
            "SELECT logical_call_id FROM structured_attempt_events WHERE trace_id=? LIMIT 1",
            ("trace-async-runtime-retry",),
        )
        .fetchone()[0]
    )
    assert [
        event.event_type for event in get_structured_attempt_events(logical_call_id)
    ] == [
        "received",
        "validation_failed",
        "recovery_decided",
        "received",
        "validated",
    ]
    final_call = io_log._get_db().execute(
        "SELECT logical_call_id FROM llm_calls WHERE trace_id=? ORDER BY id DESC LIMIT 1",
        ("trace-async-runtime-retry",),
    ).fetchone()
    assert final_call == (logical_call_id,)
