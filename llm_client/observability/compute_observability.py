"""Provider-neutral contracts for compute usage and task attribution.

Provider adapters are intentionally outside this module.  They normalize output
from tools such as ccusage or CodexBar into these contracts; they do not scrape
provider endpoints or assign subscription entitlement a dollar value.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from llm_client import io_log

BillingMode = Literal["subscription", "api", "local_gpu", "unknown"]
OutcomeStatus = Literal["pass", "fail", "unknown"]


class ComputeObservabilityError(ValueError):
    """Raised when a compute-observability contract cannot be trusted."""


class QuotaWindow(BaseModel):
    """One provider-reported quota window, such as a session or weekly window."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    used_percent: float = Field(ge=0, le=100)
    reset_at: datetime | None = None
    limit: float | None = Field(default=None, ge=0)


class UsageSnapshotV1(BaseModel):
    """Normalized usage observation with explicit actual-vs-diagnostic costs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    observed_at: datetime
    machine_id: str = Field(min_length=1)
    worker_id: str | None = Field(default=None, min_length=1)
    provider: str = Field(min_length=1)
    model: str | None = Field(default=None, min_length=1)
    account_fingerprint: str
    billing_mode: BillingMode
    quota_windows: tuple[QuotaWindow, ...] = ()
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    api_equivalent_cost_usd: float | None = Field(default=None, ge=0)
    actual_marginal_cost_usd: float | None = Field(default=None, ge=0)
    actual_cost_source: str | None = Field(default=None, min_length=1)
    raw_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("account_fingerprint")
    @classmethod
    def _account_fingerprint_is_non_secret(cls, value: str) -> str:
        if value != "unknown" and not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("account_fingerprint must be 'unknown' or a lowercase SHA-256 digest")
        return value


class TaskAttemptReceiptV1(BaseModel):
    """Orchestrator-owned identity that joins work to compute observations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1)
    parent_task_id: str | None = Field(default=None, min_length=1)
    attempt_id: str = Field(min_length=1)
    trace_id: str | None = Field(default=None, min_length=1)
    logical_call_id: str | None = Field(default=None, min_length=1)
    attempt_ordinal: int | None = Field(default=None, ge=0)
    provider: str = Field(min_length=1)
    model: str | None = Field(default=None, min_length=1)
    account_fingerprint: str
    machine_id: str = Field(min_length=1)
    worker_id: str | None = Field(default=None, min_length=1)
    billing_mode: BillingMode
    started_at: datetime
    ended_at: datetime | None = None
    parallel_branch_count: int = Field(default=1, ge=1)
    task_type: str | None = Field(default=None, min_length=1)
    difficulty: float | None = Field(default=None, ge=0)
    estimated_value: float | None = Field(default=None, ge=0)
    usage_snapshot_ids: tuple[str, ...] = ()

    @field_validator("account_fingerprint")
    @classmethod
    def _account_fingerprint_is_non_secret(cls, value: str) -> str:
        if value != "unknown" and not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("account_fingerprint must be 'unknown' or a lowercase SHA-256 digest")
        return value

    @field_validator("ended_at")
    @classmethod
    def _end_is_not_before_start(cls, value: datetime | None, info: object) -> datetime | None:
        start = info.data.get("started_at") if hasattr(info, "data") else None
        if value is not None and start is not None and value < start:
            raise ValueError("ended_at cannot precede started_at")
        return value


class OutcomeReceiptV1(BaseModel):
    """Outcome facts supplied by the orchestration/control-plane owner."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    tests_status: OutcomeStatus = "unknown"
    ci_status: OutcomeStatus = "unknown"
    static_analysis_status: OutcomeStatus = "unknown"
    coordinator_decision: Literal["accepted", "rejected", "revised", "unknown"] = "unknown"
    merged: bool | None = None
    reverted: bool | None = None
    regressed: bool | None = None
    weighted_shipped_value: float | None = Field(default=None, ge=0)
    critical_path_seconds: float | None = Field(default=None, ge=0)
    human_intervention_count: int = Field(default=0, ge=0)
    human_intervention_minutes: float = Field(default=0, ge=0)
    recorded_at: datetime
    evidence_refs: tuple[str, ...] = ()


class TaskComputeLinkV1(BaseModel):
    """Idempotent attribution edge between an attempt and a usage snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    attribution_reason: Literal["explicit", "trace", "session", "unattributed"]
    attribution_confidence: Literal["high", "medium", "low"]


_FORBIDDEN_RAW_KEYS = re.compile(
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)",
    re.IGNORECASE,
)


def _assert_sanitized(value: object) -> None:
    """Reject raw records that could contain credentials."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            if _FORBIDDEN_RAW_KEYS.search(str(key)):
                raise ComputeObservabilityError(
                    f"credential-bearing raw field is not allowed: {key}"
                )
            _assert_sanitized(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_sanitized(child)


def persist_usage_snapshot(
    snapshot: UsageSnapshotV1,
    *,
    sanitized_raw_record: Mapping[str, object],
) -> bool:
    """Persist one snapshot and its sanitized source record idempotently."""

    _assert_sanitized(sanitized_raw_record)
    raw_json = json.dumps(sanitized_raw_record, sort_keys=True, separators=(",", ":"))
    raw_sha256 = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
    if raw_sha256 != snapshot.raw_record_sha256:
        raise ComputeObservabilityError(
            "raw_record_sha256 does not match sanitized source record"
        )

    imported_at = datetime.now(snapshot.observed_at.tzinfo).isoformat()
    inserted = False

    def _write(db: object) -> None:
        nonlocal inserted
        existing = db.execute(
            "SELECT snapshot_id FROM usage_snapshots WHERE snapshot_id = ?",
            (snapshot.snapshot_id,),
        ).fetchone()
        if existing is not None:
            return

        raw_existing = db.execute(
            "SELECT raw_record_sha256 FROM usage_source_records WHERE raw_record_sha256 = ?",
            (raw_sha256,),
        ).fetchone()
        if raw_existing is not None:
            raise ComputeObservabilityError(
                "raw source record already exists under a different snapshot ID"
            )

        db.execute(
            """INSERT INTO usage_source_records
               (raw_record_sha256, source_name, source_version, observed_at, raw_json, imported_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                raw_sha256,
                snapshot.source_name,
                snapshot.source_version,
                snapshot.observed_at.isoformat(),
                raw_json,
                imported_at,
            ),
        )
        db.execute(
            """INSERT INTO usage_snapshots
               (snapshot_id, raw_record_sha256, source_name, source_version, observed_at,
                machine_id, worker_id, provider, model, account_fingerprint, billing_mode,
                quota_windows_json, input_tokens, cached_input_tokens, output_tokens,
                reasoning_tokens, api_equivalent_cost_usd, actual_marginal_cost_usd,
                actual_cost_source, imported_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot.snapshot_id,
                raw_sha256,
                snapshot.source_name,
                snapshot.source_version,
                snapshot.observed_at.isoformat(),
                snapshot.machine_id,
                snapshot.worker_id,
                snapshot.provider,
                snapshot.model,
                snapshot.account_fingerprint,
                snapshot.billing_mode,
                json.dumps([window.model_dump(mode="json") for window in snapshot.quota_windows]),
                snapshot.input_tokens,
                snapshot.cached_input_tokens,
                snapshot.output_tokens,
                snapshot.reasoning_tokens,
                snapshot.api_equivalent_cost_usd,
                snapshot.actual_marginal_cost_usd,
                snapshot.actual_cost_source,
                imported_at,
            ),
        )
        inserted = True

    io_log._run_db_write(_write)
    return inserted
