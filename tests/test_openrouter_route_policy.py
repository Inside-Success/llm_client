"""Tests for the typed OpenRouter route-policy boundary."""

from __future__ import annotations

import pytest

from llm_client.core.errors import LLMConfigurationError
from llm_client.core.client_dispatch import _finalize_result
from llm_client.core.data_types import LLMCallResult
from llm_client.execution.call_contracts import OpenRouterRoutePolicyV1
from llm_client.utils.openrouter import (
    _enable_openrouter_inline_metadata,
    _openrouter_response_cache_status,
    compile_openrouter_route_policy,
)
from llm_client.observability.replay import build_call_snapshot, snapshot_fingerprint


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
    with pytest.raises(ValueError, match="zero_data_retention"):
        OpenRouterRoutePolicyV1(
            zero_data_retention=True,
            response_cache_mode="enabled",
        )
    with pytest.raises(ValueError, match="requires response_cache_mode='enabled'"):
        OpenRouterRoutePolicyV1(response_cache_ttl_seconds=300)
    with pytest.raises(ValueError, match="greater than 0"):
        OpenRouterRoutePolicyV1(
            response_cache_mode="enabled",
            response_cache_ttl_seconds=0,
        )


def test_policy_normalizes_provider_names_without_changing_order() -> None:
    policy = OpenRouterRoutePolicyV1(allowed_providers=(" Morph ", "DeepInfra"))
    assert policy.allowed_providers == ("Morph", "DeepInfra")


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


def test_policy_applies_explicit_response_cache_headers() -> None:
    payload = {
        "model": "openrouter/deepseek/deepseek-v4-flash",
        "openrouter_route_policy": OpenRouterRoutePolicyV1(
            response_cache_mode="enabled",
            response_cache_ttl_seconds=600,
        ),
    }

    _enable_openrouter_inline_metadata(payload["model"], payload)

    assert payload["extra_headers"] == {
        "X-OpenRouter-Cache": "true",
        "X-OpenRouter-Cache-TTL": "600",
        "X-OpenRouter-Metadata": "enabled",
    }


def test_response_cache_omits_per_call_broadcast_trace_from_cache_key() -> None:
    payload = {
        "model": "openrouter/deepseek/deepseek-v4-flash",
        "metadata": {"task": "corpus", "trace_id": "corpus/batch-1/attempt-1"},
        "openrouter_route_policy": OpenRouterRoutePolicyV1(
            response_cache_mode="enabled"
        ),
    }

    _enable_openrouter_inline_metadata(payload["model"], payload)

    assert "trace" not in payload
    assert payload["metadata"]["trace_id"] == "corpus/batch-1/attempt-1"


def test_response_cache_rejects_explicit_broadcast_trace_body() -> None:
    payload = {
        "model": "openrouter/deepseek/deepseek-v4-flash",
        "trace": {"trace_id": "caller-owned"},
        "openrouter_route_policy": OpenRouterRoutePolicyV1(
            response_cache_mode="enabled"
        ),
    }

    with pytest.raises(LLMConfigurationError) as raised:
        _enable_openrouter_inline_metadata(payload["model"], payload)

    assert raised.value.error_code == "openrouter_response_cache_conflicts_with_trace_body"


def test_default_policy_does_not_enable_response_cache() -> None:
    payload = {
        "model": "openrouter/deepseek/deepseek-v4-flash",
        "openrouter_route_policy": OpenRouterRoutePolicyV1(),
    }

    _enable_openrouter_inline_metadata(payload["model"], payload)

    assert payload["extra_headers"]["X-OpenRouter-Cache"] == "false"


def test_refresh_policy_clears_only_the_matching_cached_response() -> None:
    payload = {
        "model": "openrouter/deepseek/deepseek-v4-flash",
        "openrouter_route_policy": OpenRouterRoutePolicyV1(
            response_cache_mode="refresh",
            response_cache_ttl_seconds=600,
        ),
    }

    _enable_openrouter_inline_metadata(payload["model"], payload)

    assert payload["extra_headers"]["X-OpenRouter-Cache"] == "true"
    assert payload["extra_headers"]["X-OpenRouter-Cache-Clear"] == "true"
    assert payload["extra_headers"]["X-OpenRouter-Cache-TTL"] == "600"


