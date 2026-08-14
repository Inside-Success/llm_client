"""Focused tests for the internal structured-call runtime split.

# mock-ok: validates the runtime seam against patched provider transports
"""

from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace
from typing import Annotated, Literal
from unittest.mock import AsyncMock, MagicMock, patch

import litellm
import pytest
from pydantic import BaseModel, Field, ValidationError

from llm_client import LLMCallResult, LRUCache
from llm_client.core.errors import LLMCapabilityError, LLMError, LLMLogicalDeadlineError
from llm_client.execution.responses_runtime import (
    _openrouter_compatible_strict_json_schema,
    _provider_compatible_discriminated_union_schema,
    _strict_json_schema,
    _strict_openai_response_model_schema,
)
from llm_client.execution.structured_runtime import (
    _acall_llm_structured_impl,
    _build_parse_repair_message,
    _build_validation_repair_message,
    _call_llm_structured_impl,
    _robust_validate_json,
    _StructuredValidationRetry,
)


class _City(BaseModel):
    """Minimal schema used to exercise the structured runtime seam."""

    name: str


class _BoundedCount(BaseModel):
    """Response model that distinguishes provider and local validation."""

    count: int = Field(ge=1, description="A strictly positive count.")


class _UniqueTags(BaseModel):
    """Schema whose uniqueness rule remains a caller-side invariant."""

    tags: list[str] = Field(json_schema_extra={"uniqueItems": True})


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


def test_openrouter_schema_projection_removes_unsupported_unique_items() -> None:
    """OpenRouter receives the array shape without its unsupported value keyword."""
    schema = _strict_json_schema(_UniqueTags.model_json_schema())

    projected = _openrouter_compatible_strict_json_schema(schema)

    assert schema["properties"]["tags"]["uniqueItems"] is True
    assert "uniqueItems" not in projected["properties"]["tags"]
    assert projected["properties"]["tags"]["type"] == "array"
    assert projected["properties"]["tags"]["items"] == {"type": "string"}


def test_openrouter_schema_projection_rejects_unconstrained_schema() -> None:
    """An open JSON-value schema must not be silently narrowed to a scalar."""
    with pytest.raises(ValueError, match="cannot represent an unconstrained"):
        _openrouter_compatible_strict_json_schema({})


def test_provider_projection_rewrites_only_disjoint_literal_union() -> None:
    """Provider projection preserves the local contract and proves disjointness."""

    schema = _strict_openai_response_model_schema(_PlannerEnvelope)
    projected = _provider_compatible_discriminated_union_schema(schema)

    assert "oneOf" in schema["properties"]["decision"]
    assert "oneOf" not in projected["properties"]["decision"]
    assert "anyOf" in projected["properties"]["decision"]
    assert "discriminator" not in projected["properties"]["decision"]
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        _PlannerEnvelope.model_validate(
            {"decision": {"action": "unknown", "query": "shipping"}}
        )


def test_provider_projection_preserves_overlapping_one_of() -> None:
    """An arbitrary oneOf is not weakened into anyOf without a proof."""

    schema = {
        "oneOf": [
            {"type": "object", "properties": {"value": {"type": "string"}}},
            {"type": "object", "properties": {"value": {"type": "string"}}},
        ]
    }

    projected = _provider_compatible_discriminated_union_schema(schema)

    assert "oneOf" in projected
    assert "anyOf" not in projected


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
        "openrouter/deepseek/deepseek-v4-flash",
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


