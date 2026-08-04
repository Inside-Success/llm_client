#!/usr/bin/env python3
"""Show live session summaries derived from claims plus trackers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "enforced_planning").is_dir():
            return parent
    raise RuntimeError("Unable to locate repo root containing enforced_planning/")


REPO_ROOT = _find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning import client_session_metadata, session_lifecycle  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project")
    parser.add_argument("--agent")
    parser.add_argument("--scope")
    parser.add_argument("--branch")
    parser.add_argument("--session-id")
    parser.add_argument("--include-ended", action="store_true")
    parser.add_argument(
        "--codex-session-index",
        type=Path,
        default=client_session_metadata.DEFAULT_CODEX_SESSION_INDEX,
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def enrich_client_displays(
    payload: dict[str, object],
    *,
    codex_session_index: Path,
) -> None:
    """Add read-only client display projections to session-status output."""

    sessions = payload.get("sessions")
    if not isinstance(sessions, list):
        raise ValueError("session status payload requires a sessions list")
    for session in sessions:
        if not isinstance(session, dict):
            raise ValueError("session status entries must be objects")
        session_id = session.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session status entries require session_id")
        session["client_display"] = client_session_metadata.resolve_client_session_display(
            session_id,
            codex_session_index=codex_session_index,
        ).model_dump(mode="json")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = session_lifecycle.status_sessions(
        project=args.project,
        agent=args.agent,
        scope=args.scope,
        branch=args.branch,
        session_id=args.session_id,
        include_ended=args.include_ended,
    )
    enrich_client_displays(payload, codex_session_index=args.codex_session_index)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    label = "Live and ended sessions" if args.include_ended else "Live sessions"
    print(f"{label}: {payload['session_count']}")
    for session in payload["sessions"]:
        session_name = session["session_name"] or "<missing-session-name>"
        current_phase = session["current_phase"] or "<missing-current-phase>"
        hierarchy = session["hierarchy_role"]
        if session["parent_scope"]:
            hierarchy = f"{hierarchy}:parent={session['parent_scope']}"
        print(
            f"- {session['project']}:{session['scope']} "
            f"[{session['health_status']}] "
            f"{session_name} :: {current_phase} "
            f"(hierarchy={hierarchy}; recovery={session['recovery_action']})"
        )
        client_display = session["client_display"]
        display_name = client_display["display_name"] or f"<{client_display['state']}>"
        print(
            f"  client_thread={display_name}; "
            f"routing_session_id={session['session_id']}"
        )
        if session["health_issues"]:
            print(f"  issues={','.join(session['health_issues'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
