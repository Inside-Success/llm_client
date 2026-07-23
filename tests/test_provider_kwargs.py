"""Focused tests for provider-kwargs preparation at the public client boundary.

These tests keep the transport contract explicit: llm_client may attach
underscore-prefixed runtime control objects internally, but provider-facing
kwargs must stay JSON-serializable and must not receive those private values.
"""

from __future__ import annotations

import litellm
import pytest
from unittest.mock import patch

from llm_client.core.client import _prepare_call_kwargs, _prepare_responses_kwargs
from llm_client.core.errors import DeprecatedModelError


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


def test_openrouter_deepseek_forwards_max_reasoning_and_broadcast_trace() -> None:
    """Normalized reasoning and required identity should reach OpenRouter."""

    call_kwargs = _prepare_call_kwargs(
        "openrouter/deepseek/deepseek-v4-flash",
        [{"role": "user", "content": "hello"}],
        timeout=0,
        num_retries=0,
        reasoning_effort="max",
        api_base=None,
        kwargs={
            "metadata": {
                "_llm_client_logged": True,
                "task": "service_desk",
                "trace_id": "service-desk/trial-0/triager/0",
            }
        },
    )

    assert call_kwargs["reasoning_effort"] == "max"
    assert call_kwargs["allowed_openai_params"] == ["reasoning_effort"]
    assert call_kwargs["provider"] == {"require_parameters": True}
    assert call_kwargs["trace"] == {
        "trace_id": "service-desk/trial-0/triager/0",
        "trace_name": "service_desk",
        "generation_name": "service_desk",
    }


def test_openrouter_max_reasoning_survives_installed_litellm_normalization() -> None:
    """The transport dependency must preserve max effort without a network call."""

    call_kwargs = _prepare_call_kwargs(
        "openrouter/deepseek/deepseek-v4-flash",
        [{"role": "user", "content": "hello"}],
        timeout=0,
        num_retries=0,
        reasoning_effort="max",
        api_base=None,
        kwargs={},
    )

    normalized = litellm.get_optional_params(
        model=call_kwargs.pop("model"),
        custom_llm_provider="openrouter",
        **{
            key: value
            for key, value in call_kwargs.items()
            if key not in {"messages", "timeout", "extra_headers"}
        },
    )

    assert normalized["reasoning_effort"] == "max"


def test_openrouter_normalized_passthrough_merges_caller_allowlist() -> None:
    """Compatibility declaration should preserve caller-owned allowed params."""

    call_kwargs = _prepare_call_kwargs(
        "openrouter/deepseek/deepseek-v4-flash",
        [{"role": "user", "content": "hello"}],
        timeout=0,
        num_retries=0,
        reasoning_effort="max",
        api_base=None,
        kwargs={"allowed_openai_params": ["verbosity"]},
    )

    assert call_kwargs["allowed_openai_params"] == [
        "reasoning_effort",
        "verbosity",
    ]


def test_openrouter_normalized_passthrough_preserves_provider_routing() -> None:
    """Capability enforcement should preserve caller-owned provider sorting."""

    call_kwargs = _prepare_call_kwargs(
        "openrouter/deepseek/deepseek-v4-flash",
        [{"role": "user", "content": "hello"}],
        timeout=0,
        num_retries=0,
        reasoning_effort="max",
        api_base=None,
        kwargs={"provider": {"sort": "throughput", "allow_fallbacks": False}},
    )

    assert call_kwargs["provider"] == {
        "sort": "throughput",
        "allow_fallbacks": False,
        "require_parameters": True,
    }


def test_openrouter_normalized_passthrough_rejects_capability_opt_out() -> None:
    """A normalized control must not be sent through a route allowed to ignore it."""

    with pytest.raises(ValueError, match="require_parameters=False"):
        _prepare_call_kwargs(
            "openrouter/deepseek/deepseek-v4-flash",
            [{"role": "user", "content": "hello"}],
            timeout=0,
            num_retries=0,
            reasoning_effort="max",
            api_base=None,
            kwargs={"provider": {"require_parameters": False}},
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("preset", "unsafe-account-preset"),
        ("plugins", [{"id": "auto-router"}]),
    ],
)
def test_openrouter_rejects_opaque_model_selection(
    key: str,
    value: object,
) -> None:
    """Provider payloads must not bypass the pre-dispatch model policy."""

    with pytest.raises(ValueError, match="model-selection policy"):
        _prepare_call_kwargs(
            "openrouter/deepseek/deepseek-v4-flash",
            [{"role": "user", "content": "hello"}],
            timeout=0,
            num_retries=0,
            reasoning_effort=None,
            api_base=None,
            kwargs={key: value},
        )


@pytest.mark.parametrize(
    "banned_model",
    [
        "anthropic/claude-opus-4.8",
        "anthropic/claude-fable-5",
    ],
)
def test_openrouter_rejects_banned_provider_model_arrays(
    banned_model: str,
) -> None:
    """Payload-level model arrays receive the complete hard-block policy."""

    with pytest.raises(DeprecatedModelError, match="HARD-BLOCKED MODEL"):
        _prepare_call_kwargs(
            "openrouter/deepseek/deepseek-v4-flash",
            [{"role": "user", "content": "hello"}],
            timeout=0,
            num_retries=0,
            reasoning_effort=None,
            api_base=None,
            kwargs={"models": ["deepseek/deepseek-chat", banned_model]},
        )


def test_openrouter_broadcast_trace_preserves_explicit_caller_fields() -> None:
    """Automatic trace identity must not replace caller-owned hierarchy."""

    call_kwargs = _prepare_call_kwargs(
        "openrouter/deepseek/deepseek-v4-flash",
        [{"role": "user", "content": "hello"}],
        timeout=0,
        num_retries=0,
        reasoning_effort="max",
        api_base=None,
        kwargs={
            "metadata": {"task": "service_desk", "trace_id": "automatic"},
            "trace": {
                "trace_id": "caller-trace",
                "parent_span_id": "parent-7",
                "feature": "simulation",
            },
        },
    )

    assert call_kwargs["trace"] == {
        "trace_id": "caller-trace",
        "trace_name": "service_desk",
        "generation_name": "service_desk",
        "parent_span_id": "parent-7",
        "feature": "simulation",
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
    assert "trace" not in call_kwargs


def test_normalized_reasoning_is_not_family_allowlisted() -> None:
    """Unknown/new provider routes should receive normalized controls unchanged."""

    call_kwargs = _prepare_call_kwargs(
        "future-provider/new-reasoning-model",
        [{"role": "user", "content": "hello"}],
        timeout=0,
        num_retries=0,
        reasoning_effort="xhigh",
        api_base=None,
        kwargs={},
    )

    assert call_kwargs["reasoning_effort"] == "xhigh"


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


def test_explicit_openrouter_api_base_rejects_bare_auto_model() -> None:
    """A custom OpenRouter base must not hide an opaque primary selector."""

    with pytest.raises(ValueError, match="model-selection policy"):
        _prepare_call_kwargs(
            "auto",
            [{"role": "user", "content": "hello"}],
            timeout=0,
            num_retries=0,
            reasoning_effort=None,
            api_base="https://openrouter.ai/api/v1",
            kwargs={},
        )


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
