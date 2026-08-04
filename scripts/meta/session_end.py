#!/usr/bin/env python3
"""Retire exact-session live claims when a tool runtime truly terminates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _bootstrap_package() -> None:
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, choices=["codex", "claude-code", "openclaw"])
    parser.add_argument("--session-id")
    parser.add_argument("--reason", default="session ended")
    parser.add_argument("--claims-dir", type=Path)
    parser.add_argument(
        "--hook",
        action="store_true",
        help="Read and validate a native SessionEnd JSON payload from stdin.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _hook_identity(payload: dict[str, Any], agent: str) -> tuple[str, str]:
    if payload.get("hook_event_name") != "SessionEnd":
        raise ValueError("session-end hook requires hook_event_name=SessionEnd")
    raw_session_id = payload.get("session_id")
    if not isinstance(raw_session_id, str) or not raw_session_id.strip():
        raise ValueError("session-end hook requires a non-empty session_id")
    reason = payload.get("reason")
    reason_text = reason.strip() if isinstance(reason, str) and reason.strip() else "session ended"
    session_id = raw_session_id.strip()
    if not session_id.startswith(f"{agent}:"):
        session_id = f"{agent}:{session_id}"
    return session_id, reason_text


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    session_id = args.session_id
    reason = args.reason
    try:
        if args.hook:
            raw = json.loads(sys.stdin.read())
            if not isinstance(raw, dict):
                raise ValueError("session-end hook input must be a JSON object")
            session_id, reason = _hook_identity(raw, args.agent)
        payload = session_lifecycle.end_runtime_session(
            agent=args.agent,
            session_id=session_id,
            reason=reason,
            claims_dir=args.claims_dir,
        )
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        if args.hook:
            print(json.dumps({"systemMessage": f"session-end coordination unavailable: {exc}"}))
            return 0
        raise
    if args.json or args.hook:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"session ended: {payload['session_id']}; "
            f"retired {payload['ended_count']} live claim(s)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
