"""Contract tests for the shared allowed-model execution policy."""

from collections.abc import Iterable
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
    SHARED_EXECUTION_MODELS,
    evaluate_model_execution_policy,
    evaluate_reasoning_policy,
)
from llm_client.inside_success_policy import INSIDE_SUCCESS_ADDITIONAL_EXECUTION_MODELS


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
        "codex/gpt-5.4",
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
    """Generic GPT-5.5 aliases stay absent outside the company overlay."""
    assert not any("gpt-5.5" in model for model in SHARED_EXECUTION_MODELS)
    assert not any("gpt-5.5" in model for model in REASONING_CAPABILITIES)


def test_gpt54_family_is_absent_from_execution_policy() -> None:
    """Generic GPT-5.4 aliases stay absent outside the company overlay."""
    assert not any("gpt-5.4" in model for model in SHARED_EXECUTION_MODELS)
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


# --- The reviewed downstream overlay is the ONLY way a banned family runs ---
#
# This is the Inside Success downstream. Upstream
# (BrianMills2718/llm_client) asserts flatly that no Opus or GPT-5.4 route
# reaches `ALLOWED_EXECUTION_MODELS`; here that assertion is false on purpose.
# `llm_client/inside_success_policy.py` carries a reviewed, human-accepted
# exception -- the benchmark-selected Grounded Research roster -- and
# `model_execution_policy.py` unions it into the allowlist.
#
# Copying the upstream guard down unchanged would fail, and deleting it would
# leave nothing. So the downstream invariant is narrower and still has teeth:
#
#   1. the shared upstream set stays clean -- a banned family may enter the
#      composed allowlist only through the overlay, never through the set both
#      repositories share. This is what catches the next personal->company
#      sync, or a local edit, quietly adding Opus to the shared set. It asserts
#      on SHARED_EXECUTION_MODELS by name, because deriving the shared set as
#      ALLOWED_EXECUTION_MODELS minus the overlay would subtract away any route
#      that leaked into both, which is the leak's actual shape;
#   2. the overlay's banned roster is pinned here, so it cannot grow another
#      banned route without someone editing this list next to the acceptance
#      record in inside_success_policy.py;
#   3. a banned route that is NOT on that reviewed roster is still refused at
#      the gate, with a justification supplied.
#
# `test_gpt54_family_is_absent_from_execution_policy` above covers one family
# against the generic set and REASONING_CAPABILITIES; point 1 here is the
# family-general form over the same shared set, and adds Opus, which had none.
#
# Point 3 matters because the failure does not present as an open door. Once a
# route is in the allowlist it stops failing with "not in the llm_client
# execution allowlist" and starts failing with "requires model_justification"
# -- which any caller clears by passing a string. Nothing reviews that string.

BANNED_MODEL_FAMILIES = ("opus", "gpt-5.4", "gpt-5-4")

# Exactly the banned-family routes the reviewed Inside Success overlay accepts.
# Keep in sync with INSIDE_SUCCESS_ADDITIONAL_EXECUTION_MODELS and the
# `model_override_acceptance` record beside it.
REVIEWED_DOWNSTREAM_BANNED_ROUTES = (
    "claude-code/claude-opus-4-8",
    "codex/gpt-5.4-mini",
    "codex/gpt-5.4-nano",
    "openrouter/anthropic/claude-opus-4.8",
    "openrouter/openai/gpt-5.4-mini",
    "openrouter/openai/gpt-5.4-nano",
)


def _banned_routes(models: Iterable[str]) -> list[str]:
    lowered = ((model, model.lower()) for model in models)
    return sorted(
        model
        for model, low in lowered
        if any(family in low for family in BANNED_MODEL_FAMILIES)
    )


def test_shared_upstream_allowlist_carries_no_banned_family() -> None:
    """A banned family may reach the gate only through the reviewed overlay."""

    leaked = _banned_routes(SHARED_EXECUTION_MODELS)

    assert leaked == [], (
        "banned model routes reached the execution allowlist outside the "
        f"reviewed Inside Success overlay: {leaked}. ADR 0016 decision 5 and "
        "Plan #348 ban the Opus and GPT-5.4 families in the shared runtime. "
        "The company exception lives in llm_client/inside_success_policy.py "
        "next to its acceptance record; it does not belong in the set both "
        "repositories share."
    )


def test_reviewed_overlay_roster_has_not_grown() -> None:
    """The accepted exception is a fixed roster, not an open category."""

    overlay = _banned_routes(INSIDE_SUCCESS_ADDITIONAL_EXECUTION_MODELS)

    assert overlay == sorted(REVIEWED_DOWNSTREAM_BANNED_ROUTES), (
        "the Inside Success overlay's banned-family roster changed. Every "
        "Opus/GPT-5.4 route it allows is a reviewed exception recorded in "
        "llm_client/inside_success_policy.py under model_override_acceptance. "
        "Adding one is a policy decision: update that record, then update "
        "REVIEWED_DOWNSTREAM_BANNED_ROUTES here."
    )


def test_unreviewed_banned_route_is_refused_even_with_a_justification() -> None:
    """A justification is a caller-supplied string, not a review of the ban."""

    unreviewed = (
        "openrouter/anthropic/claude-opus-4.1",
        "openrouter/openai/gpt-5.4",
        "gpt-5.4",
    )
    for model in unreviewed:
        assert model not in ALLOWED_EXECUTION_MODELS, (
            f"{model} is used here as a route the reviewed overlay does not "
            "cover; it must stay outside the allowlist for this test to mean "
            "anything."
        )
        with pytest.raises(LLMConfigurationError, match="execution allowlist"):
            evaluate_model_execution_policy(
                [model],
                justification="benchmark-selected for a downstream consumer",
            )
