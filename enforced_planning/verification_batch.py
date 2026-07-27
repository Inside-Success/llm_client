"""Freeze terminal verification to immutable Git bytes until explicit invalidation.

The batch state lives in the worktree-specific Git directory so it cannot pollute
the reviewed diff.  A frozen batch is deliberately narrow: it proves only that
the named decision and command still refer to the exact clean commit that began
verification.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import posixpath
import subprocess
from typing import Any


class VerificationBatchError(RuntimeError):
    """Report malformed state or mutation of a frozen verification batch."""


@dataclass(frozen=True)
class VerificationBatch:
    """Bind one terminal verification decision to exact Git bytes."""

    schema_version: int
    status: str
    branch: str
    revision: str
    decision: str
    command: str
    allowed_untracked: tuple[str, ...]
    frozen_at: str

    def to_dict(self) -> dict[str, Any]:
        """Return stable JSON-safe batch state for agents and hooks."""

        return asdict(self)


def _git(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run Git with captured output so failures remain actionable."""

    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise VerificationBatchError(f"git {' '.join(args)} failed: {detail}")
    return result


def resolve_repo_root(repo_root: Path) -> Path:
    """Resolve a caller path to the exact Git worktree under verification."""

    result = _git(repo_root.expanduser().resolve(), "rev-parse", "--show-toplevel")
    return Path(result.stdout.strip()).resolve()


def _git_private_path(repo_root: Path, name: str) -> Path:
    """Return a worktree-local untracked Git metadata path."""

    result = _git(repo_root, "rev-parse", "--git-path", name)
    path = Path(result.stdout.strip())
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def state_path(repo_root: Path) -> Path:
    """Return the private state path for the current worktree."""

    root = resolve_repo_root(repo_root)
    return _git_private_path(root, "verification-batch.json")


def history_path(repo_root: Path) -> Path:
    """Return the append-only local invalidation history path."""

    root = resolve_repo_root(repo_root)
    return _git_private_path(root, "verification-batch-history.jsonl")


def _head(repo_root: Path) -> str:
    """Return the exact commit currently checked out."""

    return _git(repo_root, "rev-parse", "HEAD").stdout.strip()


def _branch(repo_root: Path) -> str:
    """Return the symbolic branch and reject detached verification targets."""

    result = _git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise VerificationBatchError("verification batch requires a named branch, not detached HEAD")
    return result.stdout.strip()


def _tracked_dirty(repo_root: Path) -> bool:
    """Return whether staged or unstaged tracked bytes differ from HEAD."""

    unstaged = _git(repo_root, "diff", "--quiet", check=False)
    staged = _git(repo_root, "diff", "--cached", "--quiet", check=False)
    return unstaged.returncode != 0 or staged.returncode != 0


def _normalize_relative_path(path: str) -> str:
    """Normalize one allowlisted repository-relative path without escape."""

    raw = path.strip().replace("\\", "/")
    if raw.startswith("/"):
        raise VerificationBatchError(f"allowed untracked path must be relative: {path!r}")
    normalized = posixpath.normpath(raw)
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or normalized == "." or normalized == ".." or normalized.startswith("../"):
        raise VerificationBatchError(f"allowed untracked path must stay within the repository: {path!r}")
    return normalized.rstrip("/")


def _untracked_paths(repo_root: Path) -> tuple[str, ...]:
    """Return every untracked, non-ignored file because it may affect execution."""

    result = _git(repo_root, "ls-files", "--others", "--exclude-standard", "-z")
    return tuple(sorted(item for item in result.stdout.split("\0") if item))


def _unexpected_untracked(repo_root: Path, allowed: tuple[str, ...]) -> tuple[str, ...]:
    """Return untracked files not covered by an explicit exact path or subtree."""

    return tuple(
        path
        for path in _untracked_paths(repo_root)
        if not any(path == prefix or path.startswith(prefix + "/") for prefix in allowed)
    )


