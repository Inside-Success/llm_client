"""Import and report privacy-preserving agent tool-usage evidence."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from llm_client.cli.common import get_db_path
from llm_client.observability.agent_tool_usage import (
    ToolSurfaceMatcher,
    build_usage_report,
    import_transcripts,
)


def cmd_tool_usage_import(args: argparse.Namespace) -> None:
    """Import structured calls from configured client transcript roots."""

    matcher = ToolSurfaceMatcher(
        surface=args.surface,
        aliases=tuple(args.alias or ()),
    )
    codex_roots: tuple[Path, ...] = ()
    claude_roots: tuple[Path, ...] = ()
    if args.client in {"both", "codex"}:
        codex_roots = tuple(
            Path(value).expanduser()
            for value in (args.codex_root or [Path.home() / ".codex" / "sessions"])
        )
    if args.client in {"both", "claude"}:
        claude_roots = tuple(
            Path(value).expanduser()
            for value in (args.claude_root or [Path.home() / ".claude" / "projects"])
        )
    summary = import_transcripts(
        codex_roots=codex_roots,
        claude_roots=claude_roots,
        db_path=Path(args.db).expanduser(),
        matcher=matcher,
        skip_malformed_files=args.skip_malformed_files,
    )
    print(summary.model_dump_json(indent=2))


def cmd_tool_usage_report(args: argparse.Namespace) -> None:
    """Print aggregate usage evidence for one logical tool surface."""

    report = build_usage_report(
        db_path=Path(args.db).expanduser(),
        tool_surface=args.surface,
    )
    if args.format == "json":
        print(report.model_dump_json(indent=2))
        return

    print(f"Tool usage: {report.tool_surface}")
    print(
        f"Calls: {report.total_calls}  Sessions: {report.sessions}  "
        f"Projects: {report.projects}"
    )
    print(f"Outcomes: {_format_counts(report.by_outcome)}")
    print(f"Clients: {_format_counts(report.by_client)}")
    print(f"Operations: {_format_counts(report.by_operation)}")
    print(f"Months: {_format_counts(report.by_month)}")
    print(f"Transcript coverage: {report.coverage_note}")
    if report.duration_samples:
        print(
            f"Latency samples: {report.duration_samples}  "
            f"p50={report.duration_p50_ms}ms  p95={report.duration_p95_ms}ms"
        )
    else:
        print("Latency samples: 0")
    print(f"Helpfulness: {report.helpfulness_status} — {report.helpfulness_note}")


def _format_counts(counts: dict[str, int]) -> str:
    """Render sorted count mappings for the compact table output."""

    if not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))


def register_parser(subparsers: Any) -> None:
    """Register the `tool-usage import|report` CLI surface."""

    parser = subparsers.add_parser(
        "tool-usage",
        help="Import/report structured agent tool calls without transcript content",
    )
    commands = parser.add_subparsers(dest="tool_usage_command")

    import_parser = commands.add_parser(
        "import",
        help="Import actual structured Codex/Claude calls into the usage ledger",
    )
    import_parser.add_argument(
        "--surface",
        required=True,
        help="Stable logical tool name, for example codebase-memory",
    )
    import_parser.add_argument(
        "--alias",
        action="append",
        help="Additional server/namespace/name fragment; repeat as needed",
    )
    import_parser.add_argument(
        "--client",
        choices=["both", "codex", "claude"],
        default="both",
        help="Transcript client roots to scan (default: both)",
    )
    import_parser.add_argument(
        "--codex-root",
        action="append",
        help="Codex JSONL file/directory; repeatable (default: ~/.codex/sessions)",
    )
    import_parser.add_argument(
        "--claude-root",
        action="append",
        help="Claude JSONL file/directory; repeatable (default: ~/.claude/projects)",
    )
    import_parser.add_argument(
        "--skip-malformed-files",
        action="store_true",
        help=(
            "Explicitly exclude whole malformed files and report hashed exclusions; "
            "default behavior fails loud"
        ),
    )
    import_parser.add_argument(
        "--db",
        default=str(get_db_path()),
        help="SQLite ledger path (default: LLM_CLIENT_DB_PATH or shared observability DB)",
    )
    import_parser.set_defaults(handler=cmd_tool_usage_import)

    report_parser = commands.add_parser(
        "report",
        help="Report frequency and transport outcomes; helpfulness remains unmeasured",
    )
    report_parser.add_argument(
        "--surface",
        required=True,
        help="Stable logical tool name used during import",
    )
    report_parser.add_argument(
        "--db",
        default=str(get_db_path()),
        help="SQLite ledger path (default: LLM_CLIENT_DB_PATH or shared observability DB)",
    )
    report_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format",
    )
    report_parser.set_defaults(handler=cmd_tool_usage_report)


__all__ = ["cmd_tool_usage_import", "cmd_tool_usage_report", "register_parser"]
