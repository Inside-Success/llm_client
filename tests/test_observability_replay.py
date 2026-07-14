"""Tests for shared call snapshot comparison and replay helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path
import json
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from llm_client import (
    LRUCache,
    RetryPolicy,
    acall_llm,
    acall_llm_structured,
    call_llm,
    call_llm_structured,
    io_log,
)
from llm_client.execution.call_contracts import StructuredOutputPolicy
from llm_client.observability import replay as replay_module


@pytest.fixture(autouse=True)
def _isolate_io_log(tmp_path: Path):
    """Isolate observability state for replay-helper tests."""

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

    yield tmp_path

    io_log._enabled = old_enabled
    io_log._data_root = old_root
    io_log._project = old_project
    io_log._db_path = old_db_path
    if io_log._db_conn is not None:
        io_log._db_conn.close()
    io_log._db_conn = old_db_conn
    io_log._last_cleanup_date = old_last_cleanup


class ReplayItem:
    """Minimal module-level structured model for replay-path tests."""

    @classmethod
    def model_json_schema(cls) -> dict[str, object]:
        return {
            "title": "ReplayItem",
            "type": "object",
            "properties": {
                "value": {"type": "string", "description": "Replay value."},
            },
            "required": ["value"],
        }


class RuntimeReplayItem(BaseModel):
    """Importable strict response model for the real public-call snapshot test."""

    value: str


def _insert_call(snapshot: dict[str, object], *, response: str = "ok", error: str | None = None) -> int:
    """Insert one call row with snapshot metadata and return its call id."""

    result = MagicMock(
        content=response,
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        cost=0.0,
        finish_reason="stop",
    )
    io_log.log_call(
        model="resolved-model",
        messages=[{"role": "user", "content": "hi"}],
        result=result if error is None else None,
        error=RuntimeError(error) if error is not None else None,
        latency_s=0.1,
        caller="call_llm",
        task="test.task",
        trace_id="trace.original",
        prompt_ref="prompt@1",
        call_snapshot=snapshot,
        call_fingerprint=replay_module.snapshot_fingerprint(snapshot),
    )
    db = io_log._get_db()
    row = db.execute("SELECT MAX(id) FROM llm_calls").fetchone()
    assert row is not None and row[0] is not None
    return int(row[0])


def _provider_response(content: str) -> MagicMock:
    """Build the smallest provider-shaped response needed by runtime capture tests."""

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.choices[0].message.tool_calls = None
    response.choices[0].message.refusal = None
    response.choices[0].finish_reason = "stop"
    response.usage.prompt_tokens = 1
    response.usage.completion_tokens = 1
    response.usage.total_tokens = 2
    return response


def _latest_snapshot(trace_id: str) -> dict[str, Any]:
    """Read back the newest persisted call snapshot for one test trace."""

    row = io_log._get_db().execute(
        "SELECT call_snapshot FROM llm_calls WHERE trace_id = ? ORDER BY id DESC LIMIT 1",
        (trace_id,),
    ).fetchone()
    assert row is not None
    snapshot = json.loads(row[0])
    assert isinstance(snapshot, dict)
    return snapshot


def _latest_call_id(trace_id: str) -> int:
    """Return the newest persisted call id for one runtime trace."""

    row = io_log._get_db().execute(
        "SELECT id FROM llm_calls WHERE trace_id = ? ORDER BY id DESC LIMIT 1",
        (trace_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _snapshot_builder_kwargs() -> dict[str, Any]:
    """Return one complete text snapshot input before the v3 budget field."""

    return {
        "public_api": "call_llm",
        "call_kind": "text",
        "requested_model": "provider/text-model",
        "messages": [{"role": "user", "content": "hi"}],
        "prompt_ref": "prompt@1",
        "timeout": 60,
        "num_retries": 0,
        "reasoning_effort": None,
        "api_base": None,
        "base_delay": 1.0,
        "max_delay": 30.0,
        "retry_on": None,
        "fallback_models": [],
        "public_kwargs": {},
        "retry_policy": RetryPolicy(max_retries=0),
        "cache_policy": None,
        "execution_mode": "text",
    }


def _historical_v2_snapshot() -> dict[str, Any]:
    """Return a literal closed-v2 fixture independent of the current builder."""

    return {
        "snapshot_version": 2,
        "public_api": "call_llm",
        "call_kind": "text",
        "request": {
            "requested_model": "provider/text-model",
            "messages": [{"role": "user", "content": "hi"}],
            "prompt_ref": "prompt@1",
            "control": {
                "timeout": 60,
                "num_retries": 0,
                "reasoning_effort": None,
                "api_base": None,
                "base_delay": 1.0,
                "max_delay": 30.0,
                "retry_on": None,
                "fallback_models": [],
                "execution_mode": "text",
                "structured_output_mode": None,
                "retry_policy": {
                    "max_retries": 0,
                    "base_delay": 1.0,
                    "max_delay": 30.0,
                    "retry_on": None,
                    "on_retry": None,
                    "backoff": None,
                    "should_retry": None,
                },
                "cache_policy": {"mode": "disabled"},
            },
            "kwargs": {},
            "response_model_fqn": None,
            "response_model_schema": None,
        },
        "replay": {"unsupported_keys": []},
    }


def test_v3_snapshot_retains_budget_and_fingerprint_changes() -> None:
    """The effective spend ceiling is exact original-call identity in v3."""

    low = replay_module.build_call_snapshot(**_snapshot_builder_kwargs(), max_budget=0.2)
    high = replay_module.build_call_snapshot(**_snapshot_builder_kwargs(), max_budget=0.35)

    assert low["snapshot_version"] == 3
    assert low["request"]["control"]["max_budget"] == 0.2
    assert replay_module.snapshot_fingerprint(low) != replay_module.snapshot_fingerprint(high)


@pytest.mark.parametrize("value", ["0.35", -0.1, float("inf"), float("nan")])
def test_v3_snapshot_rejects_missing_or_invalid_budget(value: object) -> None:
    """V3 rejects absent, coerced, negative, and nonfinite budget state."""

    with pytest.raises(TypeError):
        replay_module.build_call_snapshot(**_snapshot_builder_kwargs())
    with pytest.raises(ValueError, match="max_budget"):
        replay_module.build_call_snapshot(**_snapshot_builder_kwargs(), max_budget=value)


# mock-ok: dispatch is replaced to verify historical envelope reads without provider I/O.
def test_historical_v1_v2_snapshots_remain_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Literal historical v1/v2 records retain their pre-v3 replay behavior."""

    captured_versions: list[int] = []

    def fake_text(*args: object, **kwargs: object) -> tuple[dict[str, str], str]:
        captured_versions.append(len(captured_versions) + 1)
        return {"value": "ok"}, "result"

    monkeypatch.setattr(replay_module, "_call_text_for_replay", fake_text)
    v2 = _historical_v2_snapshot()
    replay_module._ReplaySnapshotV2.model_validate(v2)
    v2_call_id = _insert_call(v2)
    replay_module.replay_call_snapshot(
        v2_call_id,
        trace_id="trace.historical.v2.replay",
        max_budget=0.1,
    )

    v1 = json.loads(json.dumps(v2))
    v1["snapshot_version"] = 1
    v1["request"]["control"].pop("retry_policy")
    v1["request"]["control"].pop("cache_policy")
    v1_call_id = _insert_call(v1)
    replay_module.replay_call_snapshot(
        v1_call_id,
        trace_id="trace.historical.v1.replay",
        max_budget=0.1,
    )
    assert captured_versions == [1, 2]


