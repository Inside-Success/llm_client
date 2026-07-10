"""Cost-source ordering: provider-reported beats computed beats fallback.

The root fix for flat-rate cost drift: when the provider returns the actual
billed cost (OpenRouter does — litellm exposes it via
``response._hidden_params["response_cost"]`` and/or ``usage.cost``), that value
wins over litellm's price-table estimate, which in turn wins over the flat
per-token floor. Both the completions path (``cost_utils._compute_cost``) and
the Responses API path (``responses_runtime._compute_responses_cost``) follow
the same ordering.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from llm_client.execution.responses_runtime import _compute_responses_cost
from llm_client.utils.cost_utils import (
    FALLBACK_COST_FLOOR_USD_PER_TOKEN,
    _compute_cost,
    _parse_cost_result,
    _provider_reported_cost,
)


def _response(
    hidden_cost: object = None,
    usage_cost: object = None,
    total_tokens: int = 100,
) -> SimpleNamespace:
    usage = SimpleNamespace(
        prompt_tokens=60, completion_tokens=40, total_tokens=total_tokens
    )
    if usage_cost is not None:
        usage.cost = usage_cost
    response = SimpleNamespace(usage=usage)
    if hidden_cost is not None:
        response._hidden_params = {"response_cost": hidden_cost}
    return response


class TestProviderReportedCost:
    def test_hidden_params_response_cost_extracted(self) -> None:
        assert _provider_reported_cost(_response(hidden_cost=0.00123)) == 0.00123

    def test_usage_cost_extracted(self) -> None:
        assert _provider_reported_cost(_response(usage_cost=0.00456)) == 0.00456

    def test_hidden_params_beats_usage_cost(self) -> None:
        response = _response(hidden_cost=0.001, usage_cost=0.002)
        assert _provider_reported_cost(response) == 0.001

    def test_zero_negative_bool_and_mock_are_not_costs(self) -> None:
        assert _provider_reported_cost(_response(hidden_cost=0.0)) is None
        assert _provider_reported_cost(_response(hidden_cost=-0.1)) is None
        assert _provider_reported_cost(_response(hidden_cost=True)) is None
        assert _provider_reported_cost(_response(usage_cost="0.01")) is None
        # A bare MagicMock auto-creates truthy attributes; none of them may
        # masquerade as a provider cost.
        assert _provider_reported_cost(MagicMock()) is None


class TestComputeCostOrdering:
    def test_provider_reported_beats_computed(self) -> None:
        with patch("litellm.completion_cost", return_value=0.5) as mock_cost:
            cost, source = _compute_cost(_response(hidden_cost=0.00123))
        assert (cost, source) == (0.00123, "provider_reported")
        mock_cost.assert_not_called()

    def test_computed_when_no_provider_cost(self) -> None:
        with patch("litellm.completion_cost", return_value=0.5):
            cost, source = _compute_cost(_response())
        assert (cost, source) == (0.5, "computed")

    def test_fallback_last_resort(self) -> None:
        with patch("litellm.completion_cost", side_effect=Exception("no pricing")):
            cost, source = _compute_cost(_response(total_tokens=100))
        assert source == "fallback_estimate"
        assert cost == 100 * FALLBACK_COST_FLOOR_USD_PER_TOKEN

    def test_provider_reported_rescues_pricing_failure(self) -> None:
        with patch("litellm.completion_cost", side_effect=Exception("no pricing")):
            cost, source = _compute_cost(_response(usage_cost=0.00456))
        assert (cost, source) == (0.00456, "provider_reported")


class TestResponsesCostOrdering:
    def test_provider_reported_beats_computed(self) -> None:
        usage = {"prompt_tokens": 60, "completion_tokens": 40, "total_tokens": 100}
        with patch("litellm.completion_cost", return_value=0.5) as mock_cost:
            cost, source = _compute_responses_cost(_response(usage_cost=0.00456), usage)
        assert (cost, source) == (0.00456, "provider_reported")
        mock_cost.assert_not_called()

    def test_computed_when_no_provider_cost(self) -> None:
        usage = {"prompt_tokens": 60, "completion_tokens": 40, "total_tokens": 100}
        with patch("litellm.completion_cost", return_value=0.5):
            cost, source = _compute_responses_cost(_response(), usage)
        assert (cost, source) == (0.5, "computed")

    def test_fallback_last_resort(self) -> None:
        usage = {"prompt_tokens": 60, "completion_tokens": 40, "total_tokens": 100}
        with patch("litellm.completion_cost", side_effect=Exception("no pricing")):
            cost, source = _compute_responses_cost(_response(), usage)
        assert source == "fallback_estimate"
        assert cost == 100 * FALLBACK_COST_FLOOR_USD_PER_TOKEN


class TestParseCostResultCompatibility:
    def test_tuple_passthrough(self) -> None:
        assert _parse_cost_result((0.1, "provider_reported")) == (0.1, "provider_reported")

    def test_legacy_float_gets_default_source(self) -> None:
        assert _parse_cost_result(0.1) == (0.1, "computed")
        assert _parse_cost_result(0.1, default_source="x") == (0.1, "x")
