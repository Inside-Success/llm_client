"""Contract and negative-control tests for transcript-backed tool usage."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from llm_client.observability.agent_tool_usage import (
    TranscriptParseError,
    ToolSurfaceMatcher,
    build_usage_report,
    import_transcripts,
    parse_claude_transcript,
    parse_codex_transcript,
)


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    """Write deterministic JSONL fixtures without copying real transcripts."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def _matcher() -> ToolSurfaceMatcher:
    """Return the codebase-memory matcher used across fixture cases."""

    return ToolSurfaceMatcher(
        surface="codebase-memory",
        aliases=("codebase-memory", "codebase_memory_mcp"),
    )


def _codex_old_fixture(path: Path) -> None:
    """Create an old response-item call/output transcript."""

    _write_jsonl(
        path,
        [
            {
                "timestamp": "2026-07-01T10:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": "SECRET_CODEX_OLD_SESSION",
                    "cwd": "/private/SECRET_PATH/project-meta",
                },
            },
            {
                "timestamp": "2026-07-01T10:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "mcp__codebase_memory_mcp__search_graph",
                    "arguments": '{"q":"SECRET_QUERY"}',
                    "call_id": "call-old",
                },
            },
            {
                "timestamp": "2026-07-01T10:00:02Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call-old",
                    "output": '{"result":"SECRET_RESULT"}',
                },
            },
        ],
    )


def _codex_current_fixture(path: Path) -> None:
    """Create current MCP-end success/error events and one missing output."""

    _write_jsonl(
        path,
        [
            {
                "timestamp": "2026-07-02T10:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": "SECRET_CODEX_CURRENT_SESSION",
                    "cwd": "/private/SECRET_PATH/llm_client/worktrees/branch",
                },
            },
            {
                "timestamp": "2026-07-02T10:00:00.500Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "namespace": "mcp__codebase_memory_mcp",
                    "name": "list_projects",
                    "arguments": "{}",
                    "call_id": "call-current-ok",
                },
            },
            {
                "timestamp": "2026-07-02T10:00:01Z",
                "type": "event_msg",
                "payload": {
                    "type": "mcp_tool_call_end",
                    "call_id": "call-current-ok",
                    "invocation": {
                        "server": "codebase-memory-mcp",
                        "tool": "list_projects",
                        "arguments": {"secret": "SECRET_QUERY"},
                    },
                    "result": {
                        "Ok": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": '{"results":[{"error":"SECRET_RESULT"}]}',
                                }
                            ]
                        }
                    },
                    "duration": {"secs": 0, "nanos": 250_000_000},
                },
            },
            {
                "timestamp": "2026-07-02T10:00:02Z",
                "type": "event_msg",
                "payload": {
                    "type": "mcp_tool_call_end",
                    "call_id": "call-current-error",
                    "invocation": {
                        "server": "codebase-memory-mcp",
                        "tool": "index_status",
                        "arguments": {},
                    },
                    "result": {"Err": "SECRET_ERROR"},
                    "duration": {"secs": 1, "nanos": 0},
                },
            },
            {
                "timestamp": "2026-07-02T10:00:03Z",
                "type": "event_msg",
                "payload": {
                    "type": "mcp_tool_call_end",
                    "call_id": "call-current-app-error",
                    "invocation": {
                        "server": "codebase-memory-mcp",
                        "tool": "search_code",
                        "arguments": {},
                    },
                    "result": {
                        "Ok": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": '{"error":"SECRET_ERROR"}',
                                }
                            ]
                        }
                    },
                },
            },
            {
                "timestamp": "2026-07-02T10:00:04Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "namespace": "mcp__codebase_memory_mcp",
                    "name": "trace_call_path",
                    "arguments": '{"function_name":"SECRET_QUERY"}',
                    "call_id": "call-missing",
                },
            },
        ],
    )


def _negative_control_fixture(path: Path) -> None:
    """Create names and definitions that must never count as invocations."""

    _write_jsonl(
        path,
        [
            {
                "timestamp": "2026-07-03T10:00:00Z",
                "type": "session_meta",
                "payload": {"id": "negative", "cwd": "/tmp/negative"},
            },
            {
                "timestamp": "2026-07-03T10:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "content": "Mention mcp__codebase_memory_mcp__search_graph only.",
                },
            },
            {
                "timestamp": "2026-07-03T10:00:02Z",
                "type": "event_msg",
                "payload": {
                    "type": "tool_definition",
                    "name": "mcp__codebase_memory_mcp__search_graph",
                },
            },
        ],
    )


def _claude_fixture(path: Path) -> None:
    """Create a Claude tool-use/result error transcript."""

    _write_jsonl(
        path,
        [
            {
                "timestamp": "2026-07-04T10:00:00Z",
                "type": "assistant",
                "sessionId": "SECRET_CLAUDE_SESSION",
                "cwd": "/private/SECRET_PATH/project-meta",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu-1",
                            "name": "mcp__codebase_memory_mcp__search_graph",
                            "input": {"q": "SECRET_QUERY"},
                        }
                    ]
                },
            },
            {
                "timestamp": "2026-07-04T10:00:01Z",
                "type": "user",
                "sessionId": "SECRET_CLAUDE_SESSION",
                "cwd": "/private/SECRET_PATH/project-meta",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu-1",
                            "is_error": True,
                            "content": "SECRET_ERROR",
                        }
                    ]
                },
            },
        ],
    )


