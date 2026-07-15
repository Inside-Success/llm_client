"""Real-repository controls for experiment Git provenance helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from llm_client.utils import git_utils


def _git(repo: Path, *arguments: str) -> str:
    """Run Git in a temporary real repository and return stdout."""

    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a committed repository and enter it for helpers that use process cwd."""

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-q", "-m", "baseline")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_working_tree_provenance_includes_tracked_staged_and_untracked(
    git_repo: Path,
) -> None:
    """A dirty readout covers every path class used during an experiment run."""

    (git_repo / "tracked.txt").write_text("modified\n", encoding="utf-8")
    (git_repo / "staged.txt").write_text("staged\n", encoding="utf-8")
    (git_repo / "untracked file.txt").write_text("untracked\n", encoding="utf-8")
    _git(git_repo, "add", "staged.txt")

    assert git_utils.is_git_dirty()
    assert git_utils.get_working_tree_files() == [
        "staged.txt",
        "tracked.txt",
        "untracked file.txt",
    ]


def test_commit_diff_and_categories_use_real_git_history(git_repo: Path) -> None:
    """Commit comparisons return exact paths and useful stable categories."""

    base = git_utils.get_git_head()
    assert base is not None
    (git_repo / "tests").mkdir()
    (git_repo / "tests" / "test_feature.py").write_text("assert True\n", encoding="utf-8")
    (git_repo / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(git_repo, "add", "tests/test_feature.py", "feature.py")
    _git(git_repo, "commit", "-q", "-m", "feature")
    candidate = git_utils.get_git_head()
    assert candidate is not None

    files = git_utils.get_diff_files(base, candidate)

    assert files == ["feature.py", "tests/test_feature.py"]
    assert git_utils.classify_diff_files(files) == {"code", "tests"}


def test_invalid_diff_revisions_fail_loud(git_repo: Path) -> None:
    """Comparison does not turn an invalid revision into an empty clean diff."""

    head = git_utils.get_git_head()
    assert head is not None
    with pytest.raises(ValueError, match="cannot compute git diff"):
        git_utils.get_diff_files("not-a-revision", head)
