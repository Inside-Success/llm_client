from __future__ import annotations

import asyncio
import logging
from unittest.mock import patch

import pytest

from llm_client.core.model_availability import clear_model_unavailability, filter_available_models
from llm_client.execution.execution_kernel import (
    _maybe_register_provider_cooldown,
    run_async_with_fallback,
    run_async_with_retry,
    run_sync_with_fallback,
    run_sync_with_retry,
)


def test_run_sync_with_retry_retries_and_succeeds() -> None:
    attempts: list[int] = []
    warnings: list[str] = []

    def invoke(attempt: int) -> str:
        attempts.append(attempt)
        if attempt < 2:
            raise ValueError("transient")
        return "ok"

    result = run_sync_with_retry(
        caller="test",
        model="m",
        max_retries=3,
        invoke=invoke,
        should_retry=lambda exc: isinstance(exc, ValueError),
        compute_delay=lambda attempt, exc: (0.0, "none"),
        warning_sink=warnings,
        logger=logging.getLogger("test_execution_kernel"),
    )

    assert result == "ok"
    assert attempts == [0, 1, 2]
    assert len([w for w in warnings if w.startswith("RETRY")]) == 2


def test_retry_decision_persists_before_optional_retry_hook() -> None:
    """A failing notification hook cannot erase the kernel's retry decision."""

    observed: list[tuple[str, object]] = []

    def invoke(_attempt: int) -> str:
        raise ValueError("transient")

    def on_decision(attempt: int, _exc: Exception, decision: str) -> None:
        observed.append((decision, attempt))

    def on_retry(_attempt: int, _exc: Exception, _delay: float) -> None:
        observed.append(("hook", "raised"))
        raise RuntimeError("notification failed")

    with pytest.raises(RuntimeError, match="notification failed"):
        run_sync_with_retry(
            caller="test",
            model="m",
            max_retries=1,
            invoke=invoke,
            should_retry=lambda _exc: True,
            compute_delay=lambda _attempt, _exc: (0.0, "none"),
            warning_sink=[],
            logger=logging.getLogger("test_execution_kernel"),
            on_decision=on_decision,
            on_retry=on_retry,
        )

    assert observed == [("retry", 0), ("hook", "raised")]


def test_non_retryable_failure_reports_exhausted_decision() -> None:
    """The terminal callback reflects policy, not only max-retry arithmetic."""

    decisions: list[tuple[int, str]] = []

    with pytest.raises(ValueError, match="terminal"):
        run_sync_with_retry(
            caller="test",
            model="m",
            max_retries=3,
            invoke=lambda _attempt: (_ for _ in ()).throw(ValueError("terminal")),
            should_retry=lambda _exc: False,
            compute_delay=lambda _attempt, _exc: (0.0, "none"),
            warning_sink=[],
            logger=logging.getLogger("test_execution_kernel"),
            on_decision=lambda attempt, _exc, decision: decisions.append(
                (attempt, decision)
            ),
        )

    assert decisions == [(0, "exhausted")]


def test_sync_retry_does_not_start_after_logical_deadline() -> None:
    """A total deadline stops the retry chain before its next provider attempt."""

    attempts: list[int] = []
    now = [10.0]

    def invoke(attempt: int) -> str:
        attempts.append(attempt)
        now[0] = 11.0
        raise ValueError("transient")

    with pytest.raises(TimeoutError, match="logical call deadline elapsed before retry"):
        run_sync_with_retry(
            caller="test",
            model="m",
            max_retries=1,
            invoke=invoke,
            should_retry=lambda _exc: True,
            compute_delay=lambda _attempt, _exc: (1.0, "none"),
            warning_sink=[],
            logger=logging.getLogger("test_execution_kernel"),
            deadline_at=12.0,
            clock=lambda: now[0],
        )

    assert attempts == [0]


@pytest.mark.asyncio
async def test_async_retry_does_not_start_after_logical_deadline() -> None:
    """Async retry shares the same total-deadline boundary."""

    attempts: list[int] = []
    now = [10.0]

    async def invoke(attempt: int) -> str:
        attempts.append(attempt)
        now[0] = 11.0
        raise ValueError("transient")

    with pytest.raises(TimeoutError, match="logical call deadline elapsed before retry"):
        await run_async_with_retry(
            caller="test",
            model="m",
            max_retries=1,
            invoke=invoke,
            should_retry=lambda _exc: True,
            compute_delay=lambda _attempt, _exc: (1.0, "none"),
            warning_sink=[],
            logger=logging.getLogger("test_execution_kernel"),
            deadline_at=12.0,
            clock=lambda: now[0],
        )

    assert attempts == [0]


@pytest.mark.asyncio
async def test_run_async_with_retry_retries_and_succeeds() -> None:
    attempts: list[int] = []
    warnings: list[str] = []

    async def invoke(attempt: int) -> str:
        attempts.append(attempt)
        if attempt < 1:
            raise RuntimeError("transient")
        return "ok"

    result = await run_async_with_retry(
        caller="test",
        model="m",
        max_retries=2,
        invoke=invoke,
        should_retry=lambda exc: isinstance(exc, RuntimeError),
        compute_delay=lambda attempt, exc: (0.0, "none"),
        warning_sink=warnings,
        logger=logging.getLogger("test_execution_kernel"),
    )

    assert result == "ok"
    assert attempts == [0, 1]
    assert len([w for w in warnings if w.startswith("RETRY")]) == 1


