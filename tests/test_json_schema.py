from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from llm_client.core.data_types import LLMCallResult
from llm_client.execution.call_contracts import StructuredOutputPolicy
from llm_client.json_schema import (
    acall_llm_json_schema,
    call_llm_json_schema,
    json_schema_response_model,
)


COUNT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "count": {
            "type": "integer",
            "minimum": 1,
        },
    },
    "required": ["count"],
    "additionalProperties": False,
}


def _result(content: str = '{"count":1}') -> LLMCallResult:
    return LLMCallResult(
        content=content,
        usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        cost=0.001,
        model="openrouter/openai/gpt-5-mini",
        resolved_model="openrouter/openai/gpt-5-mini",
        finish_reason="stop",
    )


def _provider_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.choices[0].finish_reason = "stop"
    response.usage.prompt_tokens = 10
    response.usage.completion_tokens = 5
    response.usage.total_tokens = 15
    return response


def test_json_schema_response_model_exposes_exact_schema_and_validates_locally() -> None:
    response_model = json_schema_response_model(
        COUNT_SCHEMA,
        schema_name="count_response",
    )

    assert response_model.__name__ == "count_response"
    assert response_model.model_json_schema() == COUNT_SCHEMA
    assert response_model.model_validate_json('{"count":1}').root == {"count": 1}
    with pytest.raises(ValidationError, match="less than the minimum"):
        response_model.model_validate_json('{"count":0}')
    with pytest.raises(ValidationError, match="Additional properties"):
        response_model.model_validate({"count": 1, "extra": True})


def test_json_schema_response_model_rejects_invalid_schema_and_name() -> None:
    with pytest.raises(ValueError, match="Invalid JSON Schema"):
        json_schema_response_model(
            {"type": "object", "required": "not-an-array"},
            schema_name="response",
        )
    with pytest.raises(ValueError, match="schema_name"):
        json_schema_response_model(COUNT_SCHEMA, schema_name="not provider safe")


def test_call_llm_json_schema_uses_strict_structured_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def fake_call(
        model: str,
        messages: list[dict[str, Any]],
        response_model: type[Any],
        **kwargs: Any,
    ) -> tuple[Any, LLMCallResult]:
        observed.update(
            model=model,
            messages=messages,
            response_model=response_model,
            kwargs=kwargs,
        )
        return response_model.model_validate({"count": 1}), _result()

    monkeypatch.setattr("llm_client.json_schema.call_llm_structured", fake_call)
    payload, result = call_llm_json_schema(
        "openrouter/openai/gpt-5-mini",
        [{"role": "user", "content": "Return one."}],
        COUNT_SCHEMA,
        schema_name="count_response",
        task="test",
        trace_id="test/json-schema/sync",
        max_budget=1,
    )

    assert payload == {"count": 1}
    assert result.cost == 0.001
    assert observed["response_model"].model_json_schema() == COUNT_SCHEMA
    policy = observed["kwargs"]["structured_output_policy"]
    assert isinstance(policy, StructuredOutputPolicy)
    assert policy.mode == "require_native_json_schema"


@pytest.mark.asyncio
async def test_acall_llm_json_schema_has_async_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async_call = AsyncMock()

    async def fake_call(
        model: str,
        messages: list[dict[str, Any]],
        response_model: type[Any],
        **kwargs: Any,
    ) -> tuple[Any, LLMCallResult]:
        return response_model.model_validate({"count": 2}), _result('{"count":2}')

    async_call.side_effect = fake_call
    monkeypatch.setattr("llm_client.json_schema.acall_llm_structured", async_call)

    payload, _result_meta = await acall_llm_json_schema(
        "openrouter/openai/gpt-5-mini",
        [{"role": "user", "content": "Return two."}],
        COUNT_SCHEMA,
        schema_name="count_response",
        task="test",
        trace_id="test/json-schema/async",
        max_budget=1,
    )

    assert payload == {"count": 2}
    policy = async_call.call_args.kwargs["structured_output_policy"]
    assert policy.mode == "require_native_json_schema"


def test_call_llm_json_schema_preserves_explicit_output_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = MagicMock()

    def fake_call(
        model: str,
        messages: list[dict[str, Any]],
        response_model: type[Any],
        **kwargs: Any,
    ) -> tuple[Any, LLMCallResult]:
        call(model, messages, response_model, **kwargs)
        return response_model.model_validate({"count": 1}), _result()

    monkeypatch.setattr("llm_client.json_schema.call_llm_structured", fake_call)
    explicit = StructuredOutputPolicy(mode="auto")
    call_llm_json_schema(
        "openrouter/openai/gpt-5-mini",
        [{"role": "user", "content": "Return one."}],
        COUNT_SCHEMA,
        structured_output_policy=explicit,
        task="test",
        trace_id="test/json-schema/policy",
        max_budget=1,
    )

    assert call.call_args.kwargs["structured_output_policy"] is explicit


@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema", return_value=True)
@patch("llm_client.core.client.litellm.completion")
def test_json_schema_call_reuses_provider_projection_and_local_repair_retry(
    completion: MagicMock,
    _supports_schema: MagicMock,
    _completion_cost: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_CLIENT_OPENROUTER_ROUTING", "off")
    monkeypatch.setenv("LLM_CLIENT_ROUTE_CERTIFICATION_OBSERVATION", "disabled")
    completion.side_effect = [
        _provider_response('{"count":0}'),
        _provider_response('{"count":2}'),
    ]

    payload, _meta = call_llm_json_schema(
        "openrouter/openai/gpt-5-mini",
        [{"role": "user", "content": "Return a positive count."}],
        COUNT_SCHEMA,
        schema_name="count_response",
        task="test",
        trace_id="test/json-schema/provider-projection",
        max_budget=0,
        num_retries=1,
        base_delay=0,
    )

    assert payload == {"count": 2}
    assert completion.call_count == 2
    sent_schema = completion.call_args.kwargs["response_format"]["json_schema"]["schema"]
    assert "minimum" not in sent_schema["properties"]["count"]
    assert completion.call_args.kwargs["messages"][-1]["role"] == "user"
    assert "validation" in completion.call_args.kwargs["messages"][-1]["content"].lower()