# mock-ok: dispatch is replaced to prove missing fresh authority fails before I/O.
def test_v3_replay_requires_fresh_explicit_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """A captured original budget cannot silently authorize a new v3 call."""

    snapshot = replay_module.build_call_snapshot(
        **_snapshot_builder_kwargs(), max_budget=0.35
    )
    call_id = _insert_call(snapshot)
    dispatched = False

    def fake_text(*args: object, **kwargs: object) -> tuple[dict[str, str], str]:
        nonlocal dispatched
        dispatched = True
        return {"value": "unexpected"}, "result"

    monkeypatch.setattr(replay_module, "_call_text_for_replay", fake_text)
    with pytest.raises(ValueError, match="fresh explicit max_budget"):
        replay_module.replay_call_snapshot(call_id, trace_id="trace.v3.no-budget")
    for invalid_budget in ("0.2", True, -0.1, float("inf"), float("nan")):
        with pytest.raises(ValueError, match="replay max_budget"):
            replay_module.replay_call_snapshot(
                call_id,
                trace_id="trace.v3.invalid-budget",
                max_budget=invalid_budget,
            )
    assert dispatched is False


# mock-ok: dispatch is replaced so captured and fresh budgets can be compared directly.
def test_v3_replay_dispatches_fresh_budget_not_captured_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replay validates original identity but dispatches under new spend authority."""

    snapshot = replay_module.build_call_snapshot(
        **_snapshot_builder_kwargs(), max_budget=0.35
    )
    call_id = _insert_call(snapshot)
    captured: dict[str, object] = {}

    def fake_text(*args: object, **kwargs: object) -> tuple[dict[str, str], str]:
        captured.update(kwargs)
        return {"value": "ok"}, "result"

    monkeypatch.setattr(replay_module, "_call_text_for_replay", fake_text)
    replay_module.replay_call_snapshot(
        call_id,
        trace_id="trace.v3.fresh-budget",
        max_budget=0.2,
    )
    assert snapshot["request"]["control"]["max_budget"] == 0.35
    assert captured["max_budget"] == 0.2


def test_snapshot_fingerprint_ignores_ephemeral_metadata() -> None:
    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm",
        call_kind="text",
        requested_model="gpt-5",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=2,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=None,
        public_kwargs={"temperature": 0},
    )
    with_ephemeral_metadata = json.loads(json.dumps(snapshot))
    with_ephemeral_metadata["captured_at"] = "2026-07-13T12:00:00Z"
    with_ephemeral_metadata["call_id"] = 123
    with_ephemeral_metadata["latency_s"] = 4.2

    assert replay_module.snapshot_fingerprint(snapshot) == replay_module.snapshot_fingerprint(
        with_ephemeral_metadata
    )


def test_v2_snapshot_fingerprint_includes_public_api() -> None:
    """Sync and async dispatch surfaces are material exact-replay identity."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm",
        call_kind="text",
        requested_model="gpt-5",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=None,
        public_kwargs={},
    )
    async_snapshot = json.loads(json.dumps(snapshot))
    async_snapshot["public_api"] = "acall_llm"

    assert replay_module.snapshot_fingerprint(snapshot) != replay_module.snapshot_fingerprint(
        async_snapshot
    )


def test_snapshot_marks_non_json_kwargs_as_replay_unsupported() -> None:
    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm",
        call_kind="text",
        requested_model="gpt-5",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref=None,
        max_budget=0.0,
        timeout=60,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=None,
        public_kwargs={"non_json": object()},
    )

    replay = snapshot["replay"]
    assert isinstance(replay, dict)
    assert replay["unsupported_keys"] == ["non_json"]


