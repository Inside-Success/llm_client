"""Contract tests for durable outer application-run observability."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

import llm_client.io_log as io_log
from llm_client.observability.observed_runs import (
    ObservedRun,
    get_observed_run,
    list_observed_runs,
)


@pytest.fixture(autouse=True)
def _isolate_io_log(tmp_path: Path):
    """Keep observed-run evidence in a fresh database for every test."""

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

    yield

    io_log.close()
    io_log._enabled = old_enabled
    io_log._data_root = old_root
    io_log._project = old_project
    io_log._db_path = old_db_path
    io_log._db_conn = old_db_conn
    io_log._last_cleanup_date = old_last_cleanup


def _run(**overrides: object) -> ObservedRun:
    kwargs: dict[str, object] = {
        "project": "process_tracing",
        "operation": "central_claim_review",
        "executable": "scripts/review_central_claims.py",
        "run_id": "run_pt_review_1",
        "root_trace_id": "pt.review.1",
        "runtime_revision": "abc123",
        "config_sha256": "sha256:" + "a" * 64,
        "requested_model": "openrouter/openai/gpt-5.6-luna",
        "reasoning_effort": "medium",
        "max_budget": 0.05,
    }
    kwargs.update(overrides)
    return ObservedRun(**kwargs)  # type: ignore[arg-type]


def _record_linked_call(trace_id: str, *, phase: str = "started") -> None:
    io_log.record_call_lifecycle_event(
        {
            "event_id": f"evt_{trace_id.replace('/', '_')}_{phase}",
            "timestamp": "2026-07-29T00:00:00+00:00",
            "logical_call_id": "llmcall_linked",
            "trace_id": trace_id,
            "task": "process_tracing.central_claim_review",
            "phase": phase,
            "requested_model": "openrouter/openai/gpt-5.6-luna",
            "call_kind": "structured",
        }
    )


def test_start_is_durable_before_context_body() -> None:
    run = _run()

    record = get_observed_run(run.run_id)

    assert record.status == "running"
    assert record.ended_at is None
    assert record.root_trace_id == "pt.review.1"
    run.cancel(reason="test cleanup")


def test_running_query_reports_current_linked_call_count() -> None:
    run = _run()
    _record_linked_call(run.child_trace_id("in_flight"))

    assert get_observed_run(run.run_id).linked_call_count == 1
    assert list_observed_runs(status="running")[0].linked_call_count == 1
    run.cancel(reason="test cleanup")


def test_clean_context_exit_completes_run() -> None:
    with _run() as run:
        assert run.child_trace_id("verdict_h1") == "pt.review.1/verdict_h1"

    record = get_observed_run(run.run_id)
    assert record.status == "completed"
    assert record.ended_at is not None
    assert record.linked_call_count == 0


def test_early_context_completion_fails_instead_of_recording_false_success() -> None:
    with pytest.raises(RuntimeError, match="clean context exit"):
        with _run() as run:
            run.complete()

    assert get_observed_run(run.run_id).status == "failed_before_call_start"


def test_nested_context_restores_parent_lineage() -> None:
    from llm_client.observability.observed_runs import (
        _require_active_observed_run_child_trace,
    )

    with _run() as outer:
        _require_active_observed_run_child_trace(outer.child_trace_id("before"))
        with _run(run_id="run_inner", root_trace_id="pt.inner") as inner:
            _require_active_observed_run_child_trace(inner.child_trace_id("inside"))
            with pytest.raises(ValueError, match="run.child_trace_id"):
                _require_active_observed_run_child_trace(
                    outer.child_trace_id("blocked")
                )
        _require_active_observed_run_child_trace(outer.child_trace_id("after"))


def test_exception_before_call_is_persisted_and_propagated() -> None:
    with pytest.raises(ValueError, match="unknown target"):
        with _run() as run:
            run.set_phase("target_validation")
            raise ValueError("unknown target")

    record = get_observed_run(run.run_id)
    assert record.status == "failed_before_call_start"
    assert record.error_type == "ValueError"
    assert record.error_phase == "target_validation"
    assert record.error_message == "unknown target"
    assert record.linked_call_count == 0


def test_exception_after_linked_call_is_failed_after_call_start() -> None:
    with pytest.raises(RuntimeError, match="provider failed"):
        with _run() as run:
            run.set_phase("claim_review")
            _record_linked_call(run.child_trace_id("verdict_h1"))
            raise RuntimeError("provider failed")

    record = get_observed_run(run.run_id)
    assert record.status == "failed_after_call_start"
    assert record.linked_call_count == 1
    assert record.error_phase == "claim_review"


def test_explicit_cancellation_is_terminal() -> None:
    with _run() as run:
        run.cancel(reason="operator requested stop")

    record = get_observed_run(run.run_id)
    assert record.status == "cancelled"
    assert record.error_type == "Cancelled"
    assert record.error_message == "operator requested stop"


@pytest.mark.asyncio
async def test_async_cancellation_is_terminal_and_propagated() -> None:
    async def _cancelled() -> None:
        async with _run(run_id="run_async", root_trace_id="pt.async") as run:
            run.set_phase("awaiting_model")
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _cancelled()

    record = get_observed_run("run_async")
    assert record.status == "cancelled"
    assert record.error_phase == "awaiting_model"


@pytest.mark.parametrize(
    "segment",
    [
        "",
        " ",
        "/absolute",
        "trailing/",
        "two/segments",
        ".",
        "..",
        "bad segment",
        "x" * 129,
    ],
)
def test_child_trace_segment_rejects_ambiguous_lineage(segment: str) -> None:
    run = _run()
    with pytest.raises(ValueError, match="trace segment"):
        run.child_trace_id(segment)
    run.cancel(reason="test cleanup")


def test_duplicate_run_id_fails_loud() -> None:
    first = _run()
    with pytest.raises(sqlite3.IntegrityError):
        _run()
    first.cancel(reason="test cleanup")


@pytest.mark.parametrize("field", ["run_id", "root_trace_id"])
def test_run_identifiers_are_bounded(field: str) -> None:
    with pytest.raises(ValueError, match="at most 256 characters"):
        _run(**{field: "x" * 257})


def test_recent_runs_can_be_filtered_for_incomplete_work() -> None:
    running = _run()
    with _run(
        run_id="run_other_project",
        root_trace_id="other.trace",
        project="other_project",
    ):
        pass

    assert [record.run_id for record in list_observed_runs(status="running")] == [
        running.run_id
    ]
    assert list_observed_runs(project="other_project")[0].status == "completed"
    running.cancel(reason="test cleanup")


def test_terminal_transition_cannot_be_rewritten() -> None:
    run = _run()
    run.complete()
    with pytest.raises(RuntimeError, match="already terminal"):
        run.cancel(reason="too late")


def test_persistence_failure_is_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail_write(_: object) -> None:
        raise sqlite3.OperationalError("observability database is read-only")

    monkeypatch.setattr(io_log, "_run_db_write", _fail_write)

    with pytest.raises(sqlite3.OperationalError, match="read-only"):
        _run()


def test_error_message_rejects_sensitive_content_without_hiding_failure() -> None:
    with pytest.raises(ValueError, match="api_key"):
        with _run() as run:
            raise ValueError("api_key=secret-value")

    record = get_observed_run(run.run_id)
    assert record.status == "failed_before_call_start"
    assert record.error_type == "ValueError"
    assert record.error_message == "sensitive error detail redacted"
