"""Tests for shared call snapshot comparison and replay helpers."""

from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from llm_client import LRUCache, RetryPolicy, call_llm_structured, io_log
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


def test_snapshot_fingerprint_ignores_ephemeral_metadata() -> None:
    left = replay_module.build_call_snapshot(
        public_api="call_llm",
        call_kind="text",
        requested_model="gpt-5",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
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
        public_api="acall_llm",
        call_kind="text",
        requested_model="gpt-5",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
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

    assert replay_module.snapshot_fingerprint(left) == replay_module.snapshot_fingerprint(right)


def test_snapshot_marks_non_json_kwargs_as_replay_unsupported() -> None:
    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm",
        call_kind="text",
        requested_model="gpt-5",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref=None,
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


def test_compare_call_snapshots_reports_compact_differences() -> None:
    left = replay_module.build_call_snapshot(
        public_api="call_llm",
        call_kind="text",
        requested_model="gpt-5",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
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
    replay_module.replay_call_snapshot(call_id, trace_id="trace.strict.replay")

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
    replay_module.replay_call_snapshot(call_id, trace_id="trace.policy.replay")

    retry = captured["retry"]
    assert isinstance(retry, RetryPolicy)
    assert retry.max_retries == 0
    assert retry.base_delay == 1.0
    assert retry.max_delay == 30.0
    assert retry.retry_on is None
    assert captured["fallback_models"] == []
    assert "cache" in captured
    assert captured["cache"] is None


@patch("llm_client.execution.structured_runtime._model_supports_native_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.completion")
def test_runtime_snapshot_uses_effective_retry_and_disabled_cache(
    mock_completion: MagicMock,
    mock_cost: MagicMock,
    mock_supports: MagicMock,
) -> None:
    """The real structured runtime persists the effective policy passed by its caller."""

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = '{"value":"ok"}'
    response.choices[0].message.tool_calls = None
    response.choices[0].message.refusal = None
    response.choices[0].finish_reason = "stop"
    response.usage.prompt_tokens = 1
    response.usage.completion_tokens = 1
    response.usage.total_tokens = 2
    mock_completion.return_value = response

    call_llm_structured(
        "provider/native-model",
        [{"role": "user", "content": "hi"}],
        RuntimeReplayItem,
        num_retries=9,
        retry=RetryPolicy(max_retries=0),
        fallback_models=[],
        cache=None,
        structured_output_policy=StructuredOutputPolicy(
            mode="require_native_json_schema"
        ),
        task="test.runtime.snapshot",
        trace_id="trace.runtime.snapshot",
        max_budget=0,
    )

    db = io_log._get_db()
    row = db.execute(
        "SELECT call_snapshot FROM llm_calls WHERE trace_id = ? ORDER BY id DESC LIMIT 1",
        ("trace.runtime.snapshot",),
    ).fetchone()
    assert row is not None
    snapshot = json.loads(row[0])
    control = snapshot["request"]["control"]
    assert control["num_retries"] == 0
    assert control["retry_policy"]["max_retries"] == 0
    assert control["cache_policy"] == {"mode": "disabled"}
    assert control["fallback_models"] == []


def test_snapshot_marks_custom_retry_and_enabled_cache_replay_unsupported() -> None:
    """Replay refuses execution controls whose runtime state cannot be reconstructed."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="provider/native-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
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
        replay_module.replay_call_snapshot(call_id, trace_id="trace.unsupported.replay")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda control: control["retry_policy"].__setitem__("max_retries", "0"),
        lambda control: control.__setitem__("num_retries", 1),
        lambda control: control.__setitem__("fallback_models", "none"),
        lambda control: control.__setitem__("cache_policy", {}),
    ],
)
def test_replay_rejects_coerced_or_inconsistent_execution_policy(
    mutate: Callable[[dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typed replay refuses malformed or contradictory v2 execution policy state."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="provider/native-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
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

    with pytest.raises(ValueError, match="invalid replay-safe execution policy state"):
        replay_module.replay_call_snapshot(call_id, trace_id="trace.tampered.replay")


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
        replay_module.replay_call_snapshot(call_id, trace_id="trace.override.replay")


def test_replay_rejects_public_api_call_kind_mismatch() -> None:
    """V2 replay cannot reinterpret a structured snapshot as a text call."""

    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="provider/native-model",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
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
        replay_module.replay_call_snapshot(call_id, trace_id="trace.kind.replay")


def test_replay_call_snapshot_uses_new_trace_and_preserves_original_record(monkeypatch) -> None:
    snapshot = replay_module.build_call_snapshot(
        public_api="call_llm_structured",
        call_kind="structured",
        requested_model="gpt-5",
        messages=[{"role": "user", "content": "hi"}],
        prompt_ref="prompt@1",
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
