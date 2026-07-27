#!/usr/bin/env python3
"""Close every live lane owned by one qualified plan."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _add_repo_root_to_path() -> None:
    """Make the sibling package importable from source and installed paths."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "enforced_planning").is_dir():
            sys.path.insert(0, str(parent))
            return
    raise RuntimeError("Unable to locate repository root containing enforced_planning/")


_add_repo_root_to_path()

from enforced_planning.plan_close import close_plan_lanes  # noqa: E402
from enforced_planning.worktree_paths import resolve_canonical_repo_root  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse plan-close arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=int, required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--submitted-revision")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run atomic plan-owned lane closeout."""
    args = parse_args(argv)
    invocation_root = Path(args.project_root).expanduser().resolve()
    root = resolve_canonical_repo_root(invocation_root)
    revision = args.submitted_revision
    if not revision:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=invocation_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            print("Unable to resolve submitted Git revision.", file=sys.stderr)
            return 2
        revision = completed.stdout.strip()
    result = close_plan_lanes(
        qualified_plan_id=f"{root.name.lower().replace('_', '-')}#{args.plan}",
        submitted_revision=revision,
        dry_run=args.dry_run,
    )
    payload = result.model_dump(mode="json")
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif result.success:
        print(f"Closed {len(result.lanes)} lane(s) for {result.qualified_plan_id}.")
    else:
        print(
            f"Plan close blocked for {result.qualified_plan_id}: "
            + "; ".join(result.failures),
            file=sys.stderr,
        )
    return 0 if result.success else 2


if __name__ == "__main__":
    raise SystemExit(main())
