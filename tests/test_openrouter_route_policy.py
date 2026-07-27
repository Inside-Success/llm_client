"""Tests for the typed OpenRouter route-policy boundary."""

from __future__ import annotations

import pytest

from llm_client.core.errors import LLMConfigurationError
from llm_client.execution.call_contracts import OpenRouterRoutePolicyV1
from llm_client.utils.openrouter import (
    _enable_openrouter_inline_metadata,
    compile_openrouter_route_policy,
)
from llm_client.observability.replay import build_call_snapshot


def test_compiles_typed_policy_without_unrelated_defaults() -> None:
    policy = OpenRouterRoutePolicyV1(
        allowed_providers=("Morph", "DeepInfra"),
        data_collection="deny",
        zero_data_retention=True,
        allow_provider_fallbacks=False,
        sort="price",
    )

    assert compile_openrouter_route_policy(policy) == {
        "require_parameters": True,
        "only": ["Morph", "DeepInfra"],
        "data_collection": "deny",
        "zdr": True,
        "allow_fallbacks": False,
        "sort": "price",
    }


def test_policy_rejects_empty_or_conflicting_constraints() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        OpenRouterRoutePolicyV1(allowed_providers=())
    with pytest.raises(ValueError, match="conflicts"):
        OpenRouterRoutePolicyV1(data_collection="allow", zero_data_retention=True)


def test_policy_applies_to_openrouter_payload() -> None:
    payload = {
        "model": "openrouter/deepseek/deepseek-v4-flash",
        "openrouter_route_policy": OpenRouterRoutePolicyV1(
            allowed_providers=("Morph",), zero_data_retention=True
        ),
    }

    _enable_openrouter_inline_metadata(payload["model"], payload)

    assert payload["provider"] == {
        "require_parameters": True,
        "only": ["Morph"],
        "zdr": True,
    }
    assert "openrouter_route_policy" not in payload


def test_policy_rejects_raw_provider_conflict_before_dispatch() -> None:
    payload = {
        "model": "openrouter/deepseek/deepseek-v4-flash",
        "provider": {"only": ["Morph"]},
        "openrouter_route_policy": OpenRouterRoutePolicyV1(),
    }

    with pytest.raises(LLMConfigurationError) as raised:
        _enable_openrouter_inline_metadata(payload["model"], payload)

    assert raised.value.error_code == "openrouter_route_policy_conflicts_with_provider_kwargs"


def test_policy_rejects_non_openrouter_route_before_dispatch() -> None:
    payload = {"model": "openai/gpt-4o", "openrouter_route_policy": OpenRouterRoutePolicyV1()}

    with pytest.raises(LLMConfigurationError) as raised:
        _enable_openrouter_inline_metadata(payload["model"], payload)

    assert raised.value.error_code == "openrouter_route_policy_on_non_openrouter_route"


def test_policy_is_replay_serializable() -> None:
    snapshot = build_call_snapshot(
        public_api="call_llm",
        call_kind="text",
        requested_model="openrouter/deepseek/deepseek-v4-flash",
        messages=[{"role": "user", "content": "hello"}],
        prompt_ref=None,
        max_budget=1.0,
        timeout=30,
        num_retries=0,
        reasoning_effort=None,
        api_base=None,
        base_delay=0.0,
        max_delay=0.0,
        retry_on=None,
        fallback_models=None,
        public_kwargs={
            "openrouter_route_policy": OpenRouterRoutePolicyV1(
                allowed_providers=("Morph",), zero_data_retention=True
            )
        },
    )

    assert snapshot["request"]["kwargs"]["openrouter_route_policy"] == {
        "allowed_providers": ["Morph"],
        "data_collection": None,
        "zero_data_retention": True,
        "allow_provider_fallbacks": True,
        "sort": None,
        "require_parameters": True,
    }
    assert snapshot["replay"]["unsupported_keys"] == []
