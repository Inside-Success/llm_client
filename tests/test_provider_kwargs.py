"""Focused tests for provider-kwargs preparation at the public client boundary.

These tests keep the transport contract explicit: llm_client may attach
underscore-prefixed runtime control objects internally, but provider-facing
kwargs must stay JSON-serializable and must not receive those private values.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

from llm_client.core.client import _prepare_call_kwargs, _prepare_responses_kwargs


def test_prepare_call_kwargs_strips_internal_runtime_objects() -> None:
    """Provider kwargs should exclude underscore-prefixed internal control objects."""

    monitor = object()
    call_kwargs = _prepare_call_kwargs(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "hello"}],
        timeout=0,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        kwargs={
            "_lifecycle_monitor": monitor,
            "metadata": {"scope": "test"},
        },
    )

    assert "_lifecycle_monitor" not in call_kwargs
    assert call_kwargs["metadata"] == {"scope": "test"}


def test_openrouter_completion_requests_inline_route_metadata() -> None:
    """Ordinary OpenRouter calls should receive routing evidence inline."""

    call_kwargs = _prepare_call_kwargs(
        "openrouter/deepseek/deepseek-v4-flash",
        [{"role": "user", "content": "hello"}],
        timeout=0,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        kwargs={"extra_headers": {"X-Trace": "trace-1"}},
    )

    assert call_kwargs["extra_headers"] == {
        "X-Trace": "trace-1",
        "X-OpenRouter-Metadata": "enabled",
    }


def test_openrouter_metadata_respects_explicit_caller_disable() -> None:
    """Header injection must not override an explicit per-call policy."""

    call_kwargs = _prepare_call_kwargs(
        "openrouter/deepseek/deepseek-v4-flash",
        [{"role": "user", "content": "hello"}],
        timeout=0,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        kwargs={"extra_headers": {"x-openrouter-metadata": "disabled"}},
    )

    assert call_kwargs["extra_headers"] == {"x-openrouter-metadata": "disabled"}


def test_non_openrouter_completion_does_not_receive_router_header() -> None:
    """Provider-specific metadata headers must not leak to direct routes."""

    call_kwargs = _prepare_call_kwargs(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "hello"}],
        timeout=0,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        kwargs={},
    )

    assert "extra_headers" not in call_kwargs


def test_explicit_openrouter_api_base_requests_inline_metadata() -> None:
    """A bare model on OpenRouter's API base is still an OpenRouter call."""

    call_kwargs = _prepare_call_kwargs(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "hello"}],
        timeout=0,
        num_retries=0,
        reasoning_effort=None,
        api_base="https://openrouter.ai/api/v1",
        kwargs={},
    )

    assert call_kwargs["extra_headers"] == {"X-OpenRouter-Metadata": "enabled"}


def test_openrouter_responses_requests_inline_route_metadata() -> None:
    """The Responses transport should use the same inline evidence policy."""

    call_kwargs = _prepare_responses_kwargs(
        "openrouter/openai/gpt-5.5",
        [{"role": "user", "content": "hello"}],
        timeout=0,
        reasoning_effort=None,
        api_base=None,
        kwargs={},
    )

    assert call_kwargs["extra_headers"] == {"X-OpenRouter-Metadata": "enabled"}


@patch("litellm.get_supported_openai_params", return_value=["thinking"])
def test_prepare_call_kwargs_uses_configured_direct_gemini_thinking_budget(
    _mock_supported: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct Gemini thinking defaults should come from shared config, not a hardcoded zero."""

    monkeypatch.setenv("LLM_CLIENT_DIRECT_GEMINI_THINKING_BUDGET", "512")
    call_kwargs = _prepare_call_kwargs(
        "gemini/gemini-2.5-pro",
        [{"role": "user", "content": "hello"}],
        timeout=0,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        kwargs={},
    )

    assert call_kwargs["thinking"] == {"type": "enabled", "budget_tokens": 512}


@patch("litellm.get_supported_openai_params", return_value=["thinking"])
def test_prepare_call_kwargs_allows_disabling_direct_gemini_auto_thinking(
    _mock_supported: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Consumers can disable auto-injected direct-Gemini thinking config entirely."""

    monkeypatch.setenv("LLM_CLIENT_DIRECT_GEMINI_THINKING_BUDGET", "off")
    call_kwargs = _prepare_call_kwargs(
        "gemini/gemini-2.5-pro",
        [{"role": "user", "content": "hello"}],
        timeout=0,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        kwargs={},
    )

    assert "thinking" not in call_kwargs
