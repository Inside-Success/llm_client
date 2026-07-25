"""Tests for shared timeout-policy helpers."""

from __future__ import annotations

import asyncio

import pytest

import llm_client.execution.timeout_policy as timeout_policy
from llm_client.execution.timeout_policy import (
    default_timeout_for_caller,
    normalize_timeout,
)


def test_normalize_timeout_ban_appends_warning_and_zeroes_timeout(
    monkeypatch,
) -> None:
    """Global timeout ban should zero the timeout and emit one stable warning."""
    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "ban")
    warnings: list[str] = []

    normalized = normalize_timeout(
        120,
        caller="test_timeout_policy",
        warning_sink=warnings,
    )

    assert normalized == 0
    assert warnings == [
        "TIMEOUT_DISABLED[test_timeout_policy]: timeout=120s ignored "
        "(set LLM_CLIENT_TIMEOUT_POLICY=allow to re-enable)."
    ]


def test_normalize_timeout_negative_values_clamp_to_zero(monkeypatch) -> None:
    """Negative timeout values should normalize to zero without warnings."""
    monkeypatch.delenv("LLM_CLIENT_TIMEOUT_POLICY", raising=False)
    warnings: list[str] = []

    normalized = normalize_timeout(
        -5,
        caller="test_timeout_policy",
        warning_sink=warnings,
    )

    assert normalized == 0
    assert warnings == []


def test_normalize_timeout_rejects_positive_fractional_seconds(monkeypatch) -> None:
    """A sub-second value must not silently truncate to a disabled deadline."""

    monkeypatch.delenv("LLM_CLIENT_TIMEOUT_POLICY", raising=False)

    with pytest.raises(ValueError, match="whole number of seconds"):
        normalize_timeout(0.001, caller="test_timeout_policy")


def test_default_timeout_for_structured_calls_is_finite(monkeypatch) -> None:
    """Structured calls should inherit a longer finite shared default."""

    monkeypatch.delenv("LLM_CLIENT_DEFAULT_TIMEOUT", raising=False)
    monkeypatch.delenv("LLM_CLIENT_DEFAULT_STRUCTURED_TIMEOUT", raising=False)

    assert default_timeout_for_caller(caller="call_llm_structured") == 60
    assert default_timeout_for_caller(caller="acall_llm_structured") == 60


def test_default_timeout_for_structured_calls_honors_env_override(monkeypatch) -> None:
    """Structured default timeout should stay configurable from env."""

    monkeypatch.setenv("LLM_CLIENT_DEFAULT_STRUCTURED_TIMEOUT", "240")

    assert default_timeout_for_caller(caller="call_llm_structured") == 240


def test_malformed_safety_timeout_uses_default_and_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Malformed safety configuration must not silently disable liveness."""

    monkeypatch.setenv("LLM_CLIENT_SAFETY_TIMEOUT", "not-a-number")

    with caplog.at_level("WARNING"):
        resolved = timeout_policy.safety_timeout_s()

    assert resolved == timeout_policy.DEFAULT_SAFETY_TIMEOUT_S
    assert "INVALID_SAFETY_TIMEOUT" in caplog.text
    assert "not-a-number" in caplog.text


@pytest.mark.asyncio
async def test_async_safety_ceiling_returns_completed_awaitable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The process-side ceiling must preserve an ordinary async result."""

    monkeypatch.setattr(timeout_policy, "safety_timeout_s", lambda: 0.05)

    async def _complete() -> str:
        return "ok"

    assert await timeout_policy._await_with_safety_ceiling(
        _complete(),
        caller="test.completed",
        model="provider/model",
    ) == "ok"


@pytest.mark.asyncio
async def test_async_safety_ceiling_cancels_nonreturning_awaitable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider await that ignores request timeout must be cancelled."""

    monkeypatch.setattr(timeout_policy, "safety_timeout_s", lambda: 0.01)
    cancelled = asyncio.Event()

    async def _never_returns() -> None:
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    with pytest.raises(
        TimeoutError,
        match=r"test\.hung timed out after 0\.01s async attempt safety ceiling.*provider/model",
    ):
        await timeout_policy._await_with_safety_ceiling(
            _never_returns(),
            caller="test.hung",
            model="provider/model",
        )

    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_external_cancellation_is_not_relabelled_as_safety_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller cancellation propagates unchanged while still draining the provider task."""

    monkeypatch.setattr(timeout_policy, "safety_timeout_s", lambda: 60)
    provider_cancelled = asyncio.Event()

    async def _never_returns() -> None:
        try:
            await asyncio.Future()
        finally:
            provider_cancelled.set()

    call = asyncio.create_task(
        timeout_policy._await_with_safety_ceiling(
            _never_returns(),
            caller="test.external_cancel",
            model="provider/model",
        )
    )
    await asyncio.sleep(0)
    call.cancel()

    with pytest.raises(asyncio.CancelledError):
        await call

    assert provider_cancelled.is_set()


@pytest.mark.asyncio
async def test_provider_timeout_is_not_relabelled_as_safety_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider-raised timeout remains distinct from client cancellation."""

    monkeypatch.setattr(timeout_policy, "safety_timeout_s", lambda: 1)

    async def _provider_timeout() -> None:
        raise TimeoutError("provider request timed out")

    with pytest.raises(TimeoutError, match="^provider request timed out$") as caught:
        await timeout_policy._await_with_safety_ceiling(
            _provider_timeout(),
            caller="test.provider_timeout",
            model="provider/model",
        )

    assert "safety ceiling" not in str(caught.value)


@pytest.mark.asyncio
async def test_disabled_async_safety_ceiling_allows_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit zero safety ceiling must preserve caller-owned waiting."""

    monkeypatch.setattr(timeout_policy, "safety_timeout_s", lambda: 0)

    async def _complete_later() -> str:
        await asyncio.sleep(0)
        return "ok"

    assert await timeout_policy._await_with_safety_ceiling(
        _complete_later(),
        caller="test.disabled",
        model="provider/model",
    ) == "ok"
