"""Git utilities for truthful llm_client experiment provenance."""

import subprocess
from collections.abc import Sequence
from pathlib import Path


def _git_output(arguments: Sequence[str], *, cwd: Path | None = None) -> str | None:
    """Return git stdout, or ``None`` when the directory is not a Git worktree."""

    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _nul_paths(output: str | None) -> list[str]:
    """Parse a NUL-delimited Git path list into stable unique paths."""

    if output is None:
        return []
    return sorted({path for path in output.split("\0") if path})


def get_git_head() -> str | None:
    """Return the current git HEAD commit hash, or None if not in a repo."""

    output = _git_output(("rev-parse", "HEAD"))
    return output.strip() if output else None


def get_working_tree_files() -> list[str]:
    """Return tracked and untracked paths changed from ``HEAD`` in the current worktree."""

    tracked = _nul_paths(_git_output(("diff", "--name-only", "-z", "HEAD", "--")))
    untracked = _nul_paths(
        _git_output(("ls-files", "--others", "--exclude-standard", "-z", "--"))
    )
    return sorted(set(tracked) | set(untracked))


def is_git_dirty() -> bool:
    """Return whether the current worktree has tracked or untracked changes."""

    return bool(get_working_tree_files())


def get_diff_files(base_commit: str, candidate_commit: str) -> list[str]:
    """Return paths changed between two commits, failing loud for invalid revisions."""

    output = _git_output(
        ("diff", "--name-only", "-z", base_commit, candidate_commit, "--")
    )
    if output is None:
        raise ValueError(
            f"cannot compute git diff for revisions {base_commit!r} and {candidate_commit!r}"
        )
    return _nul_paths(output)


def classify_diff_files(files: Sequence[str]) -> set[str]:
    """Classify changed paths into compact experiment-comparison categories."""

    categories: set[str] = set()
    for file_name in files:
        path = Path(file_name)
        first = path.parts[0] if path.parts else ""
        if first in {"tests", "test"}:
            categories.add("tests")
        elif first in {"docs", "notebooks"} or path.suffix.lower() in {".md", ".rst"}:
            categories.add("docs")
        elif first in {"prompts"}:
            categories.add("prompts")
        elif first in {"config", "configs"} or path.suffix.lower() in {".yaml", ".yml", ".toml"}:
            categories.add("config")
        elif path.suffix.lower() in {".py", ".js", ".jsx", ".ts", ".tsx"}:
            categories.add("code")
        else:
            categories.add("other")
    return categories
