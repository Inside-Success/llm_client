"""Privacy-preserving usage evidence imported from agent client transcripts.

The importer accepts only structured call events from Codex and Claude JSONL
logs. It deliberately excludes arguments, results, transcript text, raw paths,
and unhashed session identifiers from the normalized model and SQLite schema.
Transport outcomes (returned/error/missing) are not semantic correctness or
helpfulness judgments.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator


AgentClient = Literal["codex", "claude"]
TranscriptOutcome = Literal[
    "returned",
    "transport_error",
    "application_error",
    "missing",
]


class TranscriptParseError(ValueError):
    """Raised when a JSONL transcript contains a malformed event line."""


class ToolSurfaceMatcher(BaseModel):
    """Match a logical tool surface across client-specific identifiers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    surface: str = Field(description="Stable logical tool name used in reports.")
    aliases: tuple[str, ...] = Field(
        default=(),
        description="Additional server, namespace, or fully-qualified-name fragments.",
    )

    @field_validator("surface")
    @classmethod
    def _surface_must_be_nonempty(cls, value: str) -> str:
        """Reject an empty matcher that could accidentally select every call."""

        if not value.strip():
            raise ValueError("surface must be non-empty")
        return value.strip()

    def matches(self, *identifiers: str | None) -> bool:
        """Return whether any client identifier contains a configured alias."""

        candidates = [_normalize_identifier(value) for value in identifiers if value]
        aliases = {
            _normalize_identifier(value)
            for value in (self.surface, *self.aliases)
            if value.strip()
        }
        return any(alias in candidate for alias in aliases for candidate in candidates)


class AgentToolUsageEvent(BaseModel):
    """One normalized, content-free structured tool invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(description="Stable hash used for idempotent import.")
    occurred_at: str = Field(description="Client-recorded ISO timestamp for the call.")
    client: AgentClient = Field(description="Agent client that recorded the call.")
    project: str = Field(description="Repository name inferred from cwd without storing cwd.")
    tool_surface: str = Field(description="Stable logical tool surface.")
    operation: str = Field(description="Tool operation name without MCP namespace.")
    outcome: TranscriptOutcome = Field(
        description=(
            "Transcript evidence only: returned, transport error, explicit application "
            "error, or missing result."
        )
    )
    duration_ms: int | None = Field(
        default=None,
        description="Client-recorded duration when the transcript supplies it.",
    )
    session_id_hash: str = Field(description="SHA-256 of the client session identifier.")
    cwd_hash: str | None = Field(description="SHA-256 of cwd; raw cwd is never persisted.")
    source_file_hash: str = Field(
        description="SHA-256 of the transcript path; raw path is never persisted."
    )
    source_format: str = Field(description="Structured event format used by the parser.")
    input_size_bytes: int = Field(
        ge=0,
        description="Serialized input size for diagnostics; input content is discarded.",
    )
    output_size_bytes: int = Field(
        ge=0,
        description="Serialized output size for diagnostics; output content is discarded.",
    )


class ToolUsageImportSummary(BaseModel):
    """Aggregate result of one transcript import pass."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    files_scanned: int
    files_skipped: int
    coverage_complete: bool
    parse_error_file_hashes: tuple[str, ...]
    sessions_with_calls: int
    events_found: int
    inserted: int
    updated: int
    duplicates: int
    by_client: dict[str, int]
    by_outcome: dict[str, int]


