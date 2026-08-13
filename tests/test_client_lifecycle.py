"""Focused regression tests for public-call lifecycle emission.

These tests isolate the wrapper boundary in ``llm_client.core.client`` and prove
that the public text/structured entrypoints emit lifecycle events again after
the wrapper-side liveness logic was restored.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from llm_client.core import client
import llm_client.io_log as io_log
from llm_client.execution import structured_runtime
import llm_client.execution.timeout_policy as timeout_policy
from llm_client.core.data_types import LLMCallResult
from llm_client.core.errors import (
    LLMBudgetExceededError,
    LLMBudgetReservationOverrunError,
    LLMError,
    LLMTransientError,
)
from llm_client.observability import (
    ObservedRun,
    get_budget_scope_snapshot,
    get_observed_run,
)


@pytest.fixture(autouse=True)
def _isolate_io_log(tmp_path: Path):
    """Keep lifecycle logging isolated in a temp DB for each test."""

    old_enabled = io_log._enabled
    old_root = io_log._data_root
    old_project = io_log._project
    old_db_path = io_log._db_path
    old_db_conn = io_log._db_conn
    old_last_cleanup = io_log._last_cleanup_date

    io_log._enabled = True
    io_log._data_root = tmp_path
    io_log._project = "test_project"
    io_log._db_path = tmp_path / "test.db"
    io_log._db_conn = None
    io_log._last_cleanup_date = None
    structured_runtime._INSTRUCTOR_CLIENT_CACHE.clear()
    structured_runtime._INSTRUCTOR_READY_CLIENT_IDS.clear()

    yield

    structured_runtime._INSTRUCTOR_CLIENT_CACHE.clear()
    structured_runtime._INSTRUCTOR_READY_CLIENT_IDS.clear()
    io_log._enabled = old_enabled
    io_log._data_root = old_root
    io_log._project = old_project
    io_log._db_path = old_db_path
    io_log.close()
    io_log._db_conn = old_db_conn
    io_log._last_cleanup_date = old_last_cleanup


class _ResponseModel(BaseModel):
    """Small structured-output contract used to test wrapper lifecycle emission."""

    label: str


def _mock_structured_response(content: str = '{"label":"ok"}') -> MagicMock:
    """Build one provider response for the composed structured-call path."""

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.choices[0].message.refusal = None
    response.choices[0].finish_reason = "stop"
    response.usage.prompt_tokens = 10
    response.usage.completion_tokens = 5
    response.usage.total_tokens = 15
    return response


def _typed_lifecycle_phases(logical_call_id: str) -> list[str]:
    """Return the canonical typed phases for one exact logical call."""

    rows = io_log._get_db().execute(
        """SELECT phase FROM call_lifecycle_events
           WHERE logical_call_id = ? ORDER BY id""",
        (logical_call_id,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _lifecycle_rows() -> list[tuple[str, dict[str, Any]]]:
    """Return Foundation lifecycle rows from the isolated observability DB."""

    db = io_log._get_db()
    rows = db.execute(
        """
        SELECT event_type, payload
        FROM foundation_events
        WHERE event_type = 'LLMCallLifecycle'
        ORDER BY id ASC
        """
    ).fetchall()
    out: list[tuple[str, dict[str, Any]]] = []
    for event_type, payload_text in rows:
        out.append((event_type, json.loads(payload_text)))
    return out


def _insert_settled_cost(trace_id: str, cost: float) -> None:
    """Write the normal call row that precedes durable reservation settlement."""

    db = io_log._get_db()
    db.execute(
        """INSERT INTO llm_calls (timestamp, model, cost, marginal_cost, error, trace_id)
           VALUES (?, ?, ?, ?, NULL, ?)""",
        ("2026-07-25T00:00:00+00:00", "test-model", cost, cost, trace_id),
    )
    db.commit()


def _mock_stream_chunk(text: str) -> Any:
    """Build one sync/async stream chunk compatible with LLMStream finalization."""

    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = text
    return chunk


@pytest.mark.asyncio
async def test_parallel_public_calls_share_one_root_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two public calls overlap under one durable root and a third is rejected."""

    _insert_settled_cost("root/concurrent/prior", 0.04)
    release = asyncio.Event()
    both_started = asyncio.Event()
    seen_provider_kwargs: list[dict[str, Any]] = []
    started = 0

    async def _held_runtime(model: str, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        nonlocal started
        seen_provider_kwargs.append(dict(kwargs))
        started += 1
        if started == 2:
            both_started.set()
        await release.wait()
        cost = 0.06 if kwargs["trace_id"].endswith("graph") else 0.07
        _insert_settled_cost(kwargs["trace_id"], cost)
        return SimpleNamespace(cost=cost, model=model, resolved_model=model)

    monkeypatch.setattr(
        "llm_client.execution.text_runtime._acall_llm_impl", _held_runtime
    )
    root_kwargs = {
        "task": "test.concurrent",
        "max_budget": 0.20,
        "budget_scope_trace_id": "root/concurrent",
        "budget_scope_mode": "reserved_concurrent",
        "budget_reservation": 0.08,
    }
    graph = asyncio.create_task(
        client.acall_llm(
            "gpt-4",
            [{"role": "user", "content": "graph"}],
            trace_id="root/concurrent/graph",
            **root_kwargs,
        )
    )
    wiki = asyncio.create_task(
        client.acall_llm(
            "gpt-4",
            [{"role": "user", "content": "wiki"}],
            trace_id="root/concurrent/wiki",
            **root_kwargs,
        )
    )
    await asyncio.wait_for(both_started.wait(), timeout=5)

    with pytest.raises(LLMBudgetExceededError):
        await client.acall_llm(
            "gpt-4",
            [{"role": "user", "content": "third"}],
            trace_id="root/concurrent/third",
            task="test.concurrent",
            max_budget=0.20,
            budget_scope_trace_id="root/concurrent",
            budget_scope_mode="reserved_concurrent",
            budget_reservation=0.01,
        )

    release.set()
    await asyncio.gather(graph, wiki)
    snapshot = get_budget_scope_snapshot(scope_trace_id="root/concurrent", max_budget=0.20)
    assert snapshot.settled_microusd == 170_000
    assert snapshot.active_reserved_microusd == 0
    assert snapshot.available_microusd == 30_000
    for kwargs in seen_provider_kwargs:
        assert "budget_scope_trace_id" not in kwargs
        assert "budget_scope_mode" not in kwargs
        assert "budget_reservation" not in kwargs


class _MockAsyncStream:
    """Async iterator shaped like litellm.async streaming responses."""

    def __init__(self, chunks: list[Any], fail_after: bool = False) -> None:
        self._chunks = chunks
        self._fail_after = fail_after
        self._index = 0

    def __aiter__(self) -> "_MockAsyncStream":
        return self

    async def __anext__(self) -> Any:
        if self._index < len(self._chunks):
            chunk = self._chunks[self._index]
            self._index += 1
            return chunk
        if self._fail_after:
            raise RuntimeError("boom")
        raise StopAsyncIteration


def test_call_llm_structured_emits_started_and_completed_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sync structured wrapper should emit lifecycle rows and pass the monitor through."""

    # mock-ok: isolates public wrapper lifecycle emission without provider calls.
    def _fake_impl(
        model: str,
        messages: list[dict[str, Any]],
        response_model: type[BaseModel],
        **kwargs: Any,
    ) -> tuple[BaseModel, LLMCallResult]:
        monitor = kwargs["_lifecycle_monitor"]
        monitor.enable_progress_tracking(default_source="unit_test")
        monitor.mark_progress(source="unit_test")
        parsed = response_model(label="ok")
        result = LLMCallResult(
            content=parsed.model_dump_json(),
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            cost=0.0,
            model=model,
            resolved_model=model,
            finish_reason="stop",
            raw_response={"ok": True},
            warnings=[],
            cost_source="computed",
        )
        return parsed, result

    monkeypatch.setattr(
        "llm_client.execution.structured_runtime._call_llm_structured_impl",
        _fake_impl,
    )

    parsed, result = client.call_llm_structured(
        "gemini/gemini-2.5-flash",
        [{"role": "user", "content": "hello"}],
        _ResponseModel,
        task="test.lifecycle",
        trace_id="trace.lifecycle.sync",
        max_budget=0.1,
        logical_timeout=12,
        lifecycle_heartbeat_interval_s=0,
        lifecycle_stall_after_s=0,
    )

    assert parsed.label == "ok"
    assert result.resolved_model == "gemini/gemini-2.5-flash"

    rows = _lifecycle_rows()
    assert [payload["llm_call_lifecycle"]["phase"] for _, payload in rows] == [
        "started",
        "progress",
        "completed",
    ]
    completed = rows[-1][1]["llm_call_lifecycle"]
    assert rows[0][1]["llm_call_lifecycle"]["logical_timeout_s"] == 12
    assert completed["logical_timeout_s"] == 12
    assert completed["progress_observable"] is True
    assert completed["progress_source"] == "unit_test"
    assert completed["progress_event_count"] == 1


def test_composed_sync_structured_call_emits_one_terminal_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real sync wrapper/runtime composition has one public terminal."""

    # mock-ok: provider transport is fake; public/runtime lifecycle composition is real.
    monkeypatch.setattr(
        "llm_client.execution.structured_runtime._model_supports_native_schema",
        lambda _model: True,
    )
    monkeypatch.setattr(
        "llm_client.core.client.litellm.completion",
        lambda **_kwargs: _mock_structured_response(),
    )
    monkeypatch.setattr(
        "llm_client.core.client.litellm.completion_cost",
        lambda **_kwargs: 0.001,
    )

    parsed, result = client.call_llm_structured(
        "openrouter/deepseek/deepseek-v4-flash",
        [{"role": "user", "content": "Return a label."}],
        _ResponseModel,
        num_retries=0,
        fallback_models=[],
        task="test.lifecycle.composed.sync",
        trace_id="trace.lifecycle.composed.sync",
        max_budget=0.1,
        lifecycle_heartbeat_interval_s=0,
        lifecycle_stall_after_s=0,
    )

    assert parsed.label == "ok"
    assert result.logical_call_id
    phases = _typed_lifecycle_phases(result.logical_call_id)
    assert phases.count("started") == 1
    assert [phase for phase in phases if phase in {"completed", "failed", "cancelled"}] == [
        "completed"
    ]
    terminal_rows = io_log._get_db().execute(
        "SELECT COUNT(*) FROM llm_calls WHERE logical_call_id = ?",
        (result.logical_call_id,),
    ).fetchone()
    assert terminal_rows == (1,)


@pytest.mark.asyncio
async def test_composed_async_structured_call_emits_one_terminal_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real async wrapper/runtime composition has one public terminal."""

    # mock-ok: provider transport is fake; public/runtime lifecycle composition is real.
    async def _completion(**_kwargs: Any) -> MagicMock:
        return _mock_structured_response()

    monkeypatch.setattr(
        "llm_client.execution.structured_runtime._model_supports_native_schema",
        lambda _model: True,
    )
    monkeypatch.setattr(
        "llm_client.core.client.litellm.acompletion",
        _completion,
    )
    monkeypatch.setattr(
        "llm_client.core.client.litellm.completion_cost",
        lambda **_kwargs: 0.001,
    )

    parsed, result = await client.acall_llm_structured(
        "openrouter/deepseek/deepseek-v4-flash",
        [{"role": "user", "content": "Return a label."}],
        _ResponseModel,
        num_retries=0,
        fallback_models=[],
        task="test.lifecycle.composed.async",
        trace_id="trace.lifecycle.composed.async",
        max_budget=0.1,
        lifecycle_heartbeat_interval_s=0,
        lifecycle_stall_after_s=0,
    )

    assert parsed.label == "ok"
    assert result.logical_call_id
    phases = _typed_lifecycle_phases(result.logical_call_id)
    assert phases.count("started") == 1
    assert [phase for phase in phases if phase in {"completed", "failed", "cancelled"}] == [
        "completed"
    ]
    terminal_rows = io_log._get_db().execute(
        "SELECT COUNT(*) FROM llm_calls WHERE logical_call_id = ?",
        (result.logical_call_id,),
    ).fetchone()
    assert terminal_rows == (1,)


def test_incomplete_failed_attempt_cost_releases_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partial cost evidence cannot turn an error lease into settled custody."""

    # mock-ok: isolates the outer budget wrapper's typed-error contract.
    def _fake_impl(*args: Any, **kwargs: Any) -> tuple[BaseModel, LLMCallResult]:
        error = LLMError("provider failed after one priced response")
        error.cost = 0.002
        error.cost_source = "provider_reported"
        error.cost_covers_all_attempts = False
        raise error

    monkeypatch.setattr(
        "llm_client.execution.structured_runtime._call_llm_structured_impl",
        _fake_impl,
    )
    with pytest.raises(LLMError, match="provider failed"):
        client.call_llm_structured(
            "gemini/gemini-2.5-flash",
            [{"role": "user", "content": "hello"}],
            _ResponseModel,
            task="test.lifecycle.partial-cost",
            trace_id="trace.lifecycle.partial-cost",
            max_budget=0.1,
            budget_scope_trace_id="trace.lifecycle.partial-cost",
            budget_scope_mode="reserved_concurrent",
            budget_reservation=0.01,
            lifecycle_heartbeat_interval_s=0,
        )

    row = io_log._get_db().execute(
        """SELECT status, settled_cost_microusd FROM budget_reservations
           WHERE scope_trace_id = ?""",
        ("trace.lifecycle.partial-cost",),
    ).fetchone()
    assert row == ("released_error", None)


def test_fully_observed_failed_attempt_cost_reports_reservation_overrun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Known failed spend above its reservation remains a typed hard failure."""

    # mock-ok: isolates terminal settlement and overrun behavior.
    def _fake_impl(*args: Any, **kwargs: Any) -> tuple[BaseModel, LLMCallResult]:
        error = LLMError("validation exhausted")
        error.cost = 0.003
        error.cost_source = "attempt_aggregate"
        error.cost_covers_all_attempts = True
        raise error

    monkeypatch.setattr(
        "llm_client.execution.structured_runtime._call_llm_structured_impl",
        _fake_impl,
    )
    with pytest.raises(LLMBudgetReservationOverrunError):
        client.call_llm_structured(
            "gemini/gemini-2.5-flash",
            [{"role": "user", "content": "hello"}],
            _ResponseModel,
            task="test.lifecycle.failed-overrun",
            trace_id="trace.lifecycle.failed-overrun",
            max_budget=0.1,
            budget_scope_trace_id="trace.lifecycle.failed-overrun",
            budget_scope_mode="reserved_concurrent",
            budget_reservation=0.001,
            lifecycle_heartbeat_interval_s=0,
        )

    row = io_log._get_db().execute(
        """SELECT status, settled_cost_microusd FROM budget_reservations
           WHERE scope_trace_id = ?""",
        ("trace.lifecycle.failed-overrun",),
    ).fetchone()
    assert row == ("settled", 3_000)


def test_public_structured_call_is_joinable_to_observed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real public wrapper must leave a child lifecycle under its outer run."""

    def _fake_impl(
        model: str,
        messages: list[dict[str, Any]],
        response_model: type[BaseModel],
        **kwargs: Any,
    ) -> tuple[BaseModel, LLMCallResult]:
        parsed = response_model(label="ok")
        return parsed, LLMCallResult(
            content=parsed.model_dump_json(),
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            cost=0.0,
            model=model,
            resolved_model=model,
            finish_reason="stop",
            raw_response={"ok": True},
            warnings=[],
            cost_source="computed",
        )

    monkeypatch.setattr(
        "llm_client.execution.structured_runtime._call_llm_structured_impl",
        _fake_impl,
    )

    with ObservedRun(
        project="test_project",
        operation="structured_contract",
        executable="tests/test_client_lifecycle.py",
        run_id="run_public_join",
        root_trace_id="trace.outer",
        requested_model="gemini/gemini-2.5-flash",
        max_budget=0.1,
    ) as run:
        client.call_llm_structured(
            "gemini/gemini-2.5-flash",
            [{"role": "user", "content": "hello"}],
            _ResponseModel,
            task="test.lifecycle.join",
            trace_id=run.child_trace_id("structured"),
            max_budget=0.1,
            lifecycle_heartbeat_interval_s=0,
        )

    record = get_observed_run(run.run_id)
    assert record.status == "completed"
    assert record.linked_call_count == 1


def test_public_call_rejects_trace_outside_active_observed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active outer run must mechanically own every public call trace."""

    provider_called = False

    def _fake_impl(*args: Any, **kwargs: Any) -> tuple[BaseModel, LLMCallResult]:
        nonlocal provider_called
        provider_called = True
        raise AssertionError("provider dispatch must not occur")

    monkeypatch.setattr(
        "llm_client.execution.structured_runtime._call_llm_structured_impl",
        _fake_impl,
    )

    with pytest.raises(ValueError, match="run.child_trace_id"):
        with ObservedRun(
            project="test_project",
            operation="lineage_contract",
            executable="tests/test_client_lifecycle.py",
            run_id="run_public_lineage_rejection",
            root_trace_id="trace.outer.enforced",
            requested_model="gemini/gemini-2.5-flash",
            max_budget=0.1,
        ):
            client.call_llm_structured(
                "gemini/gemini-2.5-flash",
                [{"role": "user", "content": "hello"}],
                _ResponseModel,
                task="test.lifecycle.lineage",
                trace_id="unrelated.trace",
                max_budget=0.1,
                lifecycle_heartbeat_interval_s=0,
            )

    assert provider_called is False
    record = get_observed_run("run_public_lineage_rejection")
    assert record.status == "failed_before_call_start"
    assert record.linked_call_count == 0


def test_strict_mode_rejects_public_call_without_observed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A migrated executable can require outer custody before any dispatch."""

    provider_called = False

    def _fake_impl(*args: Any, **kwargs: Any) -> tuple[BaseModel, LLMCallResult]:
        nonlocal provider_called
        provider_called = True
        raise AssertionError("provider dispatch must not occur")

    monkeypatch.setenv("LLM_CLIENT_REQUIRE_OBSERVED_RUN", "1")
    monkeypatch.setattr(
        "llm_client.execution.structured_runtime._call_llm_structured_impl",
        _fake_impl,
    )

    with pytest.raises(RuntimeError, match="create an ObservedRun"):
        client.call_llm_structured(
            "gemini/gemini-2.5-flash",
            [{"role": "user", "content": "hello"}],
            _ResponseModel,
            task="test.lifecycle.strict",
            trace_id="strict.trace",
            max_budget=0.1,
            lifecycle_heartbeat_interval_s=0,
        )

    assert provider_called is False


def test_strict_mode_rejects_invalid_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_CLIENT_REQUIRE_OBSERVED_RUN", "sometimes")

    with pytest.raises(RuntimeError, match="must be a boolean"):
        client.call_llm_structured(
            "gemini/gemini-2.5-flash",
            [{"role": "user", "content": "hello"}],
            _ResponseModel,
            task="test.lifecycle.strict.invalid",
            trace_id="strict.invalid.trace",
            max_budget=0.1,
            lifecycle_heartbeat_interval_s=0,
        )


def test_public_call_rejects_terminal_active_observed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manually terminated context cannot accept later call lifecycle events."""

    provider_called = False

    def _fake_impl(*args: Any, **kwargs: Any) -> tuple[BaseModel, LLMCallResult]:
        nonlocal provider_called
        provider_called = True
        raise AssertionError("provider dispatch must not occur")

    monkeypatch.setattr(
        "llm_client.execution.structured_runtime._call_llm_structured_impl",
        _fake_impl,
    )

    with ObservedRun(
        project="test_project",
        operation="terminal_lineage_contract",
        executable="tests/test_client_lifecycle.py",
        run_id="run_public_terminal_rejection",
        root_trace_id="trace.outer.terminal",
        requested_model="gemini/gemini-2.5-flash",
        max_budget=0.1,
    ) as run:
        run.cancel(reason="operator stopped")
        with pytest.raises(RuntimeError, match="terminal observed run"):
            client.call_llm_structured(
                "gemini/gemini-2.5-flash",
                [{"role": "user", "content": "hello"}],
                _ResponseModel,
                task="test.lifecycle.terminal",
                trace_id=run.child_trace_id("too_late"),
                max_budget=0.1,
                lifecycle_heartbeat_interval_s=0,
            )

    assert provider_called is False
    record = get_observed_run("run_public_terminal_rejection")
    assert record.status == "cancelled"
    assert record.linked_call_count == 0


def test_call_llm_structured_uses_shared_default_timeout_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structured wrappers should apply the shared finite default timeout."""

    seen: dict[str, Any] = {}

    # mock-ok: verifies wrapper timeout resolution without provider calls.
    def _fake_impl(
        model: str,
        messages: list[dict[str, Any]],
        response_model: type[BaseModel],
        **kwargs: Any,
    ) -> tuple[BaseModel, LLMCallResult]:
        seen["timeout"] = kwargs["timeout"]
        parsed = response_model(label="ok")
        result = LLMCallResult(
            content=parsed.model_dump_json(),
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            cost=0.0,
            model=model,
            resolved_model=model,
            finish_reason="stop",
            raw_response={"ok": True},
            warnings=[],
            cost_source="computed",
        )
        return parsed, result

    monkeypatch.setattr(
        "llm_client.execution.structured_runtime._call_llm_structured_impl",
        _fake_impl,
    )

    client.call_llm_structured(
        "gemini/gemini-2.5-flash",
        [{"role": "user", "content": "hello"}],
        _ResponseModel,
        task="test.lifecycle",
        trace_id="trace.lifecycle.default_timeout",
        max_budget=0.1,
    )

    assert seen["timeout"] == 60


def test_call_llm_structured_preserves_explicit_timeout_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit timeout override should beat the shared structured default."""

    seen: dict[str, Any] = {}

    # mock-ok: verifies wrapper timeout resolution without provider calls.
    def _fake_impl(
        model: str,
        messages: list[dict[str, Any]],
        response_model: type[BaseModel],
        **kwargs: Any,
    ) -> tuple[BaseModel, LLMCallResult]:
        seen["timeout"] = kwargs["timeout"]
        parsed = response_model(label="ok")
        result = LLMCallResult(
            content=parsed.model_dump_json(),
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            cost=0.0,
            model=model,
            resolved_model=model,
            finish_reason="stop",
            raw_response={"ok": True},
            warnings=[],
            cost_source="computed",
        )
        return parsed, result

    monkeypatch.setattr(
        "llm_client.execution.structured_runtime._call_llm_structured_impl",
        _fake_impl,
    )

    client.call_llm_structured(
        "gemini/gemini-2.5-flash",
        [{"role": "user", "content": "hello"}],
        _ResponseModel,
        timeout=45,
        task="test.lifecycle",
        trace_id="trace.lifecycle.override_timeout",
        max_budget=0.1,
    )

    assert seen["timeout"] == 45


def test_stream_llm_emits_started_progress_completed_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sync streaming emits lifecycle rows when stream reaches natural end."""

    # mock-ok: keeps provider out of the test while validating lifecycle.
    monkeypatch.setattr(
        "llm_client.core.client.litellm.stream_chunk_builder",
        lambda chunks: None,
    )
    seen_provider_kwargs: dict[str, Any] = {}

    def _completion(**kwargs: Any) -> Any:
        seen_provider_kwargs.update(kwargs)
        return iter([_mock_stream_chunk("hello")])

    monkeypatch.setattr("llm_client.core.client.litellm.completion", _completion)

    stream = client.stream_llm(
        "gpt-4",
        [{"role": "user", "content": "Hi"}],
        task="test.lifecycle.stream",
        trace_id="trace.lifecycle.stream.sync",
        budget_scope_trace_id="trace.lifecycle.stream.sync",
        budget_scope_mode="reserved_concurrent",
        budget_reservation=0.01,
        max_budget=0.1,
        lifecycle_heartbeat_interval_s=0,
        lifecycle_stall_after_s=0,
    )
    assert list(stream) == ["hello"]

    rows = _lifecycle_rows()
    assert [payload["llm_call_lifecycle"]["phase"] for _, payload in rows] == [
        "started",
        "progress",
        "completed",
    ]
    completed = rows[-1][1]["llm_call_lifecycle"]
    assert completed["progress_event_count"] == 1
    assert completed["progress_observable"] is True
    assert completed.get("error_type") is None
    assert "budget_scope_trace_id" not in seen_provider_kwargs
    assert "budget_scope_mode" not in seen_provider_kwargs
    assert "budget_reservation" not in seen_provider_kwargs


def test_stream_llm_emits_failed_lifecycle_on_iteration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sync stream iteration errors emit progress then failed lifecycle row."""

    # mock-ok: provider mocked; lifecycle behavior is the integration under test.
    class _FailingStream:
        def __iter__(self) -> "_FailingStream":
            return self

        def __next__(self) -> Any:
            if hasattr(self, "_yielded"):
                raise RuntimeError("boom")
            self._yielded = True
            return _mock_stream_chunk("part")

    monkeypatch.setattr(
        "llm_client.core.client.litellm.stream_chunk_builder",
        lambda chunks: None,
    )
    monkeypatch.setattr("llm_client.core.client.litellm.completion", lambda **kwargs: _FailingStream())

    stream = client.stream_llm(
        "gpt-4",
        [{"role": "user", "content": "Hi"}],
        task="test.lifecycle.stream",
        trace_id="trace.lifecycle.stream.sync.fail",
        max_budget=0.1,
        lifecycle_heartbeat_interval_s=0,
        lifecycle_stall_after_s=0,
    )
    with pytest.raises(RuntimeError, match="boom"):
        list(stream)

    rows = _lifecycle_rows()
    assert [payload["llm_call_lifecycle"]["phase"] for _, payload in rows] == [
        "started",
        "progress",
        "failed",
    ]
    failed = rows[-1][1]["llm_call_lifecycle"]
    assert failed["error_type"] == "RuntimeError"
    assert failed["error_message"] == "boom"
    assert failed["progress_event_count"] == 1


def test_stream_close_releases_durable_budget_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit close releases a concurrent stream lease exactly once."""

    class _ClosableStream:
        def __iter__(self) -> "_ClosableStream":
            return self

        def __next__(self) -> Any:
            return _mock_stream_chunk("never consumed")

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "llm_client.core.client.litellm.stream_chunk_builder", lambda chunks: None
    )
    monkeypatch.setattr(
        "llm_client.core.client.litellm.completion", lambda **kwargs: _ClosableStream()
    )
    stream = client.stream_llm(
        "gpt-4",
        [{"role": "user", "content": "Hi"}],
        task="test.lifecycle.stream.close",
        trace_id="trace.lifecycle.stream.close",
        max_budget=0.1,
        budget_scope_trace_id="trace.lifecycle.stream.close",
        budget_scope_mode="reserved_concurrent",
        budget_reservation=0.05,
    )
    stream.close()
    stream.close()
    snapshot = get_budget_scope_snapshot(
        scope_trace_id="trace.lifecycle.stream.close", max_budget=0.1
    )
    assert snapshot.active_reserved_microusd == 0


