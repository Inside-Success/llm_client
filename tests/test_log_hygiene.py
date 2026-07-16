"""Log-hygiene gates (Session 35): timeout-policy spam, provider finish_reason
masking, retry-log diagnostics, LoggingWorker noise filter.

Five noise/correctness classes diagnosed from a real CI engine log. Each test
class below is one gate from the session brief.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from llm_client.core.client import call_llm_structured


class _Item(BaseModel):
    name: str


def _mock_response(
    content: str = '{"name": "x"}',
    finish_reason: str = "stop",
    provider_specific_fields: dict | None = None,
) -> MagicMock:
    """Build a mock litellm completion response."""
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = content
    mock.choices[0].message.tool_calls = None
    mock.choices[0].message.refusal = None
    mock.choices[0].finish_reason = finish_reason
    mock.choices[0].provider_specific_fields = provider_specific_fields
    mock.usage.prompt_tokens = 10
    mock.usage.completion_tokens = 5
    mock.usage.total_tokens = 15
    return mock


@pytest.fixture(autouse=True)
def _reset_timeout_warning_state():
    """Isolate the once-per-caller TIMEOUT_DISABLED dedup between tests."""
    from llm_client.execution import timeout_policy

    timeout_policy._reset_timeout_disabled_warning_state()
    yield
    timeout_policy._reset_timeout_disabled_warning_state()


def _timeout_disabled_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "TIMEOUT_DISABLED" in r.getMessage()]


@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.completion")
class TestTimeoutDisabledSpam:
    """FIX 1: library-default timeouts must not warn under policy=ban."""

    def _call(self, mock_completion, *, timeout=None, trace_id: str = "t35-fix1"):
        mock_completion.return_value = _mock_response()
        kwargs = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        return call_llm_structured(
            "gpt-4o",
            [{"role": "user", "content": "Extract"}],
            response_model=_Item,
            task="test",
            trace_id=trace_id,
            max_budget=0,
            **kwargs,
        )

    def test_ban_with_default_timeout_logs_nothing(
        self, mock_completion, mock_cost, mock_supports, monkeypatch, caplog
    ) -> None:
        """Gate (a): 50 sequential structured calls, timeout unset, policy=ban
        -> ZERO TIMEOUT_DISABLED records (not even DEBUG)."""
        monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "ban")
        with caplog.at_level(logging.DEBUG):
            for i in range(50):
                result, meta = self._call(mock_completion, trace_id=f"t35-fix1-a-{i}")
                assert result.name == "x"
        assert _timeout_disabled_records(caplog) == []
        # The banned default must not resurrect a request timeout: the call
        # goes out with the safety ceiling, exactly as before this fix.
        assert mock_completion.call_args.kwargs["timeout"] == 300

    def test_ban_with_explicit_timeout_warns_once_per_caller(
        self, mock_completion, mock_cost, mock_supports, monkeypatch, caplog
    ) -> None:
        """Gate (b): explicit timeout=60 under ban -> exactly ONE warning for
        the caller across repeated calls (repeats at DEBUG)."""
        monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "ban")
        with caplog.at_level(logging.DEBUG):
            for i in range(5):
                self._call(mock_completion, timeout=60, trace_id=f"t35-fix1-b-{i}")
        records = _timeout_disabled_records(caplog)
        warnings = [r for r in records if r.levelno == logging.WARNING]
        debugs = [r for r in records if r.levelno == logging.DEBUG]
        assert len(warnings) == 1
        assert "call_llm_structured" in warnings[0].getMessage()
        assert len(debugs) == 4

    def test_allow_fills_default_and_logs_nothing(
        self, mock_completion, mock_cost, mock_supports, monkeypatch, caplog
    ) -> None:
        """Gate (c): policy=allow behavior unchanged — the structured default
        (180s) is filled and forwarded, no TIMEOUT_DISABLED records."""
        monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "allow")
        monkeypatch.delenv("LLM_CLIENT_DEFAULT_STRUCTURED_TIMEOUT", raising=False)
        with caplog.at_level(logging.DEBUG):
            self._call(mock_completion, trace_id="t35-fix1-c")
        assert _timeout_disabled_records(caplog) == []
        assert mock_completion.call_args.kwargs["timeout"] == 180


def _retry_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "attempt 1/" in r.getMessage() and "failed" in r.getMessage()]


@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
class TestProviderFinishReasonMasking:
    """FIX 2: finish_reason='error' masked as 'stop' by litellm must be a
    retryable provider error, not a downstream schema dump."""

    def _messages(self):
        return [{"role": "user", "content": "Extract"}]

    @patch("llm_client.core.client.litellm.completion")
    def test_sync_provider_error_is_retried_with_clean_line(
        self, mock_completion, mock_cost, mock_supports, caplog
    ) -> None:
        """Gate (a): finish_reason='error' (raw, preserved by litellm in
        provider_specific_fields) + truncated JSON -> retried as
        source=provider, next attempt succeeds, ONE clean line, no schema dump."""
        bad = _mock_response(
            content='{"name": "trunca',
            finish_reason="stop",  # litellm's normalization output
            provider_specific_fields={"native_finish_reason": "error"},
        )
        good = _mock_response()
        mock_completion.side_effect = [bad, good]

        with caplog.at_level(logging.DEBUG):
            result, meta = call_llm_structured(
                "gpt-4o",
                self._messages(),
                response_model=_Item,
                task="t35-task",
                trace_id="t35-fix2-sync",
                max_budget=0,
                base_delay=0.0,
                max_delay=0.0,
            )

        assert result.name == "x"
        retries = _retry_records(caplog)
        assert len(retries) == 1
        line = retries[0].getMessage()
        assert "source=provider" in line
        # Routing may normalize the model id (e.g. openrouter/openai/gpt-4o);
        # the line must carry a non-empty model= either way.
        assert "model=" in line and "gpt-4o" in line
        assert "task=t35-task" in line
        assert "finish_reason='error'" in line
        assert '"$defs"' not in line and '"properties"' not in line
        assert len(line) < 400

    @patch("llm_client.core.client.litellm.completion")
    def test_sync_schema_failure_stays_distinguishable(
        self, mock_completion, mock_cost, mock_supports, caplog
    ) -> None:
        """Gate (b): normal 'stop' + schema-invalid JSON still surfaces as a
        validation failure — the two classes stay distinguishable."""
        bad = _mock_response(content='{"wrong_field": 1}')
        good = _mock_response()
        mock_completion.side_effect = [bad, good]

        with caplog.at_level(logging.DEBUG):
            result, _ = call_llm_structured(
                "gpt-4o",
                self._messages(),
                response_model=_Item,
                task="test",
                trace_id="t35-fix2-schema",
                max_budget=0,
                base_delay=0.0,
                max_delay=0.0,
            )

        assert result.name == "x"
        retries = _retry_records(caplog)
        assert len(retries) == 1
        line = retries[0].getMessage()
        assert "_StructuredValidationRetry" in line
        assert "provider reported finish_reason" not in line

    @patch("llm_client.core.client.litellm.acompletion")
    def test_async_provider_error_is_retried(
        self, mock_acompletion, mock_cost, mock_supports, caplog
    ) -> None:
        """Gate (c): the async path classifies and retries identically."""
        import asyncio

        from llm_client.core.client import acall_llm_structured

        bad = _mock_response(
            content='{"name": "trunca',
            finish_reason="stop",
            provider_specific_fields={"native_finish_reason": "error"},
        )
        good = _mock_response()

        async def _fake_acompletion(**kwargs):
            return _fake_acompletion.responses.pop(0)

        _fake_acompletion.responses = [bad, good]
        mock_acompletion.side_effect = _fake_acompletion

        async def _run():
            return await acall_llm_structured(
                "gpt-4o",
                self._messages(),
                response_model=_Item,
                task="t35-task",
                trace_id="t35-fix2-async",
                max_budget=0,
                base_delay=0.0,
                max_delay=0.0,
            )

        with caplog.at_level(logging.DEBUG):
            result, _ = asyncio.run(_run())

        assert result.name == "x"
        retries = _retry_records(caplog)
        assert len(retries) == 1
        line = retries[0].getMessage()
        assert "source=provider" in line
        assert "finish_reason='error'" in line

    def test_provider_error_reports_provider_delay_source(
        self, mock_cost, mock_supports
    ) -> None:
        """The failure-source classifier reports source=provider, not none."""
        from llm_client.core.errors import LLMProviderResponseError
        from llm_client.execution.retry import RetryPolicy, _compute_retry_delay, _is_retryable

        err = LLMProviderResponseError("provider reported finish_reason='error'")
        assert _is_retryable(err) is True
        _, source = _compute_retry_delay(
            attempt=0,
            error=err,
            policy=RetryPolicy(max_retries=2),
            backoff_fn=lambda attempt, base, cap: 0.0,
        )
        assert source == "provider"


@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.completion")
class TestRetryLogDiagnostics:
    """FIX 3: retry lines carry the model id and never dump the full schema."""

    def test_schema_validation_retry_line_is_compact(
        self, mock_completion, mock_cost, mock_supports, caplog
    ) -> None:
        import json as _json

        from litellm import JSONSchemaValidationError

        big_schema = {
            "title": "ClaimLedger",
            "type": "object",
            "properties": {f"field_{i}": {"type": "string", "description": "x" * 40} for i in range(30)},
            "$defs": {"Inner": {"type": "object", "properties": {"v": {"type": "integer"}}}},
        }
        # litellm's validate_schema raises with model="" — the empty `model=,`
        # from the attempt-4 log — and embeds the ENTIRE schema in str(error).
        schema_error = JSONSchemaValidationError(
            model="",
            llm_provider="",
            raw_response='{"claims": [{"id": "C-1", "text": "' + "y" * 500 + '"}]}',
            schema=_json.dumps(big_schema),
        )
        assert len(str(schema_error)) > 2000  # the noise this fix removes

        mock_completion.side_effect = [schema_error, _mock_response()]

        with caplog.at_level(logging.DEBUG):
            result, _ = call_llm_structured(
                "openrouter/qwen/qwen3-235b-a22b",
                [{"role": "user", "content": "Extract"}],
                response_model=_Item,
                task="test",
                trace_id="t35-fix3",
                max_budget=0,
                base_delay=0.0,
                max_delay=0.0,
            )

        assert result.name == "x"
        retries = _retry_records(caplog)
        assert len(retries) == 1
        line = retries[0].getMessage()
        assert "model=openrouter/qwen/qwen3-235b-a22b" in line
        assert '"$defs"' not in line
        assert '"properties"' not in line
        assert "schema=ClaimLedger" in line
        assert len(line) < 400


class TestLiteLLMLoggingWorkerNoiseFilter:
    """FIX 4: suppress ONLY LoggingWorker CancelledError/TimeoutError
    tracebacks on the 'LiteLLM' logger; everything else passes through."""

    _WORKER_PATH = "/site-packages/litellm/litellm_core_utils/logging_worker.py"

    def _record(
        self,
        *,
        pathname: str,
        msg: str,
        exc: BaseException | None,
    ) -> logging.LogRecord:
        exc_info = (type(exc), exc, None) if exc is not None else None
        return logging.LogRecord(
            name="LiteLLM",
            level=logging.ERROR,
            pathname=pathname,
            lineno=103,
            msg=msg,
            args=(),
            exc_info=exc_info,
        )

    def _emit_through_logger(self, record: logging.LogRecord) -> list[logging.LogRecord]:
        """Send a record through the real 'LiteLLM' logger (where llm_client
        installs the filter at import) and capture what survives."""
        import llm_client  # noqa: F401 — importing installs the filter

        captured: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, rec: logging.LogRecord) -> None:
                captured.append(rec)

        target = logging.getLogger("LiteLLM")
        handler = _Capture(level=logging.DEBUG)
        old_level = target.level
        target.addHandler(handler)
        target.setLevel(logging.DEBUG)
        try:
            target.handle(record)
        finally:
            target.removeHandler(handler)
            target.setLevel(old_level)
        return captured

    def test_cancellation_family_is_suppressed(self) -> None:
        import asyncio

        for exc in (TimeoutError(), asyncio.CancelledError()):
            record = self._record(
                pathname=self._WORKER_PATH,
                msg="LoggingWorker error: ",
                exc=exc,
            )
            assert self._emit_through_logger(record) == []

    def test_other_logging_worker_errors_pass_through(self) -> None:
        """A blanket mute would be a task failure: a real callback error from
        the same module and message prefix must still surface."""
        record = self._record(
            pathname=self._WORKER_PATH,
            msg="LoggingWorker error: boom",
            exc=ValueError("boom"),
        )
        assert len(self._emit_through_logger(record)) == 1

    def test_other_litellm_error_records_pass_through(self) -> None:
        record = self._record(
            pathname="/site-packages/litellm/main.py",
            msg="litellm.APIConnectionError: connection reset",
            exc=TimeoutError(),  # even with a timeout attached
        )
        assert len(self._emit_through_logger(record)) == 1

    def test_filter_installed_at_import(self) -> None:
        import llm_client  # noqa: F401
        from llm_client.utils.litellm_log_filters import LiteLLMLoggingWorkerNoiseFilter

        target = logging.getLogger("LiteLLM")
        assert any(isinstance(f, LiteLLMLoggingWorkerNoiseFilter) for f in target.filters)