class ToolUsageReport(BaseModel):
    """Read-only aggregate report over one logical tool surface."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_surface: str
    total_calls: int
    sessions: int
    projects: int
    by_client: dict[str, int]
    by_operation: dict[str, int]
    by_month: dict[str, int]
    by_outcome: dict[str, int]
    duration_samples: int
    duration_p50_ms: int | None
    duration_p95_ms: int | None
    transcript_coverage_complete: bool
    import_files_scanned: int
    import_files_skipped: int
    coverage_note: str
    helpfulness_status: Literal["unmeasured"] = "unmeasured"
    helpfulness_rated_calls: int = 0
    helpfulness_note: str = (
        "A returned tool call establishes transport completion; it does not establish "
        "helpfulness, correct selection, source truth, or decision impact."
    )


@dataclass(frozen=True, slots=True)
class _PendingCall:
    """In-memory call data awaiting a result; content is never retained."""

    call_id: str
    occurred_at: str
    operation: str
    source_format: str
    input_size_bytes: int
    sequence: int


@dataclass(frozen=True, slots=True)
class _CompletedCall:
    """In-memory normalized call before session metadata is hashed."""

    call_id: str
    occurred_at: str
    operation: str
    outcome: TranscriptOutcome
    duration_ms: int | None
    source_format: str
    input_size_bytes: int
    output_size_bytes: int
    sequence: int


@dataclass(frozen=True, slots=True)
class _PersistenceCounts:
    """Classify observations as new rows, matured rows, or duplicates."""

    inserted: int
    updated: int
    duplicates: int


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_tool_usage (
    event_id TEXT PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    client TEXT NOT NULL,
    project TEXT NOT NULL,
    tool_surface TEXT NOT NULL,
    operation TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('returned', 'transport_error', 'application_error', 'missing')
    ),
    duration_ms INTEGER,
    session_id_hash TEXT NOT NULL,
    cwd_hash TEXT,
    source_file_hash TEXT NOT NULL,
    source_format TEXT NOT NULL,
    input_size_bytes INTEGER NOT NULL,
    output_size_bytes INTEGER NOT NULL,
    imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_tool_usage_surface
    ON agent_tool_usage(tool_surface);
CREATE INDEX IF NOT EXISTS idx_agent_tool_usage_occurred
    ON agent_tool_usage(occurred_at);
CREATE INDEX IF NOT EXISTS idx_agent_tool_usage_client
    ON agent_tool_usage(client);
CREATE INDEX IF NOT EXISTS idx_agent_tool_usage_operation
    ON agent_tool_usage(operation);
CREATE INDEX IF NOT EXISTS idx_agent_tool_usage_outcome
    ON agent_tool_usage(outcome);
CREATE TABLE IF NOT EXISTS agent_tool_usage_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    imported_at TEXT NOT NULL,
    tool_surface TEXT NOT NULL,
    files_scanned INTEGER NOT NULL,
    files_skipped INTEGER NOT NULL,
    coverage_complete INTEGER NOT NULL,
    parse_error_file_hashes TEXT NOT NULL,
    events_found INTEGER NOT NULL,
    inserted INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_tool_usage_imports_surface
    ON agent_tool_usage_imports(tool_surface, id);
"""


