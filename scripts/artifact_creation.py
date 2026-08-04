#!/usr/bin/env python3
"""Run native, staged, reporting, and feedback artifact-governance operations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning.artifact_creation import (  # noqa: E402
    ArtifactCreationError,
    DEFAULT_FEEDBACK_PATH,
    DEFAULT_RECEIPT_PATH,
    audit_repository,
    build_report,
    evaluate_native_payload,
    evaluate_paths,
    record_feedback,
    record_feedback_disposition,
    staged_new_paths,
)


def _parser() -> argparse.ArgumentParser:
    """Build the multi-operation command parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    hook = subparsers.add_parser("hook", help="Evaluate one native PreToolUse payload from stdin.")
    hook.add_argument("--client", required=True, choices=("codex", "claude-code"))
    hook.add_argument("--mode", choices=("off", "observe", "enforce"))
    hook.add_argument("--receipt-path", type=Path, default=DEFAULT_RECEIPT_PATH)
    hook.add_argument("--json", action="store_true")

    check = subparsers.add_parser("check", help="Evaluate newly staged files before commit or CI.")
    check.add_argument("--repo-root", type=Path, default=Path.cwd())
    check.add_argument("--mode", choices=("off", "observe", "enforce"))
    check.add_argument("--receipt-path", type=Path, default=DEFAULT_RECEIPT_PATH)
    check.add_argument("--json", action="store_true")

    report = subparsers.add_parser("report", help="Summarize decisions, latency, and linked feedback.")
    report.add_argument("--repo-root", type=Path)
    report.add_argument("--receipt-path", type=Path, default=DEFAULT_RECEIPT_PATH)
    report.add_argument("--feedback-path", type=Path, default=DEFAULT_FEEDBACK_PATH)

    audit = subparsers.add_parser("audit", help="Find expired quarantine and invalid retained generated records.")
    audit.add_argument("--repo-root", type=Path, default=Path.cwd())

    feedback = subparsers.add_parser("feedback", help="Record friction or a reusable recommendation.")
    feedback.add_argument("--type", required=True, choices=("friction", "recommendation"))
    feedback.add_argument("--receipt-id", required=True)
    feedback.add_argument("--observation", required=True)
    feedback.add_argument("--recommendation", required=True)
    feedback.add_argument("--feedback-path", type=Path, default=DEFAULT_FEEDBACK_PATH)

    resolve_feedback = subparsers.add_parser(
        "resolve-feedback",
        help="Append a resolution, accepted-risk, or supersession disposition.",
    )
    resolve_feedback.add_argument("--feedback-id", required=True)
    resolve_feedback.add_argument(
        "--disposition",
        required=True,
        choices=("resolved", "accepted_risk", "superseded"),
    )
    resolve_feedback.add_argument("--resolution", required=True)
    resolve_feedback.add_argument(
        "--feedback-path",
        type=Path,
        default=DEFAULT_FEEDBACK_PATH,
    )
    return parser


def _native_notice(message: str) -> str:
    """Render a non-blocking client-visible hook notice."""

    return json.dumps({"systemMessage": message}, sort_keys=True)


def _render_decision(decision: dict[str, Any], *, as_json: bool) -> int:
    """Render one decision for a native or terminal caller."""

    if as_json:
        print(json.dumps(decision, indent=2, sort_keys=True))
    elif decision["decision"] == "deny":
        violations = []
        for item in decision["target_decisions"]:
            if item["decision"] == "violation":
                details = "; ".join(item["details"])
                violations.append(f"{item['path']}: {item['reason_code']} ({details})")
        message = "Artifact creation denied. " + " | ".join(violations)
        if decision.get("recovery"):
            message += f". {decision['recovery']}"
        message += (
            f" Receipt: {decision['receipt_id']}. Record false-positive friction with "
            "`python scripts/artifact_creation.py feedback ...`."
        )
        print(message, file=sys.stderr)
    elif decision["decision"] == "observe_violation":
        print(
            _native_notice(
                "OBSERVE ONLY: artifact creation would be denied in enforce mode "
                f"({decision['receipt_id']})."
            )
        )
    return 2 if decision["decision"] == "deny" else 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch artifact creation operations."""

    args = _parser().parse_args(argv)
    try:
        if args.command == "hook":
            payload = json.loads(sys.stdin.read())
            if not isinstance(payload, dict):
                raise ArtifactCreationError("PreToolUse payload must be a JSON object")
            decision = evaluate_native_payload(
                payload,
                client=args.client,
                mode=args.mode,
                receipt_path=args.receipt_path,
            )
            return _render_decision(decision.model_dump(mode="json"), as_json=args.json)

        if args.command == "check":
            repo_root = args.repo_root.expanduser().resolve()
            paths = staged_new_paths(repo_root)
            decision = evaluate_paths(
                repo_root=repo_root,
                target_paths=paths,
                force_new_paths=set(paths),
                client="git-staged",
                tool_name="pre-commit",
                mode=args.mode,
                receipt_path=args.receipt_path,
            )
            return _render_decision(decision.model_dump(mode="json"), as_json=args.json)

        if args.command == "report":
            print(
                json.dumps(
                    build_report(
                        receipt_path=args.receipt_path,
                        feedback_path=args.feedback_path,
                        repo_root=args.repo_root,
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "audit":
            audit = audit_repository(args.repo_root)
            print(json.dumps(audit.model_dump(mode="json"), indent=2, sort_keys=True))
            return 2 if audit.mode == "enforce" and audit.finding_count else 0

        if args.command == "feedback":
            record = record_feedback(
                feedback_type=args.type,
                receipt_id=args.receipt_id,
                observation=args.observation,
                recommendation=args.recommendation,
                feedback_path=args.feedback_path,
            )
        else:
            record = record_feedback_disposition(
                feedback_id=args.feedback_id,
                disposition=args.disposition,
                resolution=args.resolution,
                feedback_path=args.feedback_path,
            )
        print(json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True))
        return 0
    except (ArtifactCreationError, json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"Artifact creation governance failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
