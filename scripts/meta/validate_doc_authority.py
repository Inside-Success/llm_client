#!/usr/bin/env python3
"""Validate or manage documentation-authority reconciliation obligations."""

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

from enforced_planning import doc_authority  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI args for doc-authority validation and obligation management."""

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--list-obligations", action="store_true")
    mode.add_argument("--record-obligation", action="store_true")
    mode.add_argument("--resolve-obligation", action="store_true")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--config")
    parser.add_argument("--project")
    parser.add_argument("--concern")
    parser.add_argument("--authority-surface")
    parser.add_argument("--artifact-path")
    parser.add_argument("--required-action")
    parser.add_argument("--created-by-agent")
    parser.add_argument("--created-by-scope")
    parser.add_argument("--plan-ref")
    parser.add_argument("--owner-scope")
    parser.add_argument("--notes")
    parser.add_argument("--obligation-id")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _print_json(payload: object) -> None:
    """Emit stable JSON output."""

    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    """Run validation or mutate obligation state."""

    args = parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve()
    config_path = Path(args.config).expanduser().resolve() if args.config else None

    if args.record_obligation:
        required = (
            args.project,
            args.concern,
            args.authority_surface,
            args.artifact_path,
            args.required_action,
            args.created_by_agent,
            args.created_by_scope,
        )
        if not all(required):
            raise ValueError(
                "--record-obligation requires --project, --concern, --authority-surface, "
                "--artifact-path, --required-action, --created-by-agent, and --created-by-scope"
            )
        record = doc_authority.record_obligation(
            project=args.project,
            concern=args.concern,
            authority_surface=args.authority_surface,
            artifact_path=args.artifact_path,
            required_action=args.required_action,
            created_by_agent=args.created_by_agent,
            created_by_scope=args.created_by_scope,
            plan_ref=args.plan_ref,
            owner_scope=args.owner_scope,
            notes=args.notes,
        )
        if args.json:
            _print_json(record.to_dict())
        else:
            print(f"Recorded obligation: {record.obligation_id}")
        return 0

    if args.resolve_obligation:
        if not args.obligation_id:
            raise ValueError("--resolve-obligation requires --obligation-id")
        record = doc_authority.resolve_obligation(
            obligation_id=args.obligation_id,
            notes=args.notes,
        )
        if args.json:
            _print_json(record.to_dict())
        else:
            print(f"Resolved obligation: {record.obligation_id}")
        return 0

    if args.list_obligations:
        obligations = [
            obligation.to_dict()
            for obligation in doc_authority.list_obligations(
                project=args.project,
                concern=args.concern,
            )
        ]
        if args.json:
            _print_json({"obligations": obligations})
        else:
            for obligation in obligations:
                print(
                    f"{obligation['status']}: {obligation['project']} "
                    f"{obligation['concern']} {obligation['artifact_path']} -> "
                    f"{obligation['authority_surface']} ({obligation['obligation_id']})"
                )
        return 0

    issues = [
        issue.to_dict()
        for issue in doc_authority.validate_doc_authority(
            repo_root,
            config_path=config_path,
        )
    ]
    exit_code = 1 if any(issue["severity"] == "fail" for issue in issues) else 0
    if args.json:
        _print_json({"issues": issues})
    else:
        if not issues:
            print("Authority validation OK: no unresolved drift.")
        for issue in issues:
            print(f"{issue['severity']}: {issue['code']} — {issue['message']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
