"""CLI tests for the ``review-cycle`` subcommand."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_load_task_file_json(tmp_path: Path) -> None:
    from llm_client.cli.review_cycle import _load_task_file

    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task_id": "t1",
                "artifact_paths": ["paper.md"],
                "workspace_path": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )

    task = _load_task_file(str(task_file))

    assert task.task_id == "t1"
    assert task.artifact_paths == ["paper.md"]


def test_load_task_file_missing_exits(tmp_path: Path) -> None:
    from llm_client.cli.review_cycle import _load_task_file

    with pytest.raises(SystemExit):
        _load_task_file(str(tmp_path / "missing.json"))


def test_cli_review_cycle_threads_task_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from llm_client.cli import review_cycle as cli_mod
    from llm_client.workflow.review_cycle import ReviewCycleSignoff

    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task_id": "t1",
                "artifact_paths": ["paper.md"],
                "workspace_path": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_run(task):
        calls.append(task)
        return ReviewCycleSignoff(
            task_id=task.task_id,
            final_status="pass",
            cycles_completed=1,
            final_verdict="pass",
            stop_reason="ok",
            budget_spent_usd=0.0,
            actionable_count=0,
            discussion_queue_count=0,
            artifact_index={},
        )

    monkeypatch.setattr(cli_mod, "run_review_cycle", fake_run)

    cli_mod.cmd_review_cycle(MagicMock(task_file=str(task_file)))

    assert calls[0].task_id == "t1"