# mock-ok: dispatch is replaced to prove diagnostic message content fails before I/O.
def test_snapshot_marks_non_json_message_content_as_replay_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replay never dispatches a diagnostic summary in place of original message content."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm",
        call_kind="text",
        requested_model="gpt-5",
        messages=[{"role": "user", "content": object()}],
        prompt_ref=None,
        max_budget=0.0,
        timeout=60,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=None,
        public_kwargs={},
    )

    replay = snapshot["replay"]
    assert isinstance(replay, dict)
    assert replay["unsupported_keys"] == ["messages"]
    replay["unsupported_keys"] = []
    call_id = _insert_call(snapshot)
    monkeypatch.setattr(
        replay_module,
        "_call_text_for_replay",
        lambda *args, **kwargs: ({"value": "unexpected"}, "result"),
    )

    with pytest.raises(ValueError, match="replay-unsupported normalized value"):
        replay_module.replay_call_snapshot(call_id, trace_id="trace.message.lossy.replay", max_budget=0.0)


def test_compare_call_snapshots_reports_compact_differences() -> None:
    left = replay_module.build_call_snapshot(
        public_api="call_llm",
        call_kind="text",
        requested_model="gpt-5",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=2,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=None,
        public_kwargs={"temperature": 0},
    )
    right = replay_module.build_call_snapshot(
        public_api="call_llm",
        call_kind="text",
        requested_model="gpt-5",
        messages=[{"role": "user", "content": "different"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=2,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=None,
        public_kwargs={"temperature": 0},
    )

    left_id = _insert_call(left, response="left")
    right_id = _insert_call(right, response="right")

    report = replay_module.compare_call_snapshots(left_id, right_id)
    assert report["fingerprints_match"] is False
    assert any("request.messages[0].content" in diff for diff in report["request_differences"])
    assert "request:" in replay_module.format_call_diff(report)


def test_structured_output_mode_changes_snapshot_fingerprint() -> None:
    """Strict execution policy is caller-visible replay identity."""

    common = {
        "public_api": "call_llm_structured",
        "call_kind": "structured",
        "requested_model": "provider/native-model",
        "messages": [{"role": "user", "content": "hi"}],
        "prompt_ref": "prompt@1",
        "max_budget": 0.0,
        "timeout": 60,
        "num_retries": 0,
        "reasoning_effort": None,
        "api_base": None,
        "base_delay": 1.0,
        "max_delay": 30.0,
        "retry_on": None,
        "fallback_models": None,
        "public_kwargs": {},
        "response_model": ReplayItem,
    }
    automatic = replay_module.build_call_snapshot(
        **common,
        structured_output_mode="auto",
    )
    strict = replay_module.build_call_snapshot(
        **common,
        structured_output_mode="require_native_json_schema",
    )

    assert replay_module.snapshot_fingerprint(automatic) != replay_module.snapshot_fingerprint(
        strict
    )


# mock-ok: replay dispatch is replaced so reconstructed typed kwargs can be inspected.
def test_replay_restores_strict_structured_output_policy(monkeypatch) -> None:
    """Replay rebuilds the typed strict policy instead of forwarding provider data."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="provider/native-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=None,
        public_kwargs={},
        structured_output_mode="require_native_json_schema",
        response_model=ReplayItem,
    )
    call_id = _insert_call(snapshot)
    captured: dict[str, object] = {}

    def fake_structured(
        model: str,
        messages: list[dict[str, object]],
        response_model: type[object],
        **kwargs: object,
    ) -> tuple[dict[str, str], str]:
        captured.update(kwargs)
        return {"value": "ok"}, "result"

    monkeypatch.setattr(replay_module, "_call_structured_for_replay", fake_structured)
    replay_module.replay_call_snapshot(call_id, trace_id="trace.strict.replay", max_budget=0.0)

    policy = captured["structured_output_policy"]
    assert isinstance(policy, StructuredOutputPolicy)
    assert policy.mode == "require_native_json_schema"


def test_snapshot_records_effective_retry_and_disabled_cache() -> None:
    """Replay identity uses resolved retry policy rather than shadowed legacy values."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="provider/native-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=9,
        reasoning_effort=None,
        api_base=None,
        base_delay=9.0,
        max_delay=90.0,
        retry_on=["legacy"],
        fallback_models=[],
        public_kwargs={},
        retry_policy=RetryPolicy(
            max_retries=0,
            base_delay=0.25,
            max_delay=2.0,
            retry_on=["transient"],
        ),
        cache_policy=None,
        structured_output_mode="require_native_json_schema",
        response_model=ReplayItem,
    )

    control = snapshot["request"]["control"]
    assert control["num_retries"] == 0
    assert control["base_delay"] == 0.25
    assert control["max_delay"] == 2.0
    assert control["retry_on"] == ["transient"]
    assert control["retry_policy"] == {
        "max_retries": 0,
        "base_delay": 0.25,
        "max_delay": 2.0,
        "retry_on": ["transient"],
        "on_retry": None,
        "backoff": None,
        "should_retry": None,
    }
    assert control["cache_policy"] == {"mode": "disabled"}
    assert snapshot["replay"]["unsupported_keys"] == []


def test_replay_restores_effective_retry_fallback_and_disabled_cache(monkeypatch) -> None:
    """A v2 replay rebuilds the exact typed policy used by the original call."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="provider/native-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=2,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=[],
        public_kwargs={},
        retry_policy=RetryPolicy(max_retries=0),
        cache_policy=None,
        structured_output_mode="require_native_json_schema",
        response_model=ReplayItem,
    )
    call_id = _insert_call(snapshot)
    captured: dict[str, object] = {}

    def fake_structured(
        model: str,
        messages: list[dict[str, object]],
        response_model: type[object],
        **kwargs: object,
    ) -> tuple[dict[str, str], str]:
        captured.update(kwargs)
        return {"value": "ok"}, "result"

    monkeypatch.setattr(replay_module, "_call_structured_for_replay", fake_structured)
    replay_module.replay_call_snapshot(call_id, trace_id="trace.policy.replay", max_budget=0.0)

    retry = captured["retry"]
    assert isinstance(retry, RetryPolicy)
    assert retry.max_retries == 0
    assert retry.base_delay == 1.0
    assert retry.max_delay == 30.0
    assert retry.retry_on is None
    assert captured["fallback_models"] == []
    assert "cache" in captured
    assert captured["cache"] is None


# mock-ok: provider transport is replaced; the public runtime and SQLite snapshot are real.
@patch("llm_client.execution.structured_runtime._model_supports_native_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.completion")
def test_runtime_snapshot_uses_effective_retry_and_disabled_cache(
    mock_completion: MagicMock,
    mock_cost: MagicMock,
    mock_supports: MagicMock,
) -> None:
    """The real structured runtime persists the effective policy passed by its caller."""

    mock_completion.return_value = _provider_response('{"value":"ok"}')

    call_llm_structured(
        "provider/native-model",
        [{"role": "user", "content": "hi"}],
        RuntimeReplayItem,
        num_retries=9,
        retry=RetryPolicy(max_retries=0, base_delay=0.25, max_delay=2.0),
        fallback_models=["provider/fallback-b", "provider/fallback-a"],
        cache=None,
        structured_output_policy=StructuredOutputPolicy(
            mode="require_native_json_schema"
        ),
        task="test.runtime.snapshot",
        trace_id="trace.runtime.snapshot",
        max_budget=0,
    )

    snapshot = _latest_snapshot("trace.runtime.snapshot")
    control = snapshot["request"]["control"]
    assert control["num_retries"] == 0
    assert control["retry_policy"]["max_retries"] == 0
    assert control["retry_policy"]["base_delay"] == 0.25
    assert control["retry_policy"]["max_delay"] == 2.0
    assert control["cache_policy"] == {"mode": "disabled"}
    assert control["fallback_models"] == [
        "provider/fallback-b",
        "provider/fallback-a",
    ]


# mock-ok: provider transport is replaced; the public async runtime and SQLite snapshot are real.
@pytest.mark.asyncio
@patch("llm_client.execution.structured_runtime._model_supports_native_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
async def test_async_runtime_snapshot_uses_effective_retry_and_disabled_cache(
    mock_acompletion: AsyncMock,
    mock_cost: MagicMock,
    mock_supports: MagicMock,
) -> None:
    """The async structured runtime persists the same resolved policy as sync."""

    mock_acompletion.return_value = _provider_response('{"value":"ok"}')
    await acall_llm_structured(
        "provider/native-model",
        [{"role": "user", "content": "hi"}],
        RuntimeReplayItem,
        num_retries=9,
        retry=RetryPolicy(max_retries=0, base_delay=0.25, max_delay=2.0),
        fallback_models=["provider/fallback-b", "provider/fallback-a"],
        cache=None,
        structured_output_policy=StructuredOutputPolicy(
            mode="require_native_json_schema"
        ),
        task="test.async.runtime.snapshot",
        trace_id="trace.async.runtime.snapshot",
        max_budget=0,
    )

    control = _latest_snapshot("trace.async.runtime.snapshot")["request"]["control"]
    assert control["retry_policy"]["max_retries"] == 0
    assert control["retry_policy"]["base_delay"] == 0.25
    assert control["retry_policy"]["max_delay"] == 2.0
    assert control["fallback_models"] == [
        "provider/fallback-b",
        "provider/fallback-a",
    ]
    assert control["cache_policy"] == {"mode": "disabled"}
    assert control["structured_output_mode"] == "require_native_json_schema"


# mock-ok: provider transport is replaced; both public text runtimes persist real snapshots.
@pytest.mark.parametrize("is_async", [False, True])
@pytest.mark.asyncio
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
async def test_text_runtimes_snapshot_effective_retry_cache_and_execution_mode(
    mock_acompletion: AsyncMock,
    mock_cost: MagicMock,
    is_async: bool,
) -> None:
    """Sync and async text entry points persist replayable effective controls."""

    mock_acompletion.return_value = _provider_response("ok")
    trace_id = f"trace.text.runtime.snapshot.{is_async}"
    kwargs = {
        "num_retries": 9,
        "retry": RetryPolicy(max_retries=0, base_delay=0.25, max_delay=2.0),
        "fallback_models": ["provider/fallback-b", "provider/fallback-a"],
        "cache": None,
        "execution_mode": "text",
        "task": "test.text.runtime.snapshot",
        "trace_id": trace_id,
        "max_budget": 0,
    }
    if is_async:
        await acall_llm("provider/text-model", [{"role": "user", "content": "hi"}], **kwargs)
    else:
        call_llm("provider/text-model", [{"role": "user", "content": "hi"}], **kwargs)

    control = _latest_snapshot(trace_id)["request"]["control"]
    assert control["retry_policy"]["max_retries"] == 0
    assert control["retry_policy"]["base_delay"] == 0.25
    assert control["retry_policy"]["max_delay"] == 2.0
    assert control["fallback_models"] == [
        "provider/fallback-b",
        "provider/fallback-a",
    ]
    assert control["cache_policy"] == {"mode": "disabled"}
    assert control["execution_mode"] == "text"


@pytest.mark.parametrize(
    "public_api",
    ["call_llm", "acall_llm", "call_llm_structured", "acall_llm_structured"],
)
# mock-ok: provider transports are replaced; both public-runtime passes, persistence,
# fingerprint validation, envelope validation, and replay reconstruction are real.
def test_public_runtime_snapshots_round_trip_timeout_disabled(
    public_api: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every public producer must replay its real timeout-disabled snapshot."""

    sync_completion = MagicMock(return_value=_provider_response('{"value":"ok"}'))
    async_completion = AsyncMock(return_value=_provider_response('{"value":"ok"}'))
    monkeypatch.setattr("llm_client.core.client.litellm.completion", sync_completion)
    monkeypatch.setattr("llm_client.core.client.litellm.acompletion", async_completion)
    monkeypatch.setattr("llm_client.core.client.litellm.completion_cost", lambda *_args, **_kwargs: 0.001)
    monkeypatch.setattr(
        "llm_client.execution.structured_runtime._model_supports_native_schema",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "ban")

    trace_id = f"trace.timeout-disabled.{public_api}"
    common_kwargs = {
        "timeout": 60,
        "num_retries": 0,
        "retry": RetryPolicy(max_retries=0, base_delay=0.25, max_delay=2.0),
        "fallback_models": [],
        "cache": None,
        "task": "test.timeout-disabled.round-trip",
        "trace_id": trace_id,
        "max_budget": 0,
    }
    messages = [{"role": "user", "content": "hi"}]
    if public_api == "call_llm":
        call_llm("provider/text-model", messages, **common_kwargs)
    elif public_api == "acall_llm":
        asyncio.run(acall_llm("provider/text-model", messages, **common_kwargs))
    elif public_api == "call_llm_structured":
        call_llm_structured(
            "provider/native-model",
            messages,
            RuntimeReplayItem,
            structured_output_policy=StructuredOutputPolicy(
                mode="require_native_json_schema"
            ),
            **common_kwargs,
        )
    else:
        asyncio.run(
            acall_llm_structured(
                "provider/native-model",
                messages,
                RuntimeReplayItem,
                structured_output_policy=StructuredOutputPolicy(
                    mode="require_native_json_schema"
                ),
                **common_kwargs,
            )
        )

    call_id = _latest_call_id(trace_id)
    snapshot = _latest_snapshot(trace_id)
    assert snapshot["request"]["control"]["timeout"] == 0
    if public_api == "call_llm_structured":
        original_provider_kwargs = dict(sync_completion.call_args.kwargs)
    else:
        original_provider_kwargs = dict(async_completion.call_args.kwargs)

    sync_completion.reset_mock()
    async_completion.reset_mock()
    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "allow")

    replay_trace_id = f"trace.timeout-disabled.replay.{public_api}"
    replay_module.replay_call_snapshot(
        call_id,
        trace_id=replay_trace_id,
        max_budget=0.0,
    )

    assert _latest_snapshot(replay_trace_id) == snapshot
    if public_api == "call_llm_structured":
        sync_completion.assert_called_once()
        provider_kwargs = sync_completion.call_args.kwargs
    else:
        async_completion.assert_awaited_once()
        provider_kwargs = async_completion.call_args.kwargs
    assert {
        key: value for key, value in provider_kwargs.items() if key != "metadata"
    } == {
        key: value
        for key, value in original_provider_kwargs.items()
        if key != "metadata"
    }


