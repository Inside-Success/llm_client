"""Focused tests for the internal structured-call runtime split.

# mock-ok: validates the runtime seam against patched provider transports
"""

from __future__ import annotations

from typing import Annotated, Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field, ValidationError

from llm_client import LRUCache
from llm_client.core.errors import LLMCapabilityError
from llm_client.execution.responses_runtime import (
    _openrouter_compatible_strict_json_schema,
    _provider_compatible_discriminated_union_schema,
    _strict_openai_response_model_schema,
    _strict_json_schema,
)
from llm_client.execution.structured_runtime import _acall_llm_structured_impl, _call_llm_structured_impl


class _City(BaseModel):
    """Minimal schema used to exercise the structured runtime seam."""

    name: str


class _BoundedCount(BaseModel):
    """Response model that distinguishes provider and local validation."""

    count: int = Field(ge=1, description="A strictly positive count.")


class _SearchDecision(BaseModel):
    action: Literal["search"]
    query: str


class _TraverseDecision(BaseModel):
    action: Literal["traverse"]
    seed_id: str


class _PlannerEnvelope(BaseModel):
    decision: Annotated[
        _SearchDecision | _TraverseDecision,
        Field(discriminator="action"),
    ]


class _StopDecision(BaseModel):
    action: Literal["control.stop_retrieval"]
    reason: str


class _StopEnvelope(BaseModel):
    decision: _StopDecision = Field(description="Concrete next planner decision.")


def _mock_structured_response(content: str = '{"name":"Tokyo"}') -> MagicMock:
    """Build a minimal structured completion response."""
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = content
    mock.choices[0].finish_reason = "stop"
    mock.usage.prompt_tokens = 10
    mock.usage.completion_tokens = 5
    mock.usage.total_tokens = 15
    return mock


def test_openrouter_schema_projection_preserves_structural_contract_and_local_validation() -> None:
    """OpenRouter receives structural JSON Schema while Pydantic keeps value checks."""

    schema = _strict_json_schema(_BoundedCount.model_json_schema())
    projected = _openrouter_compatible_strict_json_schema(schema)

    assert schema["properties"]["count"]["minimum"] == 1
    assert projected["additionalProperties"] is False
    assert projected["required"] == ["count"]
    assert projected["properties"]["count"]["type"] == "integer"
    assert "minimum" not in projected["properties"]["count"]
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        _BoundedCount.model_validate({"count": 0})


def test_provider_projection_rewrites_only_disjoint_literal_union() -> None:
    """Provider projection preserves the local contract and proves disjointness."""

    schema = _strict_openai_response_model_schema(_PlannerEnvelope)
    projected = _provider_compatible_discriminated_union_schema(schema)

    assert "oneOf" in schema["properties"]["decision"]
    assert "oneOf" not in projected["properties"]["decision"]
    assert "anyOf" in projected["properties"]["decision"]
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        _PlannerEnvelope.model_validate(
            {"decision": {"action": "unknown", "query": "shipping"}}
        )


def test_provider_projection_preserves_overlapping_one_of() -> None:
    """An arbitrary oneOf is not weakened without a disjointness proof."""

    schema = {
        "oneOf": [
            {"type": "object", "properties": {"value": {"type": "string"}}},
            {"type": "object", "properties": {"value": {"type": "string"}}},
        ]
    }
    projected = _provider_compatible_discriminated_union_schema(schema)

    assert "oneOf" in projected
    assert "anyOf" not in projected


