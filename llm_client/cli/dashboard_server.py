"""Loopback-only browser view for the local cost dashboard."""

from __future__ import annotations

import html
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta, timezone
from typing import Any

import llm_client.io_log as _io_log


def _open_read_only_db() -> sqlite3.Connection:
    """Open the shared ledger without migrations or writer locks."""

    uri = f"{_io_log._db_path.resolve().as_uri()}?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=3.0)
    db.execute("PRAGMA busy_timeout = 3000")
    return db


def _rollup_window(db: sqlite3.Connection, hours: int, budget: float | None) -> dict[str, Any]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(minute=0, second=0, microsecond=0).isoformat()
    calls, cost, unpriced = db.execute(
        """SELECT COALESCE(SUM(call_count), 0), COALESCE(SUM(total_cost), 0),
                  COALESCE(SUM(unpriced_call_count), 0)
           FROM dashboard_spend_hourly WHERE bucket_start >= ?""", (cutoff,)
    ).fetchone()
    top = db.execute(
        """SELECT project, model, SUM(total_cost) FROM dashboard_spend_hourly
           WHERE bucket_start >= ? GROUP BY project, model ORDER BY 3 DESC LIMIT 1""", (cutoff,)
    ).fetchone()
    data = {"hours": hours, "calls": calls, "cost": cost, "rate_per_hour": cost / hours,
            "unpriced_calls": unpriced, "top_route": None if top is None else {"project": top[0], "model": top[1], "cost": top[2]}}
    if budget is not None:
        if budget <= 0:
            raise ValueError("dashboard budgets must be positive USD values")
        data.update(budget=budget, budget_ratio=cost / budget, alert=cost >= budget * 0.8)
    return data


def _data(hourly_budget: float | None, daily_budget: float | None, granularity: str = "hour") -> dict[str, Any]:
    if granularity not in {"hour", "day"}:
        raise ValueError("granularity must be hour or day")
    db = _open_read_only_db()
    try:
        bucket = "%Y-%m-%d %H:00" if granularity == "hour" else "%Y-%m-%d"
        hours = 72 if granularity == "hour" else 30 * 24
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        series = db.execute(f"SELECT strftime('{bucket}', bucket_start), COALESCE(SUM(total_cost),0) FROM dashboard_spend_hourly WHERE bucket_start >= ? GROUP BY 1 ORDER BY 1", (cutoff,)).fetchall()
        projects = db.execute("SELECT project, COALESCE(SUM(total_cost),0) FROM dashboard_spend_hourly WHERE bucket_start >= ? GROUP BY 1 ORDER BY 2 DESC LIMIT 12", (cutoff,)).fetchall()
        models = db.execute("SELECT model, COALESCE(SUM(total_cost),0) FROM dashboard_spend_hourly WHERE bucket_start >= ? GROUP BY 1 ORDER BY 2 DESC LIMIT 12", (cutoff,)).fetchall()
        return {"last_hour": _rollup_window(db, 1, hourly_budget), "last_day": _rollup_window(db, 24, daily_budget), "granularity": granularity, "series": series, "projects": projects, "models": models}
    finally:
        db.close()


def _page(data: dict[str, Any]) -> str:
    cards = []
    for label, item in (("Last hour", data["last_hour"]), ("Last 24 hours", data["last_day"])):
        top = item["top_route"] or {"project": "-", "model": "-", "cost": 0}
        alert = "<p class='alert'>ALERT: ≥80% configured budget</p>" if item.get("alert") else ""
        cards.append(f"<section><h2>{label}</h2><strong>${item['cost']:.4f}</strong><p>${item['rate_per_hour']:.4f}/hour · {item['calls']} calls · unpriced {item['unpriced_calls']}</p><p>Top: {html.escape(str(top['project']))} / {html.escape(str(top['model']))} (${top['cost']:.4f})</p>{alert}</section>")
    return "<!doctype html><meta http-equiv='refresh' content='30'><title>LLM Cost Dashboard</title><style>body{background:#10131a;color:#e8edf5;font:16px system-ui;margin:3rem;max-width:1100px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem}section{background:#191f2b;border:1px solid #344054;border-radius:12px;padding:1.25rem}strong{font-size:2rem;color:#82d6ff}.alert{color:#ffb4a9;font-weight:bold}small,a{color:#aab4c4}.chart{display:block;width:100%;height:240px;background:#191f2b;border-radius:12px}.bar{fill:#82d6ff}.label{fill:#aab4c4;font-size:11px}.ranked{list-style:none;margin:0;padding:1rem;background:#191f2b;border-radius:12px}.ranked li{display:grid;grid-template-columns:minmax(180px,35%) 1fr auto;gap:.6rem;align-items:center;margin:.45rem 0}.ranked .name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ranked .track{height:1rem;background:#344054}.ranked .fill{height:100%;background:#82d6ff}.ranked .value{font-variant-numeric:tabular-nums;color:#aab4c4}</style><h1>LLM Cost Dashboard</h1><small>Local ledger · refreshes every 30 seconds · <a href='/?granularity=hour'>hourly</a> · <a href='/?granularity=day'>daily</a> · <a href='/api/dashboard'>JSON</a></small><main>" + "".join(cards) + "</main><h2>Spend over time (" + data["granularity"] + ")</h2><svg id='series' class='chart' viewBox='0 0 1000 240' preserveAspectRatio='none'></svg><h2>Project breakdown</h2><ol id='projects' class='ranked'></ol><h2>Model breakdown</h2><ol id='models' class='ranked'></ol><script>const d=" + json.dumps(data) + ";function bars(id,a){let s=document.getElementById(id),w=1000,h=240,m=Math.max(...a.map(x=>x[1]),.01),step=Math.ceil(a.length/8);a.forEach((x,i)=>{let bw=w/a.length*.72,bh=x[1]/m*(h-35),px=i*w/a.length+(w/a.length-bw)/2,label=i%step?'':x[0].slice(5,16);s.innerHTML+=`<rect class=bar x='${px}' y='${h-22-bh}' width='${bw}' height='${bh}'/><text class=label x='${px}' y='${h-6}'>${label}</text>`})}function ranked(id,a){let s=document.getElementById(id),m=Math.max(...a.map(x=>x[1]),.01);a.forEach(x=>{let li=document.createElement('li'),name=document.createElement('span'),track=document.createElement('span'),fill=document.createElement('span'),value=document.createElement('span');name.className='name';name.textContent=x[0];track.className='track';fill.className='fill';fill.style.width=`${100*x[1]/m}%`;value.className='value';value.textContent=`$${x[1].toFixed(4)}`;track.append(fill);li.append(name,track,value);s.append(li)})}bars('series',d.series);ranked('projects',d.projects);ranked('models',d.models)</script>"


def serve(*, host: str, port: int, hourly_budget: float | None, daily_budget: float | None) -> None:
    # Verify the ledger is readable before binding the browser endpoint.
    _data(hourly_budget, daily_budget)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path, _, query = self.path.partition("?")
            granularity = "day" if "granularity=day" in query else "hour"
            data = _data(hourly_budget, daily_budget, granularity)
            if path == "/api/dashboard":
                body = json.dumps(data, indent=2).encode()
                content_type = "application/json"
            elif path == "/":
                body = _page(data).encode()
                content_type = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200); self.send_header("Content-Type", content_type); self.end_headers(); self.wfile.write(body)
        def log_message(self, _format: str, *_args: Any) -> None: return
    server = HTTPServer((host, port), Handler)
    print(f"LLM cost dashboard: http://{host}:{port}", flush=True)
    server.serve_forever()
