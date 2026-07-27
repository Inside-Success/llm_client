#!/usr/bin/env python3
"""Start or refresh one sanctioned session contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap_package() -> None:
    """Load local package support or the target repo's upstream bootstrap."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "enforced_planning").is_dir():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return
    for parent in current.parents:
        helper = parent / "scripts" / "_upstream_enforced_planning.py"
        if helper.is_file():
            if str(helper.parent) not in sys.path:
                sys.path.insert(0, str(helper.parent))
            from _upstream_enforced_planning import bootstrap_upstream_package  # type: ignore[import-not-found]

            bootstrap_upstream_package(current)
            return
    raise RuntimeError("Unable to locate local or upstream enforced_planning support")


_bootstrap_package()

from enforced_planning import session_lifecycle  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the complete session-start contract without hidden defaults."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--intent", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--worktree-path", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--broader-goal", required=True)
    parser.add_argument("--current-phase", required=True)
    parser.add_argument("--plan")
    parser.add_argument("--allow-unplanned", action="store_true")
    parser.add_argument("--allow-parallel", action="store_true")
    parser.add_argument("--session-id")
    parser.add_argument("--session-name")
    parser.add_argument("--claim-type", choices=["program", "write", "review", "research"])
    parser.add_argument("--parent-scope")
    parser.add_argument("--write-path", action="append", default=[])
    parser.add_argument("--read-path", action="append", default=[])
    parser.add_argument("--next-phase", action="append", default=[])
    parser.add_argument("--depends-on", action="append", default=[])
    parser.add_argument("--stop-condition", action="append", default=[])
    parser.add_argument("--requires-shared-infra-changes", action="store_true")
    parser.add_argument("--notes")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Start the session and expose its initial mailbox state."""
    args = parse_args(argv)
    payload = session_lifecycle.start_session(
        agent=args.agent,
        project=args.project,
        scope=args.scope,
        intent=args.intent,
        repo_root=args.repo_root,
        worktree_path=args.worktree_path,
        branch=args.branch,
        broader_goal=args.broader_goal,
        current_phase=args.current_phase,
        plan_ref=args.plan,
        allow_unplanned=args.allow_unplanned,
        allow_parallel=args.allow_parallel,
        session_id=args.session_id,
        session_name=args.session_name,
        claim_type=args.claim_type,
        parent_scope=args.parent_scope,
        write_paths=args.write_path or None,
        read_paths=args.read_path or None,
        intended_next_phases=args.next_phase,
        depends_on_repos=args.depends_on,
        requires_shared_infra_changes=args.requires_shared_infra_changes,
        stop_conditions=args.stop_condition,
        notes=args.notes,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"{payload['action']}: {payload['session_name']} "
            f"({payload['broader_goal']}) -> {payload['tracker_path']}"
        )
        print(payload["coordination_mailbox"]["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
