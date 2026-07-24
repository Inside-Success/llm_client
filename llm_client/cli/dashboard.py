"""Read-only operator dashboard for recent LLM spend."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import llm_client.io_log as _io_log
from llm_client.cli.common import format_cost


def _window(db: Any, hours: int, budget: float | None = None) -> dict[str, Any]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    row = db.execute(
        """SELECT COUNT(*), COALESCE(SUM(COALESCE(marginal_cost, cost)), 0),
                  SUM(CASE WHEN cost_source IS NULL OR cost_source IN ('unspecified', 'unavailable') THEN 1 ELSE 0 END)
           FROM llm_calls
           WHERE timestamp >= ? AND error IS NULL
             AND (cost_source IS NOT NULL OR billing_mode IS NOT NULL)""",
        (cutoff,),
    ).fetchone()
    top = db.execute(
        """SELECT project, model, COALESCE(SUM(COALESCE(marginal_cost, cost)), 0)
           FROM llm_calls
           WHERE timestamp >= ? AND error IS NULL
             AND (cost_source IS NOT NULL OR billing_mode IS NOT NULL)
           GROUP BY project, model ORDER BY 3 DESC LIMIT 1""",
        (cutoff,),
    ).fetchone()
    result = {
        "hours": hours, "calls": row[0], "cost": row[1], "rate_per_hour": row[1] / hours,
        "unpriced_calls": row[2],
        "top_route": None if top is None else {"project": top[0], "model": top[1], "cost": top[2]},
    }
    if budget is not None:
        if budget <= 0:
            raise ValueError("dashboard budgets must be positive USD values")
        result["budget"] = budget
        result["budget_ratio"] = result["cost"] / budget
        result["alert"] = result["cost"] >= budget * 0.8
    return result


def cmd_dashboard(args: argparse.Namespace) -> None:
    if getattr(args, "serve", False):
        from llm_client.cli.dashboard_server import serve
        serve(host=args.host, port=args.port, hourly_budget=args.hourly_budget, daily_budget=args.daily_budget)
        return
    # Use the observability owner so additive schema migrations run before the
    # dashboard attempts to persist a deduplicated threshold crossing.
    db = _io_log._get_db()
    if getattr(args, "alerts", False):
        rows = db.execute(
            """SELECT period_start, window_hours, budget, observed_cost, created_at
               FROM cost_alerts ORDER BY created_at DESC LIMIT ?""",
            (getattr(args, "alert_limit", 20),),
        ).fetchall()
        data = [
            {"period_start": row[0], "window_hours": row[1], "budget": row[2], "observed_cost": row[3], "created_at": row[4]}
            for row in rows
        ]
        if args.format == "json":
            print(json.dumps({"alerts": data}, indent=2))
        else:
            print("No dashboard alerts." if not data else "\n".join(
                f"{item['created_at']} | {item['window_hours']}h | {format_cost(item['observed_cost'])}/{format_cost(item['budget'])}"
                for item in data
            ))
        return
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "last_hour": _window(db, 1, args.hourly_budget),
        "last_day": _window(db, 24, args.daily_budget),
    }
    now = datetime.now(timezone.utc)
    for window, period_start in (
        (data["last_hour"], now.replace(minute=0, second=0, microsecond=0).isoformat()),
        (data["last_day"], now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()),
    ):
        if window.get("alert"):
            db.execute(
                """INSERT OR IGNORE INTO cost_alerts
                   (period_start, window_hours, budget, observed_cost, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (period_start, window["hours"], window["budget"], window["cost"], now.isoformat()),
            )
    db.commit()
    if args.format == "json":
        print(json.dumps(data, indent=2))
        return
    print("LLM cost dashboard")
    for label, window in (("Last hour", data["last_hour"]), ("Last 24 hours", data["last_day"])):
        top = window["top_route"]
        top_text = "none" if top is None else f"{top['project']}/{top['model']} ({format_cost(top['cost'])})"
        alert = " | ALERT: >=80% of configured budget" if window.get("alert") else ""
        print(f"{label}: {format_cost(window['cost'])} across {window['calls']} calls | {format_cost(window['rate_per_hour'])}/hour | unpriced: {window['unpriced_calls']} | top: {top_text}{alert}")


def register_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("dashboard", help="Show recent spend rate and accountable route")
    parser.add_argument("--format", choices=["table", "json"], default="table")
    parser.add_argument("--hourly-budget", type=float, help="Warn at 80% of this last-hour USD budget")
    parser.add_argument("--daily-budget", type=float, help="Warn at 80% of this last-24-hours USD budget")
    parser.add_argument("--alerts", action="store_true", help="Show persisted threshold crossings")
    parser.add_argument("--alert-limit", type=int, default=20, help="Maximum persisted alerts to show")
    parser.add_argument("--serve", action="store_true", help="Serve a loopback browser dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: loopback only)")
    parser.add_argument("--port", type=int, default=8765, help="Browser dashboard port")
    parser.set_defaults(handler=cmd_dashboard)
