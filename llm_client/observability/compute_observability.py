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
from datetime import datetime, timezone
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
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|account[_-]?email|email)",
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


def persist_task_attempt(receipt: TaskAttemptReceiptV1) -> bool:
    """Persist an orchestrator attempt receipt idempotently."""

    inserted = False

    def _write(db: object) -> None:
        nonlocal inserted
        existing = db.execute(
            "SELECT attempt_id FROM task_attempt_receipts WHERE attempt_id = ?",
            (receipt.attempt_id,),
        ).fetchone()
        if existing is not None:
            return
        db.execute(
            """INSERT INTO task_attempt_receipts
               (attempt_id, task_id, parent_task_id, trace_id, logical_call_id,
                attempt_ordinal, provider, model, account_fingerprint, machine_id,
                worker_id, billing_mode, started_at, ended_at, parallel_branch_count,
                task_type, difficulty, estimated_value, usage_snapshot_ids_json, imported_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                receipt.attempt_id,
                receipt.task_id,
                receipt.parent_task_id,
                receipt.trace_id,
                receipt.logical_call_id,
                receipt.attempt_ordinal,
                receipt.provider,
                receipt.model,
                receipt.account_fingerprint,
                receipt.machine_id,
                receipt.worker_id,
                receipt.billing_mode,
                receipt.started_at.isoformat(),
                receipt.ended_at.isoformat() if receipt.ended_at else None,
                receipt.parallel_branch_count,
                receipt.task_type,
                receipt.difficulty,
                receipt.estimated_value,
                json.dumps(receipt.usage_snapshot_ids),
                datetime.now(receipt.started_at.tzinfo).isoformat(),
            ),
        )
        inserted = True

    io_log._run_db_write(_write)
    return inserted


def persist_outcome(receipt: OutcomeReceiptV1) -> bool:
    """Persist one orchestrator outcome receipt idempotently."""

    inserted = False

    def _write(db: object) -> None:
        nonlocal inserted
        existing = db.execute(
            "SELECT attempt_id FROM outcome_receipts WHERE task_id = ? AND attempt_id = ?",
            (receipt.task_id, receipt.attempt_id),
        ).fetchone()
        if existing is not None:
            return
        db.execute(
            """INSERT INTO outcome_receipts
               (task_id, attempt_id, tests_status, ci_status, static_analysis_status,
                coordinator_decision, merged, reverted, regressed, weighted_shipped_value,
                critical_path_seconds, human_intervention_count, human_intervention_minutes,
                recorded_at, evidence_refs_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                receipt.task_id,
                receipt.attempt_id,
                receipt.tests_status,
                receipt.ci_status,
                receipt.static_analysis_status,
                receipt.coordinator_decision,
                None if receipt.merged is None else int(receipt.merged),
                None if receipt.reverted is None else int(receipt.reverted),
                None if receipt.regressed is None else int(receipt.regressed),
                receipt.weighted_shipped_value,
                receipt.critical_path_seconds,
                receipt.human_intervention_count,
                receipt.human_intervention_minutes,
                receipt.recorded_at.isoformat(),
                json.dumps(receipt.evidence_refs),
            ),
        )
        inserted = True

    io_log._run_db_write(_write)
    return inserted


def persist_task_compute_link(link: TaskComputeLinkV1) -> bool:
    """Persist an explicit or confidence-labeled attribution edge."""

    inserted = False

    def _write(db: object) -> None:
        nonlocal inserted
        existing = db.execute(
            "SELECT attempt_id FROM task_compute_links WHERE attempt_id = ? AND snapshot_id = ?",
            (link.attempt_id, link.snapshot_id),
        ).fetchone()
        if existing is not None:
            return
        db.execute(
            """INSERT INTO task_compute_links
               (task_id, attempt_id, snapshot_id, attribution_reason, attribution_confidence)
               VALUES (?, ?, ?, ?, ?)""",
            (
                link.task_id,
                link.attempt_id,
                link.snapshot_id,
                link.attribution_reason,
                link.attribution_confidence,
            ),
        )
        inserted = True

    io_log._run_db_write(_write)
    return inserted