def parse_codex_transcript(
    path: Path,
    matcher: ToolSurfaceMatcher,
) -> list[AgentToolUsageEvent]:
    """Parse actual Codex function-call and MCP-end events from one JSONL file."""

    records = _load_jsonl(path)
    session_id: str | None = None
    cwd: str | None = None
    pending: dict[str, _PendingCall] = {}
    completed: dict[str, _CompletedCall] = {}
    sequence = 0

    for record in records:
        timestamp = _string(record.get("timestamp"))
        record_type = _string(record.get("type"))
        payload = _mapping(record.get("payload"))

        if record_type == "session_meta" and payload is not None:
            session_id = _string(payload.get("id")) or session_id
            cwd = _string(payload.get("cwd")) or cwd
            continue
        if payload is None:
            continue

        payload_type = _string(payload.get("type"))
        if record_type == "response_item" and payload_type == "function_call":
            name = _string(payload.get("name"))
            namespace = _string(payload.get("namespace"))
            if not matcher.matches(name, namespace):
                continue
            call_id = _required_string(payload.get("call_id"), path, "call_id")
            occurred_at = _required_string(timestamp, path, "timestamp")
            sequence += 1
            pending[call_id] = _PendingCall(
                call_id=call_id,
                occurred_at=occurred_at,
                operation=_operation_name(name, namespace),
                source_format="codex_function_call",
                input_size_bytes=_serialized_size(payload.get("arguments")),
                sequence=sequence,
            )
            continue

        if record_type == "response_item" and payload_type == "function_call_output":
            output_call_id = _string(payload.get("call_id"))
            call = pending.pop(output_call_id or "", None)
            if call is None or call.call_id in completed:
                continue
            output = payload.get("output")
            completed[call.call_id] = _CompletedCall(
                call_id=call.call_id,
                occurred_at=call.occurred_at,
                operation=call.operation,
                outcome=_explicit_outcome(output, payload.get("is_error")),
                duration_ms=None,
                source_format=call.source_format,
                input_size_bytes=call.input_size_bytes,
                output_size_bytes=_serialized_size(output),
                sequence=call.sequence,
            )
            continue

        if record_type == "event_msg" and payload_type == "mcp_tool_call_end":
            invocation = _mapping(payload.get("invocation"))
            if invocation is None:
                continue
            server = _string(invocation.get("server"))
            tool = _string(invocation.get("tool"))
            if not matcher.matches(server, tool):
                continue
            call_id = _required_string(payload.get("call_id"), path, "call_id")
            occurred_at = _required_string(timestamp, path, "timestamp")
            sequence += 1
            result = payload.get("result")
            completed[call_id] = _CompletedCall(
                call_id=call_id,
                occurred_at=occurred_at,
                operation=_operation_name(tool, server),
                outcome=_result_outcome(result),
                duration_ms=_duration_ms(payload.get("duration")),
                source_format="codex_mcp_tool_call_end",
                input_size_bytes=_serialized_size(invocation.get("arguments")),
                output_size_bytes=_serialized_size(result),
                sequence=sequence,
            )
            pending.pop(call_id, None)

    for call in pending.values():
        if call.call_id in completed:
            continue
        completed[call.call_id] = _CompletedCall(
            call_id=call.call_id,
            occurred_at=call.occurred_at,
            operation=call.operation,
            outcome="missing",
            duration_ms=None,
            source_format=call.source_format,
            input_size_bytes=call.input_size_bytes,
            output_size_bytes=0,
            sequence=call.sequence,
        )

    return _materialize_events(
        calls=sorted(completed.values(), key=lambda call: call.sequence),
        client="codex",
        path=path,
        matcher=matcher,
        session_id=session_id,
        cwd=cwd,
    )


def parse_claude_transcript(
    path: Path,
    matcher: ToolSurfaceMatcher,
) -> list[AgentToolUsageEvent]:
    """Parse actual Claude tool-use/result events from one JSONL file."""

    records = _load_jsonl(path)
    session_id: str | None = None
    cwd: str | None = None
    pending: dict[str, _PendingCall] = {}
    completed: dict[str, _CompletedCall] = {}
    sequence = 0

    for record in records:
        session_id = _string(record.get("sessionId")) or session_id
        cwd = _string(record.get("cwd")) or cwd
        timestamp = _string(record.get("timestamp"))
        record_type = _string(record.get("type"))
        message = _mapping(record.get("message"))
        if message is None:
            continue
        content = _sequence(message.get("content"))

        if record_type == "assistant":
            for item_value in content:
                item = _mapping(item_value)
                if item is None or _string(item.get("type")) != "tool_use":
                    continue
                name = _string(item.get("name"))
                if not matcher.matches(name):
                    continue
                call_id = _required_string(item.get("id"), path, "tool_use.id")
                occurred_at = _required_string(timestamp, path, "timestamp")
                sequence += 1
                pending[call_id] = _PendingCall(
                    call_id=call_id,
                    occurred_at=occurred_at,
                    operation=_operation_name(name, None),
                    source_format="claude_tool_use",
                    input_size_bytes=_serialized_size(item.get("input")),
                    sequence=sequence,
                )
            continue

        if record_type == "user":
            for item_value in content:
                item = _mapping(item_value)
                if item is None or _string(item.get("type")) != "tool_result":
                    continue
                result_call_id = _string(item.get("tool_use_id"))
                call = pending.pop(result_call_id or "", None)
                if call is None:
                    continue
                output = item.get("content")
                completed[call.call_id] = _CompletedCall(
                    call_id=call.call_id,
                    occurred_at=call.occurred_at,
                    operation=call.operation,
                    outcome=_explicit_outcome(output, item.get("is_error")),
                    duration_ms=None,
                    source_format=call.source_format,
                    input_size_bytes=call.input_size_bytes,
                    output_size_bytes=_serialized_size(output),
                    sequence=call.sequence,
                )

    for call in pending.values():
        completed[call.call_id] = _CompletedCall(
            call_id=call.call_id,
            occurred_at=call.occurred_at,
            operation=call.operation,
            outcome="missing",
            duration_ms=None,
            source_format=call.source_format,
            input_size_bytes=call.input_size_bytes,
            output_size_bytes=0,
            sequence=call.sequence,
        )

    return _materialize_events(
        calls=sorted(completed.values(), key=lambda call: call.sequence),
        client="claude",
        path=path,
        matcher=matcher,
        session_id=session_id,
        cwd=cwd,
    )


