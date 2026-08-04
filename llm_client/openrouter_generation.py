"""Fetch and retain OpenRouter's provider identity for one generation.

The completion response identifies the generation, while OpenRouter's
authenticated generation endpoint identifies the actual upstream provider.
Keeping those facts separate prevents a requested model prefix from being
misrepresented as observed routing evidence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python


OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
logger = logging.getLogger(__name__)


def _digest(payload: object) -> str:
    """Return a canonical SHA-256 digest for persisted provider evidence."""

    encoded = json.dumps(
        to_jsonable_python(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class OpenRouterGenerationEvidence(BaseModel):
    """Authenticated OpenRouter metadata for one completed generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["openrouter-generation-evidence-v1"] = (
        "openrouter-generation-evidence-v1"
    )
    evidence_id: str = Field(pattern=r"^orgen1_[0-9a-f]{24}$")
    generation_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    provider_name: str = Field(
        min_length=1,
        description="Actual provider_name returned by OpenRouter for the generation.",
    )
    endpoint_id: str | None = Field(
        default=None,
        min_length=1,
        description="Exact successful OpenRouter provider endpoint identity, when reported.",
    )
    upstream_id: str | None = Field(default=None, min_length=1)
    retrieval_attempt_count: int = Field(ge=1)
    retrieved_at: datetime
    source_url: str = Field(min_length=1)
    record_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def build(
        cls,
        *,
        generation_id: str,
        model: str,
        provider_name: str,
        endpoint_id: str | None,
        upstream_id: str | None,
        retrieval_attempt_count: int,
        retrieved_at: datetime,
        source_url: str,
    ) -> "OpenRouterGenerationEvidence":
        """Build immutable evidence with deterministic identity and replay digest."""

        payload = {
            "schema_version": "openrouter-generation-evidence-v1",
            "generation_id": generation_id,
            "model": model,
            "provider_name": provider_name,
            "endpoint_id": endpoint_id,
            "upstream_id": upstream_id,
            "retrieval_attempt_count": retrieval_attempt_count,
            "retrieved_at": retrieved_at,
            "source_url": source_url,
        }
        digest = _digest(payload)
        return cls.model_validate(
            payload
            | {
                "evidence_id": f"orgen1_{digest[:24]}",
                "record_digest": digest,
            }
        )

    @model_validator(mode="after")
    def _validate_replay(self) -> "OpenRouterGenerationEvidence":
        """Reject corrupted or self-inconsistent persisted evidence."""

        payload = self.model_dump(
            mode="json", exclude={"evidence_id", "record_digest"}
        )
        expected = _digest(payload)
        if self.record_digest != expected:
            raise ValueError("OpenRouter generation evidence digest mismatch")
        if self.evidence_id != f"orgen1_{expected[:24]}":
            raise ValueError("OpenRouter generation evidence identity mismatch")
        return self


class OpenRouterGenerationEvidenceStore:
    """Persist authenticated generation evidence once as replayable JSON."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def append(self, evidence: OpenRouterGenerationEvidence) -> Path:
        """Write evidence atomically without overwriting an existing identity."""

        evidence = OpenRouterGenerationEvidence.model_validate(
            evidence.model_dump(mode="json")
        )
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{evidence.evidence_id}.json"
        encoded = evidence.model_dump_json(indent=2) + "\n"
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.root,
                prefix=f".{evidence.evidence_id}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            os.link(temporary_path, path)
        except FileExistsError:
            existing = OpenRouterGenerationEvidence.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            if existing != evidence:
                raise ValueError("OpenRouter generation evidence identity conflict") from None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return path


def _required_text(data: dict[str, Any], key: str) -> str:
    """Read one required nonblank generation response field."""

    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"OpenRouter generation metadata is missing {key}")
    return value.strip()


def _successful_endpoint_id(data: dict[str, Any]) -> str | None:
    """Return the sole successful provider endpoint when OpenRouter reports it."""

    responses = data.get("provider_responses")
    if responses is None:
        return None
    if not isinstance(responses, list):
        raise ValueError("OpenRouter provider_responses is not a list")
    successful = [
        item
        for item in responses
        if isinstance(item, dict) and item.get("status") == 200
    ]
    if len(successful) != 1:
        raise ValueError(
            "OpenRouter generation metadata does not identify one successful endpoint"
        )
    endpoint_id = successful[0].get("endpoint_id")
    if not isinstance(endpoint_id, str) or not endpoint_id.strip():
        return None
    return endpoint_id.strip()


def fetch_openrouter_generation_evidence(
    generation_id: str,
    *,
    api_key: str | None = None,
    api_base: str = OPENROUTER_API_BASE,
    client: httpx.Client | None = None,
    retrieved_at: datetime | None = None,
    max_attempts: int = 5,
    initial_retry_delay_seconds: float = 0.5,
) -> OpenRouterGenerationEvidence:
    """Fetch exact upstream-provider evidence for one OpenRouter generation.

    This performs authenticated reads only. It retries an initial 404 because
    OpenRouter's generation record is observably eventually consistent; every
    retry is logged and bounded. It never retries the model call or substitutes
    a provider.
    """

    normalized_id = generation_id.strip()
    if not normalized_id:
        raise ValueError("generation_id must be nonblank")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least one")
    if initial_retry_delay_seconds < 0:
        raise ValueError("initial_retry_delay_seconds cannot be negative")
    token = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not token:
        raise ValueError("OPENROUTER_API_KEY is required to read generation metadata")
    source_url = f"{api_base.rstrip('/')}/generation"
    owns_client = client is None
    active_client = client or httpx.Client()
    try:
        payload: Any = None
        for attempt in range(1, max_attempts + 1):
            response = active_client.get(
                source_url,
                params={"id": normalized_id},
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code != 404 or attempt == max_attempts:
                response.raise_for_status()
                payload = response.json()
                break
            delay = initial_retry_delay_seconds * (2 ** (attempt - 1))
            logger.warning(
                "OPENROUTER_GENERATION_METADATA_PENDING"
                "[attempt=%d/%d delay_s=%s]",
                attempt,
                max_attempts,
                delay,
            )
            time.sleep(delay)
    finally:
        if owns_client:
            active_client.close()
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ValueError("OpenRouter generation response lacks a data object")
    data = payload["data"]
    returned_id = _required_text(data, "id")
    if returned_id != normalized_id:
        raise ValueError("OpenRouter generation response identity mismatch")
    return OpenRouterGenerationEvidence.build(
        generation_id=returned_id,
        model=_required_text(data, "model"),
        provider_name=_required_text(data, "provider_name"),
        endpoint_id=_successful_endpoint_id(data),
        upstream_id=(
            str(data["upstream_id"]).strip()
            if data.get("upstream_id") is not None
            else None
        ),
        retrieval_attempt_count=attempt,
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
        source_url=f"{source_url}?id={normalized_id}",
    )


__all__ = [
    "OPENROUTER_API_BASE",
    "OpenRouterGenerationEvidence",
    "OpenRouterGenerationEvidenceStore",
    "fetch_openrouter_generation_evidence",
]
