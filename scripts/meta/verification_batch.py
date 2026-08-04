#!/usr/bin/env python3
"""Freeze, check, or explicitly invalidate an exact terminal verification batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


for parent in Path(__file__).resolve().parents:
    if (parent / "enforced_planning").is_dir():
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        break
else:
    raise RuntimeError("cannot locate installed enforced_planning package")

from enforced_planning.verification_batch import VerificationBatchError  # noqa: E402
from enforced_planning.verification_batch import check_batch  # noqa: E402
from enforced_planning.verification_batch import freeze_batch  # noqa: E402
from enforced_planning.verification_batch import thaw_batch  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    """Build the agent-drivable verification-batch command contract."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true", help="Emit one JSON result")
    subparsers = parser.add_subparsers(dest="action", required=True)
    freeze = subparsers.add_parser("freeze", help="Bind verification to clean HEAD")
    freeze.add_argument("--decision", required=True)
    freeze.add_argument("--command", required=True)
    freeze.add_argument(
        "--allow-untracked",
        action="append",
        default=[],
        help="Narrow repo-relative operational file or subtree allowed outside the commit",
    )
    check = subparsers.add_parser("check", help="Validate the active freeze, if present")
    check.add_argument("--require-active", action="store_true")
    thaw = subparsers.add_parser("thaw", help="Invalidate the active batch explicitly")
    thaw.add_argument("--reason", required=True)
    return parser


def main() -> int:
    """Execute one verification-batch transition with visible failure output."""

    args = _parser().parse_args()
    try:
        payload: dict[str, Any]
        if args.action == "freeze":
            batch = freeze_batch(
                args.repo_root,
                decision=args.decision,
                command=args.command,
                allowed_untracked=tuple(args.allow_untracked),
            )
            payload = {"ok": True, "action": "freeze", "batch": batch.to_dict()}
        elif args.action == "check":
            checked_batch = check_batch(args.repo_root, require_active=args.require_active)
            payload = {
                "ok": True,
                "action": "check",
                "active": checked_batch is not None,
                "batch": checked_batch.to_dict() if checked_batch else None,
            }
        else:
            batch = thaw_batch(args.repo_root, reason=args.reason)
            payload = {"ok": True, "action": "thaw", "invalidated_revision": batch.revision}
    except VerificationBatchError as exc:
        if args.json:
            print(json.dumps({"ok": False, "action": args.action, "error": str(exc)}, sort_keys=True))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    elif args.action == "check" and not payload["active"]:
        print("No active verification batch.")
    else:
        batch_payload = payload.get("batch")
        revision = (
            batch_payload.get("revision")
            if isinstance(batch_payload, dict)
            else payload.get("invalidated_revision")
        )
        print(f"Verification batch {args.action}: {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
