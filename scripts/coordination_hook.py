#!/usr/bin/env python3
"""Expose canonical mailbox requests through native Codex lifecycle hooks."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal


def _bootstrap_package() -> None:
    """Load the local package or a governed repo's upstream bootstrap."""

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
        "Unable to locate a local enforced_planning package or "
        "scripts/_upstream_enforced_planning.py"
    )


_bootstrap_package()

from enforced_planning import coordination_claims, coordination_messages  # noqa: E402


SUPPORTED_EVENTS = {"SessionStart", "UserPromptSubmit", "PostToolUse", "PreToolUse", "Stop"}
MUTATION_TOOL_NAMES = frozenset({"bash", "apply_patch", "edit", "write"})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse test and rollout overrides without changing the hook wire format."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims-dir", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--agent", choices=("codex", "claude-code"), default="codex")
    parser.add_argument("--project", help="Canonical project override supplied by a repository compatibility hook.")
    return parser.parse_args(argv)


def _read_hook_input(*, project_supplied: bool) -> dict[str, Any]:
    """Read and validate the common native lifecycle-hook fields from stdin."""

    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict):
        raise ValueError("Lifecycle hook input must be a JSON object")
    required_fields = ("session_id", "hook_event_name") if project_supplied else ("session_id", "cwd", "hook_event_name")
    for field in required_fields:
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"Lifecycle hook input requires non-empty {field!r}")
    if payload["hook_event_name"] not in SUPPORTED_EVENTS:
        raise ValueError(f"Unsupported Codex hook event: {payload['hook_event_name']}")
    return payload


def _canonical_project(cwd: str) -> str | None:
    """Resolve a worktree cwd, or return no project for a non-Git workspace path."""

    repository = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if repository.returncode == 128:
        return None
    repository.check_returncode()
    top = repository.stdout.strip()
    worktrees = subprocess.run(
        ["git", "-C", top, "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    canonical_root = next(
        (line.removeprefix("worktree ") for line in worktrees if line.startswith("worktree ")),
        top,
    )
    return Path(canonical_root).name


def _claimed_projects(*, agent: str, session_id: str, claims_dir: Path | None) -> tuple[str, ...]:
    """Return exact-session live claim projects without adopting another lane."""

    claims = coordination_claims.check_claims(claims_dir=claims_dir)
    return tuple(
        sorted(
            {
                project
                for claim in claims
                if claim.agent == agent and claim.session_id == session_id
                for project in claim.projects
            }
        )
    )


def _session_id(agent: str, raw_session_id: str) -> str:
    """Normalize one native client session UUID into canonical claim identity."""

    return raw_session_id if raw_session_id.startswith(f"{agent}:") else f"{agent}:{raw_session_id}"


def _delivery_event_id(payload: dict[str, Any], *, agent: str, session_id: str) -> str:
    """Derive one client-neutral identity for a native lifecycle callback.

    Native turn/event IDs are preferred. A timestamp is only a compatibility
    fallback because it is weaker: adapters that receive neither must fail
    before they can create observation evidence.
    """

    # Claude Code's UserPromptSubmit payload identifies the native prompt with
    # ``prompt_id``.  It is an event identity, not a session identity, so it
    # preserves the same duplicate-suppression boundary as the turn/tool IDs
    # above.  Do not substitute a session ID when an event lacks one.
    for field in ("event_id", "turn_id", "prompt_id", "tool_use_id", "tool_call_id", "timestamp"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            token = f"{field}:{value.strip()}"
            break
    else:
        # Native SessionStart payloads from Claude Code and Codex can omit both
        # an event ID and a timestamp. A short-lived bucket preserves duplicate
        # suppression for concurrently configured host/repository hooks without
        # pretending the session ID is a unique lifecycle event. Claude Stop
        # payloads likewise omit an event ID, but do provide the exact final
        # assistant message; its digest is a duplicate-safe boundary identity.
        if payload["hook_event_name"] == "SessionStart":
            token = f"sessionstart-bucket:{int(time.time() // 30)}"
        elif payload["hook_event_name"] == "Stop" and isinstance(
            payload.get("last_assistant_message"), str
        ):
            message_digest = hashlib.sha256(
                payload["last_assistant_message"].encode("utf-8")
            ).hexdigest()
            token = f"stop-message:{message_digest}"
        else:
            raise ValueError("Lifecycle hook requires a native event ID or timestamp for duplicate-safe delivery")
    material = "\0".join((agent, session_id, payload["hook_event_name"], token))
    return f"event_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:32]}"


def _render_codex_result(event_name: str, summary: str) -> dict[str, Any]:
    """Render the event-specific output accepted by the native Codex client."""

    if event_name == "SessionStart":
        return {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": summary,
            }
        }
    return {"systemMessage": summary}


def _tool_command(payload: dict[str, Any]) -> str | None:
    """Return the direct shell command from one native tool payload, when present."""

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for field in ("command", "cmd"):
        command = tool_input.get(field)
        if isinstance(command, str) and command.strip():
            return command
    return None


def _is_exact_acknowledgement_command(
    payload: dict[str, Any],
    *,
    session_id: str,
    active_message_ids: tuple[str, ...],
) -> bool:
    """Allow only one structurally exact mailbox acknowledgement shell command."""

    command = _tool_command(payload)
    if command is None:
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if len(tokens) != 5:
        return False
    interpreter, script, action, flag, raw_request = tokens
    if Path(interpreter).name not in {"python", "python3"}:
        return False
    if not script.replace("\\", "/").endswith("scripts/meta/coordination_messages.py"):
        return False
    if action != "acknowledge" or flag != "--request-json":
        return False
    try:
        request = json.loads(raw_request)
    except json.JSONDecodeError:
        return False
    if not isinstance(request, dict) or set(request) - {
        "current_session_id",
        "message_id",
        "disposition",
        "note",
        "response_ref",
    }:
        return False
    return (
        request.get("current_session_id") == session_id
        and request.get("message_id") in active_message_ids
        and request.get("disposition") in {"accepted", "declined", "deferred", "information_only"}
        and isinstance(request.get("note"), str)
        and bool(request["note"].strip())
    )


def _is_mutation_boundary(payload: dict[str, Any]) -> bool:
    """Return whether a PreToolUse callback represents a common mutation tool."""

    tool_name = payload.get("tool_name")
    return isinstance(tool_name, str) and tool_name.strip().lower() in MUTATION_TOOL_NAMES


def _render_boundary_denial(event_name: str, summary: str) -> dict[str, Any]:
    """Render a native blocking decision for mutation or final-response boundaries."""

    if event_name == "Stop":
        return {"decision": "block", "reason": summary}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": summary,
        }
    }


