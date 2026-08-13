"""Provider-free tests for exact raw structured-attempt artifacts."""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import os
from pathlib import Path
import stat
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from llm_client import acall_llm_structured, call_llm_structured, io_log
from llm_client.core.errors import LLMError
from llm_client.observability import get_budget_scope_snapshot
from llm_client.observability.raw_artifacts import (
    StructuredRawArtifactError,
    cleanup_structured_raw_artifacts,
    prepare_structured_raw_artifact_store,
    read_structured_raw_artifact,
    write_structured_raw_artifact,
)
from llm_client.observability.selected_attempts import (
    get_runtime_selected_attempt_receipt,
    get_runtime_selected_raw_content,
)
from llm_client.observability.structured_attempts import (
    get_structured_attempt_events,
)


class _Decision(BaseModel):
    """Minimal structured response for real runtime tests."""

    action: str


def _native_response(content: str) -> MagicMock:
    """Build one provider-shaped response while retaining the real runtime."""

    response = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = "stop"
    response.choices = [choice]
    response.usage.prompt_tokens = 1
    response.usage.completion_tokens = 1
    response.usage.total_tokens = 2
    return response


def _responses_response(content: str) -> MagicMock:
    """Build a Responses-API structured response for custody verification."""

    response = MagicMock()
    response.output_text = content
    response.status = "completed"
    response.output = []
    response.usage.input_tokens = 1
    response.usage.output_tokens = 1
    response.usage.total_tokens = 2
    response.usage.cost = None
    return response


@pytest.fixture(autouse=True)
def _isolated_observability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    """Use a real temporary SQLite database and sidecar root for every test."""

    old = (
        io_log._enabled,
        io_log._data_root,
        io_log._project,
        io_log._db_path,
        io_log._db_conn,
    )
    io_log._enabled = True
    io_log._data_root = tmp_path
    io_log._project = "raw-artifact-test"
    io_log._db_path = tmp_path / "attempts.db"
    io_log._db_conn = None
    monkeypatch.delenv("LLM_CLIENT_STRUCTURED_RAW_ARTIFACTS", raising=False)
    monkeypatch.setenv(
        "LLM_CLIENT_STRUCTURED_RAW_ARTIFACT_ROOT",
        str(tmp_path / "llm_client_structured_raw"),
    )
    monkeypatch.delenv("LLM_CLIENT_STRUCTURED_RAW_RETENTION_DAYS", raising=False)
    yield
    io_log.close()
    (
        io_log._enabled,
        io_log._data_root,
        io_log._project,
        io_log._db_path,
        io_log._db_conn,
    ) = old


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable exact raw artifacts for one isolated test."""

    monkeypatch.setenv("LLM_CLIENT_STRUCTURED_RAW_ARTIFACTS", "on")


def test_raw_artifacts_are_disabled_by_default(tmp_path: Path) -> None:
    """Default operation retains no raw sidecar and claims no replayability."""

    assert prepare_structured_raw_artifact_store() is False
    assert write_structured_raw_artifact("logical-1", 0, '{"action":"accept"}') is None
    assert not (tmp_path / "llm_client_structured_raw").exists()


# mock-ok: provider bytes are controlled; runtime lifecycle, SQLite joining, and
# sidecar reopening are real.
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.responses")
def test_responses_api_selected_output_has_exact_raw_custody(
    responses: MagicMock, _cost: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Responses structured output is replayable like Completions output."""

    _enable(monkeypatch)
    raw = '{\n"action":"accept"\n}'
    responses.return_value = _responses_response(raw)

    parsed, result = call_llm_structured(
        "gpt-5.6-terra",
        [{"role": "user", "content": "Choose"}],
        response_model=_Decision,
        task="raw-artifact.responses",
        trace_id="trace-raw-responses",
        max_budget=0,
        num_retries=0,
    )

    assert parsed.action == "accept"
    assert result.logical_call_id is not None
    receipt = get_runtime_selected_attempt_receipt(result.logical_call_id)
    selected = get_runtime_selected_raw_content(result.logical_call_id)
    events = get_structured_attempt_events(result.logical_call_id)
    assert [event.event_type for event in events] == [
        "started",
        "received",
        "validated",
    ]
    assert all(event.execution_path == "responses_api" for event in events)
    assert receipt.raw_artifact_ref is not None
    assert selected.raw_content == raw


