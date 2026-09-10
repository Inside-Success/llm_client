"""Import provider usage JSON into the shared compute-observability ledger."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from llm_client import io_log
from llm_client.cli.common import get_db_path
from llm_client.observability.compute_observability import (
    ComputeObservabilityError,
    ingest_ccusage_daily_json,
    ingest_codexbar_usage_json,
)


def _read_json(path: str) -> object:
    if path == "-":
        return json.load(sys.stdin)
    with Path(path).expanduser().open(encoding="utf-8") as handle:
        return json.load(handle)


def cmd_compute_usage_import(args: argparse.Namespace) -> None:
    """Import one machine-readable provider report."""

    payload = _read_json(args.input)
    io_log.configure(db_path=Path(args.db).expanduser(), enabled=True)
    if args.source == "ccusage":
        if not isinstance(payload, dict):
            raise ComputeObservabilityError("ccusage input must be a JSON object")
        snapshots = ingest_ccusage_daily_json(
            payload,
            machine_id=args.machine_id,
            account_fingerprint=args.account_fingerprint,
            billing_mode=args.billing_mode,
            source_version=args.source_version,
        )
    else:
        snapshots = ingest_codexbar_usage_json(
            payload,
            machine_id=args.machine_id,
            account_fingerprint=args.account_fingerprint,
            source_version=args.source_version,
        )
    print(
        json.dumps(
            {
                "source": args.source,
                "snapshots": len(snapshots),
                "snapshot_ids": [snapshot.snapshot_id for snapshot in snapshots],
            },
            indent=2,
        )
    )


def register_parser(subparsers: Any) -> None:
    """Register ``compute-usage import``."""

    parser = subparsers.add_parser(
        "compute-usage",
        help="Import provider usage/quota JSON into compute observability",
    )
    commands = parser.add_subparsers(dest="compute_usage_command")
    import_parser = commands.add_parser(
        "import",
        help="Import one ccusage or CodexBar JSON report",
    )
    import_parser.add_argument("--source", choices=["ccusage", "codexbar"], required=True)
    import_parser.add_argument("--input", default="-", help="JSON file path or - for stdin")
    import_parser.add_argument("--machine-id", required=True)
    import_parser.add_argument("--account-fingerprint", required=True)
    import_parser.add_argument(
        "--billing-mode",
        choices=["subscription", "api", "local_gpu", "unknown"],
        default="subscription",
    )
    import_parser.add_argument("--source-version", required=True)
    import_parser.add_argument(
        "--db",
        default=str(get_db_path()),
        help="SQLite path (default: LLM_CLIENT_DB_PATH or shared observability DB)",
    )
    import_parser.set_defaults(handler=cmd_compute_usage_import)


__all__ = ["cmd_compute_usage_import", "register_parser"]
