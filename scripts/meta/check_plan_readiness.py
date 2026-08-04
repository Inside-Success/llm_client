#!/usr/bin/env python3
"""Gate plan-owned lane creation on canonical readiness and explicit resume."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _add_repo_root_to_path() -> None:
    """Make the adjacent source package importable from source or installed paths."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "enforced_planning").is_dir():
            sys.path.insert(0, str(parent))
            return
    raise RuntimeError("Unable to locate repository root containing enforced_planning/")


_add_repo_root_to_path()

from enforced_planning import coordination_claims  # noqa: E402
from enforced_planning.plan_readiness import check_plan_start_readiness  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse portable plan-start gate arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualified-plan-id")
    parser.add_argument("--execution-profile", choices=("light", "coordinated", "release"), required=True)
    parser.add_argument("--query-command")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--lane-id", required=True)
    parser.add_argument("--parent-lane-id")
    parser.add_argument("--branch", required=True)
    parser.add_argument("--worktree-path", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--session-id")
    parser.add_argument("--allow-unplanned", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Explicitly resume an in-progress plan with no live lane.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the gate and emit its strict result as JSON."""
    args = parse_args(argv)
    session_id = coordination_claims.resolve_session_id(args.agent, args.session_id)
    if not session_id:
        print("Unable to resolve session identity for plan-start gate.", file=sys.stderr)
        return 2
    try:
        result = check_plan_start_readiness(
            qualified_plan_id=args.qualified_plan_id,
            execution_profile=args.execution_profile,
            query_command=args.query_command,
            repository=args.repository,
            lane_id=args.lane_id,
            parent_lane_id=args.parent_lane_id,
            branch=args.branch,
            worktree_path=args.worktree_path,
            claim_identity=f"{args.agent}:{args.repository}:{args.scope}",
            session_identity=session_id,
            allow_unplanned=args.allow_unplanned,
            resume_requested=args.resume,
        )
    except ValueError as exc:
        print(f"Plan-start gate failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
