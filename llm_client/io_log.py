"""Persistent I/O logging for LLM calls and embeddings.

Appends one JSONL record per LLM call to:
    {DATA_ROOT}/{PROJECT}/{PROJECT}_llm_client_data/calls_YYYY-MM-DD.jsonl
Appends one JSONL record per embedding call to:
    {DATA_ROOT}/{PROJECT}/{PROJECT}_llm_client_data/embeddings_YYYY-MM-DD.jsonl

Log files are date-stamped to prevent unbounded growth. Old files are
automatically deleted after a configurable retention period (default 30 days).

Optionally writes both to a SQLite database at LLM_CLIENT_DB_PATH
(default: ~/projects/data/llm_observability.db).

Configured via env vars (library convention — llm_client already auto-loads
from ~/.secrets/api_keys.env):

    LLM_CLIENT_LOG_ENABLED          — "1" (default) or "0" to disable
    LLM_CLIENT_DATA_ROOT            — base dir (default: ~/projects/data)
    LLM_CLIENT_PROJECT              — project name (default: basename(os.getcwd()))
    LLM_CLIENT_DB_PATH              — SQLite DB path (default: ~/projects/data/llm_observability.db)
    LLM_CLIENT_DB_BUSY_TIMEOUT_MS   — SQLite busy timeout in ms (default: 5000)
    LLM_CLIENT_LOG_RETENTION_DAYS   — days to keep dated JSONL logs (default: 30)

Or override at runtime via configure().
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

_enabled: bool | None = None
_data_root: Path = Path(os.environ.get("LLM_CLIENT_DATA_ROOT", str(Path.home() / "projects" / "data")))
_project: str | None = os.environ.get("LLM_CLIENT_PROJECT")
_db_path: Path = Path(os.environ.get("LLM_CLIENT_DB_PATH", str(Path.home() / "projects" / "data" / "llm_observability.db")))
_db_conn: sqlite3.Connection | None = None
_db_lock = threading.Lock()
_db_write_lock = threading.Lock()
_DB_BUSY_TIMEOUT_MS_ENV = "LLM_CLIENT_DB_BUSY_TIMEOUT_MS"
_DEFAULT_DB_BUSY_TIMEOUT_MS = 5000
_DB_LOCK_RETRIES_ENV = "LLM_CLIENT_DB_LOCK_RETRIES"
_DEFAULT_DB_LOCK_RETRIES = 6
_DB_LOCK_RETRY_DELAY_MS_ENV = "LLM_CLIENT_DB_LOCK_RETRY_DELAY_MS"
_DEFAULT_DB_LOCK_RETRY_DELAY_MS = 250
_run_timer_lock = threading.Lock()
_run_timers: dict[str, dict[str, Any]] = {}
from llm_client.observability.context import (
    ActiveExperimentRun,
    ActiveFeatureProfile,
    _active_experiment_run_id,
    _active_feature_profile,
    _normalize_feature_profile,
    activate_experiment_run,
    activate_feature_profile,
    configure_agent_spec_enforcement,
    configure_experiment_enforcement,
    configure_feature_profile,
    enforce_agent_spec,
    enforce_experiment_context,
    enforce_feature_profile,
    get_active_experiment_run_id,
    get_active_feature_profile,
)

# ---------------------------------------------------------------------------
# Date-based JSONL log rotation
# ---------------------------------------------------------------------------

_LOG_RETENTION_DAYS_ENV = "LLM_CLIENT_LOG_RETENTION_DAYS"
_DEFAULT_LOG_RETENTION_DAYS = 30
_last_cleanup_date: date | None = None
_cleanup_lock = threading.Lock()


def _get_log_retention_days() -> int:
    """Return configured log retention in days from env, default 30."""
    raw = os.environ.get(_LOG_RETENTION_DAYS_ENV, "")
    if raw.strip().isdigit():
        return max(1, int(raw.strip()))
    return _DEFAULT_LOG_RETENTION_DAYS


def _get_db_busy_timeout_ms() -> int:
    """Return configured SQLite busy timeout in milliseconds."""

    raw = os.environ.get(_DB_BUSY_TIMEOUT_MS_ENV, "")
    if raw.strip().isdigit():
        return max(0, int(raw.strip()))
    return _DEFAULT_DB_BUSY_TIMEOUT_MS


def _get_db_lock_retries() -> int:
    """Return configured retry count for transient SQLite lock failures."""

    raw = os.environ.get(_DB_LOCK_RETRIES_ENV, "")
    if raw.strip().isdigit():
        return max(0, int(raw.strip()))
    return _DEFAULT_DB_LOCK_RETRIES


def _get_db_lock_retry_delay_ms() -> int:
    """Return base retry delay for transient SQLite lock failures."""

    raw = os.environ.get(_DB_LOCK_RETRY_DELAY_MS_ENV, "")
    if raw.strip().isdigit():
        return max(1, int(raw.strip()))
    return _DEFAULT_DB_LOCK_RETRY_DELAY_MS


def _dated_jsonl_path(directory: Path, stem: str) -> Path:
    """Return the date-stamped JSONL path for today, e.g. ``calls_2026-03-19.jsonl``.

    Each day gets a new file, preventing any single file from growing unbounded.
    """
    today = date.today().isoformat()
    return directory / f"{stem}_{today}.jsonl"


def _cleanup_old_jsonl(directory: Path, stem: str) -> None:
    """Delete dated JSONL files older than the retention period.

    Matches files named ``{stem}_YYYY-MM-DD.jsonl`` and removes those whose
    date is strictly older than ``today - retention_days``. Runs at most once
    per calendar day per process to avoid unnecessary I/O on every log append.
    Never raises — cleanup failure must not break logging.
    """
    global _last_cleanup_date
    today = date.today()

    # Fast check outside lock — skip if already cleaned up today
    if _last_cleanup_date == today:
        return

    with _cleanup_lock:
        # Re-check under lock
        if _last_cleanup_date == today:
            return
        _last_cleanup_date = today

    # Do actual cleanup outside the lock — it's idempotent
    try:
        retention = _get_log_retention_days()
        cutoff = today - timedelta(days=retention)
        pattern = re.compile(rf"^{re.escape(stem)}_(\d{{4}}-\d{{2}}-\d{{2}})\.jsonl$")
        if not directory.is_dir():
            return
        for path in directory.iterdir():
            m = pattern.match(path.name)
            if m:
                try:
                    file_date = date.fromisoformat(m.group(1))
                except ValueError:
                    continue
                if file_date < cutoff:
                    path.unlink(missing_ok=True)
                    logger.debug("Deleted old log file: %s", path)
    except Exception:
        logger.debug("_cleanup_old_jsonl failed", exc_info=True)


def _append_jsonl(directory: Path, stem: str, record: dict[str, Any]) -> None:
    """Append a JSON record to today's dated JSONL file and trigger cleanup.

    Writes to ``{directory}/{stem}_YYYY-MM-DD.jsonl``. Triggers cleanup of old
    files at most once per calendar day. The write completes before any cleanup
    runs, so no data loss can occur during rotation.
    """
    path = _dated_jsonl_path(directory, stem)
    with open(path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")
    _cleanup_old_jsonl(directory, stem)


def glob_jsonl_files(directory: Path, stem: str) -> list[Path]:
    """Return all JSONL files for a given stem, both legacy and dated.

    Finds the legacy undated file (``{stem}.jsonl``) and any dated files
    (``{stem}_YYYY-MM-DD.jsonl``), sorted oldest-first. Useful for readers
    that need to scan all historical log data.
    """
    files: list[Path] = []
    if not directory.is_dir():
        return files
    legacy = directory / f"{stem}.jsonl"
    if legacy.is_file():
        files.append(legacy)
    dated = sorted(
        p for p in directory.iterdir()
        if re.match(rf"^{re.escape(stem)}_\d{{4}}-\d{{2}}-\d{{2}}\.jsonl$", p.name)
    )
    files.extend(dated)
    return files


def _billing_attribution(model: str | None) -> tuple[str | None, str | None]:
    """Return ``(billing_account, openrouter_key_fingerprint)`` for one call.

    Recorded so the account split can be audited rather than trusted. Both are
    NULL when they cannot be established: a NULL means "unknown", and must not
    be read as though the call had been attributed to the default account.

    Attribution is telemetry, not a control. It never raises into the calling
    path -- the gate that actually prevents mis-billing is key selection in
    llm_client.utils.openrouter, which does fail loud.
    """

    account: str | None = None
    fingerprint: str | None = None
    try:
        from llm_client.utils.openrouter_accounts import resolve_account

        account = resolve_account()
    except Exception as exc:  # noqa: BLE001 - telemetry must not break a call
        logger.debug("billing account unresolved: %s: %s", type(exc).__name__, exc)

    if model and str(model).startswith("openrouter/"):
        try:
            from llm_client.utils.openrouter import (
                _mask_api_key,
                _openrouter_key_candidates_from_env,
            )

            candidates = _openrouter_key_candidates_from_env()
            if candidates:
                fingerprint = _mask_api_key(candidates[0])
        except Exception as exc:  # noqa: BLE001 - telemetry must not break a call
            logger.debug("openrouter key fingerprint unresolved: %s: %s", type(exc).__name__, exc)

    return account, fingerprint


def _get_project() -> str:
    """Resolve a stable project name so observability rows group by repo, not worktree."""
    global _project
    if _project is not None:
        return _project
    cwd = Path.cwd()
    detected = _detect_git_project(cwd)
    if detected is not None:
        _project = detected
        return detected
    return cwd.name


def _detect_git_project(cwd: Path) -> str | None:
    """Recover the canonical repo identity from Git so worktrees do not fork project stats."""

    common_dir = _git_rev_parse_path(cwd, "--git-common-dir")
    if common_dir is not None:
        detected = _canonical_project_name(common_dir)
        if detected is not None:
            return detected

    repo_root = _git_rev_parse_path(cwd, "--show-toplevel")
    if repo_root is not None:
        return _canonical_project_name(repo_root)
    return None


def _git_rev_parse_path(cwd: Path, flag: str) -> Path | None:
    """Read Git metadata paths defensively so logging still works outside repositories."""

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", flag],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, NotADirectoryError, subprocess.CalledProcessError):
        return None
    raw_path = completed.stdout.strip()
    if not raw_path:
        return None
    return Path(raw_path)


def _canonical_project_name(path: Path) -> str | None:
    """Normalize repo metadata paths into one durable project identifier."""

    expanded = path.expanduser()
    if expanded.name == ".git" and expanded.parent.name:
        return expanded.parent.name
    parts = expanded.parts
    if len(parts) >= 2 and parts[-2].endswith("_worktrees"):
        return parts[-2][: -len("_worktrees")]
    if expanded.name:
        return expanded.name
    return None


def _log_dir() -> Path:
    return _data_root / _get_project() / f"{_get_project()}_llm_client_data"


def _env_logging_enabled() -> bool:
    """Return logging-enabled state from the current environment."""

    return os.environ.get("LLM_CLIENT_LOG_ENABLED", "1") == "1"


def _logging_enabled() -> bool:
    """Return the effective logging-enabled state.

    Runtime/test overrides win when set explicitly. Otherwise, read the current
    environment dynamically so test fixtures that patch `LLM_CLIENT_LOG_ENABLED`
    after import still take effect.
    """

    if _enabled is not None:
        return _enabled
    return _env_logging_enabled()


def configure(
    *,
    enabled: bool | None = None,
    data_root: str | Path | None = None,
    project: str | None = None,
    db_path: str | Path | None = None,
) -> None:
    """Override logging config at runtime."""
    global _enabled, _data_root, _project, _db_path, _db_conn
    if enabled is not None:
        _enabled = enabled
    if data_root is not None:
        _data_root = Path(data_root)
    if project is not None:
        _project = project
    if db_path is not None:
        close()
        with _db_lock:
            _db_path = Path(db_path)


def close() -> None:
    """Close the shared SQLite connection after in-flight writes finish."""

    global _db_conn
    # Match the _run_db_write -> _get_db lock order so shutdown cannot close
    # the singleton connection while a lifecycle writer is using it.
    with _db_write_lock:
        with _db_lock:
            connection = _db_conn
            _db_conn = None
            if connection is not None:
                connection.close()


def _start_run_timer(run_id: str) -> None:
    """Store process-level start clocks for an experiment run."""
    with _run_timer_lock:
        _run_timers[run_id] = {
            "wall_t0": time.monotonic(),
            "cpu_t0": time.process_time(),
            "cpu_times_t0": os.times(),
        }


def _pop_run_timer(run_id: str) -> dict[str, Any] | None:
    """Remove and return cached run timer clocks."""
    with _run_timer_lock:
        return _run_timers.pop(run_id, None)


def _auto_capture_run_timing(
    *,
    run_id: str,
    wall_time_s: float | None,
    cpu_time_s: float | None,
    cpu_user_s: float | None,
    cpu_system_s: float | None,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Fill missing runtime timing fields from start_run clocks when available."""
    timer = _run_timers.get(run_id)
    if timer is None:
        return wall_time_s, cpu_time_s, cpu_user_s, cpu_system_s

    if wall_time_s is None:
        wall_time_s = time.monotonic() - timer["wall_t0"]
    if cpu_time_s is None:
        cpu_time_s = time.process_time() - timer["cpu_t0"]
    if cpu_user_s is None or cpu_system_s is None:
        cpu_times_end = os.times()
        cpu_times_t0 = timer["cpu_times_t0"]
        if cpu_user_s is None:
            cpu_user_s = cpu_times_end.user - cpu_times_t0.user
        if cpu_system_s is None:
            cpu_system_s = cpu_times_end.system - cpu_times_t0.system

    return wall_time_s, cpu_time_s, cpu_user_s, cpu_system_s


