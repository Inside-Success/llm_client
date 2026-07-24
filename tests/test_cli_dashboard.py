from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

from llm_client.cli.dashboard import cmd_dashboard


def test_dashboard_json_exposes_rate_and_accountability(capsys) -> None:
    db = MagicMock()
    db.execute.side_effect = [
        MagicMock(fetchone=lambda: (2, 1.0, 1)), MagicMock(fetchone=lambda: ("digimon", "gpt-5.6", 1.0)),
        MagicMock(fetchone=lambda: (4, 3.0, 2)), MagicMock(fetchone=lambda: ("greer", "gpt-5.6-terra", 2.0)),
    ]
    with patch("llm_client.cli.dashboard.connect", return_value=db):
        cmd_dashboard(argparse.Namespace(format="json"))
    output = capsys.readouterr().out
    assert '"rate_per_hour": 1.0' in output
    assert '"unpriced_calls": 2' in output
    assert '"project": "greer"' in output
    first_query = db.execute.call_args_list[0].args[0]
    assert "cost_source IS NOT NULL OR billing_mode IS NOT NULL" in first_query
