"""Trusted runtime-to-route-certification join tests."""

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from llm_client.core.data_types import LLMCallResult
from llm_client.observability.selected_attempts import RuntimeSelectedAttemptReceipt
from llm_client.observability.structured_attempts import StructuredAttemptEvent
from llm_client.openrouter_generation import OpenRouterGenerationEvidence
from llm_client.route_certification_runtime import (
    compile_openrouter_native_success,
    openrouter_native_provider_schema,
    route_schema_sha256,
)


SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}
SCHEMA_HASH = "21f544defb4c21a3b1235f43bea0efb08abacd178eb4f55d54aa80a49acf1537"


class Answer(BaseModel):
    answer: str


def _receipt() -> RuntimeSelectedAttemptReceipt:
    """Build one internally consistent selected-attempt receipt fixture."""

    events = tuple(
        StructuredAttemptEvent(
            event_id=f"event-{event_type}",
            timestamp="2026-07-16T00:00:00+00:00",
            logical_call_id="logical-1",
            trace_id="trace-1",
            task="route-certification-test",
            attempt_ordinal=0,
            model="openrouter/x-ai/grok-4.5",
            execution_path="native_schema",
            schema_hash=SCHEMA_HASH[:16],
            event_type=event_type,
            raw_sha256=("a" * 64 if event_type == "received" else None),
        )
        for event_type in ("started", "received", "validated")
    )
    return RuntimeSelectedAttemptReceipt(
        call_id=1,
        logical_call_id="logical-1",
        trace_id="trace-1",
        task="route-certification-test",
        requested_model="very_intelligent",
        resolved_model="openrouter/x-ai/grok-4.5",
        selected_attempt_ordinal=0,
        schema_hash=SCHEMA_HASH[:16],
        raw_sha256="a" * 64,
        raw_artifact_ref="structured-raw-v1/a.json",
        call_fingerprint="b" * 64,
        lineage=events,
        receipt_digest="c" * 64,
    )


def _result(**changes: object) -> LLMCallResult:
    """Build the public successful result side of the trusted join."""

    values: dict[str, object] = {
        "content": '{"answer":"yes"}',
        "usage": {},
        "cost": 0.0,
        "model": "openrouter/x-ai/grok-4.5",
        "requested_model": "very_intelligent",
        "resolved_model": "openrouter/x-ai/grok-4.5",
        "logical_call_id": "logical-1",
        "raw_response": {"id": "gen-1"},
    }
    values.update(changes)
    return LLMCallResult(**values)  # type: ignore[arg-type]


def _generation() -> OpenRouterGenerationEvidence:
    """Build authenticated upstream-provider evidence for the result."""

    return OpenRouterGenerationEvidence.build(
        generation_id="gen-1",
        model="x-ai/grok-4.5",
        provider_name="XAI",
        endpoint_id="endpoint-1",
        upstream_id="upstream-1",
        retrieval_attempt_count=1,
        retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
        source_url="https://openrouter.ai/api/v1/generation?id=gen-1",
    )


def test_compiles_exact_openrouter_route_from_three_bound_sources() -> None:
    """Result, selected receipt, and generation metadata jointly certify transport."""

    observation = compile_openrouter_native_success(
        result=_result(),
        receipt=_receipt(),
        generation_evidence=_generation(),
        provider_schema=SCHEMA,
        schema_class="answer-v1",
        llm_client_revision="revision-1",
        evidence_ref="/evidence/orgen1.json",
    )

    assert observation.transport_certifies is True
    assert observation.upstream_provider_name == "XAI"
    assert observation.upstream_provider_endpoint == "endpoint-1"
    assert observation.schema_sha256 == SCHEMA_HASH
    assert observation.selected_attempt_receipt_digest == "c" * 64


def test_public_schema_helpers_match_the_runtime_provider_contract() -> None:
    schema = openrouter_native_provider_schema(Answer)
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["answer"]
    assert len(route_schema_sha256(schema)) == 64

    from llm_client import (  # noqa: PLC0415
        openrouter_native_provider_schema as public_schema,
        route_schema_sha256 as public_digest,
    )

    assert public_schema(Answer) == schema
    assert public_digest(schema) == route_schema_sha256(schema)

    from llm_client.execution.structured_runtime import (  # noqa: PLC0415
        _native_provider_schema,
    )

    assert schema == _native_provider_schema(
        Answer,
        model="openrouter/openai/gpt-5.6-terra",
    )


def test_schema_substitution_fails_join() -> None:
    """A different provider-facing schema cannot borrow a successful receipt."""

    with pytest.raises(ValueError, match="schema hash"):
        compile_openrouter_native_success(
            result=_result(),
            receipt=_receipt(),
            generation_evidence=_generation(),
            provider_schema={"type": "string"},
            schema_class="answer-v1",
            llm_client_revision="revision-1",
            evidence_ref="/evidence/orgen1.json",
        )


def test_cached_result_cannot_create_certification() -> None:
    """Reused output is not evidence that the route worked on this observation."""

    with pytest.raises(ValueError, match="cached"):
        compile_openrouter_native_success(
            result=_result(cache_hit=True),
            receipt=_receipt(),
            generation_evidence=_generation(),
            provider_schema=SCHEMA,
            schema_class="answer-v1",
            llm_client_revision="revision-1",
            evidence_ref="/evidence/orgen1.json",
        )


def test_non_openrouter_selected_attempt_fails_join() -> None:
    """OpenRouter metadata cannot be attached to a direct-provider attempt."""

    receipt = _receipt().model_copy(update={"resolved_model": "x-ai/grok-4.5"})
    with pytest.raises(ValueError, match="not an OpenRouter route"):
        compile_openrouter_native_success(
            result=_result(resolved_model="x-ai/grok-4.5"),
            receipt=receipt,
            generation_evidence=_generation(),
            provider_schema=SCHEMA,
            schema_class="answer-v1",
            llm_client_revision="revision-1",
            evidence_ref="/evidence/orgen1.json",
        )
