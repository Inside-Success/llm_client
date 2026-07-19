"""Focused tests for the internal structured-call runtime split.

# mock-ok: validates the runtime seam against patched provider transports
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch

import litellm
import pytest
from pydantic import BaseModel, Field, ValidationError

from llm_client import LRUCache
from llm_client.core.errors import LLMCapabilityError
from llm_client.execution.responses_runtime import (
    _openrouter_compatible_strict_json_schema,
    _strict_openai_response_model_schema,
    _strict_json_schema,
)
from llm_client.execution.structured_runtime import (
    _StructuredValidationRetry,
    _acall_llm_structured_impl,
    _build_validation_repair_message,
    _call_llm_structured_impl,
    _robust_validate_json,
)


class _City(BaseModel):
    """Minimal schema used to exercise the structured runtime seam."""

    name: str


class _BoundedCount(BaseModel):
    """Response model that distinguishes provider and local validation."""

    count: int = Field(ge=1, description="A strictly positive count.")


def test_openai_responses_schema_inlines_ref_siblings() -> None:
    """SDK normalization retains field semantics without illegal ref siblings."""
    class Hypothesis(BaseModel):
        read: str

    class Step(BaseModel):
        hypothesis: Hypothesis = Field(description="The actor's current reading.")

    schema = _strict_openai_response_model_schema(Step)
    hypothesis = schema["properties"]["hypothesis"]

    assert "$ref" not in hypothesis
    assert hypothesis["description"] == "The actor's current reading."
    assert hypothesis["type"] == "object"
    assert hypothesis["additionalProperties"] is False
    assert hypothesis["required"] == ["read"]


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


def test_openrouter_schema_projection_rejects_unconstrained_schema() -> None:
    """An open JSON-value schema must not be silently narrowed to a scalar."""
    with pytest.raises(ValueError, match="cannot represent an unconstrained"):
        _openrouter_compatible_strict_json_schema({})


@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion")
def test_openrouter_structured_call_sends_provider_compatible_schema(
    mock_comp: MagicMock,
    _mock_supports_schema: MagicMock,
    _mock_cost: MagicMock,
) -> None:
    """The OpenRouter native path applies the projection to the actual request."""
    mock_comp.return_value = _mock_structured_response('{"count":1}')

    parsed, _meta = _call_llm_structured_impl(
        "openrouter/anthropic/claude-opus-4.8",
        [{"role": "user", "content": "Return one."}],
        _BoundedCount,
        task="test",
        trace_id="structured.runtime.openrouter.schema_projection",
        max_budget=0,
    )

    sent_schema = mock_comp.call_args.kwargs["response_format"]["json_schema"]["schema"]
    assert parsed.count == 1
    assert "minimum" not in sent_schema["properties"]["count"]
    assert sent_schema["additionalProperties"] is False


@patch("llm_client.route_certification_runtime.observe_openrouter_native_success_from_runtime")
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion")
def test_openrouter_native_success_records_route_observation(
    mock_comp: MagicMock,
    _mock_supports_schema: MagicMock,
    _mock_cost: MagicMock,
    observe: MagicMock,
) -> None:
    """A native OpenRouter success sends its exact provider schema to observation."""
    response = _mock_structured_response('{"count":1}')
    response.id = "gen-route-observation"
    mock_comp.return_value = response
    observe.return_value = SimpleNamespace(observation_id="routeobs1_0123456789abcdef01234567")

    parsed, result = _call_llm_structured_impl(
        "openrouter/anthropic/claude-opus-4.8",
        [{"role": "user", "content": "Return one."}],
        _BoundedCount,
        task="test",
        trace_id="structured.runtime.openrouter.route_observation",
        max_budget=0,
    )

    assert parsed.count == 1
    observe.assert_called_once()
    observed_kwargs = observe.call_args.kwargs
    assert observed_kwargs["result"] is result
    assert observed_kwargs["provider_schema"] == mock_comp.call_args.kwargs["response_format"]["json_schema"]["schema"]
    assert observed_kwargs["schema_class"] == "_BoundedCount"
    assert result.warning_records[-1]["code"] == "ROUTE_CERTIFICATION_OBSERVED"


@patch("llm_client.route_certification_runtime.observe_openrouter_native_success_from_runtime")
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion")
def test_openrouter_route_observation_failure_is_visible_without_model_retry(
    mock_comp: MagicMock,
    _mock_supports_schema: MagicMock,
    _mock_cost: MagicMock,
    observe: MagicMock,
) -> None:
    """Metadata failure preserves the successful result and never reroutes the model."""
    response = _mock_structured_response('{"count":1}')
    response.id = "gen-route-observation-failure"
    mock_comp.return_value = response
    observe.side_effect = RuntimeError("generation metadata unavailable")

    parsed, result = _call_llm_structured_impl(
        "openrouter/anthropic/claude-opus-4.8",
        [{"role": "user", "content": "Return one."}],
        _BoundedCount,
        num_retries=0,
        task="test",
        trace_id="structured.runtime.openrouter.route_observation_failure",
        max_budget=0,
    )

    assert parsed.count == 1
    assert mock_comp.call_count == 1
    assert result.warning_records[-1]["code"] == "ROUTE_CERTIFICATION_OBSERVATION_FAILED"
    assert "generation metadata unavailable" in result.warnings[-1]


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


def test_local_structured_validation_accepts_transport_only_json_fence() -> None:
    """A single fenced JSON value still must satisfy the exact response model."""

    class Decision(BaseModel):
        action: Literal["answer"]
        rationale: str

    parsed = _robust_validate_json(
        Decision,
        '```json\n{"action":"answer","rationale":"Enough evidence."}\n```',
    )

    assert parsed == Decision(action="answer", rationale="Enough evidence.")
    with pytest.raises(ValidationError, match="literal_error"):
        _robust_validate_json(
            Decision,
            '{"action":"search","rationale":"Wrong action."}',
        )


def test_litellm_prevalidation_is_disabled_for_local_raw_first_validation() -> None:
    """Raw-first local validation is the temporary provider-framing boundary."""

    assert litellm.enable_json_schema_validation is False


def test_validation_repair_allows_switching_an_invalid_union_variant() -> None:
    """Repair guidance must not trap the model in its first invalid action choice."""

    class StopDecision(BaseModel):
        action: Literal["control.stop_retrieval"]
        covered_obligations: list[str]

    with pytest.raises(ValidationError) as captured:
        StopDecision.model_validate(
            {
                "action": "control.stop_retrieval",
            }
        )

    message = _build_validation_repair_message(
        _StructuredValidationRetry(
            '{"action":"control.stop_retrieval"}',
            captured.value,
        )
    )

    assert "choose another allowed variant" in message["content"]
