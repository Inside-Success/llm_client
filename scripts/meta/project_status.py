#!/usr/bin/env python3
"""Report current repository authority freshness and fail loud on stale main."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _find_framework_root() -> Path:
    """Return the installed repository root containing the shared package."""

    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "enforced_planning").is_dir():
            return parent
    raise RuntimeError("Unable to locate repository root containing enforced_planning/")


FRAMEWORK_ROOT = _find_framework_root()
if str(FRAMEWORK_ROOT) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK_ROOT))

from enforced_planning import repository_status  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse repository status arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--fetch-timeout-seconds",
        type=float,
        default=repository_status.DEFAULT_FETCH_TIMEOUT_SECONDS,
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Render one exact freshness observation and return its gate status."""

    args = parse_args(argv)
    result = repository_status.inspect_repository(
        args.repo_root,
        fetch_remote=True,
        fetch_timeout_seconds=args.fetch_timeout_seconds,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        dirty = "unknown" if result.worktree_dirty is None else ("dirty" if result.worktree_dirty else "clean")
        print(f"Repository authority: {result.status}")
        print(f"Current branch: {result.current_branch or '<detached>'}; worktree: {dirty}")
        print(
            f"Default branch: {result.default_branch or '<unknown>'}; "
            f"remote: {result.remote_name or '<unknown>'}"
        )
        if result.local_default_commit and result.remote_default_commit:
            print(
                f"Default commits: local={result.local_default_commit} "
                f"remote={result.remote_default_commit}"
            )
            print(
                f"Default drift: status={result.default_status} "
                f"ahead={result.ahead_count} behind={result.behind_count}"
            )
        if result.current_commit and result.current_branch != result.default_branch:
            print(
                f"Feature relation: commit={result.current_commit} "
                f"ahead={result.current_ahead_count} behind={result.current_behind_count}"
            )
        if result.fetch_error:
            print(f"Freshness error: {result.fetch_error}", file=sys.stderr)
        if result.status == "stale":
            print("Current authority is stale: refresh the default branch before reading local status docs.", file=sys.stderr)
        elif result.status in {"ahead", "diverged"}:
            print("Current authority differs from the remote default branch; reconcile explicitly.", file=sys.stderr)
        elif result.status.startswith("feature_base_"):
            print("Feature status is readable, but the local default branch requires reconciliation.")
        if result.current_branch != result.default_branch and result.default_status != "current":
            print(
                "Local default-branch authority also requires reconciliation: "
                f"{result.default_status}."
            )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