@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion")
def test_sync_logical_timeout_caps_provider_attempt_and_stops_chain(
    mock_comp: MagicMock,
    _mock_supports_schema: MagicMock,
) -> None:
    """One hung sync attempt exhausts the total budget without retry/fallback."""

    def _slow_completion(**_: object) -> object:
        time.sleep(0.1)
        return _mock_structured_response('{"count":1}')

    mock_comp.side_effect = _slow_completion
    started = time.monotonic()

    with pytest.raises(
        LLMLogicalDeadlineError,
        match="structured logical call deadline elapsed",
    ):
        _call_llm_structured_impl(
            "openrouter/deepseek/deepseek-v4-flash",
            [{"role": "user", "content": "Return one."}],
            _BoundedCount,
            timeout=60,
            logical_timeout=0.02,
            num_retries=3,
            fallback_models=["openrouter/deepseek/deepseek-v4-flash"],
            task="test",
            trace_id="structured.runtime.logical_deadline.sync",
            max_budget=0,
        )

    assert time.monotonic() - started < 0.09
    assert mock_comp.call_count == 1
    assert 0 < mock_comp.call_args.kwargs["timeout"] <= 0.02


@pytest.mark.asyncio
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
async def test_async_logical_timeout_caps_provider_attempt_and_stops_chain(
    mock_acompletion: AsyncMock,
    _mock_supports_schema: MagicMock,
) -> None:
    """The async provider path enforces the same total structured-call budget."""

    async def _slow_completion(**_: object) -> object:
        await asyncio.sleep(0.1)
        return _mock_structured_response('{"count":1}')

    mock_acompletion.side_effect = _slow_completion
    started = time.monotonic()

    with pytest.raises(
        LLMLogicalDeadlineError,
        match="structured logical call deadline elapsed",
    ):
        await _acall_llm_structured_impl(
            "openrouter/deepseek/deepseek-v4-flash",
            [{"role": "user", "content": "Return one."}],
            _BoundedCount,
            timeout=60,
            logical_timeout=0.02,
            num_retries=3,
            fallback_models=["openrouter/deepseek/deepseek-v4-flash"],
            task="test",
            trace_id="structured.runtime.logical_deadline.async",
            max_budget=0,
        )

    assert time.monotonic() - started < 0.09
    assert mock_acompletion.await_count == 1
    assert 0 < mock_acompletion.call_args.kwargs["timeout"] <= 0.02


@patch("llm_client.sdk.agents._route_call_structured")
def test_sync_logical_timeout_floors_agent_adapter_timeout(
    mock_agent_call: MagicMock,
) -> None:
    """A fractional remaining deadline reaches the sync agent as whole seconds."""

    mock_agent_call.return_value = (
        _BoundedCount(count=1),
        LLMCallResult(
            content='{"count":1}',
            usage={},
            cost=0.0,
            model="codex/gpt-5.6-luna",
            requested_model="codex/gpt-5.6-luna",
            resolved_model="codex/gpt-5.6-luna",
        ),
    )

    parsed, _metadata = _call_llm_structured_impl(
        "codex/gpt-5.6-luna",
        [{"role": "user", "content": "Return one."}],
        _BoundedCount,
        timeout=0,
        logical_timeout=360,
        num_retries=0,
        fallback_models=[],
        reasoning_effort="medium",
        model_justification="Exercise the exact approved Luna agent route.",
        task="test",
        trace_id="structured.runtime.agent.logical_deadline.sync",
        max_budget=0,
    )

    adapter_timeout = mock_agent_call.call_args.kwargs["timeout"]
    assert parsed.count == 1
    assert isinstance(adapter_timeout, int)
    assert 0 < adapter_timeout < 360


@pytest.mark.asyncio
@patch("llm_client.sdk.agents._route_acall_structured", new_callable=AsyncMock)
async def test_async_logical_timeout_floors_agent_adapter_timeout(
    mock_agent_call: AsyncMock,
) -> None:
    """A fractional remaining deadline reaches the async agent as whole seconds."""

    mock_agent_call.return_value = (
        _BoundedCount(count=1),
        LLMCallResult(
            content='{"count":1}',
            usage={},
            cost=0.0,
            model="codex/gpt-5.6-luna",
            requested_model="codex/gpt-5.6-luna",
            resolved_model="codex/gpt-5.6-luna",
        ),
    )

    parsed, _metadata = await _acall_llm_structured_impl(
        "codex/gpt-5.6-luna",
        [{"role": "user", "content": "Return one."}],
        _BoundedCount,
        timeout=0,
        logical_timeout=360,
        num_retries=0,
        fallback_models=[],
        reasoning_effort="medium",
        model_justification="Exercise the exact approved Luna agent route.",
        task="test",
        trace_id="structured.runtime.agent.logical_deadline.async",
        max_budget=0,
    )

    adapter_timeout = mock_agent_call.call_args.kwargs["timeout"]
    assert parsed.count == 1
    assert isinstance(adapter_timeout, int)
    assert 0 < adapter_timeout < 360


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
        "openrouter/deepseek/deepseek-v4-flash",
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
        "openrouter/deepseek/deepseek-v4-flash",
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