@pytest.mark.asyncio
async def test_astream_aclose_releases_durable_budget_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit async close releases a concurrent stream lease exactly once."""

    class _ClosableAsyncStream:
        def __aiter__(self) -> "_ClosableAsyncStream":
            return self

        async def __anext__(self) -> Any:
            return _mock_stream_chunk("never consumed")

        async def aclose(self) -> None:
            return None

    async def _stream(**_: Any) -> _ClosableAsyncStream:
        return _ClosableAsyncStream()

    monkeypatch.setattr(
        "llm_client.core.client.litellm.stream_chunk_builder", lambda chunks: None
    )
    monkeypatch.setattr("llm_client.core.client.litellm.acompletion", _stream)
    stream = await client.astream_llm(
        "gpt-4",
        [{"role": "user", "content": "Hi"}],
        task="test.lifecycle.stream.aclose",
        trace_id="trace.lifecycle.stream.aclose",
        max_budget=0.1,
        budget_scope_trace_id="trace.lifecycle.stream.aclose",
        budget_scope_mode="reserved_concurrent",
        budget_reservation=0.05,
    )
    await stream.aclose()
    await stream.aclose()
    snapshot = get_budget_scope_snapshot(
        scope_trace_id="trace.lifecycle.stream.aclose", max_budget=0.1
    )
    assert snapshot.active_reserved_microusd == 0


@pytest.mark.asyncio
async def test_acall_llm_structured_emits_failed_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Async structured wrapper should emit a terminal failed lifecycle row."""

    # mock-ok: isolates public wrapper lifecycle emission without provider calls.
    async def _fake_impl(
        model: str,
        messages: list[dict[str, Any]],
        response_model: type[BaseModel],
        **kwargs: Any,
    ) -> tuple[BaseModel, LLMCallResult]:
        monitor = kwargs["_lifecycle_monitor"]
        monitor.enable_progress_tracking(default_source="unit_test_async")
        monitor.mark_progress(source="unit_test_async")
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "llm_client.execution.structured_runtime._acall_llm_structured_impl",
        _fake_impl,
    )

    with pytest.raises(RuntimeError, match="boom"):
        await client.acall_llm_structured(
            "gemini/gemini-2.5-flash",
            [{"role": "user", "content": "hello"}],
            _ResponseModel,
            task="test.lifecycle",
            trace_id="trace.lifecycle.async",
            max_budget=0.1,
            lifecycle_heartbeat_interval_s=0,
            lifecycle_stall_after_s=0,
        )

    rows = _lifecycle_rows()
    assert [payload["llm_call_lifecycle"]["phase"] for _, payload in rows] == [
        "started",
        "progress",
        "failed",
    ]
    failed = rows[-1][1]["llm_call_lifecycle"]
    assert failed["progress_observable"] is True
    assert failed["progress_source"] == "unit_test_async"
    assert failed["progress_event_count"] == 1
    assert failed["error_type"] == "RuntimeError"
    assert failed["error_message"] == "boom"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_path", "expected_caller"),
    [
        ("responses_api", "acall_llm_structured.responses_api"),
        ("native_schema", "acall_llm_structured.native_schema"),
        ("instructor", "acall_llm_structured.instructor"),
    ],
)
async def test_async_structured_safety_timeout_cancels_provider_and_emits_failed_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    provider_path: str,
    expected_caller: str,
) -> None:
    """Every provider-backed async structured path is cancelled and logged."""

    cancelled = asyncio.Event()

    # mock-ok: the non-returning provider transport is the external failure seam;
    # cancellation, retry classification, wrapper cleanup, and SQLite lifecycle
    # persistence remain real.
    async def _hung_provider(**_: Any) -> Any:
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "ban")
    monkeypatch.setenv("LLM_CLIENT_SAFETY_TIMEOUT", "1")
    monkeypatch.setattr(timeout_policy, "safety_timeout_s", lambda: 0.05)
    monkeypatch.setattr(
        "llm_client.core.client._is_responses_api_model",
        lambda _model: provider_path == "responses_api",
    )
    monkeypatch.setattr(
        "llm_client.execution.structured_runtime._model_supports_native_schema",
        lambda _model: provider_path == "native_schema",
    )
    if provider_path == "responses_api":
        monkeypatch.setattr("llm_client.core.client.litellm.aresponses", _hung_provider)
    elif provider_path == "native_schema":
        monkeypatch.setattr("llm_client.core.client.litellm.acompletion", _hung_provider)
    else:
        import instructor

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create_with_completion=_hung_provider),
            ),
        )
        monkeypatch.setattr(instructor, "from_litellm", lambda _completion: fake_client)

    with pytest.raises(LLMTransientError) as caught:
        await asyncio.wait_for(
            client.acall_llm_structured(
                "openrouter/test-model",
                [{"role": "user", "content": "hello"}],
                _ResponseModel,
                num_retries=0,
                task="test.lifecycle.safety",
                trace_id="trace.lifecycle.async.safety",
                max_budget=0.1,
                config=client.ClientConfig(routing_policy="openrouter"),
                lifecycle_heartbeat_interval_s=0,
                lifecycle_stall_after_s=0,
            ),
            timeout=1.5,
        )

    assert isinstance(caught.value.original, TimeoutError)
    assert expected_caller in str(caught.value.original)
    assert "openrouter/test-model" in str(caught.value.original)
    assert "timed out after 0.05s async attempt safety ceiling" in str(caught.value.original)
    assert cancelled.is_set()

    rows = _lifecycle_rows()
    assert [payload["llm_call_lifecycle"]["phase"] for _, payload in rows] == [
        "started",
        "failed",
    ]
    failed = rows[-1][1]["llm_call_lifecycle"]
    assert failed["error_type"] == "TimeoutError"
    assert failed["error_message"]
    assert failed["provider_timeout_s"] == 1