@pytest.mark.parametrize(
    "public_api",
    ["call_llm", "acall_llm", "call_llm_structured", "acall_llm_structured"],
)
# mock-ok: provider transports are replaced; real public runtimes persist each snapshot.
def test_public_runtime_snapshots_retain_effective_budget_all_paths(
    public_api: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every text and structured sync/async producer captures its checked budget."""

    monkeypatch.setattr(
        "llm_client.core.client.litellm.completion",
        MagicMock(return_value=_provider_response('{"value":"ok"}')),
    )
    monkeypatch.setattr(
        "llm_client.core.client.litellm.acompletion",
        AsyncMock(return_value=_provider_response('{"value":"ok"}')),
    )
    monkeypatch.setattr(
        "llm_client.core.client.litellm.completion_cost",
        lambda *_args, **_kwargs: 0.001,
    )
    monkeypatch.setattr(
        "llm_client.execution.structured_runtime._model_supports_native_schema",
        lambda *_args, **_kwargs: True,
    )
    trace_id = f"trace.v3.budget.{public_api}"
    common_kwargs = {
        "num_retries": 0,
        "retry": RetryPolicy(max_retries=0),
        "fallback_models": [],
        "cache": None,
        "task": "test.v3.runtime-budget",
        "trace_id": trace_id,
        "max_budget": 0.35,
    }
    messages = [{"role": "user", "content": "hi"}]
    if public_api == "call_llm":
        call_llm("provider/text-model", messages, **common_kwargs)
    elif public_api == "acall_llm":
        asyncio.run(acall_llm("provider/text-model", messages, **common_kwargs))
    elif public_api == "call_llm_structured":
        call_llm_structured(
            "provider/native-model",
            messages,
            RuntimeReplayItem,
            structured_output_policy=StructuredOutputPolicy(
                mode="require_native_json_schema"
            ),
            **common_kwargs,
        )
    else:
        asyncio.run(
            acall_llm_structured(
                "provider/native-model",
                messages,
                RuntimeReplayItem,
                structured_output_policy=StructuredOutputPolicy(
                    mode="require_native_json_schema"
                ),
                **common_kwargs,
            )
        )

    snapshot = _latest_snapshot(trace_id)
    assert snapshot["snapshot_version"] == 3
    assert snapshot["request"]["control"]["max_budget"] == 0.35


@pytest.mark.parametrize(
    "value_factory",
    [
        pytest.param(lambda: Path("relative/path"), id="path"),
        pytest.param(lambda: ("a", "b"), id="tuple"),
        pytest.param(lambda: {"a", "b"}, id="set"),
        pytest.param(lambda: float("inf"), id="nonfinite-float"),
        pytest.param(lambda: {1: "value"}, id="non-string-mapping-key"),
        pytest.param(lambda: object(), id="opaque-object"),
        pytest.param(
            lambda: {"__type__": "builtins.object", "__repr__": "<object>"},
            id="legacy-diagnostic-shape",
        ),
        pytest.param(
            lambda: {
                "__llm_client_replay_unsupported__": {
                    "type": "builtins.object",
                    "reason": "diagnostic",
                    "repr": "<object>",
                }
            },
            id="current-diagnostic-shape",
        ),
    ],
)
# mock-ok: dispatch is replaced to prove lossy values fail before provider I/O.
def test_replay_rejects_lossy_normalization_when_support_metadata_is_empty(
    value_factory: Callable[[], object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Intrinsic diagnostics cannot be hidden by false-empty support metadata."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm",
        call_kind="text",
        requested_model="provider/text-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=[],
        public_kwargs={"custom": value_factory()},
        retry_policy=RetryPolicy(max_retries=0),
        cache_policy=None,
        execution_mode="text",
    )
    assert snapshot["replay"]["unsupported_keys"] == ["custom"]
    snapshot["replay"]["unsupported_keys"] = []
    call_id = _insert_call(snapshot)
    dispatched = False

    def fake_text(*args: object, **kwargs: object) -> tuple[dict[str, str], str]:
        nonlocal dispatched
        dispatched = True
        return {"value": "unexpected"}, "result"

    monkeypatch.setattr(replay_module, "_call_text_for_replay", fake_text)

    with pytest.raises(ValueError, match="replay-unsupported normalized value"):
        replay_module.replay_call_snapshot(call_id, trace_id="trace.lossy.replay", max_budget=0.0)
    assert dispatched is False


# mock-ok: dispatch is replaced so exact nested JSON kwargs can be compared directly.
def test_json_native_nested_kwargs_round_trip_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replay preserves recursively JSON-native values without false rejection."""

    nested = {"items": [1, 2.5, True, None, {"name": "value"}]}
    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm",
        call_kind="text",
        requested_model="provider/text-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=[],
        public_kwargs={"custom": nested},
        retry_policy=RetryPolicy(max_retries=0),
        cache_policy=None,
        execution_mode="text",
    )
    assert snapshot["replay"]["unsupported_keys"] == []
    call_id = _insert_call(snapshot)
    captured: dict[str, object] = {}

    def fake_text(
        model: str,
        replay_messages: list[dict[str, object]],
        **kwargs: object,
    ) -> tuple[dict[str, str], str]:
        captured.update(kwargs)
        return {"value": "ok"}, "result"

    monkeypatch.setattr(replay_module, "_call_text_for_replay", fake_text)
    replay_module.replay_call_snapshot(call_id, trace_id="trace.native-json.replay", max_budget=0.0)

    assert captured["custom"] == nested


