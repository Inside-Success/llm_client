"""Durable outer lifecycle for applications that may call an LLM."""

from __future__ import annotations

import asyncio
import os
import re
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from types import TracebackType
from typing import Literal, Sequence
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

import llm_client.io_log as _io_log

ObservedRunStatus = Literal[
    "running",
    "completed",
    "failed_before_call_start",
    "failed_after_call_start",
    "cancelled",
]

_TERMINAL_STATUSES = frozenset(
    {"completed", "failed_before_call_start", "failed_after_call_start", "cancelled"}
)
_ID_PATTERN = r"^[A-Za-z0-9._:-]+$"
_TRACE_SEGMENT = re.compile(_ID_PATTERN)
_UNSAFE_ERROR = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|api[_-]?key\s*[:=]|authorization\s*[:=]|"
    r"sk-[a-z0-9_-]{8,}|\"role\"\s*:\s*\"(?:system|user|assistant)\")"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitized_error_message(error: BaseException | None) -> str | None:
    if error is None:
        return None
    message = " ".join(str(error).split())[:500]
    if not message:
        return None
    if _UNSAFE_ERROR.search(message):
        return "sensitive error detail redacted"
    return message


class ObservedRunRecord(BaseModel):
    """One durable application-run record joined to descendant LLM traces."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(max_length=256, pattern=_ID_PATTERN)
    root_trace_id: str = Field(max_length=256, pattern=_ID_PATTERN)
    project: str = Field(min_length=1, max_length=256)
    operation: str = Field(min_length=1, max_length=256)
    executable: str = Field(min_length=1, max_length=1024)
    status: ObservedRunStatus
    started_at: str
    ended_at: str | None = None
    runtime_revision: str | None = Field(default=None, max_length=256)
    config_sha256: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    requested_model: str | None = Field(default=None, max_length=512)
    reasoning_effort: str | None = Field(default=None, max_length=64)
    max_budget: float | None = Field(default=None, gt=0)
    error_type: str | None = Field(default=None, max_length=256)
    error_phase: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=500)
    linked_call_count: int = Field(ge=0)

    @field_validator("project", "operation", "executable")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class _ObservedRunStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(max_length=256, pattern=_ID_PATTERN)
    root_trace_id: str = Field(max_length=256, pattern=_ID_PATTERN)
    project: str = Field(min_length=1, max_length=256)
    operation: str = Field(min_length=1, max_length=256)
    executable: str = Field(min_length=1, max_length=1024)
    runtime_revision: str | None = Field(default=None, max_length=256)
    config_sha256: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    requested_model: str | None = Field(default=None, max_length=512)
    reasoning_effort: str | None = Field(default=None, max_length=64)
    max_budget: float | None = Field(default=None, gt=0)

    @field_validator(
        "project",
        "operation",
        "executable",
        "runtime_revision",
        "requested_model",
        "reasoning_effort",
    )
    @classmethod
    def _strip_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


def _linked_call_count(db: object, root_trace_id: str) -> int:
    row = db.execute(  # type: ignore[attr-defined]
        """
        SELECT COUNT(DISTINCT logical_call_id)
        FROM call_lifecycle_events
        WHERE trace_id = ?
           OR substr(trace_id, 1, length(?) + 1) = ? || '/'
        """,
        (root_trace_id, root_trace_id, root_trace_id),
    ).fetchone()
    return int(row[0] if row else 0)


def get_observed_run(run_id: str) -> ObservedRunRecord:
    """Return one observed run or raise when its identity is unknown."""

    normalized = run_id.strip()
    if not normalized:
        raise ValueError("run_id must not be blank")
    db = _io_log._get_db()
    row = db.execute(
        """
        SELECT runs.run_id, runs.root_trace_id, runs.project, runs.operation,
               runs.executable, runs.status, runs.started_at, runs.ended_at,
               runs.runtime_revision, runs.config_sha256, runs.requested_model,
               runs.reasoning_effort, runs.max_budget, runs.error_type,
               runs.error_phase, runs.error_message,
               (SELECT COUNT(DISTINCT calls.logical_call_id)
                  FROM call_lifecycle_events AS calls
                 WHERE calls.trace_id = runs.root_trace_id
                    OR substr(calls.trace_id, 1, length(runs.root_trace_id) + 1)
                       = runs.root_trace_id || '/') AS linked_call_count
          FROM observed_runs AS runs
         WHERE runs.run_id = ?
        """,
        (normalized,),
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown observed run: {normalized}")
    return _record_from_row(row)


def list_observed_runs(
    *,
    project: str | None = None,
    status: ObservedRunStatus | None = None,
    limit: int = 100,
) -> tuple[ObservedRunRecord, ...]:
    """List recent observed runs under optional project and status filters."""

    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit <= 0
        or limit > 1000
    ):
        raise ValueError("limit must be an integer from 1 to 1000")
    clauses: list[str] = []
    params: list[object] = []
    if project is not None:
        normalized_project = project.strip()
        if not normalized_project:
            raise ValueError("project must not be blank")
        clauses.append("runs.project = ?")
        params.append(normalized_project)
    if status is not None:
        if status != "running" and status not in _TERMINAL_STATUSES:
            raise ValueError(f"invalid observed-run status: {status}")
        clauses.append("runs.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    query = f"""
        SELECT runs.run_id, runs.root_trace_id, runs.project, runs.operation,
               runs.executable, runs.status, runs.started_at, runs.ended_at,
               runs.runtime_revision, runs.config_sha256, runs.requested_model,
               runs.reasoning_effort, runs.max_budget, runs.error_type,
               runs.error_phase, runs.error_message,
               (SELECT COUNT(DISTINCT calls.logical_call_id)
                  FROM call_lifecycle_events AS calls
                 WHERE calls.trace_id = runs.root_trace_id
                    OR substr(calls.trace_id, 1, length(runs.root_trace_id) + 1)
                       = runs.root_trace_id || '/') AS linked_call_count
          FROM observed_runs AS runs {where}
        ORDER BY runs.started_at DESC, runs.run_id DESC
        LIMIT ?
        """  # noqa: S608 - clauses are fixed literals; values remain parameterized.
    rows = _io_log._get_db().execute(query, params).fetchall()
    return tuple(_record_from_row(row) for row in rows)


def _record_from_row(row: Sequence[object]) -> ObservedRunRecord:
    return ObservedRunRecord.model_validate(
        dict(zip(ObservedRunRecord.model_fields, row, strict=True))
    )


class ObservedRun:
    """Context manager that retains outer-run custody across all exit paths."""

    def __init__(
        self,
        *,
        project: str,
        operation: str,
        executable: str,
        run_id: str | None = None,
        root_trace_id: str | None = None,
        runtime_revision: str | None = None,
        config_sha256: str | None = None,
        requested_model: str | None = None,
        reasoning_effort: str | None = None,
        max_budget: float | None = None,
    ) -> None:
        generated_run_id = run_id or f"run_{uuid4().hex}"
        start = _ObservedRunStart(
            run_id=generated_run_id,
            root_trace_id=root_trace_id or generated_run_id,
            project=project,
            operation=operation,
            executable=executable,
            runtime_revision=runtime_revision,
            config_sha256=config_sha256,
            requested_model=requested_model,
            reasoning_effort=reasoning_effort,
            max_budget=max_budget,
        )
        if not _io_log._logging_enabled():
            raise RuntimeError("ObservedRun requires llm_client observability logging")
        self.run_id = start.run_id
        self.root_trace_id = start.root_trace_id
        self._phase = "application"
        self._finished = False
        self._context_token: Token[ObservedRun | None] | None = None
        started_at = _now()

        def _write(db: object) -> None:
            db.execute(  # type: ignore[attr-defined]
                """
                INSERT INTO observed_runs
                    (run_id, root_trace_id, project, operation, executable,
                     status, started_at, runtime_revision, config_sha256,
                     requested_model, reasoning_effort, max_budget,
                     linked_call_count)
                VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    start.run_id,
                    start.root_trace_id,
                    start.project,
                    start.operation,
                    start.executable,
                    started_at,
                    start.runtime_revision,
                    start.config_sha256,
                    start.requested_model,
                    start.reasoning_effort,
                    start.max_budget,
                ),
            )

        _io_log._run_db_write(_write)

    def __enter__(self) -> "ObservedRun":
        if self._finished:
            raise RuntimeError(f"observed run {self.run_id} is already terminal")
        if self._context_token is not None:
            raise RuntimeError(f"observed run {self.run_id} is already active")
        self._context_token = _ACTIVE_OBSERVED_RUN.set(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        token = self._context_token
        if token is None:
            raise RuntimeError(f"observed run {self.run_id} is not active")
        try:
            if not self._finished:
                if exc_type is None:
                    self._finish(status="completed")
                elif issubclass(exc_type, (asyncio.CancelledError, KeyboardInterrupt)):
                    self._finish(
                        status="cancelled",
                        error_type=exc_type.__name__,
                        error_message=_sanitized_error_message(exc),
                    )
                else:
                    self._finish_exception(exc_type, exc)
        finally:
            _ACTIVE_OBSERVED_RUN.reset(token)
            self._context_token = None
        return False

    async def __aenter__(self) -> "ObservedRun":
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        return self.__exit__(exc_type, exc, traceback)

    def child_trace_id(self, segment: str) -> str:
        """Derive one unambiguous slash-descendant trace identifier."""

        if (
            not _TRACE_SEGMENT.fullmatch(segment)
            or segment in {".", ".."}
            or len(segment) > 128
        ):
            raise ValueError(
                "trace segment must be at most 128 characters and contain only "
                "letters, numbers, '.', '_', ':', or '-'"
            )
        return f"{self.root_trace_id}/{segment}"

    def set_phase(self, phase: str) -> None:
        """Set the application-owned phase retained if the run fails."""

        normalized = phase.strip()
        if not normalized or len(normalized) > 128:
            raise ValueError("phase must be non-empty and at most 128 characters")
        self._phase = normalized

    def complete(self) -> ObservedRunRecord:
        if self._context_token is not None:
            raise RuntimeError(
                "ObservedRun context completion is controlled by clean context exit"
            )
        return self._finish(status="completed")

    def cancel(self, *, reason: str) -> ObservedRunRecord:
        normalized = reason.strip()
        if not normalized:
            raise ValueError("cancellation reason must not be blank")
        return self._finish(
            status="cancelled",
            error_type="Cancelled",
            error_message=_sanitized_error_message(RuntimeError(normalized)),
        )

    def _finish_exception(
        self,
        exc_type: type[BaseException],
        exc: BaseException | None,
    ) -> ObservedRunRecord:
        status: Literal["failed_before_call_start", "failed_after_call_start"] = (
            "failed_after_call_start"
            if self._count_linked_calls()
            else "failed_before_call_start"
        )
        return self._finish(
            status=status,
            error_type=exc_type.__name__,
            error_message=_sanitized_error_message(exc),
        )

    def _count_linked_calls(self) -> int:
        return _linked_call_count(_io_log._get_db(), self.root_trace_id)

    def _finish(
        self,
        *,
        status: Literal[
            "completed",
            "failed_before_call_start",
            "failed_after_call_start",
            "cancelled",
        ],
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> ObservedRunRecord:
        if self._finished:
            raise RuntimeError(f"observed run {self.run_id} is already terminal")
        if status not in _TERMINAL_STATUSES:
            raise ValueError(f"invalid terminal status: {status}")

        def _write(db: object) -> None:
            linked_call_count = _linked_call_count(db, self.root_trace_id)
            cursor = db.execute(  # type: ignore[attr-defined]
                """
                UPDATE observed_runs
                   SET status = ?, ended_at = ?, error_type = ?, error_phase = ?,
                       error_message = ?, linked_call_count = ?
                 WHERE run_id = ? AND status = 'running'
                """,
                (
                    status,
                    _now(),
                    error_type,
                    self._phase if error_type else None,
                    error_message,
                    linked_call_count,
                    self.run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"observed run {self.run_id} is already terminal")

        _io_log._run_db_write(_write)
        self._finished = True
        return get_observed_run(self.run_id)


_ACTIVE_OBSERVED_RUN: ContextVar[ObservedRun | None] = ContextVar(
    "llm_client_active_observed_run",
    default=None,
)


def _require_active_observed_run_child_trace(trace_id: str) -> None:
    """Reject public calls that escape the active observed-run lineage."""

    run = _ACTIVE_OBSERVED_RUN.get()
    if run is None:
        require_run = os.environ.get("LLM_CLIENT_REQUIRE_OBSERVED_RUN", "").strip().lower()
        if require_run not in {"", "0", "false", "no", "1", "true", "yes"}:
            raise RuntimeError(
                "LLM_CLIENT_REQUIRE_OBSERVED_RUN must be a boolean value"
            )
        if require_run in {"1", "true", "yes"}:
            raise RuntimeError(
                "LLM_CLIENT_REQUIRE_OBSERVED_RUN is enabled; create an ObservedRun "
                "before calling the public LLM API"
            )
        return
    if run._finished:
        raise RuntimeError(
            f"LLM call cannot attach to terminal observed run {run.run_id}"
        )
    if not trace_id.startswith(f"{run.root_trace_id}/"):
        raise ValueError(
            "trace_id for an LLM call inside ObservedRun must be a child trace "
            "created with run.child_trace_id(...)"
        )


__all__ = [
    "ObservedRun",
    "ObservedRunRecord",
    "ObservedRunStatus",
    "get_observed_run",
    "list_observed_runs",
]