@pytest.mark.asyncio
async def test_astream_llm_emits_started_progress_completed_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async streaming emits lifecycle rows when stream reaches natural end."""

    seen_provider_kwargs: dict[str, Any] = {}

    async def _stream(**kwargs: Any) -> _MockAsyncStream:
        seen_provider_kwargs.update(kwargs)
        return _MockAsyncStream([_mock_stream_chunk("hello")])

    monkeypatch.setattr(
        "llm_client.core.client.litellm.stream_chunk_builder",
        lambda chunks: None,
    )
    monkeypatch.setattr("llm_client.core.client.litellm.acompletion", _stream)

    stream = await client.astream_llm(
        "gpt-4",
        [{"role": "user", "content": "Hi"}],
        task="test.lifecycle.istream",
        trace_id="trace.lifecycle.stream.async",
        budget_scope_trace_id="trace.lifecycle.stream.async",
        budget_scope_mode="reserved_concurrent",
        budget_reservation=0.01,
        max_budget=0.1,
        lifecycle_heartbeat_interval_s=0,
        lifecycle_stall_after_s=0,
    )
    out: list[str] = []
    async for chunk in stream:
        out.append(chunk)
    assert out == ["hello"]

    rows = _lifecycle_rows()
    assert [payload["llm_call_lifecycle"]["phase"] for _, payload in rows] == [
        "started",
        "progress",
        "completed",
    ]
    completed = rows[-1][1]["llm_call_lifecycle"]
    assert completed["progress_observable"] is True
    assert completed["progress_event_count"] == 1
    assert "budget_scope_trace_id" not in seen_provider_kwargs
    assert "budget_scope_mode" not in seen_provider_kwargs
    assert "budget_reservation" not in seen_provider_kwargs


@pytest.mark.asyncio
async def test_astream_llm_emits_failed_lifecycle_on_iteration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async iteration errors emit progress then failed lifecycle row."""

    async def _stream(**_: Any) -> _MockAsyncStream:
        return _MockAsyncStream([_mock_stream_chunk("part")], fail_after=True)

    monkeypatch.setattr(
        "llm_client.core.client.litellm.stream_chunk_builder",
        lambda chunks: None,
    )
    monkeypatch.setattr("llm_client.core.client.litellm.acompletion", _stream)

    stream = await client.astream_llm(
        "gpt-4",
        [{"role": "user", "content": "Hi"}],
        task="test.lifecycle.istream",
        trace_id="trace.lifecycle.stream.async.fail",
        max_budget=0.1,
        lifecycle_heartbeat_interval_s=0,
        lifecycle_stall_after_s=0,
    )
    out: list[str] = []
    with pytest.raises(RuntimeError, match="boom"):
        async for chunk in stream:
            out.append(chunk)

    rows = _lifecycle_rows()
    assert [payload["llm_call_lifecycle"]["phase"] for _, payload in rows] == [
        "started",
        "progress",
        "failed",
    ]
    failed = rows[-1][1]["llm_call_lifecycle"]
    assert failed["error_type"] == "RuntimeError"
    assert failed["error_message"] == "boom"
    assert failed["progress_observable"] is True
