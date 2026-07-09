"""Verify the portable worktree lifecycle contract installed in this consumer."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def _canonical_repo_root() -> Path:
    """Resolve the primary checkout from Git's shared administrative dir."""
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip()).parent


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    """Run an installed governance script from the repository root."""
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_installed_creator_defaults_inside_repo() -> None:
    """Keep new worktrees under the canonical repository, never a sibling."""
    result = _run_script(
        "scripts/meta/worktree-coordination/create_worktree.py",
        "--repo-root",
        ".",
        "--print-default-worktree-dir",
    )

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == _canonical_repo_root() / "worktrees"
    assert "worktrees/" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_installed_closeout_exposes_disposition_contract() -> None:
    """Keep merge-or-disposition evidence available through the consumer CLI."""
    result = _run_script("scripts/meta/session_close.py", "--help")

    assert result.returncode == 0, result.stderr
    assert "--disposition" in result.stdout
    assert "--disposition-reason" in result.stdout
    assert "--recovery-ref" in result.stdout
    assert "--allow-discard-unique" in result.stdout


def test_lifecycle_vocabulary_is_installed() -> None:
    """Load the constrained disposition vocabulary from the installed config."""
    config_path = REPO_ROOT / "enforced_planning" / "worktree_lifecycle.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert config == {
        "schema_version": 1,
        "dispositions": {
            "merged": "merged",
            "non_closeable": ["active", "handoff"],
            "recovery_required": ["superseded", "archived", "migrated"],
            "discard_requires_authorization": ["abandoned"],
        },
    }
