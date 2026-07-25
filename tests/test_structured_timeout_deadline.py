"""Regression tests for client-enforced structured provider deadlines."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from llm_client.execution.structured_runtime import (
    _run_async_with_deadline,
    _run_sync_with_deadline,
)
from llm_client.execution.retry import _is_retryable


def test_sync_deadline_raises_while_provider_is_still_blocked() -> None:
    """A stalled sync transport must not hold the caller past its deadline."""

    started = threading.Event()
    release = threading.Event()

    def blocked_provider() -> str:
        started.set()
        release.wait(timeout=1)
        return "late"

    before = time.monotonic()
    try:
        with pytest.raises(TimeoutError, match="structured provider attempt exceeded 0.02s"):
            _run_sync_with_deadline(blocked_provider, timeout=0.02)
    finally:
        release.set()

    assert started.is_set()
    assert time.monotonic() - before < 0.5


def test_sync_deadline_preserves_fast_result_and_exception() -> None:
    """The deadline wrapper must be transparent when the provider returns."""

    assert _run_sync_with_deadline(lambda: "ok", timeout=1) == "ok"

    def fail() -> str:
        raise ValueError("provider failed")

    with pytest.raises(ValueError, match="provider failed"):
        _run_sync_with_deadline(fail, timeout=1)


@pytest.mark.asyncio
async def test_async_deadline_cancels_blocked_provider_attempt() -> None:
    """A stalled async transport is cancelled at the configured deadline."""

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked_provider() -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with pytest.raises(TimeoutError, match="structured provider attempt exceeded 0.02s"):
        await _run_async_with_deadline(blocked_provider, timeout=0.02)

    assert started.is_set()
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_async_deadline_preserves_fast_result_and_exception() -> None:
    """The async deadline wrapper preserves successful and failed outcomes."""

    async def succeed() -> str:
        return "ok"

    async def fail() -> str:
        raise ValueError("provider failed")

    assert await _run_async_with_deadline(succeed, timeout=1) == "ok"
    with pytest.raises(ValueError, match="provider failed"):
        await _run_async_with_deadline(fail, timeout=1)


@pytest.mark.parametrize(
    "message",
    [
        "peer closed connection without sending complete message body",
        "incomplete chunked read",
    ],
)
def test_incomplete_transport_response_is_retryable(message: str) -> None:
    """Abrupt provider response termination is a transient transport failure."""

    assert _is_retryable(Exception(message))
