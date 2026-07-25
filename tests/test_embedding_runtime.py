"""Offline contract tests for public embedding execution."""

# mock-ok: provider transport is controlled; the public facade, tag/budget
# contract, retry wrapper, and provider-kwargs boundary are real.

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import llm_client.core.client as client_mod
from llm_client import LLMBudgetExceededError, aembed, embed


@pytest.fixture(autouse=True)
def _explicit_embedding_test_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_CLIENT_OPENROUTER_ROUTING", "off")
    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "allow")
    monkeypatch.setattr("llm_client.utils.rate_limit._cooldown_enabled", False)


def _embedding_response() -> SimpleNamespace:
    return SimpleNamespace(
        data=[{"embedding": [0.25, 0.75]}],
        usage={"prompt_tokens": 3, "total_tokens": 3},
    )


def test_embed_consumes_unlimited_budget_without_provider_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MagicMock(return_value=_embedding_response())
    budget_check = MagicMock()
    monkeypatch.setattr(client_mod.litellm, "embedding", provider)
    monkeypatch.setattr(client_mod.litellm, "completion_cost", lambda **_: 0.001)
    monkeypatch.setattr(client_mod, "_check_budget", budget_check)

    result = embed(
        "text-embedding-3-small",
        "semantic target",
        dimensions=2,
        task="onto_canon6.semantic_embedding",
        trace_id="onto-canon6/plan0162/embedding",
        max_budget=0,
    )

    assert result.embeddings == [[0.25, 0.75]]
    budget_check.assert_called_once_with("onto-canon6/plan0162/embedding", 0.0)
    provider_kwargs = provider.call_args.kwargs
    assert provider_kwargs["dimensions"] == 2
    assert "task" not in provider_kwargs
    assert "trace_id" not in provider_kwargs
    assert "max_budget" not in provider_kwargs


def test_embed_rejects_exhausted_trace_before_provider_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MagicMock()
    monkeypatch.setattr(client_mod.litellm, "embedding", provider)
    monkeypatch.setattr(
        "llm_client.execution.call_contracts._io_log.get_cost",
        lambda **_: 2.0,
    )

    with pytest.raises(LLMBudgetExceededError, match="Budget exceeded"):
        embed(
            "text-embedding-3-small",
            "semantic target",
            task="onto_canon6.semantic_embedding",
            trace_id="onto-canon6/plan0162/embedding",
            max_budget=1.0,
        )

    provider.assert_not_called()


def test_embed_strict_mode_requires_budget_before_provider_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MagicMock()
    monkeypatch.setenv("LLM_CLIENT_REQUIRE_TAGS", "1")
    monkeypatch.setattr(client_mod.litellm, "embedding", provider)

    with pytest.raises(ValueError, match="Missing required kwargs: max_budget"):
        embed(
            "text-embedding-3-small",
            "semantic target",
            task="onto_canon6.semantic_embedding",
            trace_id="onto-canon6/plan0162/embedding",
        )

    provider.assert_not_called()


@pytest.mark.asyncio
async def test_aembed_consumes_unlimited_budget_without_provider_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = AsyncMock(return_value=_embedding_response())
    budget_check = MagicMock()
    monkeypatch.setattr(client_mod.litellm, "aembedding", provider)
    monkeypatch.setattr(client_mod.litellm, "completion_cost", lambda **_: 0.001)
    monkeypatch.setattr(client_mod, "_check_budget", budget_check)

    result = await aembed(
        "text-embedding-3-small",
        ["semantic target"],
        task="onto_canon6.semantic_embedding",
        trace_id="onto-canon6/plan0162/embedding-async",
        max_budget=0,
    )

    assert result.embeddings == [[0.25, 0.75]]
    budget_check.assert_called_once_with(
        "onto-canon6/plan0162/embedding-async",
        0.0,
    )
    provider_kwargs = provider.call_args.kwargs
    assert "task" not in provider_kwargs
    assert "trace_id" not in provider_kwargs
    assert "max_budget" not in provider_kwargs