def parse_ccusage_daily_json(
    payload: Mapping[str, object],
    *,
    machine_id: str,
    account_fingerprint: str,
    billing_mode: BillingMode,
    source_version: str,
    observed_at: datetime | None = None,
) -> tuple[UsageSnapshotV1, ...]:
    """Normalize ccusage daily JSON without reimplementing its accounting."""

    rows = payload.get("daily")
    if not isinstance(rows, list):
        raise ComputeObservabilityError("ccusage payload is missing the daily array")

    snapshots: list[UsageSnapshotV1] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ComputeObservabilityError("ccusage daily row is not an object")
        period = row.get("period", row.get("date"))
        if not isinstance(period, str) or not period:
            raise ComputeObservabilityError("ccusage daily row is missing period/date")
        row_time = observed_at or _period_timestamp(period)
        breakdowns = row.get("modelBreakdowns")
        model_rows = breakdowns if isinstance(breakdowns, list) and breakdowns else [row]
        for model_row in model_rows:
            if not isinstance(model_row, Mapping):
                raise ComputeObservabilityError("ccusage model breakdown is not an object")
            model = model_row.get("modelName")
            if model is not None and not isinstance(model, str):
                raise ComputeObservabilityError("ccusage modelName must be a string")
            raw_record = {"period": period, "row": dict(row), "model": dict(model_row)}
            raw_json = json.dumps(raw_record, sort_keys=True, separators=(",", ":"))
            raw_sha256 = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
            snapshots.append(
                UsageSnapshotV1(
                    snapshot_id=f"ccusage:{machine_id}:{account_fingerprint}:{period}:{model or 'aggregate'}",
                    source_name="ccusage",
                    source_version=source_version,
                    observed_at=row_time,
                    machine_id=machine_id,
                    provider=str(row.get("agent", "unknown")),
                    model=model,
                    account_fingerprint=account_fingerprint,
                    billing_mode=billing_mode,
                    input_tokens=_integer_field(model_row, "inputTokens"),
                    cached_input_tokens=_integer_field(model_row, "cacheReadTokens"),
                    output_tokens=_integer_field(model_row, "outputTokens"),
                    api_equivalent_cost_usd=_number_field(model_row, "cost"),
                    raw_record_sha256=raw_sha256,
                )
            )
    return tuple(snapshots)


def parse_codexbar_usage_json(
    payload: object,
    *,
    machine_id: str,
    account_fingerprint: str,
    source_version: str,
    observed_at: datetime | None = None,
) -> tuple[UsageSnapshotV1, ...]:
    """Normalize CodexBar quota JSON without retaining account identity text."""

    entries = payload if isinstance(payload, list) else [payload]
    snapshots: list[UsageSnapshotV1] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ComputeObservabilityError("CodexBar usage entry is not an object")
        provider = entry.get("provider")
        usage = entry.get("usage")
        if not isinstance(provider, str) or not isinstance(usage, Mapping):
            raise ComputeObservabilityError("CodexBar usage entry lacks provider/usage")
        timestamp = usage.get("updatedAt")
        snapshot_time = observed_at or _parse_timestamp(timestamp)
        windows: list[QuotaWindow] = []
        for window_name in ("primary", "secondary", "tertiary"):
            window = usage.get(window_name)
            if window is None:
                continue
            if not isinstance(window, Mapping):
                raise ComputeObservabilityError(f"CodexBar {window_name} window is not an object")
            used_percent = window.get("usedPercent")
            if not isinstance(used_percent, (int, float)) or isinstance(used_percent, bool):
                raise ComputeObservabilityError(
                    f"CodexBar {window_name} window lacks usedPercent"
                )
            reset_at = window.get("resetsAt")
            windows.append(
                QuotaWindow(
                    name=window_name,
                    used_percent=float(used_percent),
                    reset_at=_parse_timestamp(reset_at) if reset_at else None,
                    limit=float(window["windowMinutes"])
                    if isinstance(window.get("windowMinutes"), (int, float))
                    else None,
                )
            )
        if not windows:
            raise ComputeObservabilityError("CodexBar usage entry has no quota windows")
        raw_record = {"provider": provider, "usage": dict(usage)}
        raw_json = json.dumps(raw_record, sort_keys=True, separators=(",", ":"))
        raw_sha256 = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
        snapshots.append(
            UsageSnapshotV1(
                snapshot_id=f"codexbar:{machine_id}:{account_fingerprint}:{provider}:{snapshot_time.isoformat()}",
                source_name="codexbar",
                source_version=source_version,
                observed_at=snapshot_time,
                machine_id=machine_id,
                provider=provider,
                account_fingerprint=account_fingerprint,
                billing_mode="subscription",
                quota_windows=tuple(windows),
                raw_record_sha256=raw_sha256,
            )
        )
    return tuple(snapshots)


def _period_timestamp(period: str) -> datetime:
    try:
        return datetime.fromisoformat(period.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ComputeObservabilityError(f"unsupported ccusage period: {period}") from exc


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ComputeObservabilityError("provider timestamp is missing")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ComputeObservabilityError(f"unsupported provider timestamp: {value}") from exc


def _integer_field(row: Mapping[str, object], name: str) -> int | None:
    value = row.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ComputeObservabilityError(f"ccusage field {name} must be a non-negative integer")
    return value


def _number_field(row: Mapping[str, object], name: str) -> float | None:
    value = row.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ComputeObservabilityError(f"ccusage field {name} must be a non-negative number")
    return float(value)