def main(argv: list[str] | None = None) -> int:
    """Refresh matching claim state and expose requests to the native session."""

    args = parse_args(argv)
    try:
        payload = _read_hook_input(project_supplied=args.project is not None)
        session_id = _session_id(args.agent, payload["session_id"])
        delivery_event_id = _delivery_event_id(payload, agent=args.agent, session_id=session_id)
        project = args.project or _canonical_project(payload["cwd"])
        heartbeat_projects = (project,) if project is not None else _claimed_projects(
            agent=args.agent,
            session_id=session_id,
            claims_dir=args.claims_dir,
        )
        for heartbeat_project in heartbeat_projects:
            coordination_claims.heartbeat_claims(
                agent=args.agent,
                project=heartbeat_project,
                session_id=session_id,
                claims_dir=args.claims_dir,
                require_exact_session=True,
            )
        notice = coordination_messages.poll_session_inbox(
            agent=args.agent,
            project=project,
            session_id=session_id,
            observe=True,
            claims_dir=args.claims_dir,
            root=args.root,
            # Gate events must re-read canonical active state on every callback.
            # Native display suppression is appropriate only for advisory events.
            delivery_event_id=(
                None if payload["hook_event_name"] in {"PreToolUse", "Stop"} else delivery_event_id
            ),
            require_live_claim=False,
        )
        boundary_event: Literal["PreToolUse", "Stop"] | None = None
        if notice.active_count and payload["hook_event_name"] == "Stop":
            boundary_event = "Stop"
        elif (
            notice.active_count
            and payload["hook_event_name"] == "PreToolUse"
            and _is_mutation_boundary(payload)
            and not _is_exact_acknowledgement_command(
                payload,
                session_id=session_id,
                active_message_ids=notice.message_ids,
            )
        ):
            boundary_event = "PreToolUse"
        if boundary_event is not None:
            store = coordination_messages.CoordinationMessageStore(
                root=args.root or coordination_messages.default_message_root(args.claims_dir),
                claims_dir=args.claims_dir,
            )
            tool_name = payload.get("tool_name") if boundary_event == "PreToolUse" else None
            store.record_boundary_block(
                current_session_id=session_id,
                message_ids=notice.message_ids,
                hook_event_name=boundary_event,
                delivery_event_id=delivery_event_id,
                tool_name=tool_name if isinstance(tool_name, str) else None,
            )
            print(json.dumps(_render_boundary_denial(boundary_event, notice.summary)))
            return 0
        if notice.active_count or notice.acknowledgement_count:
            if args.agent == "codex":
                print(json.dumps(_render_codex_result(payload["hook_event_name"], notice.summary)))
            else:
                print(notice.summary)
    except (
        coordination_messages.CoordinationMessageError,
        json.JSONDecodeError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ) as exc:
        warning = f"coordination mailbox unavailable: {type(exc).__name__}: {exc}"
        print(json.dumps({"systemMessage": warning}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
