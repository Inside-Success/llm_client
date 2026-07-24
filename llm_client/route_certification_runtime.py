"""Compile trusted runtime and OpenRouter evidence into route observations."""

from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from llm_client.core.data_types import LLMCallResult
from llm_client.observability.selected_attempts import (
    RuntimeSelectedAttemptReceipt,
    get_runtime_selected_attempt_receipt,
)
from llm_client.openrouter_generation import (
    OpenRouterGenerationEvidence,
    OpenRouterGenerationEvidenceStore,
    fetch_openrouter_generation_evidence,
)
from llm_client.route_certification import (
    RouteCertificationObservation,
    RouteCertificationStore,
)


def route_schema_sha256(schema: dict[str, Any]) -> str:
    """Hash the exact provider-facing JSON Schema using runtime canonicalization."""

    return hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()


def openrouter_native_provider_schema(
    response_model: type[BaseModel],
) -> dict[str, Any]:
    """Return the exact schema the structured runtime sends through OpenRouter."""
    from llm_client.core.client import (
        _openrouter_compatible_strict_json_schema,
        _strict_json_schema,
    )

    return _openrouter_compatible_strict_json_schema(
        _strict_json_schema(response_model.model_json_schema())
    )


def _generation_id(result: LLMCallResult) -> str:
    """Extract the OpenRouter generation identity from the raw response."""

    raw = result.raw_response
    value = raw.get("id") if isinstance(raw, dict) else getattr(raw, "id", None)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("LLM result lacks an OpenRouter generation id")
    return value.strip()


def compile_openrouter_native_success(
    *,
    result: LLMCallResult,
    receipt: RuntimeSelectedAttemptReceipt,
    generation_evidence: OpenRouterGenerationEvidence,
    provider_schema: dict[str, Any],
    schema_class: str,
    llm_client_revision: str,
    evidence_ref: str,
) -> RouteCertificationObservation:
    """Join exact successful-call evidence without granting semantic truth."""

    if result.cache_hit:
        raise ValueError("cached results cannot create route certification evidence")
    if result.logical_call_id != receipt.logical_call_id:
        raise ValueError("result and selected-attempt receipt identity mismatch")
    if _generation_id(result) != generation_evidence.generation_id:
        raise ValueError("result and OpenRouter generation identity mismatch")
    if receipt.resolved_model != result.resolved_model:
        raise ValueError("result and selected-attempt model identity mismatch")
    if not receipt.resolved_model.startswith("openrouter/"):
        raise ValueError("selected attempt is not an OpenRouter route")
    full_schema_digest = route_schema_sha256(provider_schema)
    if not full_schema_digest.startswith(receipt.schema_hash):
        raise ValueError("provider schema does not match selected-attempt schema hash")
    return RouteCertificationObservation.build(
        requested_model=receipt.requested_model,
        resolved_model=f"openrouter/{generation_evidence.model}",
        upstream_provider_name=generation_evidence.provider_name,
        upstream_provider_endpoint=generation_evidence.endpoint_id,
        execution_mode="native_json_schema",
        schema_class=schema_class,
        schema_sha256=full_schema_digest,
        outcome="parseable",
        failure_stage="none",
        logical_call_id=receipt.logical_call_id,
        trace_id=receipt.trace_id,
        observed_at=generation_evidence.retrieved_at,
        llm_client_revision=llm_client_revision,
        selected_attempt_receipt_digest=receipt.receipt_digest,
        evidence_ref=evidence_ref,
    )


def observe_openrouter_native_success(
    *,
    result: LLMCallResult,
    provider_schema: dict[str, Any],
    schema_class: str,
    llm_client_revision: str,
    generation_store: OpenRouterGenerationEvidenceStore,
    certification_store: RouteCertificationStore,
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> RouteCertificationObservation:
    """Fetch, verify, and persist one successful OpenRouter native-schema route."""

    if result.logical_call_id is None:
        raise ValueError("LLM result lacks logical_call_id")
    receipt = get_runtime_selected_attempt_receipt(result.logical_call_id)
    evidence = fetch_openrouter_generation_evidence(
        _generation_id(result), api_key=api_key, client=client
    )
    evidence_path = generation_store.append(evidence)
    observation = compile_openrouter_native_success(
        result=result,
        receipt=receipt,
        generation_evidence=evidence,
        provider_schema=provider_schema,
        schema_class=schema_class,
        llm_client_revision=llm_client_revision,
        evidence_ref=str(Path(evidence_path).resolve()),
    )
    certification_store.append(observation)
    return observation


def observe_openrouter_native_success_from_runtime(
    *,
    result: LLMCallResult,
    provider_schema: dict[str, Any],
    schema_class: str,
) -> RouteCertificationObservation:
    """Persist route evidence for one successful public OpenRouter schema call.

    The store root is environment-configurable so production callers can retain
    route evidence outside the package checkout.  This helper is deliberately
    post-call only: it never retries the model call, changes its model, or
    substitutes a provider when OpenRouter metadata is temporarily unavailable.
    """

    root = Path(
        os.environ.get("LLM_ROUTE_CERTIFICATION_ROOT", "~/projects/data/llm_route_certification")
    ).expanduser()
    try:
        revision = os.environ.get("LLM_CLIENT_REVISION") or f"package:{version('llm-client')}"
    except PackageNotFoundError:
        revision = "package:uninstalled-source"
    return observe_openrouter_native_success(
        result=result,
        provider_schema=provider_schema,
        schema_class=schema_class,
        llm_client_revision=revision,
        generation_store=OpenRouterGenerationEvidenceStore(root / "generations"),
        certification_store=RouteCertificationStore(root / "observations"),
    )


__all__ = [
    "compile_openrouter_native_success",
    "openrouter_native_provider_schema",
    "observe_openrouter_native_success",
    "observe_openrouter_native_success_from_runtime",
    "route_schema_sha256",
]
