from __future__ import annotations

import argparse
from io import StringIO
import json
import sys
from typing import Any

import pytest

from llm_client.cli import json_schema_call
from llm_client.core.data_types import LLMCallResult


def _request() -> dict[str, Any]:
    return {
        "protocolVersion": "1.0",
        "model": "openrouter/openai/gpt-5-mini",
        "messages": [{"role": "user", "content": "Return one."}],
        "responseSchema": {
            "type": "object",
            "properties": {"count": {"type": "integer", "minimum": 1}},
            "required": ["count"],
            "additionalProperties": False,
        },
        "schemaName": "count_response",
        "task": "curriculum_generation",
        "traceId": "learning-environment/test",
        "maxBudget": 2.0,
        "timeout": 120,
        "numRetries": 1,
        "temperature": 0,
    }


def _result() -> LLMCallResult:
    return LLMCallResult(
        content='{"count":1}',
        usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        cost=0.002,
        marginal_cost=0.002,
        model="openrouter/openai/gpt-5-mini",
        requested_model="openrouter/openai/gpt-5-mini",
        resolved_model="openrouter/openai/gpt-5-mini",
        logical_call_id="logical-123",
        routing_trace={"selected_model": "openrouter/openai/gpt-5-mini"},
        finish_reason="stop",
        warnings=["test warning"],
        cost_source="provider_reported",
        cost_covers_all_attempts=True,
    )


def test_json_schema_call_cli_emits_stable_envelope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, Any] = {}

    def fake_call(*args: Any, **kwargs: Any) -> tuple[Any, LLMCallResult]:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return {"count": 1}, _result()

    monkeypatch.setattr(json_schema_call, "call_llm_json_schema", fake_call)
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(_request())))

    json_schema_call.cmd_json_schema_call(argparse.Namespace(request="-"))

    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["protocolVersion"] == "1.0"
    assert payload["payload"] == {"count": 1}
    assert payload["metadata"] == {
        "requestedModel": "openrouter/openai/gpt-5-mini",
        "resolvedModel": "openrouter/openai/gpt-5-mini",
        "logicalCallId": "logical-123",
        "routingTrace": {"selected_model": "openrouter/openai/gpt-5-mini"},
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        "cost": 0.002,
        "marginalCost": 0.002,
        "costSource": "provider_reported",
        "costCoversAllAttempts": True,
        "finishReason": "stop",
        "warnings": ["test warning"],
    }
    assert observed["kwargs"]["task"] == "curriculum_generation"
    assert observed["kwargs"]["trace_id"] == "learning-environment/test"
    assert observed["kwargs"]["max_budget"] == 2.0
    assert observed["kwargs"]["num_retries"] == 1
    assert observed["kwargs"]["temperature"] == 0


def test_json_schema_call_cli_rejects_malformed_request(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "stdin", StringIO('{"protocolVersion":"1.0"}'))

    with pytest.raises(SystemExit) as exit_info:
        json_schema_call.cmd_json_schema_call(argparse.Namespace(request="-"))

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["protocolVersion"] == "1.0"
    assert error["error"]["code"] == "request.invalid"


def test_json_schema_call_cli_reports_runtime_failure_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(*args: Any, **kwargs: Any) -> tuple[Any, LLMCallResult]:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(json_schema_call, "call_llm_json_schema", fail)
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(_request())))

    with pytest.raises(SystemExit) as exit_info:
        json_schema_call.cmd_json_schema_call(argparse.Namespace(request="-"))

    captured = capsys.readouterr()
    assert exit_info.value.code == 1
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"] == {
        "code": "call.failed",
        "message": "provider unavailable",
        "type": "RuntimeError",
    }


def test_json_schema_call_cli_redacts_environment_secrets_from_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "fixture-provider-secret-123"

    def fail(*args: Any, **kwargs: Any) -> tuple[Any, LLMCallResult]:
        raise RuntimeError(f"provider rejected token {secret}")

    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    monkeypatch.setattr(json_schema_call, "call_llm_json_schema", fail)
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(_request())))

    with pytest.raises(SystemExit):
        json_schema_call.cmd_json_schema_call(argparse.Namespace(request="-"))

    captured = capsys.readouterr()
    assert secret not in captured.err
    assert json.loads(captured.err)["error"]["message"] == (
        "provider rejected token [redacted]"
    )


def test_json_schema_call_request_has_no_credential_or_endpoint_fields() -> None:
    properties = json_schema_call.JsonSchemaCallRequest.model_json_schema()["properties"]

    assert "apiKey" not in properties
    assert "endpoint" not in properties
    assert "providerId" not in properties
