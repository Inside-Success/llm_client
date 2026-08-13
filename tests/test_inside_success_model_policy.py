"""Inside Success downstream policy must preserve Grounded's active seats."""

import pytest

from llm_client.core.errors import DeprecatedModelError
from llm_client.core.model_execution_policy import ALLOWED_EXECUTION_MODELS
from llm_client.execution.call_contracts import _check_model_deprecation
from llm_client.inside_success_policy import (
    INSIDE_SUCCESS_ADDITIONAL_EXECUTION_MODELS,
    INSIDE_SUCCESS_HARD_BLOCK_EXCEPTIONS,
)

EXPECTED_ADDITIONAL_ROUTES = {
    "claude-code/claude-opus-4-8",
    "claude-code/claude-sonnet-4-6",
    "claude-code/claude-sonnet-5",
    "codex/gpt-5-nano",
    "codex/gpt-5.4-mini",
    "codex/gpt-5.4-nano",
    "codex/gpt-5.5",
    "openrouter/anthropic/claude-opus-4.8",
    "openrouter/anthropic/claude-sonnet-4.6",
    "openrouter/anthropic/claude-sonnet-5",
    "openrouter/google/gemini-2.5-flash",
    "openrouter/google/gemini-2.5-flash-lite",
    "openrouter/google/gemini-3.1-flash-lite",
    "openrouter/openai/gpt-5.4-mini",
    "openrouter/openai/gpt-5.4-nano",
    "openrouter/openai/gpt-5.5",
}


def test_company_overlay_is_exact_and_allowlisted() -> None:
    assert INSIDE_SUCCESS_ADDITIONAL_EXECUTION_MODELS == EXPECTED_ADDITIONAL_ROUTES
    assert EXPECTED_ADDITIONAL_ROUTES <= ALLOWED_EXECUTION_MODELS


@pytest.mark.parametrize("model", sorted(INSIDE_SUCCESS_HARD_BLOCK_EXCEPTIONS))
def test_company_approved_route_bypasses_generic_hard_block(model: str) -> None:
    _check_model_deprecation(model)


def test_unapproved_neighbor_remains_hard_blocked() -> None:
    with pytest.raises(DeprecatedModelError, match="HARD-BLOCKED MODEL"):
        _check_model_deprecation("openrouter/anthropic/claude-opus-4.7")
