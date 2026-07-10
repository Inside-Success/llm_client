"""Cost computation and usage extraction utilities.

Extracted from client.py for concern separation. Houses the functions
that parse token usage from litellm responses, compute costs, normalize
cost return values, and extract tool calls from response messages.

This module depends on litellm for cost computation. It must not import
from client.py.
"""

from __future__ import annotations

import logging
from typing import Any

import litellm

logger = logging.getLogger(__name__)

# Accounting constant — documented in agent_ecology3/docs/ACCOUNTING_CONSTANTS.md
FALLBACK_COST_FLOOR_USD_PER_TOKEN = 0.000001


def _extract_usage(response: Any) -> dict[str, Any]:
    """Extract token usage dict from litellm response.

    Includes provider-level prompt caching details when available
    (OpenAI cached_tokens, DeepSeek prompt_cache_hit_tokens,
    Anthropic cache_read_input_tokens).
    """
    usage = response.usage
    result = {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }
    # Extract prompt caching details (litellm normalizes all providers
    # into prompt_tokens_details.cached_tokens)
    ptd = getattr(usage, "prompt_tokens_details", None)
    if ptd is not None:
        cached = getattr(ptd, "cached_tokens", None) or 0
        cache_creation = getattr(ptd, "cache_creation_tokens", None) or 0
        result["cached_tokens"] = cached
        result["cache_creation_tokens"] = cache_creation
    return result


def _provider_reported_cost(response: Any) -> float | None:
    """Actual provider-billed cost when the response carries one (e.g. OpenRouter).

    litellm surfaces it as ``response._hidden_params["response_cost"]`` and/or
    ``usage.cost``. Only a real positive number counts — any other shape means
    "not reported" (mock/absent attributes must never masquerade as cost).
    """
    hidden = getattr(response, "_hidden_params", None)
    if isinstance(hidden, dict):
        value = hidden.get("response_cost")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value)
    usage = getattr(response, "usage", None)
    value = getattr(usage, "cost", None) if usage is not None else None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return None


def _compute_cost(response: Any) -> tuple[float, str]:
    """Compute cost with explicit source tagging, preferring real cost over estimation.

    Ordering: (1) provider-reported actual cost when the response carries one,
    (2) litellm.completion_cost, (3) flat per-token floor (warned, last resort).
    """
    provider_cost = _provider_reported_cost(response)
    if provider_cost is not None:
        return provider_cost, "provider_reported"
    try:
        cost = float(litellm.completion_cost(completion_response=response))
        return cost, "computed"
    except Exception:
        # Fallback: rough estimate based on total tokens
        total: int = response.usage.total_tokens
        fallback = total * FALLBACK_COST_FLOOR_USD_PER_TOKEN
        logger.warning(
            "completion_cost failed, using fallback: $%.6f for %d tokens",
            fallback,
            total,
        )
        return fallback, "fallback_estimate"


def _parse_cost_result(value: float | tuple[float, str], default_source: str = "computed") -> tuple[float, str]:
    """Normalize cost helper return values.

    Supports both new tuple return and legacy float return to keep monkeypatch
    compatibility in tests and downstream callers.
    """
    if isinstance(value, tuple) and len(value) == 2:
        return float(value[0]), str(value[1])
    return float(value), default_source


def _extract_tool_calls(message: Any) -> list[dict[str, Any]]:
    """Extract tool calls from response message into plain dicts."""
    if not message.tool_calls:
        return []
    result: list[dict[str, Any]] = []
    for tc in message.tool_calls:
        result.append({
            "id": tc.id,
            "type": tc.type,
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments,
            },
        })
    return result
