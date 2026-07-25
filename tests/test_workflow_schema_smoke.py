"""Live-LLM schema smoke tests for the duet + deliberation stack.

The chassis's unit tests stub ``call_llm_structured`` entirely — they verify
wiring, schema-as-Python, routing, persistence, convergence. They do NOT
verify that the JSON schemas the chassis sends to a real LLM provider are
accepted by that provider.

That gap caused two failures Brian's external multi-agent review run hit:
- codex (OpenAI strict structured outputs) rejected schemas missing
  ``additionalProperties: false`` with "additionalProperties is required".
- claude-code silently failed on larger schemas with the same gap (no
  ``plan_review.json`` written, only startup log).

These tests are the minimum live-LLM round-trip that catches that class
of bug. Each test picks one (reviewer_model, schema) pair, sends a trivial
prompt asking for a default-shaped payload, and asserts the call returns
without a schema-validation error.

Gated on ``LLM_CLIENT_INTEGRATION=1`` so they don't run in offline CI.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from llm_client.workflow.duet import ImplementReview, PlanReview
from llm_client.workflow.profiles.twin_update import (
    TwinUpdateImplementReview,
    TwinUpdatePlanReview,
)


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("LLM_CLIENT_INTEGRATION"),
        reason="set LLM_CLIENT_INTEGRATION=1 to enable live-LLM smoke tests",
    ),
]


# ---------------------------------------------------------------------------
# Reviewer schemas — exercise the structured-output path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reviewer_model",
    ["claude-code/sonnet", "codex/gpt-5.4"],
)
@pytest.mark.parametrize(
    "schema_cls",
    [PlanReview, ImplementReview, TwinUpdatePlanReview, TwinUpdateImplementReview],
    ids=lambda c: c.__name__,
)
def test_reviewer_schema_accepted_by_real_llm(
    reviewer_model: str, schema_cls: type
) -> None:
    """Real LLM round-trip: the JSON schema must be accepted by the provider.

    Trivial prompt asks for ``verdict=pass`` with empty lists. We aren't
    testing the LLM's reviewing quality here — only that the schema is
    structurally valid for the provider's structured-output API.
    """
    from llm_client.core.client import call_llm_structured

    instruction = (
        f"Return a minimal {schema_cls.__name__} with verdict=\"pass\", "
        f"reviewer_summary=\"smoke ok\", reviewer_model=\"{reviewer_model}\", "
        f"and every list field empty. Do not add any extra fields."
    )
    result, _meta = call_llm_structured(
        reviewer_model,
        [{"role": "user", "content": instruction}],
        schema_cls,
        task="schema_smoke",
        trace_id=f"schema_smoke/{schema_cls.__name__}/{reviewer_model}",
        max_budget=0.50,
        timeout=300,
        cwd=os.getcwd(),
    )
    assert result.verdict == "pass", (
        f"Expected verdict='pass' from {reviewer_model} on {schema_cls.__name__}, "
        f"got {result.verdict!r}"
    )


# ---------------------------------------------------------------------------
# Deliberation Position schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reviewer_model",
    ["claude-code/sonnet", "codex/gpt-5.4"],
)
def test_deliberation_position_accepted_by_real_llm(reviewer_model: str) -> None:
    """Same idea for the deliberation Position schema — verifies the
    deliberation workflow can actually run through real LLMs.
    """
    from llm_client.core.client import call_llm_structured
    from llm_client.workflow.deliberate import Position

    instruction = (
        "Return a minimal Position with agent_name=\"smoke\", round=1, "
        "every list empty, confidence=\"low\", state=\"initial\", and "
        "reviewer_summary=\"smoke ok\". Do not add any extra fields."
    )
    result, _meta = call_llm_structured(
        reviewer_model,
        [{"role": "user", "content": instruction}],
        Position,
        task="schema_smoke",
        trace_id=f"schema_smoke/Position/{reviewer_model}",
        max_budget=0.50,
        timeout=300,
        cwd=os.getcwd(),
    )
    assert result.agent_name == "smoke", (
        f"Expected agent_name='smoke' from {reviewer_model}, got {result.agent_name!r}"
    )
    assert result.round == 1
