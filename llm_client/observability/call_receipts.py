"""Canonical, runtime-neutral receipts for completed model invocations."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CallReceiptRuntime = Literal["llm_client", "hermes", "other"]
CallReceiptGranularity = Literal["provider_call", "session_aggregate"]
CallReceiptStatus = Literal["succeeded", "failed", "interrupted_or_abandoned"]
CostObservationStatus = Literal["observed", "estimated", "unavailable"]


class LLMCallReceiptV1(BaseModel):
    """Durable evidence for one model call, without pretending gaps are facts.

    This is trusted-process execution evidence, not provider attestation. A
    session aggregate may use the same envelope only when ``granularity`` says
    so explicitly.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["llm_call_receipt_v1"] = "llm_call_receipt_v1"
    receipt_id: str = Field(min_length=1)
    runtime: CallReceiptRuntime
    granularity: CallReceiptGranularity = "provider_call"
    trace_id: str | None = None
    logical_call_id: str | None = None
    parent_call_id: str | None = None
    attempt_ordinal: int | None = Field(default=None, ge=0)
    task: str | None = None
    requested_model: str | None = None
    resolved_model: str | None = None
    provider: str | None = None
    execution_path: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    latency_s: float | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)
    cache_creation_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    cost_status: CostObservationStatus = "unavailable"
    cost_source: str | None = None
    status: CallReceiptStatus
    finish_reason: str | None = None
    error_type: str | None = None
    retry_count: int | None = Field(default=None, ge=0)
    cache_hit: bool | None = None
    request_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    prompt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    schema_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    producer_revision: str | None = None
    deployment_revision: str | None = None
    unavailable_fields: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_honest_call_identity_and_timing(self) -> "LLMCallReceiptV1":
        if self.granularity == "provider_call" and not (
            self.logical_call_id or self.trace_id
        ):
            raise ValueError("A provider-call receipt requires a logical_call_id or trace_id.")
        if self.status in {"succeeded", "failed"} and self.latency_s is None:
            if not self.unavailable_fields.get("latency_s"):
                raise ValueError(
                    "A terminal receipt requires latency_s or an explicit unavailable reason."
                )
        if self.cost_status == "unavailable" and self.cost_usd is not None:
            raise ValueError("cost_usd cannot be populated when cost_status is unavailable.")
        if self.cost_status != "unavailable" and self.cost_usd is None:
            raise ValueError("Observed or estimated cost requires cost_usd.")
        return self


def sha256_text(value: str | None) -> str | None:
    """Hash retained text without making text itself part of the receipt."""

    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def derive_started_at(completed_at: datetime, latency_s: float | None) -> datetime | None:
    """Derive start time only when the observed duration exists."""

    if latency_s is None:
        return None
    return completed_at - timedelta(seconds=latency_s)
