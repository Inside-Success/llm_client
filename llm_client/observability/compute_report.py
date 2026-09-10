"""Read-only reports over compute usage and verified task outcomes."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def build_compute_report(db_path: Path) -> list[dict[str, Any]]:
    """Return provider/model efficiency rows without assigning subscription dollars."""

    with sqlite3.connect(str(db_path)) as db:
        rows = db.execute(
            """
            SELECT
                u.provider,
                u.model,
                u.account_fingerprint,
                u.billing_mode,
                u.snapshot_id,
                u.api_equivalent_cost_usd,
                u.actual_marginal_cost_usd,
                json_extract(u.quota_windows_json, '$[0].used_percent'),
                a.attempt_id,
                a.task_id,
                a.started_at,
                a.ended_at,
                o.tests_status,
                o.ci_status,
                o.static_analysis_status,
                o.coordinator_decision,
                o.merged,
                o.reverted,
                o.regressed,
                o.weighted_shipped_value,
                o.critical_path_seconds,
                o.human_intervention_count,
                o.human_intervention_minutes
            FROM usage_snapshots u
            LEFT JOIN task_compute_links l ON l.snapshot_id = u.snapshot_id
            LEFT JOIN task_attempt_receipts a ON a.attempt_id = l.attempt_id
            LEFT JOIN outcome_receipts o
              ON o.task_id = a.task_id AND o.attempt_id = a.attempt_id
            ORDER BY u.provider, u.model, u.account_fingerprint, u.snapshot_id
            """
        ).fetchall()

    groups: dict[tuple[str, str | None, str, str], dict[str, Any]] = {}
    seen_attempts: dict[tuple[str, str | None, str, str], set[str]] = {}
    for row in rows:
        (
            provider,
            model,
            account,
            billing_mode,
            _snapshot_id,
            api_cost,
            actual_cost,
            used_percent,
            attempt_id,
            _task_id,
            _started_at,
            _ended_at,
            tests_status,
            ci_status,
            static_status,
            decision,
            merged,
            reverted,
            regressed,
            shipped_value,
            critical_path,
            intervention_count,
            intervention_minutes,
        ) = row
        key = (provider, model, account, billing_mode)
        group = groups.setdefault(
            key,
            {
                "provider": provider,
                "model": model,
                "account_fingerprint": account,
                "billing_mode": billing_mode,
                "snapshot_count": 0,
                "quota_used_percent": None,
                "api_equivalent_cost_usd": 0.0,
                "actual_marginal_cost_usd": 0.0,
                "actual_cost_coverage": 0,
                "attempt_count": 0,
                "outcome_count": 0,
                "verified_accepted_tasks": 0,
                "weighted_shipped_value": 0.0,
                "critical_path_seconds": 0.0,
                "human_intervention_count": 0,
                "human_intervention_minutes": 0.0,
            },
        )
        group["snapshot_count"] += 1
        if used_percent is not None:
            group["quota_used_percent"] = float(used_percent)
        if api_cost is not None:
            group["api_equivalent_cost_usd"] += float(api_cost)
        if actual_cost is not None:
            group["actual_marginal_cost_usd"] += float(actual_cost)
            group["actual_cost_coverage"] += 1
        if attempt_id is None or attempt_id in seen_attempts.setdefault(key, set()):
            continue
        seen_attempts[key].add(attempt_id)
        group["attempt_count"] += 1
        if decision is None:
            continue
        group["outcome_count"] += 1
        if (
            decision == "accepted"
            and tests_status == "pass"
            and ci_status == "pass"
            and static_status == "pass"
            and merged == 1
            and reverted != 1
            and regressed != 1
        ):
            group["verified_accepted_tasks"] += 1
            group["weighted_shipped_value"] += float(shipped_value or 0.0)
        group["critical_path_seconds"] += float(critical_path or 0.0)
        group["human_intervention_count"] += int(intervention_count or 0)
        group["human_intervention_minutes"] += float(intervention_minutes or 0.0)

    for group in groups.values():
        actual = (
            group["actual_marginal_cost_usd"]
            if group["actual_cost_coverage"]
            else None
        )
        group["actual_marginal_cost_usd"] = actual
        value = group["weighted_shipped_value"]
        hours = group["critical_path_seconds"] / 3600.0
        group["success_rate"] = (
            group["verified_accepted_tasks"] / group["attempt_count"]
            if group["attempt_count"]
            else None
        )
        group["shipped_value_per_actual_dollar"] = value / actual if actual else None
        group["shipped_value_per_critical_path_hour"] = value / hours if hours else None
        group["shipped_value_per_dollar_critical_path_hour"] = (
            value / (actual * hours) if actual and hours else None
        )
    return list(groups.values())
