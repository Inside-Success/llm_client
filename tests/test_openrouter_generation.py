"""OpenRouter generation evidence retrieval and integrity tests."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from llm_client.openrouter_generation import (
    OpenRouterGenerationEvidence,
    OpenRouterGenerationEvidenceStore,
    build_openrouter_inline_generation_evidence,
    fetch_openrouter_generation_evidence,
)


# mock-ok: httpx MockTransport isolates the authenticated external HTTP boundary.
def _client(payload: dict[str, object], status_code: int = 200) -> httpx.Client:
    """Build one deterministic OpenRouter generation endpoint transport."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["id"] == "gen-1"
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(status_code, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetches_exact_provider_identity_and_persists_once(tmp_path) -> None:
    """The authenticated generation record, not model prefix, names the provider."""

    retrieved_at = datetime(2026, 7, 16, tzinfo=UTC)
    client = _client(
        {
            "data": {
                "id": "gen-1",
                "model": "x-ai/grok-4.5",
                "provider_name": "XAI",
                "upstream_id": "upstream-1",
                "provider_responses": [
                    {"status": 200, "endpoint_id": "endpoint-1"}
                ],
            }
        }
    )
    evidence = fetch_openrouter_generation_evidence(
        "gen-1", api_key="secret", client=client, retrieved_at=retrieved_at
    )
    store = OpenRouterGenerationEvidenceStore(tmp_path)

    first = store.append(evidence)
    second = store.append(evidence)

    assert first == second
    assert evidence.provider_name == "XAI"
    assert evidence.endpoint_id == "endpoint-1"
    assert evidence.model == "x-ai/grok-4.5"
    assert evidence.retrieval_attempt_count == 1
    assert OpenRouterGenerationEvidence.model_validate_json(
        first.read_text(encoding="utf-8")
    ) == evidence


def test_generation_identity_substitution_fails() -> None:
    """A response for another generation cannot certify the requested call."""

    client = _client(
        {
            "data": {
                "id": "gen-other",
                "model": "x-ai/grok-4.5",
                "provider_name": "XAI",
            }
        }
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        fetch_openrouter_generation_evidence(
            "gen-1", api_key="secret", client=client
        )


def test_missing_provider_name_fails_closed() -> None:
    """A model-only generation response is not upstream-provider evidence."""

    client = _client({"data": {"id": "gen-1", "model": "x-ai/grok-4.5"}})
    with pytest.raises(ValueError, match="provider_name"):
        fetch_openrouter_generation_evidence(
            "gen-1", api_key="secret", client=client
        )


def test_retained_inline_metadata_certifies_observed_provider() -> None:
    """A completion response can attest its selected provider without history API."""

    observed_at = datetime(2026, 8, 14, tzinfo=UTC)
    evidence = build_openrouter_inline_generation_evidence(
        {
            "id": "gen-1",
            "model": "openai/gpt-5.6-terra",
            "provider": "OpenAI",
        },
        retrieved_at=observed_at,
    )

    assert evidence.generation_id == "gen-1"
    assert evidence.model == "openai/gpt-5.6-terra"
    assert evidence.provider_name == "OpenAI"
    assert evidence.endpoint_id is None
    assert (
        evidence.source_url
        == "openrouter://api/v1/chat/completions/inline-metadata?id=gen-1"
    )


def test_inline_metadata_without_observed_provider_fails_closed() -> None:
    """A generation ID and model alone cannot assert a selected provider."""

    with pytest.raises(ValueError, match="provider"):
        build_openrouter_inline_generation_evidence(
            {"id": "gen-1", "model": "openai/gpt-5.6-terra"}
        )


def test_corrupt_generation_record_fails_replay(tmp_path) -> None:
    """Provider identity cannot be changed while retaining the old digest."""

    evidence = OpenRouterGenerationEvidence.build(
        generation_id="gen-1",
        model="x-ai/grok-4.5",
        provider_name="XAI",
        endpoint_id="endpoint-1",
        upstream_id="upstream-1",
        retrieval_attempt_count=1,
        retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
        source_url="https://openrouter.ai/api/v1/generation?id=gen-1",
    )
    path = OpenRouterGenerationEvidenceStore(tmp_path).append(evidence)
    payload = evidence.model_dump(mode="json") | {"provider_name": "substituted"}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        OpenRouterGenerationEvidence.model_validate_json(
            path.read_text(encoding="utf-8")
        )


def test_generation_metadata_404_retry_is_bounded_and_recorded() -> None:
    """Eventual-consistency enrichment retries do not retry the model call."""

    attempts = 0

    # mock-ok: deterministic transport reproduces OpenRouter's observed 404-then-200 seam.
    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(404, json={"error": {"message": "not ready"}})
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "gen-1",
                    "model": "x-ai/grok-4.5",
                    "provider_name": "XAI",
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    evidence = fetch_openrouter_generation_evidence(
        "gen-1",
        api_key="secret",
        client=client,
        max_attempts=2,
        initial_retry_delay_seconds=0,
    )

    assert attempts == 2
    assert evidence.retrieval_attempt_count == 2