@pytest.fixture(autouse=True)
def _explicit_test_runtime_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep runtime-split tests independent from ambient process policy."""
    monkeypatch.setenv("LLM_CLIENT_OPENROUTER_ROUTING", "off")
    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "allow")


@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion")
def test_structured_runtime_sync_preserves_cache_and_identity_contracts(
    mock_comp: MagicMock,
    _mock_supports_schema: MagicMock,
    _mock_cost: MagicMock,
) -> None:
    """Direct sync runtime calls should preserve the structured-call return contract."""
    cache = LRUCache()
    messages = [{"role": "user", "content": "Name a city"}]
    mock_comp.return_value = _mock_structured_response()

    parsed1, meta1 = _call_llm_structured_impl(
        "gpt-4",
        messages,
        _City,
        cache=cache,
        task="test",
        trace_id="structured.runtime.sync",
        max_budget=0,
    )
    parsed2, meta2 = _call_llm_structured_impl(
        "gpt-4",
        messages,
        _City,
        cache=cache,
        task="test",
        trace_id="structured.runtime.sync",
        max_budget=0,
    )

    assert mock_comp.call_count == 1
    assert parsed1.name == "Tokyo"
    assert parsed2.name == "Tokyo"
    assert meta1.cache_hit is False
    assert meta2.cache_hit is True
    assert meta2.cost_source == "cache_hit"
    assert meta2.requested_model == "gpt-4"
    assert meta2.resolved_model == "gpt-4"
    assert meta2.routing_trace is not None
    assert meta2.routing_trace["attempted_models"] == ["gpt-4"]


@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion")
def test_openrouter_native_schema_inlines_nested_ref_siblings(
    mock_comp: MagicMock,
    _mock_supports_schema: MagicMock,
    _mock_cost: MagicMock,
) -> None:
    """The sync OpenRouter request must not send a ref with sibling description."""

    mock_comp.return_value = _mock_structured_response(
        '{"decision":{"action":"control.stop_retrieval","reason":"Enough evidence."}}'
    )
    parsed, _meta = _call_llm_structured_impl(
        "openrouter/openai/gpt-5.6-luna",
        [{"role": "user", "content": "Stop."}],
        _StopEnvelope,
        task="test",
        trace_id="structured.runtime.openrouter.ref_sibling.sync",
        max_budget=0,
    )

    decision_schema = mock_comp.call_args.kwargs["response_format"]["json_schema"][
        "schema"
    ]["properties"]["decision"]
    assert parsed.decision.action == "control.stop_retrieval"
    assert "$ref" not in decision_schema
    assert decision_schema["description"] == "Concrete next planner decision."
    assert decision_schema["type"] == "object"


@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion")
def test_openrouter_planner_call_sends_disjoint_union_as_any_of(
    mock_comp: MagicMock,
    _mock_supports_schema: MagicMock,
    _mock_cost: MagicMock,
) -> None:
    """The actual OpenRouter request receives the compatible planner schema."""

    mock_comp.return_value = _mock_structured_response(
        '{"decision":{"action":"search","query":"shipping roster"}}'
    )
    parsed, _meta = _call_llm_structured_impl(
        "openrouter/openai/gpt-5.6-luna",
        [{"role": "user", "content": "Find the shipping roster."}],
        _PlannerEnvelope,
        task="test",
        trace_id="structured.runtime.openrouter.discriminated_union",
        max_budget=0,
    )

    decision_schema = mock_comp.call_args.kwargs["response_format"]["json_schema"][
        "schema"
    ]["properties"]["decision"]
    assert parsed.decision.action == "search"
    assert "anyOf" in decision_schema
    assert "oneOf" not in decision_schema


@pytest.mark.asyncio
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
async def test_structured_runtime_async_preserves_cache_and_identity_contracts(
    mock_acompletion: AsyncMock,
    _mock_supports_schema: MagicMock,
    _mock_cost: MagicMock,
) -> None:
    """Direct async runtime calls should preserve the structured-call return contract."""
    cache = LRUCache()
    messages = [{"role": "user", "content": "Name a city"}]
    mock_acompletion.return_value = _mock_structured_response()

    parsed1, meta1 = await _acall_llm_structured_impl(
        "gpt-4",
        messages,
        _City,
        cache=cache,
        task="test",
        trace_id="structured.runtime.async",
        max_budget=0,
    )
    parsed2, meta2 = await _acall_llm_structured_impl(
        "gpt-4",
        messages,
        _City,
        cache=cache,
        task="test",
        trace_id="structured.runtime.async",
        max_budget=0,
    )

    assert mock_acompletion.call_count == 1
    assert parsed1.name == "Tokyo"
    assert parsed2.name == "Tokyo"
    assert meta1.cache_hit is False
    assert meta2.cache_hit is True
    assert meta2.cost_source == "cache_hit"
    assert meta2.requested_model == "gpt-4"
    assert meta2.resolved_model == "gpt-4"
    assert meta2.routing_trace is not None
    assert meta2.routing_trace["attempted_models"] == ["gpt-4"]


@pytest.mark.asyncio
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
async def test_openrouter_async_native_schema_inlines_nested_ref_siblings(
    mock_acompletion: AsyncMock,
    _mock_supports_schema: MagicMock,
    _mock_cost: MagicMock,
) -> None:
    """The async OpenRouter request uses the same ref-safe provider schema."""

    mock_acompletion.return_value = _mock_structured_response(
        '{"decision":{"action":"control.stop_retrieval","reason":"Enough evidence."}}'
    )
    parsed, _meta = await _acall_llm_structured_impl(
        "openrouter/openai/gpt-5.6-luna",
        [{"role": "user", "content": "Stop."}],
        _StopEnvelope,
        task="test",
        trace_id="structured.runtime.openrouter.ref_sibling.async",
        max_budget=0,
    )

    decision_schema = mock_acompletion.call_args.kwargs["response_format"]["json_schema"][
        "schema"
    ]["properties"]["decision"]
    assert parsed.decision.action == "control.stop_retrieval"
    assert "$ref" not in decision_schema
    assert decision_schema["description"] == "Concrete next planner decision."
    assert decision_schema["type"] == "object"


@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch(
    "llm_client.core.client.litellm.completion",
    side_effect=RuntimeError(
        "Invalid schema for response_format 'City': extra required key 'name' "
        "(invalid_json_schema)"
    ),
)
def test_structured_runtime_sync_raises_capability_error_for_gpt5_schema_rejection(
    _mock_comp: MagicMock,
    _mock_supports_schema: MagicMock,
) -> None:
    """Provider-side GPT-5 schema rejection should fail loudly as a capability error."""
    messages = [{"role": "user", "content": "Name a city"}]

    with pytest.raises(LLMCapabilityError, match="provider rejected structured JSON-schema output"):
        _call_llm_structured_impl(
            "openai/gpt-5-mini",
            messages,
            _City,
            task="test",
            trace_id="structured.runtime.sync.gpt5_schema",
            max_budget=0,
        )


@pytest.mark.asyncio
@patch(
    "llm_client.core.client.litellm.aresponses",
    new_callable=AsyncMock,
    side_effect=RuntimeError(
        "Invalid schema for response_format 'City': extra required key 'name' "
        "(invalid_json_schema)"
    ),
)
async def test_structured_runtime_async_raises_capability_error_for_gpt5_schema_rejection(
    _mock_aresponses: AsyncMock,
) -> None:
    """Bare GPT-5 structured responses should surface schema rejection as capability errors."""
    messages = [{"role": "user", "content": "Name a city"}]

    with pytest.raises(LLMCapabilityError, match="provider rejected structured JSON-schema output"):
        await _acall_llm_structured_impl(
            "gpt-5-mini",
            messages,
            _City,
            task="test",
            trace_id="structured.runtime.async.gpt5_schema",
            max_budget=0,
        )
