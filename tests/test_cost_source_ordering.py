"""Cost source ordering across Completions and Responses runtimes.

# mock-ok: isolates the provider-reported, computed, and fallback cost seams.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from llm_client.execution.responses_runtime import _compute_responses_cost
from llm_client.utils.cost_utils import (
    FALLBACK_COST_FLOOR_USD_PER_TOKEN,
    _compute_cost,
    _provider_reported_cost,
)


def _response(
    *,
    hidden_cost: object | None = None,
    usage_cost: object | None = None,
    total_tokens: int = 100,
) -> SimpleNamespace:
    """Build a minimal response carrying optional provider cost evidence."""

    usage = SimpleNamespace(total_tokens=total_tokens)
    if usage_cost is not None:
        usage.cost = usage_cost
    response = SimpleNamespace(usage=usage)
    if hidden_cost is not None:
        response._hidden_params = {"response_cost": hidden_cost}
    return response


@pytest.mark.parametrize("value", [0.0, 0, 0.00123])
def test_provider_reported_nonnegative_cost_is_valid(value: float) -> None:
    assert _provider_reported_cost(_response(hidden_cost=value)) == float(value)


@pytest.mark.parametrize("value", [-0.1, True, "0.01", float("nan"), float("inf")])
def test_invalid_provider_cost_is_rejected(value: object) -> None:
    assert _provider_reported_cost(_response(hidden_cost=value)) is None


def test_hidden_provider_cost_precedes_usage_cost() -> None:
    assert _provider_reported_cost(
        _response(hidden_cost=0.001, usage_cost=0.002)
    ) == pytest.approx(0.001)


def test_mock_attributes_are_not_provider_cost_evidence() -> None:
    assert _provider_reported_cost(MagicMock()) is None


@pytest.mark.parametrize("runtime", ["completions", "responses"])
def test_provider_reported_cost_precedes_computed(runtime: str) -> None:
    response = _response(usage_cost=0.0)
    usage = {"total_tokens": 100}
    with patch("litellm.completion_cost", return_value=0.5) as computed:
        result = (
            _compute_cost(response)
            if runtime == "completions"
            else _compute_responses_cost(response, usage)
        )
    assert result == (0.0, "provider_reported")
    computed.assert_not_called()


@pytest.mark.parametrize("runtime", ["completions", "responses"])
def test_computed_cost_precedes_fallback(runtime: str) -> None:
    response = _response()
    usage = {"total_tokens": 100}
    with patch("litellm.completion_cost", return_value=0.5):
        result = (
            _compute_cost(response)
            if runtime == "completions"
            else _compute_responses_cost(response, usage)
        )
    assert result == (0.5, "computed")


@pytest.mark.parametrize("runtime", ["completions", "responses"])
def test_fallback_is_last_resort(runtime: str) -> None:
    response = _response()
    usage = {"total_tokens": 100}
    with patch("litellm.completion_cost", side_effect=RuntimeError("no price")):
        result = (
            _compute_cost(response)
            if runtime == "completions"
            else _compute_responses_cost(response, usage)
        )
    assert result == (100 * FALLBACK_COST_FLOOR_USD_PER_TOKEN, "fallback_estimate")
