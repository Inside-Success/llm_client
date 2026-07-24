from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

from llm_client.cli.dashboard import cmd_dashboard


def test_dashboard_json_exposes_rate_and_accountability(capsys) -> None:
    db = MagicMock()
    db.execute.side_effect = [
        MagicMock(fetchone=lambda: (2, 1.0, 1)), MagicMock(fetchone=lambda: ("digimon", "gpt-5.6", 1.0)),
        MagicMock(fetchone=lambda: (4, 3.0, 2)), MagicMock(fetchone=lambda: ("greer", "gpt-5.6-terra", 2.0)),
        MagicMock(), MagicMock(),
    ]
    with patch("llm_client.cli.dashboard._io_log._get_db", return_value=db):
        cmd_dashboard(argparse.Namespace(format="json", hourly_budget=1.0, daily_budget=3.0))
    output = capsys.readouterr().out
    assert '"rate_per_hour": 1.0' in output
    assert '"unpriced_calls": 2' in output
    assert '"project": "greer"' in output
    assert '"alert": true' in output
    assert any("INSERT OR IGNORE INTO cost_alerts" in call.args[0] for call in db.execute.call_args_list)
    first_query = db.execute.call_args_list[0].args[0]
    assert "cost_source IS NOT NULL OR billing_mode IS NOT NULL" in first_query


def test_dashboard_alert_history_json(capsys) -> None:
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = [("2026-07-24T19:00:00+00:00", 1, 0.5, 0.435, "2026-07-24T19:25:00+00:00")]
    with patch("llm_client.cli.dashboard._io_log._get_db", return_value=db):
        cmd_dashboard(argparse.Namespace(format="json", alerts=True, alert_limit=20, hourly_budget=None, daily_budget=None))
    assert '"window_hours": 1' in capsys.readouterr().out
