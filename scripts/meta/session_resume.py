#!/usr/bin/env python3
"""Resume one plan-bound sanctioned session with a fresh runtime attachment."""

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
    """Parse the bounded session-resume identity and phase contract."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--worktree-path", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--current-phase", required=True)
    parser.add_argument("--session-id")
    parser.add_argument("--note")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Resume the session and expose its current mailbox state."""
    args = parse_args(argv)
    payload = session_lifecycle.resume_session(
        agent=args.agent,
        project=args.project,
        scope=args.scope,
        worktree_path=args.worktree_path,
        branch=args.branch,
        current_phase=args.current_phase,
        session_id=args.session_id,
        note=args.note,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['action']}: {payload['plan_ref']} -> {payload['session_id']}")
        print(payload["coordination_mailbox"]["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
