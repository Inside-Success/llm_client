"""Contract tests for the shared allowed-model execution policy."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_client import call_llm
from llm_client.core.client_dispatch import _resolve_call_plan
from llm_client.core.config import ClientConfig
from llm_client.core.data_types import _cache_key
from llm_client.core.errors import LLMConfigurationError
from llm_client.core.model_execution_policy import (
    ALLOWED_EXECUTION_MODELS,
    DEFAULT_EXECUTION_EMBEDDING_MODEL,
    DEFAULT_EXECUTION_MODEL,
    REASONING_CAPABILITIES,
    evaluate_model_execution_policy,
    evaluate_reasoning_policy,
)


def _mock_response() -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "ok"
    response.choices[0].message.tool_calls = None
    response.choices[0].message.refusal = None
    response.choices[0].finish_reason = "stop"
    response.usage.prompt_tokens = 2
    response.usage.completion_tokens = 1
    response.usage.total_tokens = 3
    return response


def test_default_route_needs_no_justification_but_requires_reasoning_policy() -> None:
    decision = evaluate_model_execution_policy(
        [DEFAULT_EXECUTION_MODEL],
        mode="enforce_allowlist",
        reasoning_effort="medium",
    )

    assert decision.enforced is True
    assert decision.uses_only_default is True
    assert decision.justification is None
    assert decision.reasoning_policy.effort == "medium"


def test_legacy_default_is_not_the_workload_routing_policy() -> None:
    assert DEFAULT_EXECUTION_MODEL == "openrouter/openai/gpt-5.6-luna"


def test_embedding_default_needs_no_justification() -> None:
    # embed() has no model_justification parameter -- callers cannot supply
    # one, so the embedding default must be exempt the same way the chat
    # default is.
    decision = evaluate_model_execution_policy(
        [DEFAULT_EXECUTION_EMBEDDING_MODEL],
        mode="enforce_allowlist",
    )

    assert decision.enforced is True
    assert decision.uses_only_default is True
    assert decision.justification is None
    assert DEFAULT_EXECUTION_EMBEDDING_MODEL == "openrouter/openai/text-embedding-3-small"
    assert DEFAULT_EXECUTION_EMBEDDING_MODEL in ALLOWED_EXECUTION_MODELS
    assert DEFAULT_EXECUTION_EMBEDDING_MODEL not in REASONING_CAPABILITIES


def test_embedding_route_resolution_fails_loud_for_disallowed_model() -> None:
    # Regression: _resolve_embedding_route previously caught every exception
    # from _resolve_call_plan, including a real execution-allowlist
    # rejection, and silently fell back to dispatching the raw unrouted
    # model string. A policy rejection must propagate like it does for
    # chat-completion routes, not disappear into a direct-provider fallback.
    from llm_client.execution.embedding_runtime import _resolve_embedding_route

    with pytest.raises(LLMConfigurationError, match="execution allowlist"):
        _resolve_embedding_route(
            model="text-embedding-not-a-real-allowlisted-model",
            api_base=None,
        )


def test_allowed_alternate_requires_and_records_justification() -> None:
    alternate = "openrouter/openai/gpt-5.6-terra"
    decision = evaluate_model_execution_policy(
        [alternate],
        mode="enforce_allowlist",
        justification="Hard semantic review requires the certified Terra route.",
        reasoning_effort="low",
    )

    assert alternate in ALLOWED_EXECUTION_MODELS
    assert decision.uses_only_default is False
    assert decision.justification == (
        "Hard semantic review requires the certified Terra route."
    )


def test_openrouter_sol_requires_explicit_justification_and_reasoning() -> None:
    model = "openrouter/openai/gpt-5.6-sol"
    decision = evaluate_model_execution_policy(
        [model],
        mode="enforce_allowlist",
        justification="Certify the explicit OpenRouter Sol route for typed authoring.",
        reasoning_effort="medium",
    )

    assert model in ALLOWED_EXECUTION_MODELS
    assert decision.reasoning_policy.effort == "medium"
    assert REASONING_CAPABILITIES[model].supported_efforts == frozenset(
        {"none", "low", "medium", "high", "xhigh", "max"}
    )


@pytest.mark.parametrize(
    "model",
    [
        "codex/gpt-5.6-sol",
        "codex/gpt-5.6-terra",
    ],
)
def test_codex_gpt56_requires_justification_and_explicit_reasoning(
    model: str,
) -> None:
    decision = evaluate_model_execution_policy(
        [model],
        mode="enforce_allowlist",
        justification="Use the operator-selected subscription-backed GPT-5.6 route.",
        reasoning_effort="low",
    )

    assert model in ALLOWED_EXECUTION_MODELS
    assert decision.uses_only_default is False
    assert decision.reasoning_policy.effort == "low"
    assert REASONING_CAPABILITIES[model].supported_efforts == frozenset(
        {"low", "medium", "high"}
    )


def test_all_supported_gpt56_family_routes_are_allowlisted() -> None:
    expected = {
        "openrouter/openai/gpt-5.6-luna",
        "openrouter/openai/gpt-5.6-sol",
        "openrouter/openai/gpt-5.6-terra",
        "gpt-5.6",
        "gpt-5.6-terra",
        "codex/gpt-5.6-luna",
        "codex/gpt-5.6-sol",
        "codex/gpt-5.6-terra",
    }

    assert expected.issubset(ALLOWED_EXECUTION_MODELS)
    assert expected.issubset(REASONING_CAPABILITIES)


def test_allowed_alternate_without_justification_fails() -> None:
    with pytest.raises(LLMConfigurationError, match="require model_justification"):
        evaluate_model_execution_policy(
            ["openrouter/openai/gpt-5.6-terra"],
            mode="enforce_allowlist",
            reasoning_effort="low",
        )


def test_legacy_openrouter_default_remains_compatible_for_unmigrated_callers() -> None:
    decision = evaluate_model_execution_policy(
        ["openrouter/openai/gpt-5.6-luna"],
        mode="enforce_allowlist",
        reasoning_effort="medium",
    )

    assert decision.uses_only_default is True


@pytest.mark.parametrize(
    "model",
    [
        "openrouter/openai/gpt-5-mini",
        "openrouter/openai/gpt-5.1-mini",
        "openrouter/openai/gpt-5.4",
        "openrouter/openai/gpt-5.4-mini",
        "codex/gpt-5.4",
        "openrouter/openai/gpt-5.5",
        "gpt-5.5",
        "gpt-5.5-pro",
        "codex/gpt-5.1-codex-mini",
        "openrouter/unknown/new-model",
    ],
)
def test_unlisted_models_fail_closed(model: str) -> None:
    with pytest.raises(LLMConfigurationError, match="not in.*allowlist"):
        evaluate_model_execution_policy(
            [model],
            mode="enforce_allowlist",
            justification="A reason cannot authorize an unlisted model.",
        )


def test_unjustified_fallback_rejects_the_whole_chain() -> None:
    with pytest.raises(LLMConfigurationError, match="require model_justification"):
        _resolve_call_plan(
            model=DEFAULT_EXECUTION_MODEL,
            fallback_models=["openrouter/openai/gpt-5.6-terra"],
            api_base=None,
            config=ClientConfig(routing_policy="openrouter"),
            model_policy="enforce_allowlist",
            reasoning_effort="none",
        )


def test_resolved_plan_records_alternate_justification() -> None:
    plan = _resolve_call_plan(
        model="openai/gpt-5.6-terra",
        fallback_models=None,
        api_base=None,
        config=ClientConfig(routing_policy="openrouter"),
        model_policy="enforce_allowlist",
        model_justification="Use the reviewed Terra planner route.",
        reasoning_effort="low",
    )

    assert plan.primary_model == "openrouter/openai/gpt-5.6-terra"
    assert plan.routing_trace["model_policy"]["justification"] == (
        "Use the reviewed Terra planner route."
    )
    assert plan.routing_trace["model_policy"]["reasoning_policy"]["effort"] == "low"


def test_configurable_reasoning_model_rejects_omission() -> None:
    with pytest.raises(LLMConfigurationError, match="reasoning_effort is required"):
        evaluate_reasoning_policy(
            [DEFAULT_EXECUTION_MODEL],
            reasoning_effort=None,
        )


def test_mandatory_reasoning_model_rejects_explicit_off() -> None:
    with pytest.raises(LLMConfigurationError, match="none.*forbidden"):
        evaluate_reasoning_policy(
            ["openrouter/x-ai/grok-4.5"],
            reasoning_effort="none",
        )


def test_model_rejects_unsupported_effort_before_provider_remapping() -> None:
    with pytest.raises(LLMConfigurationError, match="unsupported.*allowed"):
        evaluate_reasoning_policy(
            [DEFAULT_EXECUTION_MODEL],
            reasoning_effort="minimal",
        )


def test_fallback_chain_requires_one_effort_valid_for_every_configurable_leg() -> None:
    with pytest.raises(LLMConfigurationError, match="unsupported for"):
        evaluate_reasoning_policy(
            [
                "openrouter/openai/gpt-5.6-terra",
                "openrouter/deepseek/deepseek-v4-flash",
            ],
            reasoning_effort="low",
        )


def test_reasoning_capability_routes_are_all_allowlisted() -> None:
    assert set(REASONING_CAPABILITIES).issubset(ALLOWED_EXECUTION_MODELS)


def test_gpt55_family_is_absent_from_execution_policy() -> None:
    """Retired GPT-5.5 aliases cannot remain selectable or configurable."""
    assert not any("gpt-5.5" in model for model in ALLOWED_EXECUTION_MODELS)
    assert not any("gpt-5.5" in model for model in REASONING_CAPABILITIES)


def test_gpt54_family_is_absent_from_execution_policy() -> None:
    """Banned GPT-5.4 aliases cannot remain selectable or configurable."""
    assert not any("gpt-5.4" in model for model in ALLOWED_EXECUTION_MODELS)
    assert not any("gpt-5.4" in model for model in REASONING_CAPABILITIES)


def test_reasoning_effort_changes_cache_identity() -> None:
    messages = [{"role": "user", "content": "same"}]

    keys = {
        _cache_key(DEFAULT_EXECUTION_MODEL, messages, reasoning_effort=effort)
        for effort in ("none", "high", "xhigh")
    }

    assert len(keys) == 3


@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
def test_public_default_call_enforces_without_provider_policy_kwargs(
    completion: AsyncMock,
    _cost: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_CLIENT_OPENROUTER_ROUTING", "on")
    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "allow")
    completion.return_value = _mock_response()

    result = call_llm(
        DEFAULT_EXECUTION_MODEL,
        [{"role": "user", "content": "hello"}],
        task="test",
        trace_id="test-model-allowlist-default",
        max_budget=0,
        reasoning_effort="NONE",
    )

    assert result.routing_trace["model_policy"]["uses_only_default"] is True
    assert (
        result.routing_trace["model_policy"]["reasoning_policy"]["effort"]
        == "none"
    )
    provider_kwargs = completion.call_args.kwargs
    assert provider_kwargs["reasoning_effort"] == "none"
    assert "model_policy" not in provider_kwargs
    assert "model_justification" not in provider_kwargs


@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
def test_public_default_call_rejects_omitted_reasoning_before_dispatch(
    completion: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_CLIENT_OPENROUTER_ROUTING", "on")
    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "allow")

    with pytest.raises(LLMConfigurationError, match="reasoning_effort is required"):
        call_llm(
            DEFAULT_EXECUTION_MODEL,
            [{"role": "user", "content": "hello"}],
            task="test",
            trace_id="test-reasoning-policy-required",
            max_budget=0,
        )

    completion.assert_not_awaited()


@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
def test_public_unlisted_call_fails_before_dispatch(
    completion: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_CLIENT_OPENROUTER_ROUTING", "on")
    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "allow")

    with pytest.raises(LLMConfigurationError, match="not in.*allowlist"):
        call_llm(
            "openrouter/unknown/new-model",
            [{"role": "user", "content": "hello"}],
            model_policy="enforce_allowlist",
            model_justification="This must not override the allowlist.",
            task="test",
            trace_id="test-model-allowlist-reject",
            max_budget=0,
        )

    completion.assert_not_awaited()


@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
def test_removed_compatibility_mode_fails_before_dispatch(
    completion: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_CLIENT_OPENROUTER_ROUTING", "on")
    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "allow")

    with pytest.raises(LLMConfigurationError, match="compatibility mode was removed"):
        call_llm(
            DEFAULT_EXECUTION_MODEL,
            [{"role": "user", "content": "hello"}],
            model_policy="compatibility",
            task="test",
            trace_id="test-model-mini-global-reject",
            max_budget=0,
        )

    completion.assert_not_awaited()
