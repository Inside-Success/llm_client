"""Tests for the read-only compute report."""

import sqlite3

from llm_client.observability.compute_report import build_compute_report


def test_report_keeps_subscription_actual_spend_unknown(tmp_path) -> None:
    db_path = tmp_path / "observability.db"
    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE usage_snapshots (
                snapshot_id TEXT PRIMARY KEY, provider TEXT, model TEXT,
                account_fingerprint TEXT, billing_mode TEXT,
                api_equivalent_cost_usd REAL, actual_marginal_cost_usd REAL,
                quota_windows_json TEXT
            );
            CREATE TABLE task_compute_links (snapshot_id TEXT, attempt_id TEXT);
            CREATE TABLE task_attempt_receipts (
                attempt_id TEXT, task_id TEXT, started_at TEXT, ended_at TEXT
            );
            CREATE TABLE outcome_receipts (
                task_id TEXT, attempt_id TEXT, tests_status TEXT, ci_status TEXT,
                static_analysis_status TEXT, coordinator_decision TEXT, merged INTEGER,
                reverted INTEGER, regressed INTEGER, weighted_shipped_value REAL,
                critical_path_seconds REAL, human_intervention_count INTEGER,
                human_intervention_minutes REAL
            );
            INSERT INTO usage_snapshots VALUES
                ('s1', 'codex', 'gpt-5.6-luna', 'unknown', 'subscription', 1.5, NULL, '[]');
            INSERT INTO task_compute_links VALUES ('s1', 'a1');
            INSERT INTO task_attempt_receipts VALUES ('a1', 't1', NULL, NULL);
            INSERT INTO outcome_receipts VALUES
                ('t1', 'a1', 'pass', 'pass', 'pass', 'accepted', 1, 0, 0, 2.0, 3600, 1, 5.0);
            """
        )

    report = build_compute_report(db_path)

    assert report[0]["api_equivalent_cost_usd"] == 1.5
    assert report[0]["actual_marginal_cost_usd"] is None
    assert report[0]["shipped_value_per_actual_dollar"] is None
    assert report[0]["verified_accepted_tasks"] == 1
    assert report[0]["human_intervention_minutes"] == 5.0
