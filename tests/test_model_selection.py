from __future__ import annotations

import os

import pytest

from llm_client.core.model_execution_policy import evaluate_model_execution_policy
from llm_client.core.model_selection import (
    WorkloadRouteContext,
    resolve_model_chain,
    resolve_model_selection,
    resolve_workload_route,
    strict_model_policy,
)


def test_resolve_model_selection_uses_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "llm_client.core.model_selection.get_model",
        lambda task, available_only=False, use_performance=True: f"resolved::{task}",
    )

    selection = resolve_model_selection("graph_building")

    assert selection.model == "resolved::graph_building"
    assert selection.source == "task"
    assert selection.strict_models is True


def test_resolve_model_selection_preserves_override() -> None:
    selection = resolve_model_selection(
        "graph_building",
        override_model="openrouter/x-ai/grok-4.1-fast",
        strict_models=False,
    )

    assert selection.model == "openrouter/x-ai/grok-4.1-fast"
    assert selection.source == "override"
    assert selection.strict_models is False


def test_resolve_model_selection_rejects_empty_task() -> None:
    with pytest.raises(ValueError, match="task must be non-empty"):
        resolve_model_selection("   ")


def test_resolve_model_chain_resolves_primary_and_fallback_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_model(task: str, available_only: bool = False, use_performance: bool = True) -> str:
        del available_only, use_performance
        return {
            "extraction": "gpt-5.2-pro",
            "budget_extraction": "openrouter/deepseek/deepseek-chat",
        }[task]

    monkeypatch.setattr("llm_client.core.model_selection.get_model", fake_get_model)

    chain = resolve_model_chain(
        "extraction",
        fallback_tasks=["budget_extraction", "extraction"],
        fallback_models=["openrouter/deepseek/deepseek-chat", "gemini/gemini-3-flash-preview"],
    )

    assert chain.primary.model == "gpt-5.2-pro"
    assert chain.fallback_tasks == ["budget_extraction", "extraction"]
    assert chain.fallback_models == [
        "openrouter/deepseek/deepseek-chat",
        "gemini/gemini-3-flash-preview",
    ]


def test_strict_model_policy_sets_and_restores_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_CLIENT_STRICT_MODELS", raising=False)

    with strict_model_policy(True):
        assert os.environ["LLM_CLIENT_STRICT_MODELS"] == "1"

    assert "LLM_CLIENT_STRICT_MODELS" not in os.environ


def test_strict_model_policy_restores_prior_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_CLIENT_STRICT_MODELS", "0")

    with strict_model_policy(True):
        assert os.environ["LLM_CLIENT_STRICT_MODELS"] == "1"

    assert os.environ["LLM_CLIENT_STRICT_MODELS"] == "0"


def _route_context(**overrides: object) -> WorkloadRouteContext:
    values: dict[str, object] = {
        "codex_compatible": True,
        "environment": "trusted_private_automation",
        "subscription_auth_supported": True,
        "subscription_capacity": "available",
        "requires_openai_api_contract": False,
        "requires_openrouter_features": False,
        "openrouter_is_live_best_value": False,
    }
    values.update(overrides)
    return WorkloadRouteContext.model_validate(values)


def test_compatible_trusted_workload_uses_included_codex_capacity() -> None:
    route = resolve_workload_route(_route_context())

    assert route.provider == "codex_subscription"
    assert route.model == "codex/gpt-5.6-luna"
    assert route.reasoning_effort == "medium"

    decision = evaluate_model_execution_policy(
        [route.model],
        justification=route.model_justification,
        reasoning_effort=route.reasoning_effort,
    )
    assert decision.enforced is True


def test_service_workload_uses_direct_openai_api() -> None:
    route = resolve_workload_route(_route_context(environment="service"))

    assert route.provider == "openai_api"
    assert route.model == "gpt-5.6"


def test_openrouter_specific_requirement_is_an_explicit_edge_route() -> None:
    route = resolve_workload_route(
        _route_context(requires_openrouter_features=True)
    )

    assert route.provider == "openrouter"
    assert route.model == "openrouter/openai/gpt-5.6-luna"


def test_exhausted_subscription_requires_a_paid_overflow_decision() -> None:
    with pytest.raises(ValueError, match="declare paid_overflow_route"):
        resolve_workload_route(_route_context(subscription_capacity="exhausted"))


def test_exhausted_subscription_uses_declared_paid_overflow_route() -> None:
    route = resolve_workload_route(
        _route_context(
            subscription_capacity="exhausted",
            paid_overflow_route="openai_api",
        )
    )

    assert route.provider == "openai_api"
    assert route.model == "gpt-5.6"


def test_incompatible_workload_does_not_treat_subscription_state_as_overflow() -> None:
    route = resolve_workload_route(
        _route_context(
            codex_compatible=False,
            subscription_capacity="exhausted",
        )
    )

    assert route.provider == "openai_api"


def test_conflicting_provider_contracts_fail_loud() -> None:
    with pytest.raises(ValueError, match="requirements conflict"):
        resolve_workload_route(
            _route_context(
                requires_openai_api_contract=True,
                requires_openrouter_features=True,
            )
        )