def load_batch(repo_root: Path) -> VerificationBatch | None:
    """Load and strictly validate the active worktree batch, if any."""

    root = resolve_repo_root(repo_root)
    path = _git_private_path(root, "verification-batch.json")
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationBatchError(f"cannot read verification batch state: {exc}") from exc
    required = {
        "schema_version",
        "status",
        "branch",
        "revision",
        "decision",
        "command",
        "allowed_untracked",
        "frozen_at",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise VerificationBatchError("verification batch state has an unsupported schema")
    if payload["schema_version"] != 1 or payload["status"] != "frozen":
        raise VerificationBatchError("verification batch state is not an active schema-v1 freeze")
    string_fields = required - {"schema_version", "allowed_untracked"}
    if not all(isinstance(payload[key], str) and payload[key].strip() for key in string_fields):
        raise VerificationBatchError("verification batch string fields must be non-empty")
    allowed = payload["allowed_untracked"]
    if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
        raise VerificationBatchError("verification batch allowed_untracked must be a string list")
    return VerificationBatch(**{**payload, "allowed_untracked": tuple(allowed)})


def freeze_batch(
    repo_root: Path,
    *,
    decision: str,
    command: str,
    allowed_untracked: tuple[str, ...] = (),
) -> VerificationBatch:
    """Freeze a clean named branch at HEAD for one terminal decision."""

    root = resolve_repo_root(repo_root)
    normalized_decision = decision.strip()
    normalized_command = command.strip()
    if not normalized_decision or not normalized_command:
        raise VerificationBatchError("decision and command are required")
    if _tracked_dirty(root):
        raise VerificationBatchError("cannot freeze: staged or unstaged tracked bytes differ from HEAD")
    normalized_allowed = tuple(sorted({_normalize_relative_path(path) for path in allowed_untracked}))
    unexpected = _unexpected_untracked(root, normalized_allowed)
    if unexpected:
        raise VerificationBatchError(
            "cannot freeze: untracked files are not captured by the revision: " + ", ".join(unexpected)
        )
    existing = load_batch(root)
    if existing is not None:
        raise VerificationBatchError(
            f"verification batch already frozen at {existing.revision}; check or thaw it explicitly"
        )
    batch = VerificationBatch(
        schema_version=1,
        status="frozen",
        branch=_branch(root),
        revision=_head(root),
        decision=normalized_decision,
        command=normalized_command,
        allowed_untracked=normalized_allowed,
        frozen_at=datetime.now(timezone.utc).isoformat(),
    )
    path = _git_private_path(root, "verification-batch.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(batch.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return batch


def check_batch(repo_root: Path, *, require_active: bool = False) -> VerificationBatch | None:
    """Fail if an active batch no longer names the current clean branch bytes."""

    root = resolve_repo_root(repo_root)
    batch = load_batch(root)
    if batch is None:
        if require_active:
            raise VerificationBatchError("no active verification batch")
        return None
    current_branch = _branch(root)
    current_head = _head(root)
    failures: list[str] = []
    if current_branch != batch.branch:
        failures.append(f"branch changed from {batch.branch} to {current_branch}")
    if current_head != batch.revision:
        failures.append(f"HEAD changed from {batch.revision} to {current_head}")
    if _tracked_dirty(root):
        failures.append("staged or unstaged tracked bytes differ from frozen HEAD")
    unexpected = _unexpected_untracked(root, batch.allowed_untracked)
    if unexpected:
        failures.append("untracked files are not allowlisted: " + ", ".join(unexpected))
    if failures:
        raise VerificationBatchError("verification batch invalid: " + "; ".join(failures))
    return batch


def thaw_batch(repo_root: Path, *, reason: str) -> VerificationBatch:
    """Invalidate a batch explicitly and retain a local audit record."""

    root = resolve_repo_root(repo_root)
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise VerificationBatchError("thaw requires a non-empty invalidation reason")
    batch = load_batch(root)
    if batch is None:
        raise VerificationBatchError("no active verification batch to thaw")
    record = {
        **batch.to_dict(),
        "status": "invalidated",
        "invalidated_at": datetime.now(timezone.utc).isoformat(),
        "invalidation_reason": normalized_reason,
        "observed_branch": _branch(root),
        "observed_revision": _head(root),
    }
    history = _git_private_path(root, "verification-batch-history.jsonl")
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
    _git_private_path(root, "verification-batch.json").unlink()
    return batch