def test_parsers_accept_supported_structured_formats_and_reject_mentions(
    tmp_path: Path,
) -> None:
    """Count only structured calls across old/new Codex and Claude formats."""

    old_path = tmp_path / "codex" / "old.jsonl"
    current_path = tmp_path / "codex" / "current.jsonl"
    negative_path = tmp_path / "codex" / "negative.jsonl"
    claude_path = tmp_path / "claude" / "session.jsonl"
    _codex_old_fixture(old_path)
    _codex_current_fixture(current_path)
    _negative_control_fixture(negative_path)
    _claude_fixture(claude_path)

    old_events = parse_codex_transcript(old_path, _matcher())
    current_events = parse_codex_transcript(current_path, _matcher())
    negative_events = parse_codex_transcript(negative_path, _matcher())
    claude_events = parse_claude_transcript(claude_path, _matcher())

    assert [(event.operation, event.outcome) for event in old_events] == [
        ("search_graph", "returned")
    ]
    assert [(event.operation, event.outcome) for event in current_events] == [
        ("list_projects", "returned"),
        ("index_status", "transport_error"),
        ("search_code", "application_error"),
        ("trace_call_path", "missing"),
    ]
    assert negative_events == []
    assert [(event.operation, event.outcome) for event in claude_events] == [
        ("search_graph", "transport_error")
    ]
    assert current_events[0].duration_ms == 250
    assert current_events[1].duration_ms == 1000


def test_import_is_private_idempotent_and_reportable(tmp_path: Path) -> None:
    """Persist hashes and aggregates without retaining any fixture secrets."""

    codex_root = tmp_path / "codex"
    claude_root = tmp_path / "claude"
    _codex_old_fixture(codex_root / "old.jsonl")
    _codex_current_fixture(codex_root / "current.jsonl")
    _negative_control_fixture(codex_root / "negative.jsonl")
    _claude_fixture(claude_root / "session.jsonl")
    db_path = tmp_path / "usage.sqlite3"

    first = import_transcripts(
        codex_roots=(codex_root,),
        claude_roots=(claude_root,),
        db_path=db_path,
        matcher=_matcher(),
    )
    second = import_transcripts(
        codex_roots=(codex_root,),
        claude_roots=(claude_root,),
        db_path=db_path,
        matcher=_matcher(),
    )

    assert first.files_scanned == 4
    assert first.files_skipped == 0
    assert first.coverage_complete is True
    assert first.parse_error_file_hashes == ()
    assert first.sessions_with_calls == 3
    assert first.events_found == 6
    assert first.inserted == 6
    assert first.duplicates == 0
    assert second.inserted == 0
    assert second.duplicates == 6

    db_bytes = db_path.read_bytes()
    for forbidden in (
        b"SECRET_QUERY",
        b"SECRET_RESULT",
        b"SECRET_ERROR",
        b"SECRET_PATH",
        b"SECRET_CODEX_OLD_SESSION",
        b"SECRET_CODEX_CURRENT_SESSION",
        b"SECRET_CLAUDE_SESSION",
    ):
        assert forbidden not in db_bytes

    with sqlite3.connect(db_path) as db:
        columns = {
            row[1] for row in db.execute("PRAGMA table_info(agent_tool_usage)")
        }
    assert columns.isdisjoint(
        {"arguments", "result", "transcript_text", "cwd", "session_id", "source_path"}
    )

    report = build_usage_report(
        db_path=db_path,
        tool_surface="codebase-memory",
    )
    assert report.total_calls == 6
    assert report.sessions == 3
    assert report.projects == 2
    assert report.by_outcome == {
        "application_error": 1,
        "missing": 1,
        "returned": 2,
        "transport_error": 2,
    }
    assert report.by_client == {"claude": 1, "codex": 5}
    assert report.by_month == {"2026-07": 6}
    assert report.duration_samples == 2
    assert report.duration_p50_ms == 250
    assert report.duration_p95_ms == 1000
    assert report.transcript_coverage_complete is True
    assert report.import_files_scanned == 4
    assert report.import_files_skipped == 0
    assert report.coverage_note == "All scanned transcript files parsed successfully."
    assert report.helpfulness_status == "unmeasured"
    assert report.helpfulness_rated_calls == 0
    assert "does not establish helpfulness" in report.helpfulness_note


def test_malformed_transcript_fails_with_file_and_line(tmp_path: Path) -> None:
    """Surface format corruption instead of silently falling back to text counts."""

    path = tmp_path / "broken.jsonl"
    path.write_text('{"type":"session_meta"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(TranscriptParseError, match=r"broken\.jsonl:2"):
        parse_codex_transcript(path, _matcher())

    db_path = tmp_path / "partial.sqlite3"
    summary = import_transcripts(
        codex_roots=(path,),
        claude_roots=(),
        db_path=db_path,
        matcher=_matcher(),
        skip_malformed_files=True,
    )
    assert summary.files_scanned == 1
    assert summary.files_skipped == 1
    assert summary.coverage_complete is False
    assert len(summary.parse_error_file_hashes) == 1
    assert summary.events_found == 0
    report = build_usage_report(db_path=db_path, tool_surface="codebase-memory")
    assert report.transcript_coverage_complete is False
    assert report.import_files_scanned == 1
    assert report.import_files_skipped == 1
    assert "Incomplete transcript coverage" in report.coverage_note
