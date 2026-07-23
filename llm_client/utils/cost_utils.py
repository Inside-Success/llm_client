"""Cost computation and usage extraction utilities.

Extracted from client.py for concern separation. Houses the functions
that parse token usage from litellm responses, compute costs, normalize
cost return values, and extract tool calls from response messages.

This module depends on litellm for cost computation. It must not import
from client.py.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from typing import Any

import litellm

logger = logging.getLogger(__name__)

# Accounting constant — documented in agent_ecology3/docs/ACCOUNTING_CONSTANTS.md
FALLBACK_COST_FLOOR_USD_PER_TOKEN = 0.000001

_PROMPT_TOKEN_DETAIL_FIELDS = (
    "audio_tokens",
    "cache_write_tokens",
    "cached_tokens",
    "cache_creation_tokens",
    "cache_read_input_tokens",
    "image_tokens",
    "text_tokens",
    "video_tokens",
)
_COMPLETION_TOKEN_DETAIL_FIELDS = (
    "reasoning_tokens",
    "audio_tokens",
    "image_tokens",
    "text_tokens",
    "video_tokens",
    "accepted_prediction_tokens",
    "rejected_prediction_tokens",
)


def _extract_bounded_token_details(
    details: Any,
    allowed_fields: tuple[str, ...],
) -> dict[str, int]:
    """Return non-negative integer token counts from an allowlisted detail object."""

    if details is None:
        return {}
    values = details if isinstance(details, Mapping) else None
    result: dict[str, int] = {}
    for field in allowed_fields:
        value = values.get(field) if values is not None else getattr(details, field, None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[field] = value
    return result


def _add_token_details(
    result: dict[str, Any],
    *,
    prompt_details: Any = None,
    completion_details: Any = None,
) -> None:
    """Add bounded nested and convenience token-detail fields in place."""

    prompt = _extract_bounded_token_details(
        prompt_details,
        _PROMPT_TOKEN_DETAIL_FIELDS,
    )
    completion = _extract_bounded_token_details(
        completion_details,
        _COMPLETION_TOKEN_DETAIL_FIELDS,
    )
    if prompt:
        result["prompt_tokens_details"] = prompt
        if "cached_tokens" in prompt:
            result["cached_tokens"] = prompt["cached_tokens"]
        if "cache_creation_tokens" in prompt:
            result["cache_creation_tokens"] = prompt["cache_creation_tokens"]
    if completion:
        result["completion_tokens_details"] = completion
        if "reasoning_tokens" in completion:
            result["reasoning_tokens"] = completion["reasoning_tokens"]


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
    _add_token_details(
        result,
        prompt_details=getattr(usage, "prompt_tokens_details", None),
        completion_details=getattr(usage, "completion_tokens_details", None),
    )
    return result


def _provider_reported_cost(response: Any) -> float | None:
    """Return a finite provider-billed cost when the response carries one.

    LiteLLM exposes provider billing through either
    ``response._hidden_params["response_cost"]`` or ``response.usage.cost``.
    Zero is valid for free or credited calls; booleans, strings, negative
    values, and non-finite floats are not trustworthy billing evidence.
    """

    hidden = getattr(response, "_hidden_params", None)
    candidates = [hidden.get("response_cost") if isinstance(hidden, dict) else None]
    usage = getattr(response, "usage", None)
    candidates.append(getattr(usage, "cost", None) if usage is not None else None)

    for value in candidates:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            cost = float(value)
            if math.isfinite(cost) and cost >= 0:
                return cost
    return None


def _compute_cost(response: Any) -> tuple[float, str]:
    """Compute cost, preferring provider billing over computed estimates."""

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
