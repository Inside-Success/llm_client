from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from llm_client import io_log
from llm_client.execution.call_wrappers import PreparedPublicCallEnvelope, _run_async_public_call
from llm_client.observability.query import get_call_lifecycle
from llm_client.observability.structured_attempts import StructuredAttemptEvent, record_structured_attempt_event


def _event(phase: str, logical_call_id: str = "logical-1") -> dict[str, object]:
    return {"event_id": f"evt-{uuid4().hex}", "timestamp": "2026-07-24T20:00:00+00:00", "logical_call_id": logical_call_id, "trace_id": f"trace-{logical_call_id}", "task": "test", "phase": phase, "requested_model": "openrouter/deepseek/deepseek-v4-flash", "call_kind": "structured"}


def test_dispatch_without_terminal_is_discoverable_as_abandoned() -> None:
    io_log.record_call_lifecycle_event(_event("dispatched"))
    result = get_call_lifecycle(logical_call_id="logical-1")
    assert result[0]["state"] == "interrupted_or_abandoned"
    assert result[0]["events"][0]["phase"] == "dispatched"


def test_terminal_lifecycle_remains_terminal() -> None:
    io_log.record_call_lifecycle_event(_event("dispatched", "logical-2"))
    io_log.record_call_lifecycle_event(_event("completed", "logical-2"))
    result = get_call_lifecycle(trace_id="trace-logical-2")
    assert result[0]["state"] == "completed"
    assert result[0]["latest_event"]["phase"] == "completed"
    assert result[0]["elapsed_s"] is not None


def test_structured_timeout_is_not_misclassified_as_provider_error() -> None:
    record_structured_attempt_event(StructuredAttemptEvent(
        logical_call_id="timeout-logical", trace_id="timeout-trace", task="test",
        attempt_ordinal=0, model="openrouter/deepseek/deepseek-v4-flash",
        execution_path="native_schema", schema_hash="a" * 64, event_type="execution_failed", failure_class="timeout",
        execution_error_type="TimeoutError",
    ))
    result = get_call_lifecycle(logical_call_id="timeout-logical")
    assert result[0]["events"][0]["phase"] == "timeout_observed"


@pytest.mark.asyncio
async def test_async_cancellation_leaves_a_terminal_lifecycle_event() -> None:
    """Caller cancellation is durable and distinct from a provider failure."""

    trace_id = f"cancel-trace-{uuid4().hex}"
    envelope = PreparedPublicCallEnvelope(
        normalized_prompt_ref=None,
        resolved_task="test",
        resolved_trace_id=trace_id,
        resolved_max_budget=0.0,
        effective_provider_timeout=30,
        heartbeat_interval_s=0.0,
        stall_after_s=0.0,
        runtime_kwargs={},
    )

    async def _cancelled_invoke(_: dict[str, object]) -> str:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await _run_async_public_call(
            model="openrouter/deepseek/deepseek-v4-flash",
            call_kind="text",
            caller="test.cancelled",
            timeout=30,
            envelope=envelope,
            invoke=_cancelled_invoke,
            resolve_model=lambda result: result,
        )

    result = get_call_lifecycle(trace_id=trace_id)
    assert result[0]["state"] == "cancelled"
    assert [event["phase"] for event in result[0]["events"]] == ["started", "cancelled"]