def import_transcripts(
    *,
    codex_roots: Sequence[Path],
    claude_roots: Sequence[Path],
    db_path: Path,
    matcher: ToolSurfaceMatcher,
    skip_malformed_files: bool = False,
) -> ToolUsageImportSummary:
    """Scan transcript roots, persist normalized events, and return import counts.

    Malformed files fail the import by default. Callers may explicitly exclude
    whole malformed files; exclusions are then reported as path hashes and
    ``coverage_complete`` is false.
    """

    files: list[tuple[AgentClient, Path]] = []
    files.extend(("codex", path) for path in _iter_jsonl(codex_roots))
    files.extend(("claude", path) for path in _iter_jsonl(claude_roots))

    events: list[AgentToolUsageEvent] = []
    parse_error_file_hashes: list[str] = []
    for client, path in files:
        try:
            if client == "codex":
                events.extend(parse_codex_transcript(path, matcher))
            else:
                events.extend(parse_claude_transcript(path, matcher))
        except TranscriptParseError:
            if not skip_malformed_files:
                raise
            parse_error_file_hashes.append(_hash_text(str(path.resolve())))

    persistence = _persist_usage_events(events=events, db_path=db_path)
    by_client = _count_values(event.client for event in events)
    by_outcome = _count_values(event.outcome for event in events)
    summary = ToolUsageImportSummary(
        files_scanned=len(files),
        files_skipped=len(parse_error_file_hashes),
        coverage_complete=not parse_error_file_hashes,
        parse_error_file_hashes=tuple(sorted(parse_error_file_hashes)),
        sessions_with_calls=len({event.session_id_hash for event in events}),
        events_found=len(events),
        inserted=persistence.inserted,
        updated=persistence.updated,
        duplicates=persistence.duplicates,
        by_client=by_client,
        by_outcome=by_outcome,
    )
    _record_import_summary(summary=summary, db_path=db_path, tool_surface=matcher.surface)
    return summary


def persist_usage_events(
    *,
    events: Sequence[AgentToolUsageEvent],
    db_path: Path,
) -> int:
    """Persist events and return new-row count, maturing provisional rows."""

    return _persist_usage_events(events=events, db_path=db_path).inserted