def test_snapshot_marks_custom_retry_and_enabled_cache_replay_unsupported() -> None:
    """Replay refuses execution controls whose runtime state cannot be reconstructed."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="provider/native-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=2,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=[],
        public_kwargs={},
        retry_policy=RetryPolicy(max_retries=0, on_retry=lambda *_: None),
        cache_policy=LRUCache(),
        structured_output_mode="require_native_json_schema",
        response_model=ReplayItem,
    )

    assert snapshot["replay"]["unsupported_keys"] == [
        "cache_policy",
        "retry_policy.on_retry",
    ]
    call_id = _insert_call(snapshot)
    with pytest.raises(
        ValueError,
        match=r"cache_policy, retry_policy\.on_retry",
    ):
        replay_module.replay_call_snapshot(call_id, trace_id="trace.unsupported.replay", max_budget=0.0)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda control: control["retry_policy"].__setitem__("max_retries", "0"),
        lambda control: control.__setitem__("num_retries", 1),
        lambda control: control.__setitem__("fallback_models", "none"),
        lambda control: control.__setitem__("cache_policy", {}),
        lambda control: control.__setitem__("timeout", "60"),
        lambda control: control.__setitem__("timeout", -1),
        lambda control: control.__setitem__("unknown_control", True),
    ],
)
def test_replay_rejects_coerced_or_inconsistent_execution_policy(
    mutate: Callable[[dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typed replay refuses malformed or contradictory current execution policy state."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="provider/native-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=2,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=[],
        public_kwargs={},
        retry_policy=RetryPolicy(max_retries=0),
        cache_policy=None,
        structured_output_mode="require_native_json_schema",
        response_model=ReplayItem,
    )
    control = snapshot["request"]["control"]
    mutate(control)
    call_id = _insert_call(snapshot)
    monkeypatch.setattr(
        replay_module,
        "_call_structured_for_replay",
        lambda *args, **kwargs: ({"value": "unexpected"}, "result"),
    )

    with pytest.raises(
        ValueError,
        match="invalid replay-safe execution policy state|invalid v3 snapshot envelope",
    ):
        replay_module.replay_call_snapshot(call_id, trace_id="trace.tampered.replay", max_budget=0.0)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda control, request: control.__setitem__("structured_output_mode", None),
        lambda control, request: request["kwargs"].__setitem__("timeout", 999),
        lambda control, request: request["kwargs"].__setitem__(
            "structured_output_policy", {"mode": "auto"}
        ),
    ],
)
def test_replay_rejects_missing_structured_mode_or_reserved_public_control(
    mutate: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V2 replay authority cannot be removed or overridden through public kwargs."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="provider/native-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=[],
        public_kwargs={},
        retry_policy=RetryPolicy(max_retries=0),
        cache_policy=None,
        structured_output_mode="require_native_json_schema",
        response_model=ReplayItem,
    )
    request = snapshot["request"]
    mutate(request["control"], request)
    call_id = _insert_call(snapshot)
    monkeypatch.setattr(
        replay_module,
        "_call_structured_for_replay",
        lambda *args, **kwargs: ({"value": "unexpected"}, "result"),
    )

    with pytest.raises(ValueError, match="replay-safe execution policy|reserved"):
        replay_module.replay_call_snapshot(call_id, trace_id="trace.override.replay", max_budget=0.0)


def test_replay_rejects_public_api_call_kind_mismatch() -> None:
    """V2 replay cannot reinterpret a structured snapshot as a text call."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="provider/native-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=[],
        public_kwargs={},
        retry_policy=RetryPolicy(max_retries=0),
        cache_policy=None,
        structured_output_mode="require_native_json_schema",
        response_model=ReplayItem,
    )
    snapshot["call_kind"] = "text"
    call_id = _insert_call(snapshot)

    with pytest.raises(ValueError, match="requires call_kind='structured'"):
        replay_module.replay_call_snapshot(call_id, trace_id="trace.kind.replay", max_budget=0.0)