@pytest.mark.parametrize(
    "raw_headers",
    [
        {"X-OpenRouter-Cache": "true"},
        {"x-openrouter-cache-ttl": "600"},
    ],
)
def test_typed_policy_rejects_raw_response_cache_headers(
    raw_headers: dict[str, str],
) -> None:
    payload = {
        "model": "openrouter/deepseek/deepseek-v4-flash",
        "extra_headers": raw_headers,
        "openrouter_route_policy": OpenRouterRoutePolicyV1(
            response_cache_mode="enabled"
        ),
    }

    with pytest.raises(LLMConfigurationError) as raised:
        _enable_openrouter_inline_metadata(payload["model"], payload)

    assert raised.value.error_code == "openrouter_route_policy_conflicts_with_cache_headers"


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
        "response_cache_mode": "disabled",
        "response_cache_ttl_seconds": None,
    }
    assert snapshot["replay"]["unsupported_keys"] == []


def test_policy_mutation_changes_snapshot_identity() -> None:
    common = {
        "public_api": "call_llm",
        "call_kind": "text",
        "requested_model": "openrouter/deepseek/deepseek-v4-flash",
        "messages": [{"role": "user", "content": "hello"}],
        "prompt_ref": None,
        "max_budget": 1.0,
        "timeout": 30,
        "num_retries": 0,
        "reasoning_effort": None,
        "api_base": None,
        "base_delay": 0.0,
        "max_delay": 0.0,
        "retry_on": None,
        "fallback_models": None,
    }
    strict = build_call_snapshot(
        **common,
        public_kwargs={"openrouter_route_policy": OpenRouterRoutePolicyV1(zero_data_retention=True)},
    )
    relaxed = build_call_snapshot(
        **common,
        public_kwargs={"openrouter_route_policy": OpenRouterRoutePolicyV1(zero_data_retention=False)},
    )

    assert snapshot_fingerprint(strict) != snapshot_fingerprint(relaxed)


def test_response_cache_policy_changes_snapshot_identity() -> None:
    common = {
        "public_api": "call_llm",
        "call_kind": "text",
        "requested_model": "openrouter/deepseek/deepseek-v4-flash",
        "messages": [{"role": "user", "content": "hello"}],
        "prompt_ref": None,
        "max_budget": 1.0,
        "timeout": 30,
        "num_retries": 0,
        "reasoning_effort": None,
        "api_base": None,
        "base_delay": 0.0,
        "max_delay": 0.0,
        "retry_on": None,
        "fallback_models": None,
    }
    disabled = build_call_snapshot(
        **common,
        public_kwargs={"openrouter_route_policy": OpenRouterRoutePolicyV1()},
    )
    enabled = build_call_snapshot(
        **common,
        public_kwargs={
            "openrouter_route_policy": OpenRouterRoutePolicyV1(
                response_cache_mode="enabled",
                response_cache_ttl_seconds=600,
            )
        },
    )

    assert snapshot_fingerprint(disabled) != snapshot_fingerprint(enabled)


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"x-openrouter-cache-status": "HIT"}, "hit"),
        ({"llm_provider-x-openrouter-cache-status": "MISS"}, "miss"),
        ({"x-openrouter-cache-status": "UNKNOWN"}, None),
    ],
)
def test_reads_openrouter_response_cache_status(
    headers: dict[str, str], expected: str | None
) -> None:
    raw_response = type(
        "RawResponse",
        (),
        {"_hidden_params": {"additional_headers": headers}},
    )()

    assert _openrouter_response_cache_status(raw_response) == expected


def test_provider_response_cache_hit_updates_result_accounting() -> None:
    raw_response = type(
        "RawResponse",
        (),
        {"_hidden_params": {"headers": {"x-openrouter-cache-status": "HIT"}}},
    )()
    result = LLMCallResult(
        content="cached",
        usage={"total_tokens": 0},
        cost=0.0,
        model="openrouter/openai/gpt-5.6-luna",
        raw_response=raw_response,
        cost_source="provider_reported",
    )

    finalized = _finalize_result(
        result,
        requested_model="openrouter/openai/gpt-5.6-luna",
        resolved_model="openrouter/openai/gpt-5.6-luna",
        routing_trace={"attempted_models": ["openrouter/openai/gpt-5.6-luna"]},
    )

    assert finalized.cache_hit is True
    assert finalized.cost_source == "cache_hit"
    assert finalized.marginal_cost == 0.0
    assert finalized.routing_trace is not None
    assert finalized.routing_trace["openrouter_response_cache_status"] == "hit"