def _persist_usage_events(
    *,
    events: Sequence[AgentToolUsageEvent],
    db_path: Path,
) -> _PersistenceCounts:
    """Persist events while allowing only ``missing`` to mature to terminal."""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    imported_at = datetime.now(timezone.utc).isoformat()
    inserted = 0
    updated = 0
    duplicates = 0
    with sqlite3.connect(db_path) as db:
        db.executescript(_SCHEMA_SQL)
        for event in events:
            current = db.execute(
                "SELECT outcome FROM agent_tool_usage WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if current is None:
                db.execute(
                    """
                    INSERT INTO agent_tool_usage (
                        event_id, occurred_at, client, project, tool_surface, operation,
                        outcome, duration_ms, session_id_hash, cwd_hash, source_file_hash,
                        source_format, input_size_bytes, output_size_bytes, imported_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.occurred_at,
                        event.client,
                        event.project,
                        event.tool_surface,
                        event.operation,
                        event.outcome,
                        event.duration_ms,
                        event.session_id_hash,
                        event.cwd_hash,
                        event.source_file_hash,
                        event.source_format,
                        event.input_size_bytes,
                        event.output_size_bytes,
                        imported_at,
                    ),
                )
                inserted += 1
                continue

            if current[0] == "missing" and event.outcome != "missing":
                cursor = db.execute(
                    """
                    UPDATE agent_tool_usage
                    SET outcome = ?, duration_ms = ?, source_file_hash = ?,
                        source_format = ?, output_size_bytes = ?, imported_at = ?
                    WHERE event_id = ? AND outcome = 'missing'
                    """,
                    (
                        event.outcome,
                        event.duration_ms,
                        event.source_file_hash,
                        event.source_format,
                        event.output_size_bytes,
                        imported_at,
                        event.event_id,
                    ),
                )
                if cursor.rowcount == 1:
                    updated += 1
                    continue
            duplicates += 1
    return _PersistenceCounts(
        inserted=inserted,
        updated=updated,
        duplicates=duplicates,
    )


def build_usage_report(*, db_path: Path, tool_surface: str) -> ToolUsageReport:
    """Return aggregate transcript evidence without mutating the ledger."""

    if not db_path.exists():
        raise FileNotFoundError(f"tool-usage database does not exist: {db_path}")
    with sqlite3.connect(db_path) as db:
        table_exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_tool_usage'"
        ).fetchone()
        if table_exists is None:
            raise RuntimeError("agent_tool_usage table is missing; run tool-usage import first")
        total_row = db.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT session_id_hash), COUNT(DISTINCT project)
            FROM agent_tool_usage WHERE tool_surface = ?
            """,
            (tool_surface,),
        ).fetchone()
        assert total_row is not None
        durations = [
            int(row[0])
            for row in db.execute(
                """
                SELECT duration_ms FROM agent_tool_usage
                WHERE tool_surface = ? AND duration_ms IS NOT NULL
                ORDER BY duration_ms
                """,
                (tool_surface,),
            ).fetchall()
        ]
        by_client = _query_counts(db, tool_surface, "client")
        by_operation = _query_counts(db, tool_surface, "operation")
        by_outcome = _query_counts(db, tool_surface, "outcome")
        by_month = {
            str(row[0]): int(row[1])
            for row in db.execute(
                """
                SELECT substr(occurred_at, 1, 7), COUNT(*)
                FROM agent_tool_usage WHERE tool_surface = ?
                GROUP BY substr(occurred_at, 1, 7)
                ORDER BY substr(occurred_at, 1, 7)
                """,
                (tool_surface,),
            ).fetchall()
        }
        import_row = db.execute(
            """
            SELECT files_scanned, files_skipped, coverage_complete
            FROM agent_tool_usage_imports
            WHERE tool_surface = ? ORDER BY id DESC LIMIT 1
            """,
            (tool_surface,),
        ).fetchone()
        if import_row is None:
            raise RuntimeError(
                "agent_tool_usage_imports has no run for this surface; run import first"
            )

    coverage_complete = bool(import_row[2])
    files_skipped = int(import_row[1])
    coverage_note = (
        "All scanned transcript files parsed successfully."
        if coverage_complete
        else (
            f"Incomplete transcript coverage: {files_skipped} malformed file(s) "
            "were explicitly excluded by hash."
        )
    )

    return ToolUsageReport(
        tool_surface=tool_surface,
        total_calls=int(total_row[0]),
        sessions=int(total_row[1]),
        projects=int(total_row[2]),
        by_client=by_client,
        by_operation=by_operation,
        by_month=by_month,
        by_outcome=by_outcome,
        duration_samples=len(durations),
        duration_p50_ms=_percentile(durations, 0.50),
        duration_p95_ms=_percentile(durations, 0.95),
        transcript_coverage_complete=coverage_complete,
        import_files_scanned=int(import_row[0]),
        import_files_skipped=files_skipped,
        coverage_note=coverage_note,
    )


def _record_import_summary(
    *,
    summary: ToolUsageImportSummary,
    db_path: Path,
    tool_surface: str,
) -> None:
    """Persist one content-free import coverage receipt for later reports."""

    with sqlite3.connect(db_path) as db:
        db.executescript(_SCHEMA_SQL)
        db.execute(
            """
            INSERT INTO agent_tool_usage_imports (
                imported_at, tool_surface, files_scanned, files_skipped,
                coverage_complete, parse_error_file_hashes, events_found, inserted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                tool_surface,
                summary.files_scanned,
                summary.files_skipped,
                1 if summary.coverage_complete else 0,
                json.dumps(summary.parse_error_file_hashes),
                summary.events_found,
                summary.inserted,
            ),
        )


def _load_jsonl(path: Path) -> list[Mapping[str, object]]:
    """Load a JSONL file and fail with precise source context on corruption."""

    records: list[Mapping[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TranscriptParseError(f"{path}:{line_number}: {exc.msg}") from exc
            record = _mapping(value)
            if record is None:
                raise TranscriptParseError(
                    f"{path}:{line_number}: transcript line must be a JSON object"
                )
            records.append(record)
    return records


def _materialize_events(
    *,
    calls: Sequence[_CompletedCall],
    client: AgentClient,
    path: Path,
    matcher: ToolSurfaceMatcher,
    session_id: str | None,
    cwd: str | None,
) -> list[AgentToolUsageEvent]:
    """Hash provenance metadata and build public normalized events."""

    source_file_hash = _hash_text(str(path.resolve()))
    session_id_hash = _hash_text(session_id or source_file_hash)
    cwd_hash = _hash_text(cwd) if cwd else None
    project = _infer_project(cwd)
    return [
        AgentToolUsageEvent(
            event_id=_hash_text(
                "|".join((client, session_id_hash, call.call_id, call.operation))
            ),
            occurred_at=call.occurred_at,
            client=client,
            project=project,
            tool_surface=matcher.surface,
            operation=call.operation,
            outcome=call.outcome,
            duration_ms=call.duration_ms,
            session_id_hash=session_id_hash,
            cwd_hash=cwd_hash,
            source_file_hash=source_file_hash,
            source_format=call.source_format,
            input_size_bytes=call.input_size_bytes,
            output_size_bytes=call.output_size_bytes,
        )
        for call in calls
    ]


def _iter_jsonl(roots: Sequence[Path]) -> list[Path]:
    """Return a deterministic, de-duplicated list of JSONL files."""

    files: set[Path] = set()
    for root in roots:
        expanded = root.expanduser()
        if not expanded.exists():
            raise FileNotFoundError(f"transcript root does not exist: {expanded}")
        if expanded.is_file():
            if expanded.suffix == ".jsonl":
                files.add(expanded.resolve())
            continue
        files.update(path.resolve() for path in expanded.rglob("*.jsonl"))
    return sorted(files)


def _query_counts(
    db: sqlite3.Connection,
    tool_surface: str,
    column: Literal["client", "operation", "outcome"],
) -> dict[str, int]:
    """Return deterministic group counts for a whitelisted schema column."""

    rows = db.execute(
        f"""
        SELECT {column}, COUNT(*) FROM agent_tool_usage
        WHERE tool_surface = ? GROUP BY {column} ORDER BY {column}
        """,  # noqa: S608 - column is a Literal whitelist, never user input.
        (tool_surface,),
    ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def _count_values(values: Iterable[str]) -> dict[str, int]:
    """Count string values from any finite iterable in sorted key order."""

    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _percentile(values: Sequence[int], quantile: float) -> int | None:
    """Return a nearest-rank percentile for an already sorted sequence."""

    if not values:
        return None
    index = max(0, math.ceil(quantile * len(values)) - 1)
    return int(values[index])


def _normalize_identifier(value: str) -> str:
    """Normalize client-specific separators for stable substring matching."""

    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _operation_name(name: str | None, fallback: str | None) -> str:
    """Extract an operation from a fully qualified MCP name or explicit tool."""

    candidate = name or fallback or "unknown"
    if "__" in candidate:
        candidate = candidate.rsplit("__", 1)[-1]
    return candidate.strip() or "unknown"


def _result_outcome(value: object) -> TranscriptOutcome:
    """Classify only explicit structured MCP result states."""

    if value is None:
        return "missing"
    mapping = _mapping(value)
    if mapping is not None and any(key.lower() == "err" for key in mapping):
        return "transport_error"
    if _contains_explicit_error(value):
        return "application_error"
    return "returned"


def _explicit_outcome(value: object, is_error: object) -> TranscriptOutcome:
    """Classify an output using the client's explicit error flag when present."""

    if is_error is True:
        return "transport_error"
    if value is None:
        return "missing"
    if _contains_explicit_error(value):
        return "application_error"
    return "returned"


def _contains_explicit_error(value: object) -> bool:
    """Detect only explicit envelope-level errors, not domain data fields."""

    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lower().startswith("error:"):
            return True
        if not stripped.startswith("{"):
            return False
        try:
            nested = json.loads(stripped)
        except json.JSONDecodeError:
            return False
        return _contains_explicit_error(nested)

    mapping = _mapping(value)
    if mapping is None:
        return False
    if _mapping_declares_error(mapping):
        return True
    if "Ok" in mapping:
        return _mcp_envelope_declares_error(mapping["Ok"])
    if "ok" in mapping:
        return _mcp_envelope_declares_error(mapping["ok"])
    if "content" in mapping:
        return _content_declares_error(mapping["content"])
    return False


def _mapping_declares_error(mapping: Mapping[str, object]) -> bool:
    """Return whether a mapping's own status fields declare an error."""

    for key, item in mapping.items():
        if key.lower() in {"err", "error", "failed", "failure", "is_error"}:
            if item not in (None, False, ""):
                return True
    return False


def _mcp_envelope_declares_error(value: object) -> bool:
    """Inspect only the direct MCP success envelope and its content wrapper."""

    mapping = _mapping(value)
    if mapping is None:
        return False
    if _mapping_declares_error(mapping):
        return True
    if "content" in mapping:
        return _content_declares_error(mapping["content"])
    return False


def _content_declares_error(value: object) -> bool:
    """Inspect top-level JSON in MCP text items for explicit error fields."""

    if not isinstance(value, list):
        return False
    for item_value in value:
        item = _mapping(item_value)
        if item is None:
            continue
        if _mapping_declares_error(item):
            return True
        text = item.get("text")
        if not isinstance(text, str):
            continue
        stripped = text.strip()
        if stripped.lower().startswith("error:"):
            return True
        if not stripped.startswith("{"):
            continue
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        decoded_mapping = _mapping(decoded)
        if decoded_mapping is not None and _mapping_declares_error(decoded_mapping):
            return True
    return False


def _duration_ms(value: object) -> int | None:
    """Convert Codex `{secs, nanos}` duration metadata to milliseconds."""

    mapping = _mapping(value)
    if mapping is None:
        return None
    secs = mapping.get("secs", 0)
    nanos = mapping.get("nanos", 0)
    if not isinstance(secs, (int, float)) or isinstance(secs, bool):
        return None
    if not isinstance(nanos, (int, float)) or isinstance(nanos, bool):
        return None
    return max(0, int(round(float(secs) * 1000 + float(nanos) / 1_000_000)))


def _serialized_size(value: object) -> int:
    """Measure a payload before discarding it without retaining its content."""

    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    return len(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    )


def _infer_project(cwd: str | None) -> str:
    """Infer only a repository label from cwd, including governed worktrees."""

    if not cwd:
        return "unknown"
    parts = Path(cwd).parts
    if "worktrees" in parts:
        index = parts.index("worktrees")
        if index > 0:
            return parts[index - 1]
    leaf = Path(cwd).name
    if leaf.endswith("_worktrees"):
        return leaf.removesuffix("_worktrees")
    for part in reversed(parts):
        if part.endswith("_worktrees"):
            return part.removesuffix("_worktrees")
    return leaf or "unknown"


def _hash_text(value: str) -> str:
    """Return a lowercase SHA-256 digest for provenance metadata."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mapping(value: object) -> Mapping[str, object] | None:
    """Narrow unknown JSON values to string-keyed mappings."""

    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in value.items()}


def _sequence(value: object) -> Sequence[object]:
    """Narrow JSON arrays without treating strings as sequences of events."""

    if isinstance(value, list):
        return value
    return ()


def _string(value: object) -> str | None:
    """Return a non-empty string or None for unknown JSON values."""

    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _required_string(
    value: object,
    path: Path,
    field_name: str,
) -> str:
    """Return a required transcript string or fail with source context."""

    result = _string(value)
    if result is None:
        raise TranscriptParseError(f"{path}: structured call missing {field_name}")
    return result


__all__ = [
    "AgentToolUsageEvent",
    "ToolSurfaceMatcher",
    "ToolUsageImportSummary",
    "ToolUsageReport",
    "TranscriptParseError",
    "build_usage_report",
    "import_transcripts",
    "parse_claude_transcript",
    "parse_codex_transcript",
    "persist_usage_events",
]
