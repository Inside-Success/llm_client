"""Focused transport controls for subscription-backed Codex Luna."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from llm_client import LLMCallResult
from llm_client.route_certification_runtime import (
    codex_native_provider_schema,
    compile_codex_structured_success,
    route_schema_sha256,
)
from llm_client.sdk.agents import _build_codex_cli_command


class _ProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


class _SendAction(BaseModel):
    output_port_id: Literal["send"]
    content: str


class _WaitAction(BaseModel):
    output_port_id: Literal["wait"]
    reason: str


class _DiscriminatedDecision(BaseModel):
    actions: list[
        Annotated[_SendAction | _WaitAction, Field(discriminator="output_port_id")]
    ]


class _DefaultedSendAction(BaseModel):
    output_port_id: Literal["send"] = "send"
    content: str


class _DefaultedWaitAction(BaseModel):
    output_port_id: Literal["wait"] = "wait"
    reason: str


class _DefaultedDiscriminatedDecision(BaseModel):
    actions: list[
        Annotated[
            _DefaultedSendAction | _DefaultedWaitAction,
            Field(discriminator="output_port_id"),
        ]
    ]


class _DescribedNestedProfile(BaseModel):
    value: str = Field(description="The nested value.")


class _DescribedNestedEnvelope(BaseModel):
    profile: _DescribedNestedProfile = Field(
        description="The provider-visible profile description."
    )


def test_codex_schema_projects_disjoint_action_union_to_supported_any_of() -> None:
    schema = codex_native_provider_schema(_DiscriminatedDecision)
    action_schema = schema["properties"]["actions"]["items"]

    assert "oneOf" not in action_schema
    assert "discriminator" not in action_schema
    assert len(action_schema["anyOf"]) == 2


def test_codex_schema_projects_defaulted_discriminator_after_strict_normalization() -> None:
    schema = codex_native_provider_schema(_DefaultedDiscriminatedDecision)
    action_schema = schema["properties"]["actions"]["items"]

    assert "oneOf" not in action_schema
    assert "discriminator" not in action_schema
    assert len(action_schema["anyOf"]) == 2


def test_codex_schema_resolves_described_nested_ref_for_provider() -> None:
    schema = codex_native_provider_schema(_DescribedNestedEnvelope)
    profile_schema = schema["properties"]["profile"]

    assert "$ref" not in profile_schema
    assert profile_schema["description"] == (
        "The provider-visible profile description."
    )
    assert profile_schema["type"] == "object"
    assert profile_schema["additionalProperties"] is False
    assert profile_schema["required"] == ["value"]


def test_build_codex_cli_command_selects_luna_at_medium_effort(
    tmp_path: Path,
) -> None:
    command, _env, _stdin_payload = _build_codex_cli_command(
        "codex/gpt-5.6-luna",
        "Return the requested structured result.",
        output_schema={"type": "object", "properties": {}},
        kwargs={
            "working_directory": str(tmp_path),
            "approval_policy": "never",
            "sandbox_mode": "read-only",
            "skip_git_repo_check": True,
            "model_reasoning_effort": "medium",
        },
        output_path=str(tmp_path / "last.txt"),
        schema_path=str(tmp_path / "schema.json"),
    )

    assert command[command.index("--model") + 1] == "gpt-5.6-luna"
    assert 'model_reasoning_effort="medium"' in command
    assert command[command.index("-s") + 1] == "read-only"
    assert command[command.index("--output-schema") + 1] == str(
        tmp_path / "schema.json"
    )


def _subscription_result() -> LLMCallResult:
    return LLMCallResult(
        content='{"status":"ok"}',
        usage={"total_tokens": 12},
        cost=0.0,
        model="codex/gpt-5.6-luna",
        requested_model="codex/gpt-5.6-luna",
        resolved_model="codex/gpt-5.6-luna",
        finish_reason="stop",
        raw_response={"transport": "codex_cli"},
        cost_source="subscription_included",
        billing_mode="subscription_included",
        logical_call_id="llmcall_test_codex_luna",
    )


def test_compile_codex_structured_success_certifies_exact_schema() -> None:
    schema = codex_native_provider_schema(_ProbeResult)
    observation = compile_codex_structured_success(
        result=_subscription_result(),
        response_model=_ProbeResult,
        trace_id="tests/codex-luna/subscription",
        llm_client_revision="test-revision",
        evidence_ref="sqlite:///tmp/llm_observability.db#llmcall_test_codex_luna",
        observed_at=datetime(2026, 7, 29, tzinfo=UTC),
    )

    assert observation.execution_mode == "workspace_agent"
    assert observation.upstream_provider_endpoint == "codex_cli"
    assert observation.transport_certifies is True
    assert observation.selected_attempt_receipt_digest is None
    assert observation.schema_class == "_ProbeResult"
    assert observation.schema_sha256 == route_schema_sha256(schema)


def test_compile_codex_structured_success_rejects_api_billing() -> None:
    result = _subscription_result()
    result.billing_mode = "api"

    with pytest.raises(ValueError, match="subscription-backed"):
        compile_codex_structured_success(
            result=result,
            response_model=_ProbeResult,
            trace_id="tests/codex-luna/api",
            llm_client_revision="test-revision",
            evidence_ref="sqlite:///tmp/llm_observability.db#api",
        )


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"unexpected":true}',
    ],
)
def test_compile_codex_structured_success_rejects_invalid_content(
    content: str,
) -> None:
    result = _subscription_result()
    result.content = content

    with pytest.raises(ValidationError):
        compile_codex_structured_success(
            result=result,
            response_model=_ProbeResult,
            trace_id="tests/codex-luna/invalid-content",
            llm_client_revision="test-revision",
            evidence_ref="sqlite:///tmp/llm_observability.db#invalid-content",
        )
