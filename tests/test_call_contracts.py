"""Tests for the extracted pre-call contract helpers.

# mock-ok: these helpers depend on observability backend queries and guardrail
# hooks; patching isolates the contract logic without requiring real SQLite
# state or process-wide profile configuration.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from llm_client.execution.call_contracts import (
    check_budget,
    normalize_prompt_ref,
    require_tags,
    resolve_budget_scope,
)
from llm_client.execution.call_wrappers import _prepare_public_call_envelope
from llm_client.core.errors import LLMBudgetExceededError


def test_require_tags_calls_observability_guardrails() -> None:
    """Resolved tasks still invoke the same feature-profile and experiment guards."""
    with (
        patch("llm_client.execution.call_contracts._io_log.enforce_feature_profile") as mock_feature_enforce,
        patch("llm_client.execution.call_contracts._io_log.enforce_experiment_context") as mock_experiment_enforce,
    ):
        require_tags(
            "digimon.benchmark",
            "trace.required.tags",
            0,
            caller="test_call_contracts",
        )

    mock_feature_enforce.assert_called_once_with(
        "digimon.benchmark",
        caller="llm_client.core.client",
    )
    mock_experiment_enforce.assert_called_once_with(
        "digimon.benchmark",
        caller="llm_client.core.client",
    )


def test_normalize_prompt_ref_rejects_blank_values() -> None:
    """Blank prompt references fail loudly before they reach observability."""
    with pytest.raises(ValueError, match="prompt_ref must not be empty"):
        normalize_prompt_ref("   ")


def test_check_budget_raises_when_trace_is_spent() -> None:
    """Budget enforcement happens before dispatch using current trace spend."""
    with patch("llm_client.execution.call_contracts._io_log.get_cost", return_value=5.0):
        with pytest.raises(LLMBudgetExceededError, match="Budget exceeded for trace trace/budget"):
            check_budget("trace/budget", 5.0)


def test_check_budget_blocks_before_dispatch_when_reservation_would_cross_limit() -> None:
    with patch("llm_client.execution.call_contracts._io_log.get_cost", return_value=4.8):
        with pytest.raises(LLMBudgetExceededError, match="reservation exceeds"):
            check_budget("trace/budget", 5.0, reservation=0.3)


def test_public_envelope_reserves_budget_and_strips_internal_kwarg() -> None:
    with patch("llm_client.execution.call_wrappers._check_budget") as check:
        envelope = _prepare_public_call_envelope(
            caller="call_llm", timeout=30,
            messages=[{"role": "user", "content": "test"}],
            kwargs={"task": "test.task", "trace_id": "test/trace", "max_budget": 1.0,
                    "budget_reservation": 0.25, "temperature": 0.1},
        )
    assert check.call_args.kwargs["reservation"] == 0.25
    assert "budget_reservation" not in envelope.runtime_kwargs


def test_check_budget_aggregates_root_scope_and_descendants() -> None:
    """A descendant charges the root scope's settled cost and reservation."""
    with patch("llm_client.execution.call_contracts._io_log.get_cost", return_value=4.8) as get_cost:
        with pytest.raises(LLMBudgetExceededError, match="budget scope trace/root"):
            check_budget(
                "trace/root/operator",
                5.0,
                reservation=0.3,
                budget_scope_trace_id="trace/root",
            )

    get_cost.assert_called_once_with(trace_prefix="trace/root")


@pytest.mark.parametrize("scope", ["", "   ", "trace/other"])
def test_budget_scope_must_be_a_nonempty_trace_ancestor(scope: str) -> None:
    """A call cannot charge an unrelated or malformed trace scope."""
    with pytest.raises(ValueError, match="budget_scope_trace_id"):
        resolve_budget_scope("trace/root/child", scope)


@pytest.mark.parametrize(("spent", "expected"), [(2.5, "50%"), (4.0, "80%")])
def test_check_budget_emits_pre_dispatch_threshold_warning(
    spent: float, expected: str,
) -> None:
    warnings: list[str] = []
    with patch("llm_client.execution.call_contracts._io_log.get_cost", return_value=spent):
        check_budget("trace/budget", 5.0, warning_sink=warnings)
    assert len(warnings) == 1
    assert expected in warnings[0]


def test_check_budget_does_not_warn_for_unlimited_budget() -> None:
    warnings: list[str] = []
    check_budget("trace/unlimited", 0.0, warning_sink=warnings)
    assert warnings == []
