"""Read-only Git freshness status for current project authority.

The default branch is the canonical repository authority surface. This module
refreshes remote-tracking metadata and compares that immutable observation with
the local default branch without checking out, merging, rebasing, resetting, or
changing working-tree bytes.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_FETCH_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class RepositoryStatus:
    """One exact repository and default-branch freshness observation."""

    repo_root: str
    status: str
    exit_code: int
    current_branch: str | None
    default_branch: str | None
    remote_name: str | None
    local_default_commit: str | None
    remote_default_commit: str | None
    ahead_count: int | None
    behind_count: int | None
    fetch_attempted: bool
    fetch_succeeded: bool
    fetch_error: str | None
    worktree_dirty: bool | None
    default_status: str | None = None
    current_commit: str | None = None
    current_ahead_count: int | None = None
    current_behind_count: int | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-safe status payload."""

        return asdict(self)


def _run_git(
    repo_root: Path,
    args: list[str],
    *,
    timeout_seconds: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one bounded Git query without raising on ordinary Git failures."""

    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )


def _safe_error(value: str) -> str:
    """Remove URI credentials from a bounded Git error before reporting it."""

    text = value.strip()
    return re.sub(r"([a-z][a-z0-9+.-]*://)[^/@\s]+@", r"\1<redacted>@", text, flags=re.IGNORECASE)


def _unknown(
    *,
    repo_root: Path,
    current_branch: str | None,
    default_branch: str | None,
    remote_name: str | None,
    fetch_attempted: bool,
    fetch_succeeded: bool,
    fetch_error: str,
    worktree_dirty: bool | None,
) -> RepositoryStatus:
    """Build one fail-closed freshness-unknown result."""

    return RepositoryStatus(
        repo_root=str(repo_root),
        status="freshness_unknown",
        exit_code=3,
        current_branch=current_branch,
        default_branch=default_branch,
        remote_name=remote_name,
        local_default_commit=None,
        remote_default_commit=None,
        ahead_count=None,
        behind_count=None,
        fetch_attempted=fetch_attempted,
        fetch_succeeded=fetch_succeeded,
        fetch_error=fetch_error,
        worktree_dirty=worktree_dirty,
    )


def _current_branch(repo_root: Path) -> str | None:
    """Return the checked-out branch, or ``None`` for detached HEAD."""

    result = _run_git(repo_root, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _remote_name(repo_root: Path, default_branch: str | None) -> str | None:
    """Resolve authority remote from the default branch, then fall back to origin."""

    remotes = _run_git(repo_root, ["remote"])
    if remotes.returncode != 0:
        return None
    names = [line.strip() for line in remotes.stdout.splitlines() if line.strip()]
    if default_branch:
        configured = _run_git(repo_root, ["config", "--get", f"branch.{default_branch}.remote"])
        value = configured.stdout.strip()
        if configured.returncode == 0 and value in names and value != ".":
            return value
    if "origin" in names:
        return "origin"
    return names[0] if names else None


def _default_branch(repo_root: Path, remote_name: str) -> str | None:
    """Resolve the remote default branch with a local main/master fallback."""

    symbolic = _run_git(
        repo_root,
        ["symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote_name}/HEAD"],
    )
    value = symbolic.stdout.strip()
    prefix = f"{remote_name}/"
    if symbolic.returncode == 0 and value.startswith(prefix):
        return value.removeprefix(prefix)
    for candidate in ("main", "master"):
        exists = _run_git(repo_root, ["show-ref", "--verify", f"refs/heads/{candidate}"])
        if exists.returncode == 0:
            return candidate
    return None


def _ahead_behind(
    repo_root: Path,
    left_ref: str,
    right_ref: str,
) -> tuple[int, int] | None:
    """Return left-only and right-only commit counts for two Git refs."""

    counts = _run_git(
        repo_root,
        ["rev-list", "--left-right", "--count", f"{left_ref}...{right_ref}"],
    )
    if counts.returncode != 0:
        return None
    try:
        ahead_count, behind_count = (int(value) for value in counts.stdout.split())
    except (TypeError, ValueError):
        return None
    return ahead_count, behind_count


def _drift_status(ahead_count: int, behind_count: int) -> str:
    """Classify one local ref's exact relation to a remote authority ref."""

    if ahead_count and behind_count:
        return "diverged"
    if behind_count:
        return "stale"
    if ahead_count:
        return "ahead"
    return "current"


def inspect_repository(
    repo_root: Path,
    *,
    fetch_remote: bool = True,
    fetch_timeout_seconds: float = DEFAULT_FETCH_TIMEOUT_SECONDS,
) -> RepositoryStatus:
    """Inspect canonical default-branch freshness without mutating local work.

    Fetching updates remote-tracking metadata only. The current branch, local
    branch refs, index, and working-tree bytes are never changed.
    """

    root = repo_root.expanduser().resolve()
    inside = _run_git(root, ["rev-parse", "--is-inside-work-tree"])
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return _unknown(
            repo_root=root,
            current_branch=None,
            default_branch=None,
            remote_name=None,
            fetch_attempted=False,
            fetch_succeeded=False,
            fetch_error="not_a_git_worktree",
            worktree_dirty=None,
        )

    current_branch = _current_branch(root)
    dirty_result = _run_git(root, ["status", "--porcelain"])
    worktree_dirty = bool(dirty_result.stdout.strip()) if dirty_result.returncode == 0 else None
    remote_name = _remote_name(root, None)
    if not remote_name:
        return _unknown(
            repo_root=root,
            current_branch=current_branch,
            default_branch=None,
            remote_name=None,
            fetch_attempted=False,
            fetch_succeeded=False,
            fetch_error="missing_remote",
            worktree_dirty=worktree_dirty,
        )

    default_branch = _default_branch(root, remote_name)
    if not default_branch:
        return _unknown(
            repo_root=root,
            current_branch=current_branch,
            default_branch=None,
            remote_name=remote_name,
            fetch_attempted=False,
            fetch_succeeded=False,
            fetch_error="missing_default_branch",
            worktree_dirty=worktree_dirty,
        )
    tracked_remote_name = _remote_name(root, default_branch)
    if tracked_remote_name:
        remote_name = tracked_remote_name

    if not fetch_remote:
        return _unknown(
            repo_root=root,
            current_branch=current_branch,
            default_branch=default_branch,
            remote_name=remote_name,
            fetch_attempted=False,
            fetch_succeeded=False,
            fetch_error="remote_refresh_not_attempted",
            worktree_dirty=worktree_dirty,
        )

    try:
        fetched = _run_git(
            root,
            ["fetch", "--quiet", "--no-tags", remote_name],
            timeout_seconds=fetch_timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return _unknown(
            repo_root=root,
            current_branch=current_branch,
            default_branch=default_branch,
            remote_name=remote_name,
            fetch_attempted=True,
            fetch_succeeded=False,
            fetch_error=f"remote_refresh_timed_out_after_{fetch_timeout_seconds:g}s",
            worktree_dirty=worktree_dirty,
        )
    if fetched.returncode != 0:
        return _unknown(
            repo_root=root,
            current_branch=current_branch,
            default_branch=default_branch,
            remote_name=remote_name,
            fetch_attempted=True,
            fetch_succeeded=False,
            fetch_error=_safe_error(fetched.stderr or fetched.stdout or "remote_refresh_failed"),
            worktree_dirty=worktree_dirty,
        )

    local_ref = f"refs/heads/{default_branch}"
    remote_ref = f"refs/remotes/{remote_name}/{default_branch}"
    local = _run_git(root, ["rev-parse", "--verify", local_ref])
    remote = _run_git(root, ["rev-parse", "--verify", remote_ref])
    if local.returncode != 0 or remote.returncode != 0:
        return _unknown(
            repo_root=root,
            current_branch=current_branch,
            default_branch=default_branch,
            remote_name=remote_name,
            fetch_attempted=True,
            fetch_succeeded=True,
            fetch_error="missing_local_or_remote_default_ref",
            worktree_dirty=worktree_dirty,
        )

    default_counts = _ahead_behind(root, local_ref, remote_ref)
    if default_counts is None:
        return _unknown(
            repo_root=root,
            current_branch=current_branch,
            default_branch=default_branch,
            remote_name=remote_name,
            fetch_attempted=True,
            fetch_succeeded=True,
            fetch_error="invalid_ahead_behind_result",
            worktree_dirty=worktree_dirty,
        )
    ahead_count, behind_count = default_counts
    default_status = _drift_status(ahead_count, behind_count)

    on_default = current_branch == default_branch
    current = _run_git(root, ["rev-parse", "--verify", "HEAD"])
    current_commit = current.stdout.strip() if current.returncode == 0 else None
    if current_commit is None:
        return _unknown(
            repo_root=root,
            current_branch=current_branch,
            default_branch=default_branch,
            remote_name=remote_name,
            fetch_attempted=True,
            fetch_succeeded=True,
            fetch_error="missing_current_commit",
            worktree_dirty=worktree_dirty,
        )
    current_counts = _ahead_behind(root, "HEAD", remote_ref)
    if current_counts is None:
        return _unknown(
            repo_root=root,
            current_branch=current_branch,
            default_branch=default_branch,
            remote_name=remote_name,
            fetch_attempted=True,
            fetch_succeeded=True,
            fetch_error="invalid_current_ahead_behind_result",
            worktree_dirty=worktree_dirty,
        )
    current_ahead_count, current_behind_count = current_counts

    if on_default:
        status = default_status
        exit_code = 0 if status == "current" else 2
    elif current_behind_count:
        status, exit_code = "feature_base_stale", 0
    else:
        status, exit_code = "feature", 0

    return RepositoryStatus(
        repo_root=str(root),
        status=status,
        exit_code=exit_code,
        current_branch=current_branch,
        default_branch=default_branch,
        remote_name=remote_name,
        local_default_commit=local.stdout.strip(),
        remote_default_commit=remote.stdout.strip(),
        ahead_count=ahead_count,
        behind_count=behind_count,
        fetch_attempted=True,
        fetch_succeeded=True,
        fetch_error=None,
        worktree_dirty=worktree_dirty,
        default_status=default_status,
        current_commit=current_commit,
        current_ahead_count=current_ahead_count,
        current_behind_count=current_behind_count,
    )