def log_call(
    *,
    model: str,
    messages: list[dict[str, Any]] | None = None,
    result: Any = None,
    error: Exception | None = None,
    latency_s: float | None = None,
    caller: str = "call_llm",
    task: str | None = None,
    trace_id: str | None = None,
    prompt_ref: str | None = None,
    call_snapshot: dict[str, Any] | None = None,
    call_fingerprint: str | None = None,
    error_type: str | None = None,
    execution_path: str | None = None,
    retry_count: int | None = None,
    schema_hash: str | None = None,
    response_format_type: str | None = None,
    validation_errors: str | None = None,
    causal_parent_id: str | None = None,
    logical_call_id: str | None = None,
    content_persistence: Literal["full", "metadata_only"] = "full",
) -> None:
    """Append one call record with optional prompt asset identity.

    Never raises — observability must not break model execution.
    """
    if not _logging_enabled():
        return
    try:
        if content_persistence not in {"full", "metadata_only"}:
            raise ValueError(
                f"Unsupported call content-persistence mode: {content_persistence}"
            )
        metadata_only = content_persistence == "metadata_only"
        d = _log_dir()
        d.mkdir(parents=True, exist_ok=True)

        # Extract fields from result if available.
        # When a call fails with a validation error that carries the raw
        # response, store it so we can diagnose whether the model produced
        # bad output or our processing mangled it.
        response_content = None
        if error is not None and hasattr(error, "raw_content"):
            response_content = getattr(error, "raw_content", None)
        if error is not None and hasattr(error, "validation_error"):
            try:
                ve = getattr(error, "validation_error")
                if hasattr(ve, "errors"):
                    validation_errors = json.dumps(
                        [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "")} for e in ve.errors()[:10]],
                        default=str,
                    )
            except Exception:
                pass  # observability must not break execution
        usage = None
        cost = None
        cost_source = None
        billing_mode = None
        marginal_cost = None
        cache_hit = 0
        finish_reason = None
        warnings: list[str] | None = None
        n_tool_calls: int | None = None
        response_tool_calls: list[Any] | None = None
        if result is not None:
            response_content = getattr(result, "content", None)
            usage_raw = getattr(result, "usage", None)
            usage = usage_raw if isinstance(usage_raw, dict) else None
            cost_raw = getattr(result, "cost", None)
            if isinstance(cost_raw, (int, float)):
                cost = float(cost_raw)
            cost_source_raw = getattr(result, "cost_source", None)
            if isinstance(cost_source_raw, str):
                cost_source = cost_source_raw
            billing_mode_raw = getattr(result, "billing_mode", None)
            if isinstance(billing_mode_raw, str):
                billing_mode = billing_mode_raw
            marginal_raw = getattr(result, "marginal_cost", None)
            if isinstance(marginal_raw, (int, float)):
                marginal_cost = float(marginal_raw)
            elif isinstance(cost, (int, float)):
                marginal_cost = float(cost)
            cache_attr = getattr(result, "cache_hit", False)
            cache_hit = 1 if cache_attr is True else 0
            finish_reason = getattr(result, "finish_reason", None)
            warnings_raw = getattr(result, "warnings", None)
            if isinstance(warnings_raw, list):
                warnings = [str(w) for w in warnings_raw if str(w)]
            tool_calls_raw = getattr(result, "tool_calls", None)
            if isinstance(tool_calls_raw, list):
                n_tool_calls = len(tool_calls_raw)
                response_tool_calls = json.loads(
                    json.dumps(tool_calls_raw, default=str)
                )

        timestamp = datetime.now(timezone.utc).isoformat()
        stored_messages = (
            None if metadata_only else _copy_messages_for_storage(messages)
        )
        stored_response = None if metadata_only else response_content
        stored_response_tool_calls = None if metadata_only else response_tool_calls
        stored_usage = (
            _metadata_only_usage(usage) if metadata_only else usage
        )
        stored_error = None if metadata_only else (str(error) if error else None)
        stored_warnings = None if metadata_only else warnings
        stored_snapshot = None if metadata_only else call_snapshot
        stored_fingerprint = None if metadata_only else call_fingerprint
        stored_validation_errors = None if metadata_only else validation_errors
        record = {
            "timestamp": timestamp,
            "model": model,
            "messages": stored_messages,
            "response": stored_response,
            "response_tool_calls": stored_response_tool_calls,
            "usage": stored_usage,
            "cost": cost,
            "cost_source": cost_source,
            "billing_mode": billing_mode,
            "marginal_cost": marginal_cost,
            "cache_hit": cache_hit,
            "finish_reason": finish_reason,
            "latency_s": round(latency_s, 3) if latency_s is not None else None,
            "error": stored_error,
            "warnings": stored_warnings,
            "n_tool_calls": n_tool_calls,
            "caller": caller,
            "task": task,
            "trace_id": trace_id,
            "prompt_ref": prompt_ref,
            "call_snapshot": stored_snapshot,
            "call_fingerprint": stored_fingerprint,
            "error_type": error_type or (type(error).__name__ if error else None),
            "execution_path": execution_path,
            "retry_count": retry_count,
            "schema_hash": schema_hash,
            "response_format_type": response_format_type,
            "validation_errors": stored_validation_errors,
            "logical_call_id": logical_call_id,
            "content_persistence": content_persistence,
        }
        _append_jsonl(d, "calls", record)

        # SQLite dual-write
        _write_call_to_db(
            timestamp=timestamp,
            model=model,
            messages=stored_messages,
            response=stored_response,
            response_tool_calls=stored_response_tool_calls,
            n_tool_calls=n_tool_calls,
            usage=stored_usage,
            cost=cost,
            cost_source=cost_source,
            billing_mode=billing_mode,
            marginal_cost=marginal_cost,
            cache_hit=cache_hit,
            finish_reason=finish_reason,
            latency_s=round(latency_s, 3) if latency_s is not None else None,
            error=stored_error,
            caller=caller,
            task=task,
            trace_id=trace_id,
            prompt_ref=prompt_ref,
            call_snapshot=stored_snapshot,
            call_fingerprint=stored_fingerprint,
            error_type=error_type or (type(error).__name__ if error else None),
            execution_path=execution_path,
            retry_count=retry_count,
            schema_hash=schema_hash,
            response_format_type=response_format_type,
            validation_errors=stored_validation_errors,
            causal_parent_id=causal_parent_id,
            logical_call_id=logical_call_id,
            content_persistence=content_persistence,
        )
    except Exception:
        # Never break LLM calls for logging
        logger.debug("io_log.log_call failed", exc_info=True)


def log_embedding(
    *,
    model: str,
    input_count: int,
    input_chars: int,
    dimensions: int | None = None,
    usage: dict[str, Any] | None = None,
    cost: float | None = None,
    latency_s: float | None = None,
    error: Exception | None = None,
    caller: str = "embed",
    task: str | None = None,
    trace_id: str | None = None,
) -> None:
    """Append one JSONL record for an embedding call. Never raises."""
    if not _logging_enabled():
        return
    try:
        d = _log_dir()
        d.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).isoformat()
        record = {
            "timestamp": timestamp,
            "model": model,
            "input_count": input_count,
            "input_chars": input_chars,
            "dimensions": dimensions,
            "usage": usage,
            "cost": cost,
            "latency_s": round(latency_s, 3) if latency_s is not None else None,
            "error": str(error) if error else None,
            "caller": caller,
            "task": task,
            "trace_id": trace_id,
        }
        _append_jsonl(d, "embeddings", record)

        # SQLite dual-write
        _write_embedding_to_db(
            timestamp=timestamp,
            model=model,
            input_count=input_count,
            input_chars=input_chars,
            dimensions=dimensions,
            usage=usage,
            cost=cost,
            latency_s=round(latency_s, 3) if latency_s is not None else None,
            error=str(error) if error else None,
            caller=caller,
            task=task,
            trace_id=trace_id,
        )
    except Exception:
        logger.debug("io_log.log_embedding failed", exc_info=True)


