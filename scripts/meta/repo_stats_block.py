#!/usr/bin/env python3
"""Session-start repetition counters.

Human boredom is a running count of "I have done this before", available for
free. Agents do not have it: artifact number 176 looks exactly as reasonable as
number 3, because the objection only exists in aggregate and every individual
instance is defensible.

This computes the aggregate and prints it, so the count is present in context
before the next artifact is created. It judges nothing. It counts.

    python scripts/meta/repo_stats_block.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

PLAN_PATTERN = "plan[0-9]"


def _plan_named(root: Path, subdir: str, suffix: str) -> int:
    base = root / subdir
    if not base.is_dir():
        return 0
    return sum(
        1
        for path in base.rglob(f"*{suffix}")
        if "plan" in path.name.lower()
        and any(ch.isdigit() for ch in path.name)
    )


def _net_lines(root: Path, count: int = 8) -> tuple[int, int, int]:
    """Added, deleted, and commit count over the last `count` commits."""
    try:
        out = subprocess.run(
            ["git", "log", f"-{count}", "--numstat", "--format=%H"],
            cwd=root, capture_output=True, text=True, timeout=30, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return 0, 0, 0
    added = deleted = commits = 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            added += int(parts[0])
            deleted += int(parts[1])
        elif len(line) == 40 and not line.startswith(" "):
            commits += 1
    return added, deleted, commits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.project_root.resolve()

    plans = len(list((root / "docs" / "plans").glob("[0-9]*.md"))) if (root / "docs" / "plans").is_dir() else 0
    modules = _plan_named(root, "src", ".py") + _plan_named(root, "workbench", ".py")
    schemas = _plan_named(root, "schemas", ".json")
    configs = _plan_named(root, "config", ".yaml")
    added, deleted, commits = _net_lines(root)

    reach: dict = {}
    sensor = root / "scripts" / "meta" / "check_reachability.py"
    if sensor.is_file():
        try:
            out = subprocess.run(
                [sys.executable, str(sensor), "--project-root", str(root), "--json"],
                capture_output=True, text=True, timeout=120, check=False,
            ).stdout
            reach = json.loads(out) if out.strip().startswith("{") else {}
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
            reach = {}

    stats = {
        "plan_documents": plans,
        "plan_named_modules": modules,
        "plan_named_schemas": schemas,
        "plan_named_configs": configs,
        "last_commits": commits,
        "lines_added": added,
        "lines_deleted": deleted,
        "orphaned_modules": reach.get("unreachable_count"),
        "product_reachable_share": (
            round(1 - reach["product_unreachable_lines"] / reach["total_lines"], 4)
            if reach.get("total_lines") else None
        ),
    }

    if args.json:
        print(json.dumps(stats, indent=2))
        return 0

    print("repo counters (facts, not judgements):")
    print(f"  plan documents            {plans}")
    if modules:
        print(f"  plan-named modules        {modules}")
    if schemas:
        print(f"  plan-named schemas        {schemas}")
    if configs:
        print(f"  plan-named configs        {configs}")
    if commits:
        ratio = "no deletions" if not deleted else f"{added / deleted:.1f}x"
        print(
            f"  last {commits} commits          +{added:,} / -{deleted:,} lines ({ratio})"
        )
    if stats["orphaned_modules"] is not None:
        print(f"  orphaned modules          {stats['orphaned_modules']}")
    if stats["product_reachable_share"] is not None:
        print(
            f"  reachable from product    {stats['product_reachable_share']:.1%} of lines"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
