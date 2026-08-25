"""llm_client observability workbench backend.

Serves read-only queries over LLM_CLIENT_DB_PATH (default:
~/projects/data/llm_observability.db) and LLM_CLIENT_RATE_LIMIT_STATE_PATH
(default: ~/projects/data/llm_rate_limit_state.sqlite3) -- the same env vars
io_log.py and utils/rate_limit.py already honor.

Start: cd workbench/backend && uvicorn server:app --host 0.0.0.0 --port 5203 --reload
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

OBS_DB = Path(
    os.environ.get("LLM_CLIENT_DB_PATH", str(Path.home() / "projects/data/llm_observability.db"))
)
LIMIT_DB = Path(
    os.environ.get(
        "LLM_CLIENT_RATE_LIMIT_STATE_PATH",
        str(Path.home() / "projects/data/llm_rate_limit_state.sqlite3"),
    )
)

app = FastAPI(title="llm_client Observability")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def obs_con() -> sqlite3.Connection:
    """Open observability DB in read-only mode."""
    return sqlite3.connect(f"file:{OBS_DB}?mode=ro", uri=True, check_same_thread=False)


def limit_con() -> sqlite3.Connection:
    """Open rate-limit state DB in read-only mode."""
    return sqlite3.connect(f"file:{LIMIT_DB}?mode=ro", uri=True, check_same_thread=False)


@app.get("/api/health")
def health() -> dict:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/api/cost/daily")
def cost_daily(days: int = Query(default=30, ge=1, le=365)) -> list[dict]:
    """Daily cost + call count for the last N days."""
    con = obs_con()
    try:
        rows = con.execute(
            f"""
            SELECT DATE(timestamp) as day,
                   ROUND(SUM(COALESCE(marginal_cost, cost)), 4) as cost,
                   COUNT(*) as calls
            FROM llm_calls
            WHERE timestamp > datetime('now', '-{days} days')
              AND task != 'test'
            GROUP BY DATE(timestamp)
            ORDER BY day
            """,
        ).fetchall()
        return [{"day": r[0], "cost": r[1] or 0.0, "calls": r[2]} for r in rows]
    finally:
        con.close()


@app.get("/api/cost/by-project")
def cost_by_project(days: int = Query(default=7, ge=1, le=365)) -> list[dict]:
    """Cost, call count, and avg latency by project for the last N days."""
    con = obs_con()
    try:
        rows = con.execute(
            f"""
            SELECT project,
                   COUNT(*) as calls,
                   ROUND(SUM(COALESCE(marginal_cost, cost)), 4) as cost,
                   ROUND(AVG(latency_s), 2) as avg_latency_s
            FROM llm_calls
            WHERE timestamp > datetime('now', '-{days} days')
              AND project IS NOT NULL AND project != ''
              AND task != 'test'
            GROUP BY project
            ORDER BY cost DESC
            LIMIT 20
            """,
        ).fetchall()
        return [
            {"project": r[0], "calls": r[1], "cost": r[2] or 0.0, "avg_latency_s": r[3]}
            for r in rows
        ]
    finally:
        con.close()


@app.get("/api/cost/by-model")
def cost_by_model(days: int = Query(default=7, ge=1, le=365)) -> list[dict]:
    """Cost, call count, and avg latency by model for the last N days."""
    con = obs_con()
    try:
        rows = con.execute(
            f"""
            SELECT model,
                   COUNT(*) as calls,
                   ROUND(SUM(COALESCE(marginal_cost, cost)), 4) as cost,
                   ROUND(AVG(latency_s), 2) as avg_latency_s
            FROM llm_calls
            WHERE timestamp > datetime('now', '-{days} days')
              AND model IS NOT NULL AND model != ''
              AND task != 'test'
            GROUP BY model
            ORDER BY cost DESC
            LIMIT 20
            """,
        ).fetchall()
        return [
            {"model": r[0], "calls": r[1], "cost": r[2] or 0.0, "avg_latency_s": r[3]}
            for r in rows
        ]
    finally:
        con.close()


@app.get("/api/calls/recent")
def calls_recent(
    limit: int = Query(default=100, ge=1, le=500),
    project: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    has_error: bool = Query(default=False),
) -> list[dict]:
    """Recent LLM calls with optional filters."""
    con = obs_con()
    try:
        clauses: list[str] = ["task != 'test'"]
        params: list = []

        if project:
            clauses.append("project = ?")
            params.append(project)
        if model:
            clauses.append("model = ?")
            params.append(model)
        if has_error:
            clauses.append("error IS NOT NULL")

        where = " AND ".join(clauses)
        params.append(limit)

        rows = con.execute(
            f"""
            SELECT id, timestamp, project, model, task,
                   total_tokens, COALESCE(marginal_cost, cost) as cost,
                   ROUND(latency_s, 2) as latency_s,
                   finish_reason, error_type, trace_id, error
            FROM llm_calls
            WHERE {where}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [
            {
                "id": r[0],
                "timestamp": r[1],
                "project": r[2],
                "model": r[3],
                "task": r[4],
                "total_tokens": r[5],
                "cost": r[6],
                "latency_s": r[7],
                "finish_reason": r[8],
                "error_type": r[9],
                "trace_id": r[10],
                "error": r[11],
            }
            for r in rows
        ]
    finally:
        con.close()


@app.get("/api/provider-health")
def provider_health() -> list[dict]:
    """Current provider cooldown state."""
    now = time.time()
    con = limit_con()
    try:
        rows = con.execute(
            "SELECT provider, cooldown_until, source, updated_at FROM provider_cooldowns"
        ).fetchall()
    finally:
        con.close()

    result: list[dict] = []
    for provider, cooldown_until, source, updated_at in rows:
        remaining = max(0.0, float(cooldown_until) - now)
        result.append(
            {
                "provider": provider,
                "cooldown_remaining_s": round(remaining, 1),
                "quota_exhausted": remaining > 300,  # >5 min = daily quota hit
                "source": source,
            }
        )

    # Ensure known providers appear even if they have no cooldown row
    known = {"openai", "google", "anthropic", "openrouter"}
    present = {r["provider"] for r in result}
    for p in sorted(known - present):
        result.append(
            {
                "provider": p,
                "cooldown_remaining_s": 0.0,
                "quota_exhausted": False,
                "source": None,
            }
        )

    return sorted(result, key=lambda r: r["provider"])
