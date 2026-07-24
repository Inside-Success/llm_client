"""Contract tests for the shared allowed-model execution policy."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_client import call_llm
from llm_client.core.client_dispatch import _resolve_call_plan
from llm_client.core.config import ClientConfig
from llm_client.core.errors import LLMConfigurationError
from llm_client.core.errors import DeprecatedModelError
from llm_client.core.model_execution_policy import (
    ALLOWED_EXECUTION_MODELS,
    DEFAULT_EXECUTION_MODEL,
    evaluate_model_execution_policy,
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


def test_default_route_needs_no_justification() -> None:
    decision = evaluate_model_execution_policy(
        [DEFAULT_EXECUTION_MODEL],
        mode="enforce_allowlist",
    )

    assert decision.enforced is True
    assert decision.uses_only_default is True
    assert decision.justification is None


def test_allowed_alternate_requires_and_records_justification() -> None:
    alternate = "openrouter/openai/gpt-5.6-terra"
    decision = evaluate_model_execution_policy(
        [alternate],
        mode="enforce_allowlist",
        justification="Hard semantic review requires the certified Terra route.",
    )

    assert alternate in ALLOWED_EXECUTION_MODELS
    assert decision.uses_only_default is False
    assert decision.justification == (
        "Hard semantic review requires the certified Terra route."
    )


def test_allowed_alternate_without_justification_fails() -> None:
    with pytest.raises(LLMConfigurationError, match="require model_justification"):
        evaluate_model_execution_policy(
            ["openrouter/openai/gpt-5.6-terra"],
            mode="enforce_allowlist",
        )


@pytest.mark.parametrize(
    "model",
    [
        "openrouter/openai/gpt-5-mini",
        "openrouter/openai/gpt-5.1-mini",
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
        )


def test_resolved_plan_records_alternate_justification() -> None:
    plan = _resolve_call_plan(
        model="openai/gpt-5.6-terra",
        fallback_models=None,
        api_base=None,
        config=ClientConfig(routing_policy="openrouter"),
        model_policy="enforce_allowlist",
        model_justification="Use the reviewed Terra planner route.",
    )

    assert plan.primary_model == "openrouter/openai/gpt-5.6-terra"
    assert plan.routing_trace["model_policy"]["justification"] == (
        "Use the reviewed Terra planner route."
    )


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
        model_policy="enforce_allowlist",
        task="test",
        trace_id="test-model-allowlist-default",
        max_budget=0,
    )

    assert result.routing_trace["model_policy"]["uses_only_default"] is True
    provider_kwargs = completion.call_args.kwargs
    assert "model_policy" not in provider_kwargs
    assert "model_justification" not in provider_kwargs


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


@pytest.mark.parametrize(
    "model",
    [
        "openrouter/openai/gpt-5-mini",
        "openrouter/openai/gpt-5.1-mini",
        "codex/gpt-5.1-codex-mini",
    ],
)
@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
def test_prohibited_mini_routes_fail_even_in_compatibility_mode(
    completion: AsyncMock,
    model: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_CLIENT_OPENROUTER_ROUTING", "on")
    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "allow")

    with pytest.raises(DeprecatedModelError, match="HARD-BLOCKED MODEL"):
        call_llm(
            model,
            [{"role": "user", "content": "hello"}],
            model_policy="compatibility",
            task="test",
            trace_id="test-model-mini-global-reject",
            max_budget=0,
        )

    completion.assert_not_awaited()
