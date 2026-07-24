"""Read-only operator dashboard for recent LLM spend."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from llm_client.cli.common import connect, format_cost


def _window(db: Any, hours: int) -> dict[str, Any]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    row = db.execute(
        """SELECT COUNT(*), COALESCE(SUM(COALESCE(marginal_cost, cost)), 0),
                  SUM(CASE WHEN cost_source IS NULL OR cost_source IN ('unspecified', 'unavailable') THEN 1 ELSE 0 END)
           FROM llm_calls WHERE timestamp >= ? AND error IS NULL""",
        (cutoff,),
    ).fetchone()
    top = db.execute(
        """SELECT project, model, COALESCE(SUM(COALESCE(marginal_cost, cost)), 0)
           FROM llm_calls WHERE timestamp >= ? AND error IS NULL
           GROUP BY project, model ORDER BY 3 DESC LIMIT 1""",
        (cutoff,),
    ).fetchone()
    return {
        "hours": hours, "calls": row[0], "cost": row[1], "rate_per_hour": row[1] / hours,
        "unpriced_calls": row[2],
        "top_route": None if top is None else {"project": top[0], "model": top[1], "cost": top[2]},
    }


def cmd_dashboard(args: argparse.Namespace) -> None:
    db = connect()
    data = {"generated_at": datetime.now(timezone.utc).isoformat(), "last_hour": _window(db, 1), "last_day": _window(db, 24)}
    db.close()
    if args.format == "json":
        print(json.dumps(data, indent=2))
        return
    print("LLM cost dashboard")
    for label, window in (("Last hour", data["last_hour"]), ("Last 24 hours", data["last_day"])):
        top = window["top_route"]
        top_text = "none" if top is None else f"{top['project']}/{top['model']} ({format_cost(top['cost'])})"
        print(f"{label}: {format_cost(window['cost'])} across {window['calls']} calls | {format_cost(window['rate_per_hour'])}/hour | unpriced: {window['unpriced_calls']} | top: {top_text}")


def register_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("dashboard", help="Show recent spend rate and accountable route")
    parser.add_argument("--format", choices=["table", "json"], default="table")
    parser.set_defaults(handler=cmd_dashboard)