def test_run_sync_with_fallback_uses_next_model() -> None:
    warnings: list[str] = []
    seen: list[str] = []

    def execute_model(model_idx: int, model_name: str) -> str:
        seen.append(model_name)
        if model_name == "primary":
            raise ValueError("boom")
        return "ok"

    result = run_sync_with_fallback(
        models=["primary", "fallback"],
        execute_model=execute_model,
        warning_sink=warnings,
        logger=logging.getLogger("test_execution_kernel"),
    )

    assert result == "ok"
    assert seen == ["primary", "fallback"]
    assert any("FALLBACK: primary -> fallback" in w for w in warnings)


def test_run_sync_with_fallback_honors_non_fallback_boundary() -> None:
    """A caller can mark a local terminal failure as ineligible for fallback."""

    seen: list[str] = []

    def execute_model(_model_idx: int, model_name: str) -> str:
        seen.append(model_name)
        raise RuntimeError("local finalization failed")

    with pytest.raises(RuntimeError, match="local finalization failed"):
        run_sync_with_fallback(
            models=["primary", "fallback"],
            execute_model=execute_model,
            should_fallback=lambda _exc: False,
        )

    assert seen == ["primary"]


@pytest.mark.asyncio
async def test_run_async_with_fallback_uses_next_model() -> None:
    warnings: list[str] = []
    seen: list[str] = []

    async def execute_model(model_idx: int, model_name: str) -> str:
        seen.append(model_name)
        await asyncio.sleep(0)
        if model_name == "primary":
            raise ValueError("boom")
        return "ok"

    result = await run_async_with_fallback(
        models=["primary", "fallback"],
        execute_model=execute_model,
        warning_sink=warnings,
        logger=logging.getLogger("test_execution_kernel"),
    )

    assert result == "ok"
    assert seen == ["primary", "fallback"]
    assert any("FALLBACK: primary -> fallback" in w for w in warnings)


@pytest.mark.asyncio
async def test_run_async_with_fallback_honors_non_fallback_boundary() -> None:
    """The async kernel preserves the same caller-owned terminal boundary."""

    seen: list[str] = []

    async def execute_model(_model_idx: int, model_name: str) -> str:
        seen.append(model_name)
        raise RuntimeError("local finalization failed")

    with pytest.raises(RuntimeError, match="local finalization failed"):
        await run_async_with_fallback(
            models=["primary", "fallback"],
            execute_model=execute_model,
            should_fallback=lambda _exc: False,
        )

    assert seen == ["primary"]


@pytest.mark.asyncio
async def test_run_async_with_fallback_records_exhausted_model_for_future_calls() -> None:
    warnings: list[str] = []
    clear_model_unavailability()

    class ExhaustedError(Exception):
        pass

    async def execute_model(model_idx: int, model_name: str) -> str:
        del model_idx
        await asyncio.sleep(0)
        if model_name == "gemini/gemini-2.5-flash":
            raise ExhaustedError(
                "Your project has exceeded its monthly spending cap. "
                "Please go to AI Studio at https://ai.studio/spend to manage your project spend cap."
            )
        return "ok"

    result = await run_async_with_fallback(
        models=["gemini/gemini-2.5-flash", "openrouter/openai/gpt-5.4-mini"],
        execute_model=execute_model,
        warning_sink=warnings,
        logger=logging.getLogger("test_execution_kernel"),
    )

    available, suppressed = filter_available_models(
        ["gemini/gemini-2.5-flash", "openrouter/openai/gpt-5.4-mini"]
    )
    clear_model_unavailability()

    assert result == "ok"
    assert available == ["openrouter/openai/gpt-5.4-mini"]
    assert suppressed[0]["model"] == "gemini/gemini-2.5-flash"
    assert suppressed[0]["reason"] == "provider_spend_cap_exhausted"
    assert any("MODEL_UNAVAILABLE: gemini/gemini-2.5-flash" in w for w in warnings)


def test_register_provider_cooldown_emits_provider_governance_warning() -> None:
    warnings: list[str] = []

    with patch("llm_client.execution.retry._is_rate_limit_error", return_value=True), patch(
        "llm_client.execution.retry._retry_delay_hint",
        return_value=(1.5, "provider-hint"),
    ), patch(
        "llm_client.utils.rate_limit.register_rate_limit_cooldown",
        return_value=1.5,
    ):
        applied = _maybe_register_provider_cooldown(
            model="gemini/gemini-2.5-flash",
            exc=RuntimeError("rate limit"),
            warning_sink=warnings,
            logger=logging.getLogger("test_execution_kernel"),
        )

    assert applied == 1.5
    assert warnings == [
        "PROVIDER_GOVERNANCE_EVENT[cooldown_registered]: provider=google delay_s=1.5 source=provider-hint"
    ]
