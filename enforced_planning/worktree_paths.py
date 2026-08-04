"""Importable workspace and canonical-repo path helpers."""

from __future__ import annotations

from pathlib import Path


def detect_workspace_root(project_root: Path) -> Path:
    """Resolve the shared workspace root from main or worktree checkouts."""
    resolved_project_root = project_root.resolve()
    parent = resolved_project_root.parent
    if parent.name == "worktrees":
        return parent.parent.parent
    if parent.name.endswith("_worktrees"):
        return parent.parent
    return resolved_project_root.parent


def resolve_canonical_repo_root(repo_root: Path) -> Path:
    """Return the canonical repo root for a main checkout or worktree clone."""
    resolved_repo_root = repo_root.resolve()
    # Branches containing "/" create nested paths such as
    # <repo>/worktrees/feat/name. The target may already be absent during an
    # idempotent closeout, so resolve lexically through every ancestor rather
    # than relying on the immediate parent or an existing .git file.
    for ancestor in (resolved_repo_root, *resolved_repo_root.parents):
        if ancestor.name == "worktrees":
            canonical_repo_root = ancestor.parent.resolve()
            if (canonical_repo_root / ".git").exists():
                return canonical_repo_root
        if ancestor.name.endswith("_worktrees"):
            workspace_root = ancestor.parent
            canonical_name = ancestor.name.removesuffix("_worktrees")
            canonical_repo_root = (workspace_root / canonical_name).resolve()
            if (canonical_repo_root / ".git").exists():
                return canonical_repo_root
    return resolved_repo_root


__all__ = ["detect_workspace_root", "resolve_canonical_repo_root"]


def resolve_canonical_target_path(*, target_path: Path, repo_root: Path) -> Path | None:
    """Map a missing worktree-local path to the canonical repo root when safe.

    This only applies when the candidate path is lexically inside the active
    repo root. Paths outside the repo root are left alone because they may be
    genuine workspace-relative or sibling-repo targets.
    """
    resolved_repo_root = repo_root.resolve()
    canonical_repo_root = resolve_canonical_repo_root(resolved_repo_root)
    if canonical_repo_root == resolved_repo_root:
        return None

    candidate = target_path.expanduser()
    try:
        relative_target = candidate.relative_to(resolved_repo_root)
    except ValueError:
        return None

    canonical_target = (canonical_repo_root / relative_target).resolve(strict=False)
    if canonical_target.exists():
        return canonical_target
    return None


__all__ = [
    "detect_workspace_root",
    "resolve_canonical_repo_root",
    "resolve_canonical_target_path",
]
