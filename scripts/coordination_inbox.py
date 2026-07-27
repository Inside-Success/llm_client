#!/usr/bin/env python3
"""Poll the canonical coordination mailbox for one live agent session."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap_package() -> None:
    """Load a local installed package or the target repo's upstream bootstrap."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "enforced_planning").is_dir():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return
    for parent in current.parents:
        helper = parent / "scripts" / "_upstream_enforced_planning.py"
        if helper.is_file():
            scripts_dir = helper.parent
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            from _upstream_enforced_planning import bootstrap_upstream_package  # type: ignore[import-not-found]

            bootstrap_upstream_package(current)
            return
    raise RuntimeError(
        "Unable to locate a local enforced_planning package or scripts/_upstream_enforced_planning.py"
    )


_bootstrap_package()

from enforced_planning import coordination_messages  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse an agent-drivable inbox poll command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--session-id")
    parser.add_argument("--claims-dir", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--no-observe", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Poll, optionally append observation evidence, and render the notice."""
    args = parse_args(argv)
    try:
        notice = coordination_messages.poll_session_inbox(
            agent=args.agent,
            project=args.project,
            session_id=args.session_id,
            observe=not args.no_observe,
            claims_dir=args.claims_dir,
            root=args.root,
        )
    except coordination_messages.CoordinationMessageError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error_type": type(exc).__name__, "error": str(exc)}))
        else:
            print(f"coordination mailbox unavailable: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(notice.model_dump_json(indent=2))
    elif notice.active_count:
        print(notice.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
