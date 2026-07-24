"""Loopback-only browser view for the local cost dashboard."""

from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timedelta, timezone
from typing import Any

import llm_client.io_log as _io_log
from llm_client.cli.dashboard import _window


def _data(hourly_budget: float | None, daily_budget: float | None, granularity: str = "hour") -> dict[str, Any]:
    db = _io_log._get_db()
    if granularity not in {"hour", "day"}:
        raise ValueError("granularity must be hour or day")
    bucket = "%Y-%m-%d %H:00" if granularity == "hour" else "%Y-%m-%d"
    hours = 72 if granularity == "hour" else 30 * 24
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    where = "timestamp >= ? AND error IS NULL AND (cost_source IS NOT NULL OR billing_mode IS NOT NULL)"
    series = db.execute(f"SELECT strftime('{bucket}', timestamp), COALESCE(SUM(COALESCE(marginal_cost,cost)),0) FROM llm_calls WHERE {where} GROUP BY 1 ORDER BY 1", (cutoff,)).fetchall()
    projects = db.execute(f"SELECT COALESCE(project,'unknown'), COALESCE(SUM(COALESCE(marginal_cost,cost)),0) FROM llm_calls WHERE {where} GROUP BY 1 ORDER BY 2 DESC LIMIT 12", (cutoff,)).fetchall()
    models = db.execute(f"SELECT model, COALESCE(SUM(COALESCE(marginal_cost,cost)),0) FROM llm_calls WHERE {where} GROUP BY 1 ORDER BY 2 DESC LIMIT 12", (cutoff,)).fetchall()
    return {"last_hour": _window(db, 1, hourly_budget), "last_day": _window(db, 24, daily_budget), "granularity": granularity, "series": series, "projects": projects, "models": models}


def _page(data: dict[str, Any]) -> str:
    cards = []
    for label, item in (("Last hour", data["last_hour"]), ("Last 24 hours", data["last_day"])):
        top = item["top_route"] or {"project": "-", "model": "-", "cost": 0}
        alert = "<p class='alert'>ALERT: ≥80% configured budget</p>" if item.get("alert") else ""
        cards.append(f"<section><h2>{label}</h2><strong>${item['cost']:.4f}</strong><p>${item['rate_per_hour']:.4f}/hour · {item['calls']} calls · unpriced {item['unpriced_calls']}</p><p>Top: {html.escape(str(top['project']))} / {html.escape(str(top['model']))} (${top['cost']:.4f})</p>{alert}</section>")
    return "<!doctype html><meta http-equiv='refresh' content='30'><title>LLM Cost Dashboard</title><style>body{background:#10131a;color:#e8edf5;font:16px system-ui;margin:3rem;max-width:1100px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem}section{background:#191f2b;border:1px solid #344054;border-radius:12px;padding:1.25rem}strong{font-size:2rem;color:#82d6ff}.alert{color:#ffb4a9;font-weight:bold}small,a{color:#aab4c4}.chart{width:100%;height:240px;background:#191f2b;border-radius:12px}.bar{fill:#82d6ff}.label{fill:#aab4c4;font-size:11px}</style><h1>LLM Cost Dashboard</h1><small>Local ledger · refreshes every 30 seconds · <a href='/?granularity=hour'>hourly</a> · <a href='/?granularity=day'>daily</a> · <a href='/api/dashboard'>JSON</a></small><main>" + "".join(cards) + "</main><h2>Spend over time (" + data["granularity"] + ")</h2><svg id='series' class='chart'></svg><h2>Project breakdown</h2><svg id='projects' class='chart'></svg><h2>Model breakdown</h2><svg id='models' class='chart'></svg><script>const d=" + json.dumps(data) + ";function bars(id,a){let s=document.getElementById(id),w=s.clientWidth,h=s.clientHeight,m=Math.max(...a.map(x=>x[1]),.01);s.setAttribute('viewBox',`0 0 ${w} ${h}`);a.forEach((x,i)=>{let bw=w/a.length*.72,bh=x[1]/m*(h-35),px=i*w/a.length+(w/a.length-bw)/2;s.innerHTML+=`<rect class=bar x=${px} y=${h-22-bh} width=${bw} height=${bh}/><text class=label x=${px} y=${h-6}>${x[0].slice(-8)}</text>`})}bars('series',d.series);bars('projects',d.projects);bars('models',d.models)</script>"


def serve(*, host: str, port: int, hourly_budget: float | None, daily_budget: float | None) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = self.path.split("?", 1)[-1]
            granularity = "day" if "granularity=day" in query else "hour"
            data = _data(hourly_budget, daily_budget, granularity)
            if self.path == "/api/dashboard":
                body = json.dumps(data, indent=2).encode()
                content_type = "application/json"
            elif self.path == "/":
                body = _page(data).encode()
                content_type = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200); self.send_header("Content-Type", content_type); self.end_headers(); self.wfile.write(body)
        def log_message(self, _format: str, *_args: Any) -> None: return
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"LLM cost dashboard: http://{host}:{port}", flush=True)
    server.serve_forever()