def log_foundation_event(
    *,
    event: dict[str, Any],
    caller: str = "foundation",
    task: str | None = None,
    trace_id: str | None = None,
) -> None:
    """Append one FOUNDATION event record. Never raises by default."""
    if not _logging_enabled():
        return
    try:
        from llm_client.foundation import validate_foundation_event

        normalized_event = validate_foundation_event(event)
        timestamp = datetime.now(timezone.utc).isoformat()
        run_id = str(normalized_event.get("run_id") or "")
        event_id = str(normalized_event.get("event_id") or "")
        event_type = str(normalized_event.get("event_type") or "")

        d = _log_dir()
        d.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": timestamp,
            "caller": caller,
            "task": task,
            "trace_id": trace_id,
            "run_id": run_id or None,
            "event_id": event_id or None,
            "event_type": event_type or None,
            "event": normalized_event,
        }
        _append_jsonl(d, "foundation_events", record)

        _write_foundation_event_to_db(
            timestamp=timestamp,
            run_id=run_id or None,
            trace_id=trace_id,
            event_id=event_id or None,
            event_type=event_type or None,
            payload=normalized_event,
            caller=caller,
            task=task,
        )
    except Exception:
        logger.debug("io_log.log_foundation_event failed", exc_info=True)


def record_call_lifecycle_event(event: dict[str, Any]) -> None:
    """Persist one typed call lifecycle event; evidence loss is an integrity error."""
    required = ("event_id", "timestamp", "logical_call_id", "trace_id", "task", "phase", "requested_model", "call_kind")
    missing = [key for key in required if not str(event.get(key) or "").strip()]
    if missing:
        raise ValueError(f"call lifecycle event missing required fields: {', '.join(missing)}")
    def _write(db: sqlite3.Connection) -> None:
        db.execute("""INSERT INTO call_lifecycle_events
            (event_id,timestamp,project,logical_call_id,trace_id,task,phase,requested_model,resolved_model,call_kind,prompt_sha256,schema_hash,causal_parent_id,requested_timeout_s,provider_timeout_s,transport_timeout_status,timeout_policy,process_id,host_name,process_start_token,error_type,payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            event["event_id"], event["timestamp"], _get_project(), event["logical_call_id"], event["trace_id"], event["task"], event["phase"], event["requested_model"], event.get("resolved_model"), event["call_kind"], event.get("prompt_sha256"), event.get("schema_hash"), event.get("causal_parent_id"), event.get("requested_timeout_s"), event.get("provider_timeout_s"), event.get("transport_timeout_status"), event.get("timeout_policy"), event.get("process_id"), event.get("host_name"), event.get("process_start_token"), event.get("error_type"), json.dumps(event, default=str),
        ))
    _run_db_write(_write)


def log_tool_call_record(
    *,
    call_id: str,
    tool_name: str,
    operation: str,
    status: Literal["started", "succeeded", "failed"],
    started_at: str,
    provider: str | None = None,
    target: str | None = None,
    ended_at: str | None = None,
    duration_ms: int | None = None,
    attempt: int = 1,
    task: str | None = None,
    trace_id: str | None = None,
    metrics: dict[str, Any] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    # Wave 1: size tracking and data-loss detection
    result_count: int | None = None,
    cost: float | None = None,
    raw_size: int = 0,
    processed_size: int = 0,
    query_json: dict[str, Any] | None = None,
    data_loss_warning: bool = False,
    strict: bool = False,
) -> None:
    """Append one non-LLM tool-call observability record.

    This mirrors ``log_call``: dual-write to JSONL and SQLite. Existing callers
    retain best-effort behavior. Pipeline-critical callers may set ``strict``
    so disabled logging or a persistence failure propagates into product code.

    Wave 1 adds ``result_count``, ``cost``, ``raw_size``, ``processed_size``,
    ``query_json``, and ``data_loss_warning`` for size tracking and automated
    data-loss detection.
    """

    if not _logging_enabled():
        if strict:
            raise RuntimeError("Strict tool-call persistence requires logging to be enabled")
        return

    def _persist() -> None:
        """Write the JSONL and SQLite records as one fail-loud operation."""

        timestamp = datetime.now(timezone.utc).isoformat()
        record = {
            "timestamp": timestamp,
            "call_id": call_id,
            "tool_name": tool_name,
            "operation": operation,
            "provider": provider,
            "target": target,
            "status": status,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_ms": duration_ms,
            "attempt": attempt,
            "task": task,
            "trace_id": trace_id,
            "metrics": metrics or {},
            "error_type": error_type,
            "error_message": error_message,
            "result_count": result_count,
            "cost": cost,
            "raw_size": raw_size,
            "processed_size": processed_size,
            "query_json": query_json,
            "data_loss_warning": data_loss_warning,
        }

        d = _log_dir()
        d.mkdir(parents=True, exist_ok=True)
        _append_jsonl(d, "tool_calls", record)

        _write_tool_call_to_db(
            timestamp=timestamp,
            call_id=call_id,
            tool_name=tool_name,
            operation=operation,
            provider=provider,
            target=target,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            attempt=attempt,
            task=task,
            trace_id=trace_id,
            metrics=metrics or {},
            error_type=error_type,
            error_message=error_message,
            result_count=result_count,
            cost=cost,
            raw_size=raw_size,
            processed_size=processed_size,
            query_json=query_json,
            data_loss_warning=data_loss_warning,
        )

    if strict:
        _persist()
        return
    try:
        _persist()
    except Exception:
        logger.debug("io_log.log_tool_call_record failed", exc_info=True)


# ---------------------------------------------------------------------------
# SQLite observability database
# ---------------------------------------------------------------------------

_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    project TEXT,
    model TEXT NOT NULL,
    messages TEXT,
    response TEXT,
    response_tool_calls TEXT,
    n_tool_calls INTEGER,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    reasoning_tokens INTEGER,
    cached_tokens INTEGER,
    cache_creation_tokens INTEGER,
    usage_details TEXT,
    cost REAL,
    cost_source TEXT,
    billing_mode TEXT,
    marginal_cost REAL,
    cache_hit INTEGER DEFAULT 0,
    finish_reason TEXT,
    latency_s REAL,
    error TEXT,
    caller TEXT,
    task TEXT,
    trace_id TEXT,
    prompt_ref TEXT,
    call_fingerprint TEXT,
    call_snapshot TEXT,
    logical_call_id TEXT,
    content_persistence TEXT NOT NULL DEFAULT 'full'
);

CREATE TABLE IF NOT EXISTS structured_attempt_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    timestamp TEXT NOT NULL,
    project TEXT,
    logical_call_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    task TEXT NOT NULL,
    attempt_ordinal INTEGER NOT NULL,
    model TEXT NOT NULL,
    execution_path TEXT NOT NULL,
    schema_hash TEXT NOT NULL,
    event_type TEXT NOT NULL,
    raw_sha256 TEXT,
    raw_artifact_ref TEXT,
    failure_class TEXT,
    execution_error_type TEXT,
    validation_issues TEXT NOT NULL,
    recovery_decision TEXT
);

CREATE TABLE IF NOT EXISTS attempt_diagnostics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnostic_id TEXT NOT NULL UNIQUE,
    timestamp TEXT NOT NULL,
    project TEXT,
    attempt_event_id TEXT NOT NULL,
    logical_call_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    task TEXT NOT NULL,
    attempt_ordinal INTEGER NOT NULL,
    phase TEXT NOT NULL,
    origin TEXT NOT NULL,
    attribution TEXT NOT NULL,
    exception_chain TEXT NOT NULL,
    exception_fingerprint TEXT,
    http_status INTEGER,
    provider_error_code TEXT,
    provider_request_id TEXT,
    gateway_request_id TEXT,
    retry_after_s REAL,
    timeout_kind TEXT,
    response_outcome TEXT,
    sanitized_summary TEXT,
    redaction_version TEXT NOT NULL,
    artifact_ref TEXT,
    artifact_sha256 TEXT
);

CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    project TEXT,
    model TEXT NOT NULL,
    input_count INTEGER,
    input_chars INTEGER,
    dimensions INTEGER,
    prompt_tokens INTEGER,
    total_tokens INTEGER,
    cost REAL,
    latency_s REAL,
    error TEXT,
    caller TEXT,
    task TEXT,
    trace_id TEXT
);

CREATE TABLE IF NOT EXISTS task_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    project TEXT,
    task TEXT,
    trace_id TEXT,
    rubric TEXT NOT NULL,
    method TEXT NOT NULL,
    overall_score REAL NOT NULL,
    dimensions TEXT,
    reasoning TEXT,
    output_model TEXT,
    judge_model TEXT,
    agent_spec TEXT,
    prompt_id TEXT,
    cost REAL,
    latency_s REAL,
    git_commit TEXT
);

CREATE TABLE IF NOT EXISTS experiment_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    timestamp TEXT NOT NULL,
    project TEXT,
    dataset TEXT NOT NULL,
    model TEXT NOT NULL,
    config TEXT,
    provenance TEXT,
    condition_id TEXT,
    seed INTEGER,
    replicate INTEGER,
    scenario_id TEXT,
    phase TEXT,
    metrics_schema TEXT,
    n_items INTEGER DEFAULT 0,
    n_completed INTEGER DEFAULT 0,
    n_errors INTEGER DEFAULT 0,
    summary_metrics TEXT,
    total_cost REAL DEFAULT 0.0,
    wall_time_s REAL,
    cpu_time_s REAL,
    cpu_user_s REAL,
    cpu_system_s REAL,
    git_commit TEXT,
    status TEXT DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS observed_runs (
    run_id TEXT PRIMARY KEY,
    root_trace_id TEXT NOT NULL,
    project TEXT NOT NULL,
    operation TEXT NOT NULL,
    executable TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'running', 'completed', 'failed_before_call_start',
            'failed_after_call_start', 'cancelled'
        )
    ),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    runtime_revision TEXT,
    config_sha256 TEXT,
    requested_model TEXT,
    reasoning_effort TEXT,
    max_budget REAL,
    error_type TEXT,
    error_phase TEXT,
    error_message TEXT,
    linked_call_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS experiment_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    metrics TEXT NOT NULL,
    predicted TEXT,
    gold TEXT,
    latency_s REAL,
    cost REAL,
    n_tool_calls INTEGER,
    error TEXT,
    extra TEXT,
    trace_id TEXT,
    UNIQUE(run_id, item_id)
);

CREATE TABLE IF NOT EXISTS experiment_aggregates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aggregate_id TEXT NOT NULL UNIQUE,
    timestamp TEXT NOT NULL,
    project TEXT,
    dataset TEXT NOT NULL,
    family_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    condition_id TEXT,
    scenario_id TEXT,
    phase TEXT,
    metrics TEXT NOT NULL,
    provenance TEXT,
    source_run_ids TEXT
);

CREATE TABLE IF NOT EXISTS foundation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    project TEXT,
    run_id TEXT,
    trace_id TEXT,
    event_id TEXT,
    event_type TEXT,
    payload TEXT NOT NULL,
    caller TEXT,
    task TEXT
);

CREATE TABLE IF NOT EXISTS call_lifecycle_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    timestamp TEXT NOT NULL,
    project TEXT,
    logical_call_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    task TEXT NOT NULL,
    phase TEXT NOT NULL,
    requested_model TEXT NOT NULL,
    resolved_model TEXT,
    call_kind TEXT NOT NULL,
    prompt_sha256 TEXT,
    schema_hash TEXT,
    causal_parent_id TEXT,
    requested_timeout_s INTEGER,
    provider_timeout_s INTEGER,
    transport_timeout_status TEXT,
    timeout_policy TEXT,
    process_id INTEGER,
    host_name TEXT,
    process_start_token TEXT,
    error_type TEXT,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    project TEXT,
    call_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    operation TEXT NOT NULL,
    provider TEXT,
    target TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_ms INTEGER,
    attempt INTEGER NOT NULL DEFAULT 1,
    task TEXT,
    trace_id TEXT,
    metrics TEXT,
    error_type TEXT,
    error_message TEXT,
    result_count INTEGER,
    cost REAL,
    raw_size INTEGER DEFAULT 0,
    processed_size INTEGER DEFAULT 0,
    query_json TEXT,
    data_loss_warning INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS interventions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intervention_id TEXT NOT NULL UNIQUE,
    timestamp TEXT NOT NULL,
    project TEXT,
    dataset TEXT,
    git_commit TEXT,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    problem TEXT NOT NULL,
    fix TEXT NOT NULL,
    baseline_run_id TEXT,
    verification_run_id TEXT,
    affected_items TEXT,
    expected_impact TEXT,
    measured_impact TEXT,
    status TEXT DEFAULT 'proposed'
);

CREATE TABLE IF NOT EXISTS cost_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start TEXT NOT NULL,
    window_hours INTEGER NOT NULL,
    budget REAL NOT NULL,
    observed_cost REAL NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(period_start, window_hours, budget)
);

CREATE TABLE IF NOT EXISTS dashboard_spend_hourly (
    bucket_start TEXT NOT NULL,
    project TEXT NOT NULL,
    model TEXT NOT NULL,
    call_count INTEGER NOT NULL DEFAULT 0,
    unpriced_call_count INTEGER NOT NULL DEFAULT 0,
    total_cost REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (bucket_start, project, model)
);

CREATE TABLE IF NOT EXISTS budget_scopes (
    scope_trace_id TEXT PRIMARY KEY,
    max_budget_microusd INTEGER NOT NULL CHECK (max_budget_microusd > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS budget_reservations (
    reservation_id TEXT PRIMARY KEY,
    scope_trace_id TEXT NOT NULL,
    call_trace_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    reserved_microusd INTEGER NOT NULL CHECK (reserved_microusd > 0),
    status TEXT NOT NULL CHECK (
        status IN ('active', 'settled', 'released_error', 'expired')
    ),
    created_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    completed_at TEXT,
    settled_cost_microusd INTEGER,
    FOREIGN KEY(scope_trace_id) REFERENCES budget_scopes(scope_trace_id)
);
"""

_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_calls_timestamp ON llm_calls(timestamp);
CREATE INDEX IF NOT EXISTS idx_lifecycle_logical_call ON call_lifecycle_events(logical_call_id, id);
CREATE INDEX IF NOT EXISTS idx_lifecycle_trace ON call_lifecycle_events(trace_id, id);
CREATE INDEX IF NOT EXISTS idx_calls_accounted_timestamp ON llm_calls(timestamp)
    WHERE cost_source IS NOT NULL OR billing_mode IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_calls_model ON llm_calls(model);
CREATE INDEX IF NOT EXISTS idx_calls_task ON llm_calls(task);
CREATE INDEX IF NOT EXISTS idx_calls_project ON llm_calls(project);
CREATE INDEX IF NOT EXISTS idx_calls_trace_id ON llm_calls(trace_id);
CREATE INDEX IF NOT EXISTS idx_calls_prompt_ref ON llm_calls(prompt_ref);
CREATE INDEX IF NOT EXISTS idx_calls_fingerprint ON llm_calls(call_fingerprint);
CREATE INDEX IF NOT EXISTS idx_dashboard_spend_hourly_bucket ON dashboard_spend_hourly(bucket_start);
CREATE INDEX IF NOT EXISTS idx_calls_logical_call_id ON llm_calls(logical_call_id);
CREATE INDEX IF NOT EXISTS idx_structured_attempt_call ON structured_attempt_events(logical_call_id, id);
CREATE INDEX IF NOT EXISTS idx_structured_attempt_trace ON structured_attempt_events(trace_id);
CREATE INDEX IF NOT EXISTS idx_structured_attempt_class ON structured_attempt_events(failure_class);
CREATE INDEX IF NOT EXISTS idx_attempt_diagnostic_event ON attempt_diagnostics(attempt_event_id, id);
CREATE INDEX IF NOT EXISTS idx_attempt_diagnostic_call ON attempt_diagnostics(logical_call_id, attempt_ordinal, id);
CREATE INDEX IF NOT EXISTS idx_emb_timestamp ON embeddings(timestamp);
CREATE INDEX IF NOT EXISTS idx_emb_model ON embeddings(model);
CREATE INDEX IF NOT EXISTS idx_emb_task ON embeddings(task);
CREATE INDEX IF NOT EXISTS idx_emb_project ON embeddings(project);
CREATE INDEX IF NOT EXISTS idx_emb_trace_id ON embeddings(trace_id);
CREATE INDEX IF NOT EXISTS idx_scores_task ON task_scores(task);
CREATE INDEX IF NOT EXISTS idx_scores_rubric ON task_scores(rubric);
CREATE INDEX IF NOT EXISTS idx_scores_project ON task_scores(project);
CREATE INDEX IF NOT EXISTS idx_scores_trace_id ON task_scores(trace_id);
CREATE INDEX IF NOT EXISTS idx_scores_timestamp ON task_scores(timestamp);
CREATE INDEX IF NOT EXISTS idx_scores_git_commit ON task_scores(git_commit);
CREATE INDEX IF NOT EXISTS idx_expr_dataset ON experiment_runs(dataset);
CREATE INDEX IF NOT EXISTS idx_expr_model ON experiment_runs(model);
CREATE INDEX IF NOT EXISTS idx_expr_project ON experiment_runs(project);
CREATE INDEX IF NOT EXISTS idx_expr_timestamp ON experiment_runs(timestamp);
CREATE INDEX IF NOT EXISTS idx_expr_git_commit ON experiment_runs(git_commit);
CREATE INDEX IF NOT EXISTS idx_expr_condition_id ON experiment_runs(condition_id);
CREATE INDEX IF NOT EXISTS idx_expr_seed ON experiment_runs(seed);
CREATE INDEX IF NOT EXISTS idx_expr_scenario_id ON experiment_runs(scenario_id);
CREATE INDEX IF NOT EXISTS idx_expr_phase ON experiment_runs(phase);
CREATE INDEX IF NOT EXISTS idx_expr_condition_seed ON experiment_runs(condition_id, seed);
CREATE INDEX IF NOT EXISTS idx_observed_runs_project ON observed_runs(project);
CREATE INDEX IF NOT EXISTS idx_observed_runs_root_trace ON observed_runs(root_trace_id);
CREATE INDEX IF NOT EXISTS idx_observed_runs_status ON observed_runs(status);
CREATE INDEX IF NOT EXISTS idx_observed_runs_started ON observed_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_expri_run_id ON experiment_items(run_id);
CREATE INDEX IF NOT EXISTS idx_expri_item_id ON experiment_items(item_id);
CREATE INDEX IF NOT EXISTS idx_expri_trace_id ON experiment_items(trace_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_expagg_aggregate_id ON experiment_aggregates(aggregate_id);
CREATE INDEX IF NOT EXISTS idx_expagg_project ON experiment_aggregates(project);
CREATE INDEX IF NOT EXISTS idx_expagg_dataset ON experiment_aggregates(dataset);
CREATE INDEX IF NOT EXISTS idx_expagg_family_id ON experiment_aggregates(family_id);
CREATE INDEX IF NOT EXISTS idx_expagg_type ON experiment_aggregates(aggregate_type);
CREATE INDEX IF NOT EXISTS idx_expagg_condition_id ON experiment_aggregates(condition_id);
CREATE INDEX IF NOT EXISTS idx_expagg_scenario_id ON experiment_aggregates(scenario_id);
CREATE INDEX IF NOT EXISTS idx_expagg_phase ON experiment_aggregates(phase);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fevent_event_id ON foundation_events(event_id);
CREATE INDEX IF NOT EXISTS idx_fevent_run_id ON foundation_events(run_id);
CREATE INDEX IF NOT EXISTS idx_fevent_trace_id ON foundation_events(trace_id);
CREATE INDEX IF NOT EXISTS idx_fevent_event_type ON foundation_events(event_type);
CREATE INDEX IF NOT EXISTS idx_tool_calls_timestamp ON tool_calls(timestamp);
CREATE INDEX IF NOT EXISTS idx_tool_calls_call_id ON tool_calls(call_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_tool_name ON tool_calls(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_calls_operation ON tool_calls(operation);
CREATE INDEX IF NOT EXISTS idx_tool_calls_provider ON tool_calls(provider);
CREATE INDEX IF NOT EXISTS idx_tool_calls_status ON tool_calls(status);
CREATE INDEX IF NOT EXISTS idx_tool_calls_task ON tool_calls(task);
CREATE INDEX IF NOT EXISTS idx_tool_calls_trace_id ON tool_calls(trace_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_data_loss ON tool_calls(data_loss_warning);
CREATE UNIQUE INDEX IF NOT EXISTS idx_interv_id ON interventions(intervention_id);
CREATE INDEX IF NOT EXISTS idx_interv_project ON interventions(project);
CREATE INDEX IF NOT EXISTS idx_interv_dataset ON interventions(dataset);
CREATE INDEX IF NOT EXISTS idx_interv_category ON interventions(category);
CREATE INDEX IF NOT EXISTS idx_interv_status ON interventions(status);
CREATE INDEX IF NOT EXISTS idx_interv_timestamp ON interventions(timestamp);
CREATE INDEX IF NOT EXISTS idx_cost_alerts_created_at ON cost_alerts(created_at);
CREATE INDEX IF NOT EXISTS idx_budget_reservations_active_scope
ON budget_reservations(scope_trace_id, status);
CREATE INDEX IF NOT EXISTS idx_budget_reservations_expiry
ON budget_reservations(status, expires_at);
"""


def _migrate_observed_runs_status_constraint(conn: sqlite3.Connection) -> None:
    """Replace the pre-release status CHECK while preserving every run row."""

    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'observed_runs'"
    ).fetchone()
    table_sql = str(row[0]) if row and row[0] else ""
    if not any(
        legacy_status in table_sql
        for legacy_status in ("'failed_before_call'", "'failed_during_call'")
    ):
        return
    legacy_table = "observed_runs_legacy_status"
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (legacy_table,),
    ).fetchone():
        raise RuntimeError(
            f"cannot migrate observed_runs while {legacy_table} already exists"
        )
    legacy_count = int(conn.execute("SELECT COUNT(*) FROM observed_runs").fetchone()[0])

    conn.execute(
        "ALTER TABLE observed_runs RENAME TO observed_runs_legacy_status"
    )
    conn.execute(
        """
        CREATE TABLE observed_runs (
            run_id TEXT PRIMARY KEY,
            root_trace_id TEXT NOT NULL,
            project TEXT NOT NULL,
            operation TEXT NOT NULL,
            executable TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN (
                    'running', 'completed', 'failed_before_call_start',
                    'failed_after_call_start', 'cancelled'
                )
            ),
            started_at TEXT NOT NULL,
            ended_at TEXT,
            runtime_revision TEXT,
            config_sha256 TEXT,
            requested_model TEXT,
            reasoning_effort TEXT,
            max_budget REAL,
            error_type TEXT,
            error_phase TEXT,
            error_message TEXT,
            linked_call_count INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        INSERT INTO observed_runs (
            run_id, root_trace_id, project, operation, executable, status,
            started_at, ended_at, runtime_revision, config_sha256,
            requested_model, reasoning_effort, max_budget, error_type,
            error_phase, error_message, linked_call_count
        )
        SELECT
            run_id, root_trace_id, project, operation, executable,
            CASE status
                WHEN 'failed_before_call' THEN 'failed_before_call_start'
                WHEN 'failed_during_call' THEN 'failed_after_call_start'
                ELSE status
            END,
            started_at, ended_at, runtime_revision, config_sha256,
            requested_model, reasoning_effort, max_budget, error_type,
            error_phase, error_message, linked_call_count
        FROM observed_runs_legacy_status
        """
    )
    migrated_count = int(
        conn.execute("SELECT COUNT(*) FROM observed_runs").fetchone()[0]
    )
    if migrated_count != legacy_count:
        raise RuntimeError(
            "observed_runs migration row-count mismatch: "
            f"expected {legacy_count}, copied {migrated_count}"
        )
    conn.execute("DROP TABLE observed_runs_legacy_status")


def _migrate_db(conn: sqlite3.Connection) -> None:
    """Add missing columns (idempotent). For DBs created before these columns existed."""
    _migrate_observed_runs_status_constraint(conn)

    for table in ("llm_calls", "embeddings"):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "trace_id" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN trace_id TEXT")
            prefix = table[:3]
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{prefix}_trace_id ON {table}(trace_id)")

    # llm_calls: add accounting metadata fields if missing
    llm_cols = {r[1] for r in conn.execute("PRAGMA table_info(llm_calls)").fetchall()}
    if "cost_source" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN cost_source TEXT")
    if "billing_mode" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN billing_mode TEXT")
    if "marginal_cost" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN marginal_cost REAL")
    if "cache_hit" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN cache_hit INTEGER DEFAULT 0")
    if "billing_account" not in llm_cols:
        # Which credential account owns this spend. NULL means unknown -- rows
        # written before account routing, and rows backfilled from JSONL, must
        # not be read as though they were attributed to the default account.
        #
        # Deliberately not indexed. ADD COLUMN is an O(1) metadata change, but
        # this table is already ~25M rows / 28GB in practice, so building an
        # index here would stall the first call after upgrade behind a
        # multi-minute locking write -- to index a column that is NULL for every
        # pre-existing row. Attribution queries filter by time or project first,
        # which are indexed. Add one later if a real query needs it, out of band.
        conn.execute("ALTER TABLE llm_calls ADD COLUMN billing_account TEXT")
    if "openrouter_key_fingerprint" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN openrouter_key_fingerprint TEXT")
    if "prompt_ref" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN prompt_ref TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_prompt_ref ON llm_calls(prompt_ref)")
    if "call_fingerprint" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN call_fingerprint TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_fingerprint ON llm_calls(call_fingerprint)")
    if "call_snapshot" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN call_snapshot TEXT")

    if "error_type" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN error_type TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_error_type ON llm_calls(error_type)")
    if "execution_path" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN execution_path TEXT")
    if "retry_count" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN retry_count INTEGER")
    if "schema_hash" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN schema_hash TEXT")
    if "response_format_type" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN response_format_type TEXT")
    if "validation_errors" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN validation_errors TEXT")
    if "causal_parent_id" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN causal_parent_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_causal_parent_id ON llm_calls(causal_parent_id)")
    if "logical_call_id" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN logical_call_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_logical_call_id ON llm_calls(logical_call_id)")
    if "reasoning_tokens" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN reasoning_tokens INTEGER")
    if "cached_tokens" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN cached_tokens INTEGER")
    if "cache_creation_tokens" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN cache_creation_tokens INTEGER")
    if "usage_details" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN usage_details TEXT")
    if "content_persistence" not in llm_cols:
        conn.execute(
            "ALTER TABLE llm_calls ADD COLUMN "
            "content_persistence TEXT NOT NULL DEFAULT 'full'"
        )
    if "response_tool_calls" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN response_tool_calls TEXT")
    if "n_tool_calls" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN n_tool_calls INTEGER")

    lifecycle_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(call_lifecycle_events)")
    }
    if "requested_timeout_s" not in lifecycle_cols:
        conn.execute(
            "ALTER TABLE call_lifecycle_events ADD COLUMN requested_timeout_s INTEGER"
        )
    if "prompt_sha256" not in lifecycle_cols:
        conn.execute("ALTER TABLE call_lifecycle_events ADD COLUMN prompt_sha256 TEXT")
    if "schema_hash" not in lifecycle_cols:
        conn.execute("ALTER TABLE call_lifecycle_events ADD COLUMN schema_hash TEXT")
    if "causal_parent_id" not in lifecycle_cols:
        conn.execute("ALTER TABLE call_lifecycle_events ADD COLUMN causal_parent_id TEXT")
    if "transport_timeout_status" not in lifecycle_cols:
        conn.execute(
            "ALTER TABLE call_lifecycle_events ADD COLUMN transport_timeout_status TEXT"
        )

    attempt_cols = {row[1] for row in conn.execute("PRAGMA table_info(structured_attempt_events)")}
    if "execution_error_type" not in attempt_cols:
        conn.execute(
            "ALTER TABLE structured_attempt_events ADD COLUMN execution_error_type TEXT"
        )

    diagnostic_cols = {row[1] for row in conn.execute("PRAGMA table_info(attempt_diagnostics)")}
    if "response_outcome" not in diagnostic_cols:
        conn.execute("ALTER TABLE attempt_diagnostics ADD COLUMN response_outcome TEXT")

    # task_scores: add git_commit if missing
    scores_cols = {r[1] for r in conn.execute("PRAGMA table_info(task_scores)").fetchall()}
    if scores_cols and "git_commit" not in scores_cols:
        conn.execute("ALTER TABLE task_scores ADD COLUMN git_commit TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scores_git_commit ON task_scores(git_commit)")

    # experiment_runs: add provenance + CPU timing fields if missing
    run_cols = {r[1] for r in conn.execute("PRAGMA table_info(experiment_runs)").fetchall()}
    if run_cols and "provenance" not in run_cols:
        conn.execute("ALTER TABLE experiment_runs ADD COLUMN provenance TEXT")
    if run_cols and "cpu_time_s" not in run_cols:
        conn.execute("ALTER TABLE experiment_runs ADD COLUMN cpu_time_s REAL")
    if run_cols and "cpu_user_s" not in run_cols:
        conn.execute("ALTER TABLE experiment_runs ADD COLUMN cpu_user_s REAL")
    if run_cols and "cpu_system_s" not in run_cols:
        conn.execute("ALTER TABLE experiment_runs ADD COLUMN cpu_system_s REAL")
    if run_cols and "condition_id" not in run_cols:
        conn.execute("ALTER TABLE experiment_runs ADD COLUMN condition_id TEXT")
    if run_cols and "seed" not in run_cols:
        conn.execute("ALTER TABLE experiment_runs ADD COLUMN seed INTEGER")
    if run_cols and "replicate" not in run_cols:
        conn.execute("ALTER TABLE experiment_runs ADD COLUMN replicate INTEGER")
    if run_cols and "scenario_id" not in run_cols:
        conn.execute("ALTER TABLE experiment_runs ADD COLUMN scenario_id TEXT")
    if run_cols and "phase" not in run_cols:
        conn.execute("ALTER TABLE experiment_runs ADD COLUMN phase TEXT")

    # experiment_items: add trace_id if missing
    item_cols = {r[1] for r in conn.execute("PRAGMA table_info(experiment_items)").fetchall()}
    if item_cols and "trace_id" not in item_cols:
        conn.execute("ALTER TABLE experiment_items ADD COLUMN trace_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_expri_trace_id ON experiment_items(trace_id)")

    tool_call_cols = {r[1] for r in conn.execute("PRAGMA table_info(tool_calls)").fetchall()}
    if tool_call_cols and "task" not in tool_call_cols:
        conn.execute("ALTER TABLE tool_calls ADD COLUMN task TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_calls_task ON tool_calls(task)")
    if tool_call_cols and "trace_id" not in tool_call_cols:
        conn.execute("ALTER TABLE tool_calls ADD COLUMN trace_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_calls_trace_id ON tool_calls(trace_id)")
    if tool_call_cols and "metrics" not in tool_call_cols:
        conn.execute("ALTER TABLE tool_calls ADD COLUMN metrics TEXT")
    if tool_call_cols and "error_type" not in tool_call_cols:
        conn.execute("ALTER TABLE tool_calls ADD COLUMN error_type TEXT")
    if tool_call_cols and "error_message" not in tool_call_cols:
        conn.execute("ALTER TABLE tool_calls ADD COLUMN error_message TEXT")
    # Wave 1: size tracking and data-loss detection
    if tool_call_cols and "result_count" not in tool_call_cols:
        conn.execute("ALTER TABLE tool_calls ADD COLUMN result_count INTEGER")
    if tool_call_cols and "cost" not in tool_call_cols:
        conn.execute("ALTER TABLE tool_calls ADD COLUMN cost REAL")
    if tool_call_cols and "raw_size" not in tool_call_cols:
        conn.execute("ALTER TABLE tool_calls ADD COLUMN raw_size INTEGER DEFAULT 0")
    if tool_call_cols and "processed_size" not in tool_call_cols:
        conn.execute("ALTER TABLE tool_calls ADD COLUMN processed_size INTEGER DEFAULT 0")
    if tool_call_cols and "query_json" not in tool_call_cols:
        conn.execute("ALTER TABLE tool_calls ADD COLUMN query_json TEXT")
    if tool_call_cols and "data_loss_warning" not in tool_call_cols:
        conn.execute("ALTER TABLE tool_calls ADD COLUMN data_loss_warning INTEGER DEFAULT 0")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_calls_data_loss ON tool_calls(data_loss_warning)")

    conn.commit()


def _get_db() -> sqlite3.Connection:
    """Lazy singleton DB connection. Creates tables on first call."""
    global _db_conn
    with _db_lock:
        if _db_conn is not None:
            return _db_conn
        _db_path.parent.mkdir(parents=True, exist_ok=True)
        busy_timeout_ms = _get_db_busy_timeout_ms()
        _db_conn = sqlite3.connect(
            str(_db_path),
            check_same_thread=False,
            timeout=busy_timeout_ms / 1000.0,
        )
        _db_conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        _db_conn.execute("PRAGMA journal_mode = WAL")
        _db_conn.execute("PRAGMA synchronous = NORMAL")
        _db_conn.executescript(_TABLES_SQL)
        # Two fresh processes can open the same SQLite file at once. One may
        # add an old-schema column after the other's PRAGMA snapshot but before
        # its ALTER TABLE. Retry the idempotent migration from a fresh schema
        # view instead of converting that harmless race into a startup failure.
        migration_attempt = 0
        while True:
            try:
                _migrate_db(_db_conn)
                break
            except sqlite3.OperationalError as exc:
                duplicate_column = "duplicate column name" in str(exc).lower()
                if not (duplicate_column or _is_db_locked_error(exc)):
                    raise
                if migration_attempt >= _get_db_lock_retries():
                    raise
                try:
                    _db_conn.rollback()
                except sqlite3.Error:
                    pass
                time.sleep(
                    (_get_db_lock_retry_delay_ms() * (migration_attempt + 1)) / 1000.0
                )
                migration_attempt += 1
        _db_conn.executescript(_INDEXES_SQL)
        return _db_conn


def _is_db_locked_error(exc: BaseException) -> bool:
    """Return True when the exception is a transient SQLite lock failure."""

    return isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower()


def _run_db_write(write_fn: Any) -> None:
    """Execute one SQLite write with bounded retry on transient lock errors."""

    retries = _get_db_lock_retries()
    base_delay_ms = _get_db_lock_retry_delay_ms()
    attempt = 0
    while True:
        try:
            with _db_write_lock:
                db = _get_db()
                write_fn(db)
                db.commit()
            return
        except sqlite3.OperationalError as exc:
            if _db_conn is not None:
                try:
                    _db_conn.rollback()
                except sqlite3.Error:
                    logger.debug("io_log._run_db_write rollback failed", exc_info=True)
            if not _is_db_locked_error(exc) or attempt >= retries:
                raise
            delay_s = (base_delay_ms * (attempt + 1)) / 1000.0
            logger.debug(
                "io_log._run_db_write retrying after lock failure (%d/%d) in %.3fs",
                attempt + 1,
                retries,
                delay_s,
            )
            time.sleep(delay_s)
            attempt += 1


def write_structured_attempt_event(event: dict[str, Any]) -> None:
    """Persist one metadata-only structured attempt event and fail on write errors."""

    if not _logging_enabled():
        return

    def _write(db: sqlite3.Connection) -> None:
        db.execute(
            """INSERT INTO structured_attempt_events
               (event_id, timestamp, project, logical_call_id, trace_id, task,
                attempt_ordinal, model, execution_path, schema_hash, event_type,
                raw_sha256, raw_artifact_ref, failure_class, validation_issues,
                execution_error_type, recovery_decision)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event["event_id"], event["timestamp"], _get_project(),
                event["logical_call_id"], event["trace_id"], event["task"],
                event["attempt_ordinal"], event["model"], event["execution_path"],
                event["schema_hash"], event["event_type"], event.get("raw_sha256"),
                event.get("raw_artifact_ref"), event.get("failure_class"),
                json.dumps(event.get("validation_issues", []), default=str),
                event.get("execution_error_type"),
                event.get("recovery_decision"),
            ),
        )

    _run_db_write(_write)


def read_structured_attempt_events(logical_call_id: str) -> list[dict[str, Any]]:
    """Read one logical call's append-only structured attempt history."""

    rows = _get_db().execute(
        """SELECT event_id, timestamp, logical_call_id, trace_id, task,
                  attempt_ordinal, model, execution_path, schema_hash, event_type,
                  raw_sha256, raw_artifact_ref, failure_class, validation_issues,
                  execution_error_type, recovery_decision
           FROM structured_attempt_events
           WHERE logical_call_id = ? ORDER BY id""",
        (logical_call_id,),
    ).fetchall()
    keys = (
        "event_id", "timestamp", "logical_call_id", "trace_id", "task",
        "attempt_ordinal", "model", "execution_path", "schema_hash", "event_type",
        "raw_sha256", "raw_artifact_ref", "failure_class", "validation_issues",
        "execution_error_type", "recovery_decision",
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(zip(keys, row, strict=True))
        item["validation_issues"] = json.loads(item["validation_issues"] or "[]")
        result.append(item)
    return result


def read_structured_attempt_events_for_trace(
    logical_call_id: str,
    trace_id: str,
) -> list[dict[str, Any]]:
    """Read one logical call only within its exact trace boundary."""

    rows = _get_db().execute(
        """SELECT event_id, timestamp, logical_call_id, trace_id, task,
                  attempt_ordinal, model, execution_path, schema_hash, event_type,
                  raw_sha256, raw_artifact_ref, failure_class, validation_issues,
                  execution_error_type, recovery_decision
           FROM structured_attempt_events
           WHERE logical_call_id = ? AND trace_id = ? ORDER BY id""",
        (logical_call_id, trace_id),
    ).fetchall()
    keys = (
        "event_id", "timestamp", "logical_call_id", "trace_id", "task",
        "attempt_ordinal", "model", "execution_path", "schema_hash", "event_type",
        "raw_sha256", "raw_artifact_ref", "failure_class", "validation_issues",
        "execution_error_type", "recovery_decision",
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(zip(keys, row, strict=True))
        item["validation_issues"] = json.loads(item["validation_issues"] or "[]")
        result.append(item)
    return result


def read_structured_attempt_event(event_id: str) -> dict[str, Any] | None:
    """Read one structured attempt event by its immutable event identity."""

    row = _get_db().execute(
        """SELECT event_id, timestamp, logical_call_id, trace_id, task,
                  attempt_ordinal, model, execution_path, schema_hash, event_type,
                  raw_sha256, raw_artifact_ref, failure_class, validation_issues,
                  execution_error_type, recovery_decision
           FROM structured_attempt_events WHERE event_id = ?""",
        (event_id,),
    ).fetchone()
    if row is None:
        return None
    keys = (
        "event_id", "timestamp", "logical_call_id", "trace_id", "task",
        "attempt_ordinal", "model", "execution_path", "schema_hash", "event_type",
        "raw_sha256", "raw_artifact_ref", "failure_class", "validation_issues",
        "execution_error_type", "recovery_decision",
    )
    result = dict(zip(keys, row, strict=True))
    result["validation_issues"] = json.loads(result["validation_issues"] or "[]")
    return result


def write_attempt_diagnostic(diagnostic: dict[str, Any]) -> None:
    """Persist one diagnostic only when it binds the exact attempt identity."""

    if not _logging_enabled():
        raise RuntimeError("attempt diagnostic persistence requires logging to be enabled")

    def _write(db: sqlite3.Connection) -> None:
        attempt = db.execute(
            """SELECT logical_call_id, trace_id, task, attempt_ordinal
               FROM structured_attempt_events WHERE event_id = ?""",
            (diagnostic["attempt_event_id"],),
        ).fetchone()
        if attempt is None:
            raise ValueError("attempt diagnostic must bind an existing structured attempt event")
        expected = tuple(
            diagnostic[key]
            for key in ("logical_call_id", "trace_id", "task", "attempt_ordinal")
        )
        if tuple(attempt) != expected:
            raise ValueError("attempt diagnostic identity does not match structured attempt event")
        db.execute(
            """INSERT INTO attempt_diagnostics
               (diagnostic_id, timestamp, project, attempt_event_id, logical_call_id,
                trace_id, task, attempt_ordinal, phase, origin, attribution,
                exception_chain, exception_fingerprint, http_status, provider_error_code,
                provider_request_id, gateway_request_id, retry_after_s, timeout_kind, response_outcome,
                sanitized_summary, redaction_version, artifact_ref, artifact_sha256)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                diagnostic["diagnostic_id"], diagnostic["timestamp"], _get_project(),
                diagnostic["attempt_event_id"], diagnostic["logical_call_id"],
                diagnostic["trace_id"], diagnostic["task"], diagnostic["attempt_ordinal"],
                diagnostic["phase"], diagnostic["origin"], diagnostic["attribution"],
                json.dumps(diagnostic["exception_chain"]), diagnostic.get("exception_fingerprint"),
                diagnostic.get("http_status"), diagnostic.get("provider_error_code"),
                diagnostic.get("provider_request_id"), diagnostic.get("gateway_request_id"),
                diagnostic.get("retry_after_s"), diagnostic.get("timeout_kind"), diagnostic.get("response_outcome"),
                diagnostic.get("sanitized_summary"), diagnostic["redaction_version"],
                diagnostic.get("artifact_ref"), diagnostic.get("artifact_sha256"),
            ),
        )

    _run_db_write(_write)


def read_attempt_diagnostics(attempt_event_id: str) -> list[dict[str, Any]]:
    """Read ordered diagnostics bound to one structured attempt event."""

    rows = _get_db().execute(
        """SELECT diagnostic_id, timestamp, attempt_event_id, logical_call_id, trace_id,
                  task, attempt_ordinal, phase, origin, attribution, exception_chain,
                  exception_fingerprint, http_status, provider_error_code,
                  provider_request_id, gateway_request_id, retry_after_s, timeout_kind, response_outcome,
                  sanitized_summary, redaction_version, artifact_ref, artifact_sha256
           FROM attempt_diagnostics WHERE attempt_event_id = ? ORDER BY id""",
        (attempt_event_id,),
    ).fetchall()
    keys = (
        "diagnostic_id", "timestamp", "attempt_event_id", "logical_call_id", "trace_id",
        "task", "attempt_ordinal", "phase", "origin", "attribution", "exception_chain",
        "exception_fingerprint", "http_status", "provider_error_code",
        "provider_request_id", "gateway_request_id", "retry_after_s", "timeout_kind", "response_outcome",
        "sanitized_summary", "redaction_version", "artifact_ref", "artifact_sha256",
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(zip(keys, row, strict=True))
        item["exception_chain"] = tuple(json.loads(item["exception_chain"] or "[]"))
        result.append(item)
    return result


def read_structured_attempt_call_ids(trace_id: str) -> list[str]:
    """Return structured logical-call ids for a trace in first-event order."""

    rows = _get_db().execute(
        """SELECT logical_call_id, MIN(id) AS first_id
           FROM structured_attempt_events WHERE trace_id = ?
           GROUP BY logical_call_id ORDER BY first_id""",
        (trace_id,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def read_structured_terminal_calls(logical_call_id: str) -> list[dict[str, Any]]:
    """Return persisted terminal call rows for one structured logical call.

    This is an internal persistence seam. Semantic validation and the public
    typed contract live in ``observability.selected_attempts``.
    """

    rows = _get_db().execute(
        """SELECT id, model, error, caller, task, trace_id, call_fingerprint,
                  call_snapshot, execution_path, schema_hash,
                  response_format_type, logical_call_id
           FROM llm_calls
           WHERE logical_call_id = ?
           ORDER BY id""",
        (logical_call_id,),
    ).fetchall()
    keys = (
        "call_id",
        "model",
        "error",
        "caller",
        "task",
        "trace_id",
        "call_fingerprint",
        "call_snapshot",
        "execution_path",
        "schema_hash",
        "response_format_type",
        "logical_call_id",
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(zip(keys, row, strict=True))
        snapshot = item["call_snapshot"]
        if snapshot is not None:
            try:
                item["call_snapshot"] = json.loads(snapshot)
            except (TypeError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"Logical call {logical_call_id} has malformed call_snapshot JSON."
                ) from error
        result.append(item)
    return result


def _valid_token_count(value: Any) -> int | None:
    """Return a provider token count only when it is a non-negative integer."""

    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _bounded_usage_details(usage: dict[str, Any] | None) -> str | None:
    """Serialize allowlisted numeric token details without provider content."""

    allowed = {
        "prompt_tokens_details": (
            "audio_tokens",
            "cache_write_tokens",
            "cached_tokens",
            "cache_creation_tokens",
            "cache_read_input_tokens",
            "image_tokens",
            "text_tokens",
            "video_tokens",
        ),
        "completion_tokens_details": (
            "reasoning_tokens",
            "audio_tokens",
            "image_tokens",
            "text_tokens",
            "video_tokens",
            "accepted_prediction_tokens",
            "rejected_prediction_tokens",
        ),
    }
    result: dict[str, dict[str, int]] = {}
    for group, fields in allowed.items():
        raw = (usage or {}).get(group)
        if not isinstance(raw, dict):
            continue
        bounded = {
            field: count
            for field in fields
            if (count := _valid_token_count(raw.get(field))) is not None
        }
        if bounded:
            result[group] = bounded
    return json.dumps(result) if result else None


def _metadata_only_usage(
    usage: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Retain only bounded numeric token metadata from provider usage."""

    if not isinstance(usage, dict):
        return None
    result: dict[str, Any] = {}
    for field in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "reasoning_tokens",
        "cached_tokens",
        "cache_creation_tokens",
    ):
        value = _valid_token_count(usage.get(field))
        if value is not None:
            result[field] = value
    details = _bounded_usage_details(usage)
    if details is not None:
        result.update(json.loads(details))
    return result or None


def _write_call_to_db(
    *,
    timestamp: str,
    model: str,
    messages: list[dict[str, Any]] | None,
    response: str | None,
    usage: dict[str, Any] | None,
    cost: float | None,
    cost_source: str | None,
    billing_mode: str | None,
    marginal_cost: float | None,
    cache_hit: int,
    finish_reason: str | None,
    latency_s: float | None,
    error: str | None,
    caller: str,
    task: str | None,
    trace_id: str | None = None,
    prompt_ref: str | None = None,
    call_snapshot: dict[str, Any] | None = None,
    call_fingerprint: str | None = None,
    error_type: str | None = None,
    execution_path: str | None = None,
    retry_count: int | None = None,
    schema_hash: str | None = None,
    response_format_type: str | None = None,
    validation_errors: str | None = None,
    causal_parent_id: str | None = None,
    logical_call_id: str | None = None,
    content_persistence: Literal["full", "metadata_only"] = "full",
    response_tool_calls: list[Any] | None = None,
    n_tool_calls: int | None = None,
) -> None:
    """Insert a call record into SQLite. Never raises."""
    try:
        prompt_tokens = _valid_token_count((usage or {}).get("prompt_tokens"))
        completion_tokens = _valid_token_count((usage or {}).get("completion_tokens"))
        total_tokens = _valid_token_count((usage or {}).get("total_tokens"))
        reasoning_tokens = _valid_token_count((usage or {}).get("reasoning_tokens"))
        cached_tokens = _valid_token_count((usage or {}).get("cached_tokens"))
        cache_creation_tokens = _valid_token_count(
            (usage or {}).get("cache_creation_tokens")
        )
        usage_details = _bounded_usage_details(usage)

        project = _get_project() or "unknown"
        billing_account, openrouter_key_fingerprint = _billing_attribution(model)
        bucket_start = datetime.fromisoformat(timestamp).replace(
            minute=0, second=0, microsecond=0
        ).isoformat()
        accounted = cost_source is not None or billing_mode is not None
        unpriced = cost_source is None or cost_source in {"unspecified", "unavailable"}
        recorded_cost = marginal_cost if marginal_cost is not None else (cost or 0.0)

        def _write(db: sqlite3.Connection) -> None:
            db.execute(
                """INSERT INTO llm_calls
                   (timestamp, project, model, messages, response,
                    response_tool_calls, n_tool_calls,
                    prompt_tokens, completion_tokens, total_tokens,
                    reasoning_tokens, cached_tokens, cache_creation_tokens,
                    usage_details,
                    cost, cost_source, billing_mode, marginal_cost, cache_hit,
                    billing_account, openrouter_key_fingerprint,
                    finish_reason, latency_s, error, caller, task, trace_id, prompt_ref,
                    call_fingerprint, call_snapshot,
                    error_type, execution_path, retry_count,
                    schema_hash, response_format_type, validation_errors,
                    causal_parent_id, logical_call_id, content_persistence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    timestamp, project, model,
                    json.dumps(messages, default=str) if messages else None,
                    response,
                    json.dumps(response_tool_calls, default=str)
                    if response_tool_calls is not None
                    else None,
                    n_tool_calls,
                    prompt_tokens, completion_tokens, total_tokens,
                    reasoning_tokens, cached_tokens, cache_creation_tokens,
                    usage_details,
                    cost, cost_source, billing_mode, marginal_cost, cache_hit,
                    billing_account, openrouter_key_fingerprint,
                    finish_reason, latency_s, error, caller, task, trace_id, prompt_ref,
                    call_fingerprint,
                    json.dumps(call_snapshot, default=str) if call_snapshot is not None else None,
                    error_type, execution_path, retry_count,
                    schema_hash, response_format_type, validation_errors,
                    causal_parent_id, logical_call_id, content_persistence,
                ),
            )
            if error is None and accounted:
                db.execute(
                    """INSERT INTO dashboard_spend_hourly
                       (bucket_start, project, model, call_count, unpriced_call_count, total_cost)
                       VALUES (?, ?, ?, 1, ?, ?)
                       ON CONFLICT(bucket_start, project, model) DO UPDATE SET
                           call_count = call_count + 1,
                           unpriced_call_count = unpriced_call_count + excluded.unpriced_call_count,
                           total_cost = total_cost + excluded.total_cost""",
                    (bucket_start, project, model, 1 if unpriced else 0, recorded_cost),
                )

        _run_db_write(_write)
    except Exception:
        logger.debug("io_log._write_call_to_db failed", exc_info=True)


def rebuild_dashboard_spend_hourly() -> int:
    """Rebuild the derived hourly cost view from the immutable call ledger."""

    with _db_write_lock:
        db = _get_db()
        db.execute("DELETE FROM dashboard_spend_hourly")
        db.execute(
            """INSERT INTO dashboard_spend_hourly
               (bucket_start, project, model, call_count, unpriced_call_count, total_cost)
               SELECT
                 strftime('%Y-%m-%dT%H:00:00+00:00', timestamp),
                 COALESCE(project, 'unknown'), model, COUNT(*),
                 SUM(CASE WHEN cost_source IS NULL OR cost_source IN ('unspecified', 'unavailable') THEN 1 ELSE 0 END),
                 COALESCE(SUM(COALESCE(marginal_cost, cost)), 0)
               FROM llm_calls
               WHERE error IS NULL AND (cost_source IS NOT NULL OR billing_mode IS NOT NULL)
               GROUP BY 1, 2, 3"""
        )
        count = db.execute("SELECT COUNT(*) FROM dashboard_spend_hourly").fetchone()[0]
        db.commit()
        return int(count)


def _write_embedding_to_db(
    *,
    timestamp: str,
    model: str,
    input_count: int,
    input_chars: int,
    dimensions: int | None,
    usage: dict[str, Any] | None,
    cost: float | None,
    latency_s: float | None,
    error: str | None,
    caller: str,
    task: str | None,
    trace_id: str | None = None,
) -> None:
    """Insert an embedding record into SQLite. Never raises."""
    try:
        prompt_tokens = (usage or {}).get("prompt_tokens")
        total_tokens = (usage or {}).get("total_tokens")
        def _write(db: sqlite3.Connection) -> None:
            db.execute(
                """INSERT INTO embeddings
                   (timestamp, project, model, input_count, input_chars, dimensions,
                    prompt_tokens, total_tokens, cost, latency_s, error, caller, task, trace_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    timestamp, _get_project(), model,
                    input_count, input_chars, dimensions,
                    prompt_tokens, total_tokens,
                    cost, latency_s, error, caller, task, trace_id,
                ),
            )

        _run_db_write(_write)
    except Exception:
        logger.debug("io_log._write_embedding_to_db failed", exc_info=True)


def _write_foundation_event_to_db(
    *,
    timestamp: str,
    run_id: str | None,
    trace_id: str | None,
    event_id: str | None,
    event_type: str | None,
    payload: dict[str, Any],
    caller: str,
    task: str | None,
) -> None:
    """Insert a foundation event into SQLite. Never raises."""
    try:
        def _write(db: sqlite3.Connection) -> None:
            db.execute(
                """INSERT INTO foundation_events
                   (timestamp, project, run_id, trace_id, event_id, event_type, payload, caller, task)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    timestamp,
                    _get_project(),
                    run_id,
                    trace_id,
                    event_id,
                    event_type,
                    json.dumps(payload, default=str),
                    caller,
                    task,
                ),
            )

        _run_db_write(_write)
    except Exception:
        logger.debug("io_log._write_foundation_event_to_db failed", exc_info=True)


def _write_tool_call_to_db(
    *,
    timestamp: str,
    call_id: str,
    tool_name: str,
    operation: str,
    status: str,
    started_at: str,
    provider: str | None,
    target: str | None,
    ended_at: str | None,
    duration_ms: int | None,
    attempt: int,
    task: str | None,
    trace_id: str | None,
    metrics: dict[str, Any],
    error_type: str | None,
    error_message: str | None,
    # Wave 1: size tracking and data-loss detection
    result_count: int | None = None,
    cost: float | None = None,
    raw_size: int = 0,
    processed_size: int = 0,
    query_json: dict[str, Any] | None = None,
    data_loss_warning: bool = False,
) -> None:
    """Insert a tool-call record into SQLite and propagate integrity failures."""

    def _write(db: sqlite3.Connection) -> None:
        db.execute(
            """INSERT INTO tool_calls
               (timestamp, project, call_id, tool_name, operation, provider, target,
                status, started_at, ended_at, duration_ms, attempt, task, trace_id,
                metrics, error_type, error_message, result_count, cost, raw_size,
                processed_size, query_json, data_loss_warning)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                timestamp,
                _get_project(),
                call_id,
                tool_name,
                operation,
                provider,
                target,
                status,
                started_at,
                ended_at,
                duration_ms,
                attempt,
                task,
                trace_id,
                json.dumps(metrics, default=str),
                error_type,
                error_message,
                result_count,
                cost,
                raw_size,
                processed_size,
                json.dumps(query_json, default=str) if query_json else None,
                1 if data_loss_warning else 0,
            ),
        )

    _run_db_write(_write)


def import_jsonl(jsonl_path: str | Path, table: str = "llm_calls") -> int:
    """Import existing JSONL records into SQLite. Returns count imported.

    Works with both legacy undated files (``calls.jsonl``) and dated files
    (``calls_2026-03-19.jsonl``). Use ``glob_jsonl_files()`` to discover all
    files for a given stem.

    Args:
        jsonl_path: Path to the JSONL file (e.g. calls.jsonl or calls_2026-03-19.jsonl).
        table: Target table — "llm_calls" or "embeddings".

    Returns:
        Number of records imported.
    """
    path = Path(jsonl_path)
    if not path.is_file():
        raise FileNotFoundError(f"JSONL file not found: {path}")
    if table not in ("llm_calls", "embeddings"):
        raise ValueError(f"table must be 'llm_calls' or 'embeddings', got {table!r}")

    db = _get_db()
    count = 0

    # Infer project from path: .../data/{project}/{project}_llm_client_data/calls.jsonl
    project = None
    parts = path.parts
    for i, part in enumerate(parts):
        if part.endswith("_llm_client_data") and i > 0:
            project = parts[i - 1]
            break

    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue

        if table == "llm_calls":
            usage = r.get("usage") or {}
            db.execute(
                """INSERT INTO llm_calls
                   (timestamp, project, model, messages, response,
                    response_tool_calls, n_tool_calls,
                    prompt_tokens, completion_tokens, total_tokens,
                    reasoning_tokens, cached_tokens, cache_creation_tokens,
                    usage_details,
                    cost, cost_source, billing_mode, marginal_cost, cache_hit,
                    finish_reason, latency_s, error, caller, task, trace_id, prompt_ref,
                    call_fingerprint, call_snapshot, content_persistence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    r.get("timestamp"), project, r.get("model"),
                    json.dumps(r.get("messages"), default=str) if r.get("messages") else None,
                    r.get("response"),
                    json.dumps(r.get("response_tool_calls"), default=str)
                    if r.get("response_tool_calls") is not None
                    else None,
                    r.get("n_tool_calls"),
                    usage.get("prompt_tokens"), usage.get("completion_tokens"),
                    usage.get("total_tokens"),
                    _valid_token_count(usage.get("reasoning_tokens")),
                    _valid_token_count(usage.get("cached_tokens")),
                    _valid_token_count(usage.get("cache_creation_tokens")),
                    _bounded_usage_details(usage),
                    r.get("cost"),
                    r.get("cost_source"),
                    r.get("billing_mode"),
                    r.get("marginal_cost"),
                    r.get("cache_hit", 0),
                    r.get("finish_reason"),
                    r.get("latency_s"), r.get("error"),
                    r.get("caller"), r.get("task"), r.get("trace_id"), r.get("prompt_ref"),
                    r.get("call_fingerprint"),
                    json.dumps(r.get("call_snapshot"), default=str) if r.get("call_snapshot") is not None else None,
                    r.get("content_persistence", "full"),
                ),
            )
        else:  # embeddings
            usage = r.get("usage") or {}
            db.execute(
                """INSERT INTO embeddings
                   (timestamp, project, model, input_count, input_chars, dimensions,
                    prompt_tokens, total_tokens, cost, latency_s, error, caller, task, trace_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    r.get("timestamp"), project, r.get("model"),
                    r.get("input_count"), r.get("input_chars"), r.get("dimensions"),
                    usage.get("prompt_tokens"), usage.get("total_tokens"),
                    r.get("cost"), r.get("latency_s"), r.get("error"),
                    r.get("caller"), r.get("task"), r.get("trace_id"),
                ),
            )
        count += 1

    db.commit()
    return count


def log_score(
    *,
    rubric: str,
    method: str,
    overall_score: float,
    dimensions: dict[str, Any] | None = None,
    reasoning: str | None = None,
    output_model: str | None = None,
    judge_model: str | None = None,
    agent_spec: str | None = None,
    prompt_id: str | None = None,
    cost: float | None = None,
    latency_s: float | None = None,
    task: str | None = None,
    trace_id: str | None = None,
    git_commit: str | None = None,
) -> None:
    """Write a rubric score to the observability DB. Never raises."""
    if not _logging_enabled():
        return
    try:
        # Auto-capture git commit if not provided
        if git_commit is None:
            from llm_client.utils.git_utils import get_git_head

            git_commit = get_git_head()

        timestamp = datetime.now(timezone.utc).isoformat()

        # JSONL append
        d = _log_dir()
        d.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": timestamp,
            "rubric": rubric,
            "method": method,
            "overall_score": overall_score,
            "dimensions": dimensions,
            "reasoning": reasoning,
            "output_model": output_model,
            "judge_model": judge_model,
            "agent_spec": agent_spec,
            "prompt_id": prompt_id,
            "cost": cost,
            "latency_s": round(latency_s, 3) if latency_s is not None else None,
            "task": task,
            "trace_id": trace_id,
            "git_commit": git_commit,
        }
        _append_jsonl(d, "scores", record)

        # SQLite write
        db = _get_db()
        db.execute(
            """INSERT INTO task_scores
               (timestamp, project, task, trace_id, rubric, method,
                overall_score, dimensions, reasoning, output_model,
                judge_model, agent_spec, prompt_id, cost, latency_s,
                git_commit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                timestamp, _get_project(), task, trace_id, rubric, method,
                overall_score,
                json.dumps(dimensions, default=str) if dimensions else None,
                reasoning, output_model, judge_model, agent_spec, prompt_id,
                cost, round(latency_s, 3) if latency_s is not None else None,
                git_commit,
            ),
        )
        db.commit()
    except Exception:
        logger.debug("io_log.log_score failed", exc_info=True)


def _copy_messages_for_storage(
    messages: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Deep-copy messages for storage (full content, no truncation)."""
    if messages is None:
        return None
    return [dict(m) for m in messages]


# ---------------------------------------------------------------------------
# Resume / lookup functions
# ---------------------------------------------------------------------------

def _query_api() -> Any:
    """Return the query compatibility target module on demand."""

    from llm_client.observability import query as _query

    return _query


from llm_client.observability.query import (
    get_active_llm_calls,
    get_completed_traces,
    get_trace_tree,
    lookup_result,
    summarize_trace,
)


def get_cost(
    *,
    trace_id: str | None = None,
    trace_prefix: str | None = None,
    task: str | None = None,
    project: str | None = None,
    since: str | date | None = None,
) -> float:
    """Compatibility shim: delegate to ``llm_client.observability.query``."""

    return _query_api().get_cost(
        trace_id=trace_id,
        trace_prefix=trace_prefix,
        task=task,
        project=project,
        since=since,
    )


def get_background_mode_adoption(
    *,
    experiments_path: str | Path | None = None,
    since: str | date | datetime | None = None,
    run_id_prefix: str | None = None,
) -> dict[str, Any]:
    """Compatibility shim: delegate to ``llm_client.observability.query``."""

    return _query_api().get_background_mode_adoption(
        experiments_path=experiments_path,
        since=since,
        run_id_prefix=run_id_prefix,
    )


from llm_client.observability.replay import (
    compare_call_snapshots,
    format_call_diff,
    get_call_snapshot,
    replay_call_snapshot,
)


# ---------------------------------------------------------------------------
# Experiment logging
# ---------------------------------------------------------------------------

def _experiment_api() -> Any:
    """Return the experiment compatibility target module on demand."""

    from llm_client.observability import experiments as _experiments

    return _experiments


from llm_client.observability.experiments import (
    ExperimentRun,
    _build_auto_run_provenance,
    compare_cohorts,
    compare_runs,
    experiment_run,
    finish_run,
    get_experiment_aggregates,
    get_run,
    get_run_items,
    get_runs,
    log_experiment_aggregate,
    log_item,
)


def start_run(
    *,
    dataset: str,
    model: str,
    task: str | None = None,
    config: dict[str, Any] | None = None,
    condition_id: str | None = None,
    seed: int | None = None,
    replicate: int | None = None,
    scenario_id: str | None = None,
    phase: str | None = None,
    metrics_schema: list[str] | None = None,
    run_id: str | None = None,
    git_commit: str | None = None,
    provenance: dict[str, Any] | None = None,
    feature_profile: str | dict[str, Any] | None = None,
    agent_spec: str | Path | dict[str, Any] | None = None,
    allow_missing_agent_spec: bool = False,
    missing_agent_spec_reason: str | None = None,
    project: str | None = None,
) -> str:
    """Compatibility shim: delegate to ``llm_client.observability.experiments``."""

    return _experiment_api().start_run(
        dataset=dataset,
        model=model,
        task=task,
        config=config,
        condition_id=condition_id,
        seed=seed,
        replicate=replicate,
        scenario_id=scenario_id,
        phase=phase,
        metrics_schema=metrics_schema,
        run_id=run_id,
        git_commit=git_commit,
        provenance=provenance,
        feature_profile=feature_profile,
        agent_spec=agent_spec,
        allow_missing_agent_spec=allow_missing_agent_spec,
        missing_agent_spec_reason=missing_agent_spec_reason,
        project=project,
    )


# ---------------------------------------------------------------------------
# Intervention log
# ---------------------------------------------------------------------------

from llm_client.observability.interventions import (
    get_interventions,
    log_intervention,
    update_intervention,
)