# mock-ok: replay dispatch is replaced so legacy reconstruction can be inspected without I/O.
def test_historical_v1_snapshot_replays_with_legacy_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuine v1 snapshot remains readable without v2 policy fields."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="provider/native-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=1,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=None,
        public_kwargs={},
        structured_output_mode=None,
        response_model=ReplayItem,
    )
    snapshot["snapshot_version"] = 1
    control = snapshot["request"]["control"]
    control.pop("retry_policy")
    control.pop("cache_policy")
    call_id = _insert_call(snapshot)
    captured: dict[str, object] = {}

    def fake_structured(
        model: str,
        messages: list[dict[str, object]],
        response_model: type[object],
        **kwargs: object,
    ) -> tuple[dict[str, str], str]:
        captured.update(kwargs)
        return {"value": "ok"}, "result"

    monkeypatch.setattr(replay_module, "_call_structured_for_replay", fake_structured)
    replay_module.replay_call_snapshot(call_id, trace_id="trace.v1.replay", max_budget=0.0)

    assert captured["num_retries"] == 1
    assert "retry" not in captured
    assert "cache" not in captured
    assert "structured_output_policy" not in captured


@pytest.mark.parametrize(
    "mutate",
    [
        lambda snapshot: snapshot.__setitem__("snapshot_version", 1),
        lambda snapshot: snapshot.__setitem__("replay", {}),
        lambda snapshot: snapshot.__setitem__("replay", {"unsupported_keys": "none"}),
        lambda snapshot: (
            snapshot.__setitem__("public_api", "call_llm"),
            snapshot.__setitem__("call_kind", "text"),
        ),
    ],
)
# mock-ok: dispatch is replaced to prove malformed envelopes fail before provider I/O.
def test_v2_replay_rejects_downgrade_missing_metadata_or_cross_kind_reinterpretation(
    mutate: Callable[[dict[str, Any]], object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V2 replay cannot shed the policy fields that distinguish it from v1."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="provider/native-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=[],
        public_kwargs={},
        retry_policy=RetryPolicy(max_retries=0),
        cache_policy=None,
        structured_output_mode="require_native_json_schema",
        response_model=ReplayItem,
    )
    mutate(snapshot)
    call_id = _insert_call(snapshot)
    monkeypatch.setattr(
        replay_module,
        "_call_structured_for_replay",
        lambda *args, **kwargs: ({"value": "unexpected"}, "result"),
    )
    monkeypatch.setattr(
        replay_module,
        "_call_text_for_replay",
        lambda *args, **kwargs: ({"value": "unexpected"}, "result"),
    )

    with pytest.raises(ValueError, match="snapshot_version|replay metadata|structured"):
        replay_module.replay_call_snapshot(call_id, trace_id="trace.v2.guard.replay", max_budget=0.0)


def test_v2_replay_rejects_persisted_snapshot_fingerprint_mismatch() -> None:
    """Replay refuses a persisted v2 request whose stored fingerprint no longer matches."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="provider/native-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=[],
        public_kwargs={},
        retry_policy=RetryPolicy(max_retries=0),
        cache_policy=None,
        structured_output_mode="require_native_json_schema",
        response_model=ReplayItem,
    )
    call_id = _insert_call(snapshot)
    snapshot["request"]["control"]["timeout"] = 999
    io_log._get_db().execute(
        "UPDATE llm_calls SET call_snapshot = ? WHERE id = ?",
        (json.dumps(snapshot, sort_keys=True), call_id),
    )
    io_log._get_db().commit()

    with pytest.raises(ValueError, match="fingerprint"):
        replay_module.replay_call_snapshot(call_id, trace_id="trace.fingerprint.replay", max_budget=0.0)


# mock-ok: dispatch is replaced so a guard regression cannot issue a provider call.
def test_v2_replay_rejects_persisted_full_version_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stored v2 record cannot become a shape-valid v1 record after persistence."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="provider/native-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=[],
        public_kwargs={},
        retry_policy=RetryPolicy(max_retries=0),
        cache_policy=None,
        structured_output_mode="require_native_json_schema",
        response_model=ReplayItem,
    )
    call_id = _insert_call(snapshot)
    snapshot["snapshot_version"] = 1
    control = snapshot["request"]["control"]
    control.pop("retry_policy")
    control.pop("cache_policy")
    io_log._get_db().execute(
        "UPDATE llm_calls SET call_snapshot = ? WHERE id = ?",
        (json.dumps(snapshot, sort_keys=True), call_id),
    )
    io_log._get_db().commit()
    monkeypatch.setattr(
        replay_module,
        "_call_structured_for_replay",
        lambda *args, **kwargs: ({"value": "unexpected"}, "result"),
    )

    with pytest.raises(ValueError, match="fingerprint"):
        replay_module.replay_call_snapshot(call_id, trace_id="trace.downgrade.replay", max_budget=0.0)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda snapshot: snapshot.pop("public_api"),
        lambda snapshot: snapshot["request"].__setitem__("unmodeled_state", "value"),
    ],
)
# mock-ok: dispatch is replaced to prove invalid fixed-envelope state cannot reach I/O.
def test_v2_replay_rejects_missing_or_unmodeled_envelope_state(
    mutate: Callable[[dict[str, Any]], object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fixed v2 envelope cannot default or ignore replay-relevant state."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm",
        call_kind="text",
        requested_model="provider/native-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=[],
        public_kwargs={},
        retry_policy=RetryPolicy(max_retries=0),
        cache_policy=None,
        execution_mode="text",
    )
    mutate(snapshot)
    call_id = _insert_call(snapshot)
    monkeypatch.setattr(
        replay_module,
        "_call_text_for_replay",
        lambda *args, **kwargs: ({"value": "unexpected"}, "result"),
    )

    with pytest.raises(ValueError, match="snapshot envelope"):
        replay_module.replay_call_snapshot(call_id, trace_id="trace.envelope.replay", max_budget=0.0)


# mock-ok: dispatch is replaced to prove schema drift fails before provider I/O.
def test_v2_replay_rejects_response_model_schema_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A class name cannot hide a changed structured response contract on replay."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="provider/native-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=[],
        public_kwargs={},
        retry_policy=RetryPolicy(max_retries=0),
        cache_policy=None,
        structured_output_mode="require_native_json_schema",
        response_model=ReplayItem,
    )
    snapshot["request"]["response_model_schema"] = {
        "title": "ReplayItem",
        "type": "object",
        "properties": {"changed": {"type": "integer"}},
        "required": ["changed"],
    }
    call_id = _insert_call(snapshot)
    monkeypatch.setattr(
        replay_module,
        "_call_structured_for_replay",
        lambda *args, **kwargs: ({"value": "unexpected"}, "result"),
    )

    with pytest.raises(ValueError, match="schema no longer matches"):
        replay_module.replay_call_snapshot(call_id, trace_id="trace.schema-drift.replay", max_budget=0.0)


# mock-ok: replay dispatch is replaced so reconstructed capability kwargs can be inspected.
def test_v2_text_replay_restores_execution_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """A text replay retains the recorded capability contract instead of defaulting."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm",
        call_kind="text",
        requested_model="claude-code/opus",
        messages=[{"role": "user", "content": "inspect workspace"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=[],
        public_kwargs={"allowed_tools": ["Read"]},
        retry_policy=RetryPolicy(max_retries=0),
        cache_policy=None,
        execution_mode="workspace_agent",
    )
    call_id = _insert_call(snapshot)
    captured: dict[str, object] = {}

    def fake_text(
        model: str,
        messages: list[dict[str, object]],
        **kwargs: object,
    ) -> tuple[dict[str, str], str]:
        captured.update(kwargs)
        return {"value": "ok"}, "result"

    monkeypatch.setattr(replay_module, "_call_text_for_replay", fake_text)
    replay_module.replay_call_snapshot(call_id, trace_id="trace.execution-mode.replay", max_budget=0.0)

    assert captured["execution_mode"] == "workspace_agent"
    assert captured["allowed_tools"] == ["Read"]


def test_replay_call_snapshot_uses_new_trace_and_preserves_original_record(monkeypatch) -> None:
    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="gpt-5",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
        max_budget=0.0,
        timeout=60,
        num_retries=1,
        reasoning_effort=None,
        api_base=None,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=None,
        fallback_models=None,
        public_kwargs={"temperature": 0},
        structured_output_mode="auto",
        response_model=ReplayItem,
    )
    call_id = _insert_call(snapshot)

    captured: dict[str, object] = {}

    def fake_structured(model: str, messages: list[dict[str, object]], response_model: type[object], **kwargs: object) -> tuple[dict[str, str], str]:
        captured["model"] = model
        captured["messages"] = messages
        captured["response_model"] = response_model
        captured["kwargs"] = kwargs
        return {"value": "ok"}, "result"

    monkeypatch.setattr(replay_module, "_call_structured_for_replay", fake_structured)

    result = replay_module.replay_call_snapshot(
        call_id,
        trace_id="trace.replay",
        task="task.replay",
        max_budget=0.0,
        project="project.replay",
    )

    assert result["source_call_id"] == call_id
    assert captured["model"] == "gpt-5"
    assert captured["response_model"] is ReplayItem
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["trace_id"] == "trace.replay"
    assert kwargs["task"] == "task.replay"
    original = replay_module.get_call_record(call_id)
    assert original["trace_id"] == "trace.original"
    assert original["project"] == "test_project"