# mock-ok: both provider responses are controlled while retry, persistence,
# aggregate cost, and selected-attempt reconciliation execute normally.
@patch(
    "llm_client.core.client.litellm.completion_cost",
    side_effect=[0.001, 0.002],
)
@patch("llm_client.core.client.litellm.responses")
def test_responses_api_validation_repair_retains_both_attempts_and_cost(
    responses: MagicMock, _cost: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A paid invalid response remains visible after successful repair."""

    _enable(monkeypatch)
    responses.side_effect = [
        _responses_response("{}"),
        _responses_response('{"action":"accept"}'),
    ]

    parsed, result = call_llm_structured(
        "gpt-5.6-terra",
        [{"role": "user", "content": "Choose"}],
        response_model=_Decision,
        task="raw-artifact.responses.repair",
        trace_id="trace-raw-responses-repair",
        max_budget=0,
        num_retries=1,
        base_delay=0,
        max_delay=0,
    )

    assert parsed.action == "accept"
    assert result.logical_call_id is not None
    assert result.cost == pytest.approx(0.003)
    assert result.cost_source == "attempt_aggregate"
    assert result.cost_covers_all_attempts is True
    events = get_structured_attempt_events(result.logical_call_id)
    assert [event.event_type for event in events] == [
        "started",
        "received",
        "validation_failed",
        "recovery_decided",
        "started",
        "received",
        "validated",
    ]
    assert events[3].recovery_decision == "retry"
    assert get_runtime_selected_raw_content(
        result.logical_call_id
    ).raw_content == '{"action":"accept"}'


# mock-ok: both paid provider responses are controlled while terminal failure,
# failed-row persistence, and durable reservation settlement execute normally.
@patch(
    "llm_client.core.client.litellm.completion_cost",
    side_effect=[0.001, 0.002],
)
@patch("llm_client.core.client.litellm.responses")
def test_terminal_validation_failure_retains_and_settles_complete_attempt_cost(
    responses: MagicMock, _cost: MagicMock
) -> None:
    """Exhausted repairs retain known spend without classifying as success."""

    responses.side_effect = [_responses_response("{}"), _responses_response("{}")]

    with pytest.raises(LLMError) as caught:
        call_llm_structured(
            "gpt-5.6-terra",
            [{"role": "user", "content": "Choose"}],
            response_model=_Decision,
            task="raw-artifact.responses.terminal",
            trace_id="trace-raw-responses-terminal",
            max_budget=0.1,
            num_retries=1,
            base_delay=0,
            max_delay=0,
            budget_scope_trace_id="trace-raw-responses-terminal",
            budget_scope_mode="reserved_concurrent",
            budget_reservation=0.01,
        )

    assert caught.value.cost == pytest.approx(0.003)
    assert caught.value.cost_source == "attempt_aggregate"
    assert caught.value.cost_covers_all_attempts is True
    row = io_log._get_db().execute(
        """SELECT cost, marginal_cost, cost_source, error, response
           FROM llm_calls WHERE trace_id = ? ORDER BY id DESC LIMIT 1""",
        ("trace-raw-responses-terminal",),
    ).fetchone()
    assert row[0] == pytest.approx(0.003)
    assert row[1] == pytest.approx(0.003)
    assert row[2] == "attempt_aggregate"
    assert row[3]
    assert row[4] == "{}"
    snapshot = get_budget_scope_snapshot(
        scope_trace_id="trace-raw-responses-terminal", max_budget=0.1
    )
    assert snapshot.settled_microusd == 3_000
    assert snapshot.active_reserved_microusd == 0


# mock-ok: async provider responses are controlled while the async runtime,
# terminal persistence, and outer budget wrapper remain real.
@pytest.mark.asyncio
@patch(
    "llm_client.core.client.litellm.completion_cost",
    side_effect=[0.001, 0.002],
)
@patch("llm_client.core.client.litellm.aresponses", new_callable=AsyncMock)
async def test_async_terminal_validation_failure_settles_complete_attempt_cost(
    responses: AsyncMock, _cost: MagicMock
) -> None:
    """Async terminal validation failure has identical cost custody."""

    responses.side_effect = [_responses_response("{}"), _responses_response("{}")]

    with pytest.raises(LLMError) as caught:
        await acall_llm_structured(
            "gpt-5.6-terra",
            [{"role": "user", "content": "Choose"}],
            response_model=_Decision,
            task="raw-artifact.responses.terminal.async",
            trace_id="trace-raw-responses-terminal-async",
            max_budget=0.1,
            num_retries=1,
            base_delay=0,
            max_delay=0,
            budget_scope_trace_id="trace-raw-responses-terminal-async",
            budget_scope_mode="reserved_concurrent",
            budget_reservation=0.01,
        )

    assert caught.value.cost == pytest.approx(0.003)
    assert caught.value.cost_covers_all_attempts is True
    snapshot = get_budget_scope_snapshot(
        scope_trace_id="trace-raw-responses-terminal-async", max_budget=0.1
    )
    assert snapshot.settled_microusd == 3_000
    assert snapshot.active_reserved_microusd == 0


# mock-ok: one priced response and one pre-response transport failure are
# controlled while partial-cost persistence and release semantics stay real.
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.responses")
def test_partial_terminal_attempt_cost_is_counted_without_settling_reservation(
    responses: MagicMock, _cost: MagicMock
) -> None:
    """Known partial spend is retained while incomplete custody releases."""

    responses.side_effect = [_responses_response("{}"), TimeoutError("provider timeout")]

    with pytest.raises(LLMError) as caught:
        call_llm_structured(
            "gpt-5.6-terra",
            [{"role": "user", "content": "Choose"}],
            response_model=_Decision,
            task="raw-artifact.responses.partial",
            trace_id="trace-raw-responses-partial",
            max_budget=0.1,
            num_retries=1,
            base_delay=0,
            max_delay=0,
            budget_scope_trace_id="trace-raw-responses-partial",
            budget_scope_mode="reserved_concurrent",
            budget_reservation=0.01,
        )

    assert caught.value.cost == pytest.approx(0.001)
    assert caught.value.cost_covers_all_attempts is False
    row = io_log._get_db().execute(
        """SELECT cost, error FROM llm_calls
           WHERE trace_id = ? ORDER BY id DESC LIMIT 1""",
        ("trace-raw-responses-partial",),
    ).fetchone()
    assert row[0] == pytest.approx(0.001)
    assert row[1]
    reservation = io_log._get_db().execute(
        """SELECT status, settled_cost_microusd FROM budget_reservations
           WHERE scope_trace_id = ?""",
        ("trace-raw-responses-partial",),
    ).fetchone()
    assert reservation == ("released_error", None)
    snapshot = get_budget_scope_snapshot(
        scope_trace_id="trace-raw-responses-partial", max_budget=0.1
    )
    assert snapshot.settled_microusd == 1_000
    assert snapshot.active_reserved_microusd == 0


# mock-ok: provider failure and response are controlled; fallback routing,
# logical ordinals, cost coverage, and custody execute normally.
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.002)
@patch("llm_client.core.client.litellm.responses")
@patch("llm_client.core.client.litellm.completion")
def test_responses_api_fallback_keeps_one_logical_attempt_history(
    completion: MagicMock,
    responses: MagicMock,
    _cost: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Responses model fallback preserves one contiguous custody history."""

    _enable(monkeypatch)
    responses.side_effect = TimeoutError("provider timeout")
    completion.return_value = _native_response('{"action":"accept"}')

    _parsed, result = call_llm_structured(
        "gpt-5.6-terra",
        [{"role": "user", "content": "Choose"}],
        response_model=_Decision,
        task="raw-artifact.responses.fallback",
        trace_id="trace-raw-responses-fallback",
        max_budget=0,
        num_retries=0,
        fallback_models=["deepseek/deepseek-chat"],
    )

    assert result.logical_call_id is not None
    assert result.cost == pytest.approx(0.002)
    assert result.cost_covers_all_attempts is False
    events = get_structured_attempt_events(result.logical_call_id)
    assert [event.attempt_ordinal for event in events] == [0, 0, 0, 1, 1, 1]
    assert [event.event_type for event in events] == [
        "started",
        "execution_failed",
        "recovery_decided",
        "started",
        "received",
        "validated",
    ]
    assert events[2].recovery_decision == "fallback"
    assert events[0].model != events[-1].model
    assert get_runtime_selected_raw_content(
        result.logical_call_id
    ).raw_content == '{"action":"accept"}'


# mock-ok: provider bytes are controlled; async runtime and custody are real.
@pytest.mark.asyncio
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.aresponses", new_callable=AsyncMock)
async def test_async_responses_api_selected_output_has_exact_raw_custody(
    responses: AsyncMock, _cost: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Async direct Responses output has the same custody contract."""

    _enable(monkeypatch)
    raw = '{"action":"accept"}'
    responses.return_value = _responses_response(raw)

    parsed, result = await acall_llm_structured(
        "gpt-5.6-terra",
        [{"role": "user", "content": "Choose"}],
        response_model=_Decision,
        task="raw-artifact.responses.async",
        trace_id="trace-raw-responses-async",
        max_budget=0,
        num_retries=0,
    )

    assert parsed.action == "accept"
    assert result.logical_call_id is not None
    assert get_runtime_selected_raw_content(result.logical_call_id).raw_content == raw
    assert [
        event.event_type
        for event in get_structured_attempt_events(result.logical_call_id)
    ] == ["started", "received", "validated"]


def test_enabled_store_requires_observability_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raw retention cannot create unjoined artifacts when metadata is disabled."""

    _enable(monkeypatch)
    io_log._enabled = False

    with pytest.raises(StructuredRawArtifactError, match="logging is disabled"):
        prepare_structured_raw_artifact_store()


def test_enabled_unwritable_root_blocks_before_provider_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Configuration failure occurs before controlled provider transport runs."""

    _enable(monkeypatch)
    invalid_root = tmp_path / "not-a-directory"
    invalid_root.write_text("occupied")
    monkeypatch.setenv("LLM_CLIENT_STRUCTURED_RAW_ARTIFACT_ROOT", str(invalid_root))

    # mock-ok: only provider transport is controlled; the pre-dispatch runtime is real.
    with patch("llm_client.core.client.litellm.completion") as completion:
        with pytest.raises(LLMError, match="artifact root"):
            call_llm_structured(
                "deepseek/deepseek-chat",
                [{"role": "user", "content": "Choose"}],
                response_model=_Decision,
                task="raw-artifact",
                trace_id="trace-readiness",
                max_budget=0,
                num_retries=0,
                fallback_models=["gemini/gemini-2.5-flash"],
            )
    completion.assert_not_called()


def test_invalid_retention_configuration_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown switches and non-positive retention never silently default."""

    monkeypatch.setenv("LLM_CLIENT_STRUCTURED_RAW_ARTIFACTS", "sometimes")
    with pytest.raises(StructuredRawArtifactError, match="expected on or off"):
        prepare_structured_raw_artifact_store()

    _enable(monkeypatch)
    monkeypatch.setenv("LLM_CLIENT_STRUCTURED_RAW_RETENTION_DAYS", "0")
    with pytest.raises(StructuredRawArtifactError, match="positive integer"):
        prepare_structured_raw_artifact_store()


def test_exact_bytes_permissions_and_duplicate_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Odd JSON formatting survives exactly in a private hash-bound sidecar."""

    _enable(monkeypatch)
    raw = ' {\n  "action"  :  "accept"\n}\n'

    first = write_structured_raw_artifact("logical-1", 0, raw)
    second = write_structured_raw_artifact("logical-1", 0, raw)

    assert first is not None
    assert second == first
    absolute_path = (
        Path(os.environ["LLM_CLIENT_STRUCTURED_RAW_ARTIFACT_ROOT"])
        / Path(*first.artifact_ref.split("/"))
    )
    observed = read_structured_raw_artifact(
        artifact_ref=first.artifact_ref,
        logical_call_id="logical-1",
        attempt_ordinal=0,
        expected_sha256=first.raw_sha256,
    )
    assert observed.decode("utf-8") == raw
    assert stat.S_IMODE(absolute_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(absolute_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(absolute_path.parent.parent.stat().st_mode) == 0o700


def test_existing_target_symlink_is_rejected_without_following(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A matching outside symlink cannot be accepted as a successful duplicate."""

    _enable(monkeypatch)
    raw = '{"action":"accept"}'
    stored = write_structured_raw_artifact("logical-1", 0, raw)
    assert stored is not None
    path = (
        Path(os.environ["LLM_CLIENT_STRUCTURED_RAW_ARTIFACT_ROOT"])
        / Path(*stored.artifact_ref.split("/"))
    )
    path.unlink()
    outside = tmp_path / "outside.raw"
    outside.write_text(raw)
    os.chmod(outside, 0o600)
    path.symlink_to(outside)

    with pytest.raises(StructuredRawArtifactError, match="not a regular file"):
        write_structured_raw_artifact("logical-1", 0, raw)


@pytest.mark.parametrize(
    "artifact_ref",
    [
        "/tmp/outside.raw",
        "../outside.raw",
        "v2/2026-07-14/key/0-" + "a" * 64 + ".raw",
        "v1/2026-99-99/" + "a" * 64 + "/0-" + "a" * 64 + ".raw",
        "v1/2026-07-14/wrong-key/0-" + "a" * 64 + ".raw",
        "v1/2026-07-14/" + "a" * 64 + "/1-" + "a" * 64 + ".raw",
    ],
)
def test_malformed_or_substituted_reference_rejects(
    monkeypatch: pytest.MonkeyPatch, artifact_ref: str
) -> None:
    """A caller cannot escape the root or substitute call/attempt identity."""

    _enable(monkeypatch)
    with pytest.raises(StructuredRawArtifactError):
        read_structured_raw_artifact(
            artifact_ref=artifact_ref,
            logical_call_id="logical-1",
            attempt_ordinal=0,
            expected_sha256="a" * 64,
        )


def test_missing_tampered_and_non_private_artifacts_reject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact reader never returns absent, changed, or exposed bytes."""

    _enable(monkeypatch)
    stored = write_structured_raw_artifact("logical-1", 0, '{"action":"accept"}')
    assert stored is not None
    absolute_path = (
        Path(os.environ["LLM_CLIENT_STRUCTURED_RAW_ARTIFACT_ROOT"])
        / Path(*stored.artifact_ref.split("/"))
    )

    absolute_path.write_bytes(b'{"action":"reject"}')
    with pytest.raises(StructuredRawArtifactError, match="SHA-256"):
        read_structured_raw_artifact(
            artifact_ref=stored.artifact_ref,
            logical_call_id="logical-1",
            attempt_ordinal=0,
            expected_sha256=stored.raw_sha256,
        )

    absolute_path.write_text('{"action":"accept"}')
    os.chmod(absolute_path, 0o644)
    with pytest.raises(StructuredRawArtifactError, match="permissions"):
        read_structured_raw_artifact(
            artifact_ref=stored.artifact_ref,
            logical_call_id="logical-1",
            attempt_ordinal=0,
            expected_sha256=stored.raw_sha256,
        )

    os.chmod(absolute_path, 0o600)
    artifact_root = Path(os.environ["LLM_CLIENT_STRUCTURED_RAW_ARTIFACT_ROOT"])
    os.chmod(artifact_root, 0o755)
    with pytest.raises(StructuredRawArtifactError, match="directory"):
        read_structured_raw_artifact(
            artifact_ref=stored.artifact_ref,
            logical_call_id="logical-1",
            attempt_ordinal=0,
            expected_sha256=stored.raw_sha256,
        )

    os.chmod(artifact_root, 0o700)
    absolute_path.unlink()
    with pytest.raises(StructuredRawArtifactError, match="missing"):
        read_structured_raw_artifact(
            artifact_ref=stored.artifact_ref,
            logical_call_id="logical-1",
            attempt_ordinal=0,
            expected_sha256=stored.raw_sha256,
        )


def test_retention_cleanup_removes_only_expired_date_directories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configured retention bounds raw data without deleting current content."""

    _enable(monkeypatch)
    monkeypatch.setenv("LLM_CLIENT_STRUCTURED_RAW_RETENTION_DAYS", "1")
    prepare_structured_raw_artifact_store()
    root = Path(os.environ["LLM_CLIENT_STRUCTURED_RAW_ARTIFACT_ROOT"]) / "v1"
    expired = root / (date.today() - timedelta(days=2)).isoformat()
    current = root / date.today().isoformat()
    expired.mkdir(parents=True)
    current.mkdir(parents=True, exist_ok=True)
    (expired / "old").write_text("old")
    (current / "current").write_text("current")

    prepare_structured_raw_artifact_store()

    assert not expired.exists()
    assert current.exists()


def test_reader_rejects_expired_reference_before_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retention is enforced on read even when an old file has not been cleaned."""

    _enable(monkeypatch)
    monkeypatch.setenv("LLM_CLIENT_STRUCTURED_RAW_RETENTION_DAYS", "1")
    stored = write_structured_raw_artifact("logical-1", 0, '{"action":"accept"}')
    assert stored is not None
    expired_day = (date.today() - timedelta(days=2)).isoformat()
    expired_ref = stored.artifact_ref.replace(date.today().isoformat(), expired_day)

    with pytest.raises(StructuredRawArtifactError, match="expired"):
        read_structured_raw_artifact(
            artifact_ref=expired_ref,
            logical_call_id="logical-1",
            attempt_ordinal=0,
            expected_sha256=stored.raw_sha256,
        )


def test_disabled_prepare_and_explicit_cleanup_remove_expired_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabling collection does not disable cleanup of retained data."""

    _enable(monkeypatch)
    monkeypatch.setenv("LLM_CLIENT_STRUCTURED_RAW_RETENTION_DAYS", "1")
    prepare_structured_raw_artifact_store()
    version_root = Path(os.environ["LLM_CLIENT_STRUCTURED_RAW_ARTIFACT_ROOT"]) / "v1"
    expired = version_root / (date.today() - timedelta(days=30)).isoformat()
    expired.mkdir(mode=0o700)
    (expired / "old.raw").write_text("old")
    monkeypatch.setenv("LLM_CLIENT_STRUCTURED_RAW_ARTIFACTS", "off")

    assert prepare_structured_raw_artifact_store() is False
    assert not expired.exists()

    expired.mkdir(mode=0o700)
    (expired / "old.raw").write_text("old")
    assert cleanup_structured_raw_artifacts() == 1
    assert not expired.exists()


# mock-ok: provider responses are controlled; runtime, retry, SQLite, and sidecars are real.
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.completion")
def test_sync_retry_returns_exact_selected_raw_content(
    completion: MagicMock,
    _cost: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A validation retry retains both artifacts and returns exact selected bytes."""

    _enable(monkeypatch)
    selected_raw = ' { "action" : "accept" }\n'
    completion.side_effect = [_native_response("{}"), _native_response(selected_raw)]

    _parsed, result = call_llm_structured(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "Choose"}],
        response_model=_Decision,
        task="raw-artifact",
        trace_id="trace-sync-raw",
        max_budget=0,
        num_retries=1,
        base_delay=0,
    )

    assert result.logical_call_id is not None
    received = [
        event
        for event in get_structured_attempt_events(result.logical_call_id)
        if event.event_type == "received"
    ]
    assert len(received) == 2
    assert all(event.raw_artifact_ref for event in received)
    selected = get_runtime_selected_raw_content(result.logical_call_id)
    assert selected.raw_content == selected_raw
    assert selected.selected_attempt_ordinal == 1


# mock-ok: provider response is controlled; runtime, SQLite, and exact reader are real.
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.completion")
def test_public_exact_reader_rejects_absent_artifact_reference(
    completion: MagicMock,
    _cost: MagicMock,
) -> None:
    """A call made with retention off cannot be projected as replayable."""

    completion.return_value = _native_response('{"action":"accept"}')
    _parsed, result = call_llm_structured(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "Choose"}],
        response_model=_Decision,
        task="raw-artifact",
        trace_id="trace-no-raw-ref",
        max_budget=0,
        num_retries=0,
    )

    assert result.logical_call_id is not None
    with pytest.raises(StructuredRawArtifactError, match="no raw artifact reference"):
        get_runtime_selected_raw_content(result.logical_call_id)


# mock-ok: provider response is controlled; artifact corruption and strict decode are real.
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.completion")
def test_public_exact_reader_rejects_non_utf8_selected_bytes(
    completion: MagicMock,
    _cost: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hash-valid corruption cannot bypass the public UTF-8 transport contract."""

    _enable(monkeypatch)
    completion.return_value = _native_response('{"action":"accept"}')
    _parsed, result = call_llm_structured(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "Choose"}],
        response_model=_Decision,
        task="raw-artifact",
        trace_id="trace-invalid-utf8",
        max_budget=0,
        num_retries=0,
    )
    assert result.logical_call_id is not None
    receipt = get_runtime_selected_attempt_receipt(result.logical_call_id)
    assert receipt.raw_artifact_ref is not None
    root = Path(os.environ["LLM_CLIENT_STRUCTURED_RAW_ARTIFACT_ROOT"])
    old_path = root / Path(*receipt.raw_artifact_ref.split("/"))
    invalid_bytes = b"\xff"
    invalid_sha256 = hashlib.sha256(invalid_bytes).hexdigest()
    invalid_ref = receipt.raw_artifact_ref.replace(receipt.raw_sha256, invalid_sha256)
    invalid_path = root / Path(*invalid_ref.split("/"))
    old_path.rename(invalid_path)
    invalid_path.write_bytes(invalid_bytes)
    os.chmod(invalid_path, 0o600)
    io_log._get_db().execute(
        """UPDATE structured_attempt_events
           SET raw_sha256 = ?, raw_artifact_ref = ?
           WHERE logical_call_id = ? AND event_type = 'received'""",
        (invalid_sha256, invalid_ref, result.logical_call_id),
    )
    io_log._get_db().commit()

    with pytest.raises(StructuredRawArtifactError, match="not valid UTF-8"):
        get_runtime_selected_raw_content(result.logical_call_id)


# mock-ok: provider failure/success are controlled; async fallback, SQLite, and sidecars are real.
@pytest.mark.asyncio
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
async def test_async_fallback_returns_exact_selected_raw_content(
    completion: AsyncMock,
    _cost: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The async model fallback preserves and selects the successful raw bytes."""

    _enable(monkeypatch)
    selected_raw = '{\n"action":"accept"\n}'
    completion.side_effect = [TimeoutError("provider timeout"), _native_response(selected_raw)]

    _parsed, result = await acall_llm_structured(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "Choose"}],
        response_model=_Decision,
        task="raw-artifact",
        trace_id="trace-async-raw",
        max_budget=0,
        num_retries=0,
        fallback_models=["gemini/gemini-2.5-flash"],
    )

    assert result.logical_call_id is not None
    selected = get_runtime_selected_raw_content(result.logical_call_id)
    assert selected.raw_content == selected_raw
    assert selected.selected_attempt_ordinal == 1
