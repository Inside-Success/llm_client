"""Focused accounting-dimension tests for the cost CLI."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

from llm_client.cli.cost import cmd_cost


def test_cost_cli_groups_by_accounting_state(capsys) -> None:
    db = MagicMock()
    db.execute.side_effect = [
        MagicMock(fetchall=lambda: [("api_metered", "provider_reported", 2, 1.25, 10, 0.5, 0)]),
        MagicMock(fetchall=lambda: []),
    ]
    args = argparse.Namespace(
        group_by="billing_mode,cost_source", project=None, task=None, trace_id=None, days=None, format="json"
    )
    with patch("llm_client.cli.cost.connect", return_value=db):
        cmd_cost(args)
    output = capsys.readouterr().out
    assert '"billing_mode": "api_metered"' in output
    assert '"cost_source": "provider_reported"' in output


def test_cost_cli_filters_by_task(capsys) -> None:
    db = MagicMock()
    db.execute.side_effect = [
        MagicMock(fetchall=lambda: [("gpt-5.6-luna", 3, 0.15, 1000, 0.4, 0)]),
        MagicMock(fetchall=lambda: []),
    ]
    args = argparse.Namespace(
        group_by="model", project=None, task="budget_extraction", trace_id=None, days=None, format="json"
    )
    with patch("llm_client.cli.cost.connect", return_value=db):
        cmd_cost(args)
    query, params = db.execute.call_args_list[0].args
    assert "task = ?" in query
    assert "budget_extraction" in params


def test_cost_cli_rejects_unknown_accounting_group(capsys) -> None:
    args = argparse.Namespace(group_by="unknown_dimension", project=None, task=None, trace_id=None, days=None, format="table")
    with patch("llm_client.cli.cost.connect"):
        try:
            cmd_cost(args)
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected invalid accounting grouping to fail")
    assert "Invalid group-by column" in capsys.readouterr().err
