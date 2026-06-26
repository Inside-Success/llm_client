"""CLI for bounded review/apply/review cycles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from llm_client.workflow.review_cycle import ReviewCycleTask, run_review_cycle

SUCCESS_STATUSES = {"pass"}


def _load_task_file(path: str) -> ReviewCycleTask:
    """Load a ReviewCycleTask from JSON."""
    task_path = Path(path).resolve()
    if not task_path.is_file():
        print(f"error: --task-file not found: {task_path}", file=sys.stderr)
        sys.exit(2)
    try:
        payload = json.loads(task_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: --task-file must be JSON: {exc}", file=sys.stderr)
        sys.exit(2)
    return ReviewCycleTask.model_validate(payload)


def cmd_review_cycle(args: argparse.Namespace) -> None:
    """Execute ``review-cycle`` from a task file."""
    task = _load_task_file(args.task_file)
    signoff = run_review_cycle(task)
    print(f"review-cycle status: {signoff.final_status}")
    print(f"cycles: {signoff.cycles_completed}")
    print(f"budget: ${signoff.budget_spent_usd:.4f}")
    print(f"signoff: {task.run_dir() / 'signoff.json'}")
    if signoff.final_status not in SUCCESS_STATUSES:
        sys.exit(1)


def register_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "review-cycle",
        help="Run a bounded review/apply/review loop from a typed task file.",
    )
    parser.add_argument(
        "--task-file",
        required=True,
        help="Path to a JSON ReviewCycleTask config.",
    )
    parser.set_defaults(handler=cmd_review_cycle)
