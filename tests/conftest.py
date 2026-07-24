"""Shared test fixtures for llm_client test suite.

Disables observability logging during tests to prevent test mocks and fixtures
from polluting the production JSONL + SQLite observability data.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _disable_observability_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent tests from writing to the real observability DB/JSONL."""
    monkeypatch.setenv("LLM_CLIENT_LOG_ENABLED", "0")


@pytest.fixture(autouse=True)
def _isolate_process_local_model_availability() -> None:
    """Prevent one simulated provider failure from suppressing later tests."""
    from llm_client.core.model_availability import clear_model_unavailability

    clear_model_unavailability()
    yield
    clear_model_unavailability()


@pytest.fixture(autouse=True)
def _isolate_non_policy_tests_from_the_execution_allowlist(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Keep legacy transport fixtures focused on their own behavior.

    Most of the suite intentionally uses fake or historical model identifiers
    to exercise transport, retry, and parsing branches. The dedicated model
    policy module tests the real fail-closed boundary; other tests receive an
    enforced test decision so they do not become a duplicate allowlist suite.
    """
    if request.path.name == "test_model_execution_policy.py":
        return

    from llm_client.core.model_execution_policy import (
        DEFAULT_EXECUTION_MODEL,
        ModelExecutionDecision,
        REASONING_EFFORTS,
        ReasoningPolicyDecision,
    )

    def test_policy_decision(
        models: list[str],
        *,
        mode: str = "enforce_allowlist",
        justification: str | None = None,
        reasoning_effort: str | None = None,
    ) -> ModelExecutionDecision:
        selected = [str(model).strip() for model in models]
        normalized = str(justification).strip() if justification is not None else None
        uses_only_default = all(model == DEFAULT_EXECUTION_MODEL for model in selected)
        return ModelExecutionDecision(
            mode="enforce_allowlist",
            enforced=True,
            default_model=DEFAULT_EXECUTION_MODEL,
            selected_models=selected,
            uses_only_default=uses_only_default,
            justification=normalized or (
                None if uses_only_default else "Authorized synthetic model in non-policy test."
            ),
            reasoning_policy=ReasoningPolicyDecision(
                required=False,
                effort=(
                    str(reasoning_effort).strip().lower()
                    if reasoning_effort is not None
                    and str(reasoning_effort).strip().lower() in REASONING_EFFORTS
                    else None
                ),
                configurable_models=[],
            ),
        )

    monkeypatch.setattr(
        "llm_client.core.client_dispatch.evaluate_model_execution_policy",
        test_policy_decision,
    )