@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.completion")
def test_openrouter_planner_call_sends_disjoint_union_as_any_of(
    mock_comp: MagicMock,
    _mock_cost: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The actual OpenRouter native request receives the compatible planner schema."""

    monkeypatch.setenv("LLM_CLIENT_ROUTE_CERTIFICATION_OBSERVATION", "disabled")
    mock_comp.return_value = _mock_structured_response(
        '{"decision":{"action":"search","query":"shipping roster"}}'
    )

    parsed, _meta = _call_llm_structured_impl(
        "openrouter/openai/gpt-5.6-terra",
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


@patch("llm_client.route_certification_runtime.observe_openrouter_native_success_from_runtime")
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion")
def test_openrouter_native_success_records_route_observation(
    mock_comp: MagicMock,
    _mock_supports_schema: MagicMock,
    _mock_cost: MagicMock,
    observe: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A native OpenRouter success sends its exact provider schema to observation."""
    monkeypatch.setenv("LLM_CLIENT_ROUTE_CERTIFICATION_OBSERVATION", "enabled")
    response = _mock_structured_response('{"count":1}')
    response.id = "gen-route-observation"
    mock_comp.return_value = response
    observe.return_value = SimpleNamespace(observation_id="routeobs1_0123456789abcdef01234567")

    parsed, result = _call_llm_structured_impl(
        "openrouter/deepseek/deepseek-v4-flash",
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
def test_openrouter_route_observation_is_disabled_by_default(
    mock_comp: MagicMock,
    _mock_supports_schema: MagicMock,
    _mock_cost: MagicMock,
    observe: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ordinary PoC inference can skip optional provider-metadata certification."""

    response = _mock_structured_response('{"count":1}')
    response.id = "gen-route-observation-disabled"
    mock_comp.return_value = response
    monkeypatch.delenv("LLM_CLIENT_ROUTE_CERTIFICATION_OBSERVATION", raising=False)
    caplog.set_level(logging.INFO, logger="llm_client.structured_runtime")

    parsed, result = _call_llm_structured_impl(
        "openrouter/deepseek/deepseek-v4-flash",
        [{"role": "user", "content": "Return one."}],
        _BoundedCount,
        task="test",
        trace_id="structured.runtime.openrouter.route_observation_disabled",
        max_budget=0,
    )

    assert parsed.count == 1
    assert result.resolved_model == "openrouter/deepseek/deepseek-v4-flash"
    observe.assert_not_called()
    assert "ROUTE_CERTIFICATION_OBSERVATION_DISABLED" in caplog.text


@patch("llm_client.route_certification_runtime.observe_openrouter_native_success_from_runtime")
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion")
def test_openrouter_route_observation_failure_is_visible_without_model_retry(
    mock_comp: MagicMock,
    _mock_supports_schema: MagicMock,
    _mock_cost: MagicMock,
    observe: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Metadata failure preserves the successful result and never reroutes the model."""
    monkeypatch.setenv("LLM_CLIENT_ROUTE_CERTIFICATION_OBSERVATION", "enabled")
    response = _mock_structured_response('{"count":1}')
    response.id = "gen-route-observation-failure"
    mock_comp.return_value = response
    observe.side_effect = RuntimeError("generation metadata unavailable")

    parsed, result = _call_llm_structured_impl(
        "openrouter/deepseek/deepseek-v4-flash",
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
    mock.choices[0].message.refusal = None
    mock.choices[0].finish_reason = "stop"
    mock.usage.prompt_tokens = 10
    mock.usage.completion_tokens = 5
    mock.usage.total_tokens = 15
    return mock


def test_parse_repair_message_requires_json_only_schema_conformance() -> None:
    """Malformed JSON retries receive a concise provider-agnostic correction."""

    message = _build_parse_repair_message()

    assert message["role"] == "user"
    assert "not valid JSON" in message["content"]
    assert "only valid JSON" in message["content"]
    assert "supplied schema" in message["content"]


@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion")
def test_native_parse_retry_adds_corrective_message(
    mock_comp: MagicMock,
    _mock_supports_schema: MagicMock,
    _mock_cost: MagicMock,
) -> None:
    """The next bounded native attempt knows why the first response failed."""

    mock_comp.side_effect = [
        _mock_structured_response("not json"),
        _mock_structured_response('{"name":"Tokyo"}'),
    ]

    parsed, _result = _call_llm_structured_impl(
        "gpt-4",
        [{"role": "user", "content": "Name a city"}],
        _City,
        num_retries=1,
        base_delay=0,
        task="test",
        trace_id="structured.runtime.sync.parse-repair",
        max_budget=0,
    )

    assert parsed.name == "Tokyo"
    second_messages = mock_comp.call_args_list[1].kwargs["messages"]
    assert second_messages[-1] == _build_parse_repair_message()


@pytest.mark.asyncio
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
async def test_async_native_parse_retry_adds_corrective_message(
    mock_acompletion: AsyncMock,
    _mock_supports_schema: MagicMock,
    _mock_cost: MagicMock,
) -> None:
    """Async native recovery receives the same bounded correction as sync."""

    mock_acompletion.side_effect = [
        _mock_structured_response("not json"),
        _mock_structured_response('{"name":"Tokyo"}'),
    ]

    parsed, _result = await _acall_llm_structured_impl(
        "gpt-4",
        [{"role": "user", "content": "Name a city"}],
        _City,
        num_retries=1,
        base_delay=0,
        task="test",
        trace_id="structured.runtime.async.parse-repair",
        max_budget=0,
    )

    assert parsed.name == "Tokyo"
    second_messages = mock_acompletion.call_args_list[1].kwargs["messages"]
    assert second_messages[-1] == _build_parse_repair_message()


@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion")
def test_native_parse_failure_respects_zero_retry_bound(
    mock_comp: MagicMock,
    _mock_supports_schema: MagicMock,
    _mock_cost: MagicMock,
) -> None:
    """Corrective recovery never creates an attempt beyond the caller's bound."""

    mock_comp.return_value = _mock_structured_response("not json")

    with pytest.raises(LLMError, match="not valid JSON"):
        _call_llm_structured_impl(
            "gpt-4",
            [{"role": "user", "content": "Name a city"}],
            _City,
            num_retries=0,
            task="test",
            trace_id="structured.runtime.sync.parse-no-retry",
            max_budget=0,
        )

    assert mock_comp.call_count == 1


@pytest.fixture(autouse=True)
def _explicit_test_runtime_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep runtime-split tests independent from ambient process policy."""
    monkeypatch.setenv("LLM_CLIENT_OPENROUTER_ROUTING", "off")
    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "allow")


@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion")
def test_sync_timeout_ban_preserves_provider_safety_ceiling(
    mock_comp: MagicMock,
    _mock_supports_schema: MagicMock,
    _mock_cost: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled caller timeout must not become HTTPX's nonblocking timeout=0."""

    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "ban")
    mock_comp.return_value = _mock_structured_response()

    _call_llm_structured_impl(
        "gpt-4",
        [{"role": "user", "content": "Name a city"}],
        _City,
        timeout=60,
        num_retries=0,
        task="test",
        trace_id="structured.runtime.sync.timeout-ban",
        max_budget=0,
    )

    assert mock_comp.call_args.kwargs["timeout"] == 300


@patch("llm_client.sdk.agents._route_call_structured")
def test_sync_timeout_ban_preserves_requested_codex_cli_deadline(
    mock_agent_call: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The policy ban must not make the Codex CLI subprocess unbounded."""

    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "ban")
    mock_agent_call.return_value = (
        _BoundedCount(count=1),
        LLMCallResult(
            content='{"count":1}',
            usage={},
            cost=0.0,
            model="codex/gpt-5.6-luna",
            requested_model="codex/gpt-5.6-luna",
            resolved_model="codex/gpt-5.6-luna",
        ),
    )

    _call_llm_structured_impl(
        "codex/gpt-5.6-luna",
        [{"role": "user", "content": "Return one."}],
        _BoundedCount,
        timeout=60,
        num_retries=0,
        fallback_models=[],
        reasoning_effort="medium",
        model_justification="Exercise the exact approved Luna agent route.",
        task="test",
        trace_id="structured.runtime.sync.timeout-ban.codex-cli",
        max_budget=0,
    )

    assert mock_agent_call.call_args.kwargs["timeout"] == 0
    assert mock_agent_call.call_args.kwargs["agent_hard_timeout"] == 60


@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_async_timeout_ban_preserves_provider_safety_ceiling(
    mock_comp: AsyncMock,
    _mock_supports_schema: MagicMock,
    _mock_cost: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The async native-schema path preserves the same safety timeout."""

    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "ban")
    mock_comp.return_value = _mock_structured_response()

    await _acall_llm_structured_impl(
        "gpt-4",
        [{"role": "user", "content": "Name a city"}],
        _City,
        timeout=60,
        num_retries=0,
        task="test",
        trace_id="structured.runtime.async.timeout-ban",
        max_budget=0,
    )

    assert mock_comp.call_args.kwargs["timeout"] == 300


@patch("llm_client.execution.structured_runtime._model_supports_native_schema", return_value=False)
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
def test_sync_instructor_fallback_timeout_ban_preserves_provider_safety_ceiling(
    _mock_cost: MagicMock,
    _mock_supports_schema: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Instructor fallback must retain the provider safety ceiling, never timeout=0."""

    import instructor

    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "ban")
    fake_client = MagicMock()
    fake_client.chat.completions.create_with_completion.return_value = (
        _City(name="Tokyo"),
        _mock_structured_response(),
    )
    monkeypatch.setattr(instructor, "from_litellm", lambda _completion: fake_client)

    _call_llm_structured_impl(
        "openrouter/test-instructor-fallback",
        [{"role": "user", "content": "Name a city"}],
        _City,
        timeout=60,
        num_retries=0,
        task="test",
        trace_id="structured.runtime.sync.instructor.timeout-ban",
        max_budget=0,
    )

    assert fake_client.chat.completions.create_with_completion.call_args.kwargs["timeout"] == 300


@pytest.mark.asyncio
@patch("llm_client.execution.structured_runtime._model_supports_native_schema", return_value=False)
@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
async def test_async_instructor_fallback_timeout_ban_preserves_provider_safety_ceiling(
    _mock_cost: MagicMock,
    _mock_supports_schema: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async Instructor fallback must retain the provider safety ceiling too."""

    import instructor

    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "ban")
    fake_client = MagicMock()
    fake_client.chat.completions.create_with_completion = AsyncMock(
        return_value=(_City(name="Tokyo"), _mock_structured_response())
    )
    monkeypatch.setattr(instructor, "from_litellm", lambda _completion: fake_client)

    await _acall_llm_structured_impl(
        "openrouter/test-instructor-fallback",
        [{"role": "user", "content": "Name a city"}],
        _City,
        timeout=60,
        num_retries=0,
        task="test",
        trace_id="structured.runtime.async.instructor.timeout-ban",
        max_budget=0,
    )

    assert fake_client.chat.completions.create_with_completion.call_args.kwargs["timeout"] == 300


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
            "openai/gpt-5",
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
            "gpt-5",
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
