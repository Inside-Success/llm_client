#!/usr/bin/env python3
"""Cross-brain coordination claims for multi-agent work.

Manages scope claims across agent brains (claude-code, codex, openclaw).
Claims are YAML files in ``~/.claude/coordination/claims/``.

The v2 model preserves backwards-compatible v1 loading while adding the narrow
write-scope metadata needed for real collision avoidance.

Usage:
    check_coordination_claims.py --check [--project PROJECT]
    check_coordination_claims.py --claim --agent AGENT --project PROJECT --scope SCOPE --intent INTENT [--plan PLAN] [--ttl-hours TTL]
    check_coordination_claims.py --release --agent AGENT --project PROJECT --scope SCOPE
    check_coordination_claims.py --list
    check_coordination_claims.py --prune
    check_coordination_claims.py --prune-completed
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import posixpath
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from enforced_planning import claim_mutation_receipts
from enforced_planning.claim_mutation_receipts import (
    CompletedClaimArchiveError,
    MutationAuditError,
)

_LOADED_WRITER_IDENTITY = claim_mutation_receipts.writer_identity(Path(__file__))

CLAIMS_DIR = Path.home() / ".claude" / "coordination" / "claims"
DEFAULT_TTL_HOURS = 24  # Sprints run 24h; 2h caused false-expiry conflicts mid-sprint
LIVE_STATUSES = {"active", "blocked", "handoff"}
COMPLETED_STATUSES = {"complete", "completed"}
SESSION_ENDED_STATUS = "session_ended"
CLOSEABLE_STATUSES = LIVE_STATUSES | {SESSION_ENDED_STATUS}
CLAIM_TYPES = {"program", "write", "review", "research"}
STRICT_LIVE_METADATA_CLAIM_TYPES = {"program", "write", "review", "research"}
CREATION_BLOCKING_HEALTH_ISSUES = {
    "missing_project",
    "missing_write_paths",
    "missing_branch",
    "missing_worktree_path",
    "missing_session_id",
    "missing_session_name",
    "missing_work_unit_id",
    "missing_work_graph_path",
    "missing_work_graph_sha256",
}
DEFAULT_HEARTBEAT_STALE_MINUTES = 120
CLAIM_WRITE_STAGING_MAX_AGE_SECONDS = 300
_LEGACY_CLAIM_TEMP_PATTERN = re.compile(r"^\..+\.ya?ml\.[A-Za-z0-9_-]+\.tmp$")
# CLAUDE_SESSION_ID is never set by the Claude Code runtime (it only appears
# as an unresolved ${...} template substitution in skill prompts).
# CLAUDE_CODE_SSE_PORT is shared by every concurrent Claude Code session the
# CLI server spawns on one machine, so keying identity off it collides
# multiple sessions onto the same claim identity. CLAUDE_CODE_SESSION_ID is
# the genuine per-conversation UUID Claude Code actually sets in Bash-tool
# and hook subprocess environments; it must be checked first.
SESSION_ENV_KEYS = {
    "codex": ("CODEX_THREAD_ID",),
    "claude-code": ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID", "CLAUDE_CODE_SSE_PORT"),
    "openclaw": ("OPENCLAW_SESSION_ID", "OPENCLAW_RUN_ID"),
}
STRICT_NATIVE_SESSION_ENV_KEYS = {
    "codex": "CODEX_THREAD_ID",
    "claude-code": "CLAUDE_CODE_SESSION_ID",
    "openclaw": "OPENCLAW_SESSION_ID",
}


@contextmanager
def claim_registry_lock(claims_dir: Path | None = None) -> Iterator[None]:
    """Serialize claim check-and-write mutations across local agent processes."""

    resolved_claims_dir = (claims_dir or CLAIMS_DIR).expanduser().resolve()
    resolved_claims_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = resolved_claims_dir.parent / f".{resolved_claims_dir.name}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        lock_path.chmod(0o600)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            _prune_abandoned_claim_write_artifacts(resolved_claims_dir)
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _claim_write_staging_dir(claims_dir: Path) -> Path:
    """Return same-filesystem staging outside the live claim registry."""

    return claims_dir.parent / f".{claims_dir.name}-write-staging"


def _prune_abandoned_claim_write_artifacts(
    claims_dir: Path,
    *,
    minimum_age_seconds: int = CLAIM_WRITE_STAGING_MAX_AGE_SECONDS,
) -> int:
    """Remove only old atomic-write artifacts from sanctioned claim writers."""

    now = time.time()
    staging_dir = _claim_write_staging_dir(claims_dir)
    candidates = [path for path in claims_dir.glob(".*.tmp") if _LEGACY_CLAIM_TEMP_PATTERN.fullmatch(path.name)]
    if staging_dir.exists():
        candidates.extend(staging_dir.glob("*.tmp"))
    removed = 0
    for candidate in candidates:
        try:
            age = now - candidate.lstat().st_mtime
        except FileNotFoundError:
            continue
        if age < minimum_age_seconds:
            continue
        if not (candidate.is_file() or candidate.is_symlink()):
            continue
        candidate.unlink(missing_ok=True)
        removed += 1
    return removed


def _atomic_write_claim(path: Path, payload: dict[str, Any]) -> None:
    """Replace one claim without exposing a truncated or partially written file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = _claim_write_staging_dir(path.parent)
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.chmod(0o700)
    _prune_abandoned_claim_write_artifacts(path.parent)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=staging_dir,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            yaml.safe_dump(
                payload,
                handle,
                default_flow_style=False,
                sort_keys=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def refresh_prewrite_authority_projection(
    claims_dir: Path | None = None,
) -> tuple[str, str]:
    """Regenerate the replaceable pre-write projection from canonical YAML."""

    from enforced_planning.prewrite_claim_fast import projection_path_for
    from enforced_planning.prewrite_claim_projection import write_projection

    resolved = (claims_dir or CLAIMS_DIR).expanduser().resolve()
    projection = write_projection(claims_dir=resolved)
    return str(projection_path_for(resolved)), projection.registry_digest


def _registry_digest(claims_dir: Path) -> str:
    """Return the canonical digest used to bind derived projection state."""

    from enforced_planning.prewrite_claim_fast import registry_digest

    return registry_digest(claims_dir.expanduser().resolve())


def record_claim_mutation(
    *,
    operation: "claim_mutation_receipts.MutationOperation",
    claims_dir: Path,
    registry_digest_before: str | None,
    target_project: str | None,
    target_scope: str | None,
    target_claim_path: Path | None,
    session_id: str | None,
    projection_digest_after: str | None,
    archive_transaction_id: str | None = None,
) -> "claim_mutation_receipts.ClaimMutationReceiptV1":
    """Persist one terminal receipt after a sanctioned YAML/projection mutation.

    The YAML registry remains authoritative. This append-only ledger records
    which loaded runtime performed the mutation and whether the projection it
    produced still matches that authority.
    """

    from enforced_planning.prewrite_claim_projection import projection_is_current

    resolved_claims_dir = claims_dir.expanduser().resolve()
    registry_digest_after = _registry_digest(resolved_claims_dir)
    projection_current_after = projection_is_current(claims_dir=resolved_claims_dir)
    result: claim_mutation_receipts.MutationResult = (
        "applied_projection_current" if projection_current_after else "applied_projection_stale"
    )
    # Capture provenance when this module is loaded. Session closeout may
    # intentionally remove the worktree containing this source file before the
    # final receipt is emitted, but the loaded runtime remains the writer.
    writer_source_path, writer_source_sha256, writer_repo_root = _LOADED_WRITER_IDENTITY
    receipt = claim_mutation_receipts.ClaimMutationReceiptV1(
        operation=operation,
        result=result,
        writer_source_path=writer_source_path,
        writer_source_sha256=writer_source_sha256,
        writer_repo_root=writer_repo_root,
        process_id=os.getpid(),
        session_id=session_id,
        target_project=target_project,
        target_scope=target_scope,
        target_claim_path=str(target_claim_path) if target_claim_path else None,
        registry_digest_before=registry_digest_before,
        registry_digest_after=registry_digest_after,
        projection_digest_after=projection_digest_after,
        projection_current_after=projection_current_after,
        archive_transaction_id=archive_transaction_id,
        error_code=None,
    )
    try:
        claim_mutation_receipts.append_receipt(receipt)
    except OSError as exc:
        raise claim_mutation_receipts.MutationAuditError(
            operation=operation,
            target_project=target_project,
            target_scope=target_scope,
            registry_digest_after=registry_digest_after,
            projection_digest_after=projection_digest_after,
            projection_current_after=projection_current_after,
            cause=exc,
        ) from exc
    return receipt


@dataclass(frozen=True)
class ClaimRecord:
    """Normalized coordination claim record used across v1 and v2 schemas."""

    agent: str
    claimed_at: str | None
    expires_at: str | None
    projects: list[str]
    scope: str
    intent: str
    claim_type: str
    write_paths: list[str]
    read_paths: list[str]
    worktree_path: str | None
    repo_root: str | None
    branch: str | None
    session_name: str | None
    broader_goal: str | None
    tracker_path: str | None
    session_id: str | None
    heartbeat_at: str | None
    status: str
    updated_at: str | None
    parent_scope: str | None
    notes: str | None
    plan_ref: str | None
    source_file: str | None
    schema_version: int
    work_unit_id: str | None = None
    work_graph_path: str | None = None
    work_graph_sha256: str | None = None
    approval_revisions: tuple[str, ...] = ()
    parallel_root_authorized: bool = False

    def primary_project(self) -> str | None:
        """Return the first project for CLI compatibility surfaces."""
        return self.projects[0] if self.projects else None

    def is_live(self) -> bool:
        """Return whether the claim should participate in active coordination."""
        return self.status in LIVE_STATUSES

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON/YAML-safe dictionary for reporting and persistence."""
        data = asdict(self)
        data["project"] = self.primary_project()
        return data


@dataclass(frozen=True)
class ClaimInteraction:
    """Describe how one candidate claim interacts with another active claim."""

    severity: str
    reason: str
    other_agent: str
    other_scope: str
    other_claim_type: str
    projects: list[str]
    overlapping_write_paths: list[str]
    other_source_file: str | None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe interaction summary."""
        return asdict(self)


@dataclass(frozen=True)
class ClaimCheckResult:
    """Structured result for candidate-vs-active-claims evaluation."""

    candidate: ClaimRecord
    interactions: list[ClaimInteraction]

    @property
    def hard_conflicts(self) -> list[ClaimInteraction]:
        """Return hard-conflict interactions only."""
        return [item for item in self.interactions if item.severity == "hard_conflict"]

    def continuation(self) -> dict[str, Any]:
        """Describe safe work that remains outside path-local claim conflicts.

        Claim evaluation can determine whether this candidate is blocked on
        particular write paths. It cannot determine whether the caller's whole
        authorized goal has exhausted its ready queue, so a claim collision is
        never reported as a whole-goal blocker.
        """
        conflicts = self.hard_conflicts
        blocked_paths = sorted(
            {overlap.split(" <-> ", 1)[0] for conflict in conflicts for overlap in conflict.overlapping_write_paths}
        )
        writable_paths = sorted(
            {
                _normalize_repo_path(path)
                for path in self.candidate.write_paths
                if _normalize_repo_path(path) not in blocked_paths
            }
        )
        integration_owners = sorted({(conflict.other_agent, conflict.other_scope) for conflict in conflicts})
        if not conflicts:
            recommended_next_action = "Proceed with the candidate claim."
        elif writable_paths:
            recommended_next_action = (
                "Remove or defer the blocked paths, claim the remaining writable paths, "
                "and continue. Record an authority-reconciliation obligation when the "
                "deferred path indexes or governs the completed artifact."
            )
        else:
            recommended_next_action = (
                "This candidate is path-blocked. Checkpoint any completed work and move "
                "to another authorized ready work unit; report the whole goal blocked only "
                "after its complete ready queue has been evaluated."
            )
        return {
            "state": "integration_wait" if conflicts else "ready",
            "goal_blocked": False,
            "blocked_paths": blocked_paths,
            "writable_paths": writable_paths,
            "integration_owners": [{"agent": agent, "scope": scope} for agent, scope in integration_owners],
            "recommended_next_action": recommended_next_action,
        }

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe check result."""
        return {
            "candidate": self.candidate.to_dict(),
            "interactions": [item.to_dict() for item in self.interactions],
            "has_hard_conflict": bool(self.hard_conflicts),
            "continuation": self.continuation(),
        }


def claim_health_issues(claim: ClaimRecord) -> list[str]:
    """Return machine-readable health issues for one normalized claim."""
    issues: list[str] = []
    if not claim.projects:
        issues.append("missing_project")
    if claim.claim_type == "write" and not claim.write_paths:
        issues.append("missing_write_paths")
    if claim.is_live() and claim.claim_type in STRICT_LIVE_METADATA_CLAIM_TYPES:
        if not claim.branch:
            issues.append("missing_branch")
        if not claim.worktree_path:
            issues.append("missing_worktree_path")
        if not claim.session_id:
            issues.append("missing_session_id")
        if not claim.session_name:
            issues.append("missing_session_name")
        if claim.plan_ref and claim.session_id:
            if not claim.repo_root:
                issues.append("missing_repo_root")
            if not claim.broader_goal:
                issues.append("missing_broader_goal")
            if not claim.tracker_path:
                issues.append("missing_tracker_path")
        if claim.schema_version >= 3 and claim.write_paths and claim.plan_ref:
            if not claim.work_unit_id:
                issues.append("missing_work_unit_id")
            if not claim.work_graph_path:
                issues.append("missing_work_graph_path")
            if not claim.work_graph_sha256:
                issues.append("missing_work_graph_sha256")
    return issues


def claim_health_status(claim: ClaimRecord) -> str:
    """Classify one claim as healthy or weak for registry/reporting surfaces."""
    return "weak" if claim_health_issues(claim) else "healthy"


def normalize_plan_identity(plan_ref: str | None) -> str | None:
    """Return one stable numbered-plan identity from descriptive plan text."""

    if not isinstance(plan_ref, str):
        return None
    qualified = re.fullmatch(
        r"\s*([A-Za-z0-9_.-]+)#0*(\d+)\s*",
        plan_ref,
        flags=re.IGNORECASE,
    )
    if qualified:
        project = qualified.group(1).lower().replace("_", "-")
        return f"{project}#{int(qualified.group(2))}"
    match = re.search(r"\bPlan\s*#\s*0*(\d+)\b", plan_ref, flags=re.IGNORECASE)
    if not match:
        return None
    return f"Plan #{int(match.group(1))}"


def _same_claim(left: ClaimRecord, right: ClaimRecord) -> bool:
    """Return whether two records identify the same canonical claim slot."""

    return left.agent == right.agent and left.primary_project() == right.primary_project() and left.scope == right.scope


def claim_hierarchy_issues(
    claim: ClaimRecord,
    *,
    active_claims: list[ClaimRecord],
) -> list[str]:
    """Validate one claim against the existing root-program hierarchy.

    A single live session remains valid on its own. Once execution for the same
    project and normalized numbered plan becomes parallel, exactly one
    unparented program claim coordinates every other claim through
    ``parent_scope``.
    """

    if not claim.is_live() or not claim.session_id:
        return []
    project = claim.primary_project()
    plan_identity = normalize_plan_identity(claim.plan_ref)
    if not project or not plan_identity:
        return []

    issues: list[str] = []
    if claim.parent_scope:
        if claim.parent_scope == claim.scope:
            issues.append("self_parent_scope")
        parents = [
            other
            for other in active_claims
            if other.is_live()
            and other.primary_project() == project
            and other.scope == claim.parent_scope
            and not _same_claim(other, claim)
        ]
        if not parents:
            issues.append("missing_parent_claim")
        elif len(parents) > 1:
            issues.append("ambiguous_parent_scope")
        else:
            parent = parents[0]
            if parent.claim_type != "program":
                issues.append("parent_not_program")
            if not parent.session_id or claim_health_issues(parent):
                issues.append("parent_not_healthy")
            if normalize_plan_identity(parent.plan_ref) != plan_identity:
                issues.append("parent_plan_mismatch")

    cohort = [
        other
        for other in active_claims
        if other.is_live()
        and other.session_id
        and other.primary_project() == project
        and normalize_plan_identity(other.plan_ref) == plan_identity
    ]
    if not any(_same_claim(other, claim) for other in cohort):
        cohort.append(claim)
    if len(cohort) < 2:
        return list(dict.fromkeys(issues))

    roots = [other for other in cohort if other.claim_type == "program" and not other.parent_scope]
    if not roots:
        issues.append("missing_program_root")
    elif len(roots) > 1:
        issues.append("multiple_program_roots")
    else:
        root = roots[0]
        if not _same_claim(root, claim):
            if not claim.parent_scope:
                issues.append("missing_parent_scope")
            elif claim.parent_scope != root.scope:
                issues.append("wrong_parent_scope")
    return list(dict.fromkeys(issues))


def coordination_health_issues(
    claim: ClaimRecord,
    *,
    active_claims: list[ClaimRecord],
) -> list[str]:
    """Return local metadata plus cross-claim hierarchy health issues."""

    return list(dict.fromkeys(claim_health_issues(claim) + claim_hierarchy_issues(claim, active_claims=active_claims)))


def validate_claim_hierarchy_for_creation(
    candidate: ClaimRecord,
    *,
    active_claims: list[ClaimRecord],
) -> None:
    """Reject a new or refreshed session claim that would be hierarchically invalid."""

    prospective = [claim for claim in active_claims if not _same_claim(claim, candidate)] + [candidate]
    issues = claim_hierarchy_issues(candidate, active_claims=prospective)
    if issues:
        raise ValueError(
            f"Invalid plan claim hierarchy for {candidate.primary_project()}:{candidate.scope}: {', '.join(issues)}"
        )


def session_root_conflicts(
    claim: ClaimRecord,
    *,
    active_claims: list[ClaimRecord],
) -> list[ClaimRecord]:
    """Return other unparented lanes owned by the exact runtime session.

    Claim type classifies the work and its conflict semantics; it does not
    determine whether a lane is a session root. Any live claim without
    ``parent_scope`` is an ownership root for this lifecycle guard.
    """

    if not claim.is_live() or not claim.session_id or claim.parent_scope:
        return []
    return sorted(
        (
            other
            for other in active_claims
            if other.is_live()
            and other.session_id == claim.session_id
            and not other.parent_scope
            and not _same_claim(other, claim)
        ),
        key=lambda item: (item.primary_project() or "", item.scope),
    )


def validate_session_root_for_creation(
    candidate: ClaimRecord,
    *,
    active_claims: list[ClaimRecord],
) -> None:
    """Reject accidental tangent roots while preserving explicit parallelism."""

    conflicts = session_root_conflicts(candidate, active_claims=active_claims)
    if not conflicts or candidate.parallel_root_authorized:
        return
    identities = ", ".join(f"{claim.primary_project()}:{claim.scope}" for claim in conflicts)
    raise ValueError(
        "Runtime session already owns an unresolved root lane: "
        f"{identities}. Start a child with --parent-scope, close/transfer the "
        "existing root, or pass --allow-parallel for intentional parallel roots."
    )


def validate_no_preserved_lane_conflict(
    candidate: ClaimRecord,
    *,
    claims: list[ClaimRecord],
) -> None:
    """Require explicit recovery before replacing preserved ended work."""

    candidate_project = candidate.primary_project()
    candidate_plan = normalize_plan_identity(candidate.plan_ref)
    conflicts: list[ClaimRecord] = []
    for other in claims:
        if other.status != SESSION_ENDED_STATUS or _same_claim(other, candidate):
            continue
        if candidate_project not in other.projects:
            continue
        same_plan = bool(candidate_plan and normalize_plan_identity(other.plan_ref) == candidate_plan)
        write_overlap = bool(_compute_overlapping_write_paths(candidate, other))
        if same_plan or write_overlap:
            conflicts.append(other)
    if not conflicts:
        return
    identities = ", ".join(f"{claim.primary_project()}:{claim.scope}" for claim in conflicts)
    raise ValueError(
        "Preserved session-ended lane(s) still require disposition: "
        f"{identities}. Resume/take over the existing lane or close it through "
        "the sanctioned merge/recovery path before creating a replacement."
    )


def _heartbeat_stale_after() -> timedelta:
    """Return the configured heartbeat freshness window."""
    raw = os.environ.get("COORDINATION_HEARTBEAT_STALE_MINUTES", "").strip()
    if not raw:
        return timedelta(minutes=DEFAULT_HEARTBEAT_STALE_MINUTES)
    try:
        minutes = float(raw)
    except ValueError:
        return timedelta(minutes=DEFAULT_HEARTBEAT_STALE_MINUTES)
    if minutes <= 0:
        return timedelta(minutes=DEFAULT_HEARTBEAT_STALE_MINUTES)
    return timedelta(minutes=minutes)


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one git command for lifecycle diagnostics without throwing."""
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


def _resolve_repo_root_from_worktree_path(worktree_path: str | None) -> Path | None:
    """Resolve the canonical repo root from a claim worktree path when possible."""
    if not worktree_path:
        return None
    expanded = Path(worktree_path).expanduser()
    if expanded.exists():
        result = _run_git(expanded, ["rev-parse", "--show-toplevel"])
        if result.returncode == 0:
            return Path(result.stdout.strip())
    parent = expanded.parent
    if parent.name.endswith("_worktrees"):
        candidate = parent.parent / parent.name.removesuffix("_worktrees")
        if candidate.exists():
            result = _run_git(candidate, ["rev-parse", "--show-toplevel"])
            if result.returncode == 0:
                return Path(result.stdout.strip())
    return None


def _resolve_default_branch(repo_root: Path) -> str | None:
    """Return the canonical default branch name for one repo when resolvable."""
    remote_head = _run_git(repo_root, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"])
    if remote_head.returncode == 0:
        value = remote_head.stdout.strip()
        if value.startswith("origin/"):
            return value.split("/", 1)[1]
        if value:
            return value
    for candidate in ("main", "master"):
        branch_check = _run_git(repo_root, ["show-ref", "--verify", f"refs/heads/{candidate}"])
        if branch_check.returncode == 0:
            return candidate
    return None


def _default_integration_ref(repo_root: Path, default_branch: str) -> str:
    """Prefer the canonical remote default ref when it exists."""

    remote_ref = f"refs/remotes/origin/{default_branch}"
    remote_check = _run_git(repo_root, ["show-ref", "--verify", remote_ref])
    return remote_ref if remote_check.returncode == 0 else f"refs/heads/{default_branch}"


def claim_lifecycle_issues(claim: ClaimRecord) -> list[str]:
    """Return mechanically provable stale-lifecycle issues for one live claim."""
    if not claim.is_live():
        return []

    issues: list[str] = []
    repo_root = _resolve_repo_root_from_worktree_path(claim.worktree_path)
    worktree_path = Path(claim.worktree_path).expanduser() if claim.worktree_path else None

    if worktree_path is not None and not worktree_path.exists():
        issues.append("missing_worktree_on_disk")

    if claim.branch and repo_root is not None:
        branch_ref = f"refs/heads/{claim.branch}"
        branch_check = _run_git(repo_root, ["show-ref", "--verify", branch_ref])
        branch_exists = branch_check.returncode == 0
        if not branch_exists:
            issues.append("missing_branch_ref")
        else:
            default_branch = _resolve_default_branch(repo_root)
            if default_branch and default_branch != claim.branch:
                branch_sha = _run_git(repo_root, ["rev-parse", branch_ref])
                default_ref = _default_integration_ref(repo_root, default_branch)
                default_sha = _run_git(repo_root, ["rev-parse", default_ref])
                if branch_sha.returncode != 0 or default_sha.returncode != 0:
                    return issues
                if branch_sha.stdout.strip() == default_sha.stdout.strip():
                    return issues
                merged_check = _run_git(
                    repo_root,
                    ["merge-base", "--is-ancestor", branch_ref, default_ref],
                )
                if merged_check.returncode == 0:
                    issues.append("branch_merged_to_default")

    return issues


def claim_liveness_issues(
    claim: ClaimRecord,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Return stale-session issues derived from heartbeat freshness.

    Backward compatibility rule: a live claim with no `heartbeat_at` remains
    readable and does not become stale solely because the heartbeat rollout has
    not touched it yet. It is explicitly uninstrumented rather than healthy.
    """

    if not claim.is_live():
        return []
    if not claim.session_id:
        return []
    if not claim.heartbeat_at:
        return ["missing_session_heartbeat"]
    heartbeat = _parse_iso_datetime(claim.heartbeat_at)
    if heartbeat is None:
        return ["invalid_heartbeat_at"]
    reference_now = now or datetime.now(timezone.utc)
    if reference_now - heartbeat > _heartbeat_stale_after():
        return ["stale_session_heartbeat"]
    return []


def claim_runtime_status(
    claim: ClaimRecord,
    *,
    active_claims: list[ClaimRecord] | None = None,
) -> str:
    """Classify one live claim across stale/weak/healthy states."""
    if claim_lifecycle_issues(claim):
        return "stale"
    liveness_issues = claim_liveness_issues(claim)
    if any(issue != "missing_session_heartbeat" for issue in liveness_issues):
        return "stale"
    issues = (
        coordination_health_issues(claim, active_claims=active_claims)
        if active_claims is not None
        else claim_health_issues(claim)
    )
    return "weak" if issues or liveness_issues else "healthy"


def claim_enforcement_issues(claim: ClaimRecord) -> list[dict[str, str]]:
    """Return blocking operator findings that require an explicit disposition."""

    lifecycle = claim_lifecycle_issues(claim)
    if "branch_merged_to_default" not in lifecycle:
        return []
    return [
        {
            "code": "merged_active_claim_requires_disposition",
            "severity": "high",
            "message": (
                f"Active claim {claim.primary_project()}:{claim.scope} owns branch "
                f"{claim.branch!r}, which is already integrated into the canonical default branch. "
                "Run sanctioned session-close or record a supported kept-open disposition."
            ),
        }
    ]


def validate_claim_for_creation(claim: ClaimRecord) -> None:
    """Reject new claims that omit required ownership metadata for live coordination."""
    issues = [issue for issue in claim_health_issues(claim) if issue in CREATION_BLOCKING_HEALTH_ISSUES]
    if not issues:
        return
    if not claim.is_live():
        return
    flag_map = {
        "missing_project": "--project",
        "missing_write_paths": "--write-path",
        "missing_branch": "--branch",
        "missing_worktree_path": "--worktree-path",
        "missing_session_id": "--session-id",
        "missing_session_name": "--session-name",
        "missing_work_unit_id": "--work-unit-id",
        "missing_work_graph_path": "--work-graph",
        "missing_work_graph_sha256": "a validated canonical work-graph binding",
    }
    required_flags = [flag_map[item] for item in issues if item in flag_map]
    required_text = ", ".join(required_flags)
    raise ValueError(
        f"Active {claim.claim_type} claims require {required_text}. "
        "Legacy claims remain readable, but new live claims must declare real ownership."
    )


def _plan_number(plan_ref: str | None) -> int | None:
    """Extract a numbered-plan identity from canonical claim spellings."""

    if not isinstance(plan_ref, str):
        return None
    match = re.search(r"(?:\bPlan\s*#?|#)\s*0*(\d+)\b", plan_ref, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def resolve_canonical_work_unit_binding(
    *,
    repo_root: str,
    plan_ref: str,
    work_graph_path: str,
    work_unit_id: str,
) -> tuple[str, tuple[str, ...]]:
    """Validate one work unit from the canonical default ref and return its binding."""

    root = Path(repo_root).expanduser().resolve()
    normalized_path = _normalize_repo_path(work_graph_path)
    if Path(normalized_path).is_absolute() or normalized_path == ".." or normalized_path.startswith("../"):
        raise ValueError("--work-graph must be a repository-relative path")
    plan_number = _plan_number(plan_ref)
    if plan_number is None:
        raise ValueError(f"Unable to resolve numbered plan identity from {plan_ref!r}")
    if not Path(normalized_path).name.startswith(f"{plan_number}_"):
        raise ValueError(f"Work graph {normalized_path!r} does not match {plan_ref}; expected a {plan_number}_ prefix")
    default_branch = _resolve_default_branch(root)
    if not default_branch:
        raise ValueError("Unable to resolve canonical default branch for work-unit validation")
    source_ref = _default_integration_ref(root, default_branch)
    rendered = _run_git(root, ["show", f"{source_ref}:{normalized_path}"])
    if rendered.returncode != 0:
        raise ValueError(f"Canonical work graph {normalized_path!r} is unavailable at {source_ref}")
    try:
        payload = json.loads(rendered.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Canonical work graph {normalized_path!r} is invalid JSON: {exc}") from exc
    units = payload.get("units") if isinstance(payload, dict) else None
    if not isinstance(units, list):
        raise ValueError(f"Canonical work graph {normalized_path!r} requires a units list")
    matches = [unit for unit in units if isinstance(unit, dict) and unit.get("id") == work_unit_id]
    if len(matches) != 1:
        raise ValueError(
            f"Canonical work graph must contain exactly one work unit {work_unit_id!r}; found {len(matches)}"
        )
    unit = matches[0]
    readiness = unit.get("readiness")
    readiness_status = readiness.get("status") if isinstance(readiness, dict) else None
    unit_status = unit.get("status")
    if unit_status != "ready" or readiness_status != "ready":
        raise ValueError(
            f"Work unit {work_unit_id!r} is not claimable: status={unit_status!r}, readiness={readiness_status!r}"
        )
    control_types = unit.get("control_approval_types", [])
    readiness_types = readiness.get("required_approval_types", []) if isinstance(readiness, dict) else []
    approvals = readiness.get("approvals", []) if isinstance(readiness, dict) else []
    if not isinstance(control_types, list) or not all(isinstance(item, str) for item in control_types):
        raise ValueError(f"Work unit {work_unit_id!r} has invalid control_approval_types")
    if not isinstance(readiness_types, list) or not all(isinstance(item, str) for item in readiness_types):
        raise ValueError(f"Work unit {work_unit_id!r} has invalid required_approval_types")
    if not isinstance(approvals, list):
        raise ValueError(f"Work unit {work_unit_id!r} has invalid readiness approvals")
    required_types = sorted(set(control_types + readiness_types))
    approval_revisions: list[str] = []
    for approval_type in required_types:
        matching = [
            item
            for item in approvals
            if isinstance(item, dict)
            and item.get("approval_type") == approval_type
            and isinstance(item.get("role"), str)
            and item["role"].strip()
            and isinstance(item.get("approver_id"), str)
            and item["approver_id"].strip()
            and isinstance(item.get("approved_revision"), str)
            and item["approved_revision"].strip()
            and isinstance(item.get("approved_at"), str)
            and _parse_iso_datetime(item["approved_at"]) is not None
            and (
                item.get("expires_at") is None
                or (
                    isinstance(item.get("expires_at"), str)
                    and (expires_at := _parse_iso_datetime(item["expires_at"])) is not None
                    and expires_at > datetime.now(timezone.utc)
                )
            )
        ]
        if len(matching) != 1:
            raise ValueError(
                f"Work unit {work_unit_id!r} requires exactly one {approval_type!r} approval; found {len(matching)}"
            )
        approval_revisions.append(f"{approval_type}={matching[0]['approved_revision'].strip()}")
    graph_sha256 = hashlib.sha256(rendered.stdout.encode("utf-8")).hexdigest()
    return graph_sha256, tuple(sorted(approval_revisions))


def resolve_session_id(agent: str, explicit_session_id: str | None = None) -> str | None:
    """Return an explicit or environment-derived session identifier.

    The result is scoped to the named agent so one tool runtime does not
    accidentally borrow another tool's ambient session marker.
    """

    if explicit_session_id:
        return explicit_session_id
    for key in SESSION_ENV_KEYS.get(agent, ()):
        raw_value = os.environ.get(key, "").strip()
        if not raw_value:
            continue
        if agent == "claude-code" and key == "CLAUDE_CODE_SSE_PORT":
            return f"claude-code:sse:{raw_value}"
        return f"{agent}:{raw_value}"
    return None


def validate_native_session_binding(agent: str, session_id: str | None) -> None:
    """Reject an explicit session identity that contradicts the native runtime.

    Explicit identities remain necessary for lifecycle hooks and recovery tools
    whose subprocess environment does not expose a native marker. When a native
    marker *is* present, however, accepting a different value creates an owner
    that no real session can heartbeat, receive mailbox messages for, or close.
    """

    if not session_id:
        return
    native_key = STRICT_NATIVE_SESSION_ENV_KEYS.get(agent)
    native_value = os.environ.get(native_key, "").strip() if native_key else ""
    native_session_id = f"{agent}:{native_value}" if native_value else None
    if native_session_id is None or session_id == native_session_id:
        return
    raise ValueError(
        f"Explicit session ID {session_id!r} does not match the current "
        f"{agent} runtime {native_session_id!r}. Use the native session identity; "
        "do not substitute a lane name. Use sanctioned transfer or takeover for "
        "ownership changes."
    )


def _safe_string_list(value: Any) -> list[str]:
    """Normalize a scalar-or-list YAML value into a clean string list."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = [item for item in value if isinstance(item, str)]
    else:
        return []
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        stripped = item.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        deduped.append(stripped)
    return deduped


def _normalize_repo_path(path: str) -> str:
    """Normalize a repo-relative path for parent/child overlap checks."""
    normalized = posixpath.normpath(path.replace("\\", "/").strip())
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _projects_overlap(left: ClaimRecord, right: ClaimRecord) -> bool:
    """Return whether two claims touch at least one common project."""
    return bool(set(left.projects) & set(right.projects))


def _paths_overlap(left: str, right: str) -> bool:
    """Return whether two normalized repo-relative paths overlap."""
    left_norm = _normalize_repo_path(left)
    right_norm = _normalize_repo_path(right)
    return left_norm == right_norm or left_norm.startswith(f"{right_norm}/") or right_norm.startswith(f"{left_norm}/")


def _compute_overlapping_write_paths(candidate: ClaimRecord, other: ClaimRecord) -> list[str]:
    """Return normalized write-path overlaps between two claims."""
    overlaps: list[str] = []
    for left in candidate.write_paths:
        for right in other.write_paths:
            if _paths_overlap(left, right):
                overlaps.append(f"{_normalize_repo_path(left)} <-> {_normalize_repo_path(right)}")
    return sorted(set(overlaps))


def _parse_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO timestamp from claim data if present."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def normalize_claim(data: dict[str, Any], *, source_file: str | None = None) -> ClaimRecord | None:
    """Normalize a raw YAML claim into the v2 in-memory representation."""
    agent = data.get("agent")
    scope = data.get("scope")
    intent = data.get("intent")
    if not all(isinstance(value, str) and value.strip() for value in (agent, scope, intent)):
        return None
    assert isinstance(agent, str)
    assert isinstance(scope, str)
    assert isinstance(intent, str)
    agent_text = agent.strip()
    scope_text = scope.strip()
    intent_text = intent.strip()

    projects = _safe_string_list(data.get("projects"))
    legacy_project = data.get("project")
    if isinstance(legacy_project, str) and legacy_project.strip() and legacy_project.strip() not in projects:
        projects.insert(0, legacy_project.strip())

    write_paths = [_normalize_repo_path(path) for path in _safe_string_list(data.get("write_paths"))]
    read_paths = [_normalize_repo_path(path) for path in _safe_string_list(data.get("read_paths"))]
    raw_claim_type = data.get("claim_type")
    claim_type = raw_claim_type if isinstance(raw_claim_type, str) and raw_claim_type in CLAIM_TYPES else None
    if claim_type is None:
        claim_type = "write" if write_paths else "program"

    raw_status = data.get("status")
    status = raw_status if isinstance(raw_status, str) and raw_status.strip() else "active"
    raw_schema_version = data.get("schema_version")
    if isinstance(raw_schema_version, int) and raw_schema_version in {1, 2, 3}:
        schema_version = raw_schema_version
    elif any(
        key in data
        for key in (
            "work_unit_id",
            "work_graph_path",
            "work_graph_sha256",
            "approval_revisions",
        )
    ):
        schema_version = 3
    elif any(
        key in data
        for key in (
            "claim_type",
            "projects",
            "write_paths",
            "read_paths",
            "worktree_path",
            "repo_root",
            "branch",
            "session_name",
            "broader_goal",
            "tracker_path",
            "session_id",
            "heartbeat_at",
            "status",
            "updated_at",
            "parent_scope",
            "notes",
            "parallel_root_authorized",
        )
    ):
        schema_version = 2
    else:
        schema_version = 1

    return ClaimRecord(
        agent=agent_text,
        claimed_at=data.get("claimed_at") if isinstance(data.get("claimed_at"), str) else None,
        expires_at=data.get("expires_at") if isinstance(data.get("expires_at"), str) else None,
        projects=projects,
        scope=scope_text,
        intent=intent_text,
        claim_type=claim_type,
        write_paths=write_paths,
        read_paths=read_paths,
        worktree_path=data.get("worktree_path") if isinstance(data.get("worktree_path"), str) else None,
        repo_root=data.get("repo_root") if isinstance(data.get("repo_root"), str) else None,
        branch=data.get("branch") if isinstance(data.get("branch"), str) else None,
        session_name=data.get("session_name") if isinstance(data.get("session_name"), str) else None,
        broader_goal=data.get("broader_goal") if isinstance(data.get("broader_goal"), str) else None,
        tracker_path=data.get("tracker_path") if isinstance(data.get("tracker_path"), str) else None,
        session_id=data.get("session_id") if isinstance(data.get("session_id"), str) else None,
        heartbeat_at=data.get("heartbeat_at") if isinstance(data.get("heartbeat_at"), str) else None,
        status=status,
        updated_at=data.get("updated_at") if isinstance(data.get("updated_at"), str) else None,
        parent_scope=data.get("parent_scope") if isinstance(data.get("parent_scope"), str) else None,
        notes=data.get("notes") if isinstance(data.get("notes"), str) else None,
        plan_ref=data.get("plan_ref") if isinstance(data.get("plan_ref"), str) else None,
        source_file=source_file,
        schema_version=schema_version,
        work_unit_id=data.get("work_unit_id") if isinstance(data.get("work_unit_id"), str) else None,
        work_graph_path=(data.get("work_graph_path") if isinstance(data.get("work_graph_path"), str) else None),
        work_graph_sha256=(data.get("work_graph_sha256") if isinstance(data.get("work_graph_sha256"), str) else None),
        approval_revisions=tuple(_safe_string_list(data.get("approval_revisions"))),
        parallel_root_authorized=data.get("parallel_root_authorized") is True,
    )


def _load_claims(claims_dir: Path | None = None) -> list[ClaimRecord]:
    """Load live claim files from the configured or explicitly supplied registry."""
    resolved_claims_dir = claims_dir or CLAIMS_DIR
    if not resolved_claims_dir.exists():
        return []
    claims: list[ClaimRecord] = []
    now = datetime.now(timezone.utc)
    for claim_file in resolved_claims_dir.glob("*.yaml"):
        try:
            data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        expires_at = _parse_iso_datetime(data.get("expires_at"))
        if expires_at is not None and expires_at < now:
            # Loading and listing are read-only. Expired source records remain
            # auditable until the explicit --prune lifecycle action removes
            # them.
            continue
        claim = normalize_claim(data, source_file=str(claim_file))
        if claim is not None:
            claims.append(claim)
    return claims


def unregistered_claim_files() -> list[str]:
    """Return claim-dir files that coordination tooling cannot parse as claims.

    Every file in the claims directory is a claim by convention. Free-form
    `.md`/`.txt` claims (observed from Codex sessions, 2026-07-06) are invisible
    to listing/conflict/registry tooling; surfacing them loudly is the fix for
    that silent blind spot.
    """
    if not CLAIMS_DIR.exists():
        return []
    return sorted(
        str(path) for path in CLAIMS_DIR.iterdir() if path.is_file() and path.suffix.lower() not in {".yaml", ".yml"}
    )


def _claim_filename(agent: str, project: str, scope: str) -> str:
    """Generate a deterministic filename for a claim."""

    def safe(value: str) -> str:
        return value.replace("/", "_").replace(" ", "_").strip("_")

    return f"{safe(agent)}_{safe(project)}_{safe(scope)}.yaml"


def check_claims(project: str | None = None, *, claims_dir: Path | None = None) -> list[ClaimRecord]:
    """Check active claims, optionally selecting a registry and project."""
    claims = [claim for claim in _load_claims(claims_dir) if claim.is_live()]
    if project:
        claims = [claim for claim in claims if project in claim.projects]
    return claims


def list_claims(
    project: str | None = None,
    *,
    claims_dir: Path | None = None,
    include_inactive: bool = False,
) -> list[ClaimRecord]:
    """List claims with an explicit option to retain non-live audit records."""

    claims = _load_claims(claims_dir)
    if not include_inactive:
        claims = [claim for claim in claims if claim.is_live()]
    if project:
        claims = [claim for claim in claims if project in claim.projects]
    return claims


def evaluate_claim(candidate: ClaimRecord, *, active_claims: list[ClaimRecord] | None = None) -> ClaimCheckResult:
    """Classify candidate claim interactions against active live claims."""
    claims = active_claims if active_claims is not None else check_claims()
    interactions: list[ClaimInteraction] = []
    for other in claims:
        if other.agent == candidate.agent:
            continue
        if not _projects_overlap(candidate, other):
            continue

        overlapping_write_paths = _compute_overlapping_write_paths(candidate, other)
        if candidate.claim_type == "write" and other.claim_type == "write" and overlapping_write_paths:
            interactions.append(
                ClaimInteraction(
                    severity="hard_conflict",
                    reason="write_paths overlap across active write claims",
                    other_agent=other.agent,
                    other_scope=other.scope,
                    other_claim_type=other.claim_type,
                    projects=sorted(set(candidate.projects) & set(other.projects)),
                    overlapping_write_paths=overlapping_write_paths,
                    other_source_file=other.source_file,
                )
            )
            continue

        if overlapping_write_paths and {candidate.claim_type, other.claim_type} == {"write", "review"}:
            interactions.append(
                ClaimInteraction(
                    severity="soft_overlap",
                    reason="review claim overlaps an active write claim",
                    other_agent=other.agent,
                    other_scope=other.scope,
                    other_claim_type=other.claim_type,
                    projects=sorted(set(candidate.projects) & set(other.projects)),
                    overlapping_write_paths=overlapping_write_paths,
                    other_source_file=other.source_file,
                )
            )
            continue

        if candidate.scope == other.scope:
            interactions.append(
                ClaimInteraction(
                    severity="informational",
                    reason="same project/scope is already claimed, but no write-path conflict was detected",
                    other_agent=other.agent,
                    other_scope=other.scope,
                    other_claim_type=other.claim_type,
                    projects=sorted(set(candidate.projects) & set(other.projects)),
                    overlapping_write_paths=overlapping_write_paths,
                    other_source_file=other.source_file,
                )
            )
            continue

        if overlapping_write_paths:
            interactions.append(
                ClaimInteraction(
                    severity="informational",
                    reason="write-path overlap exists but the claim types do not require blocking",
                    other_agent=other.agent,
                    other_scope=other.scope,
                    other_claim_type=other.claim_type,
                    projects=sorted(set(candidate.projects) & set(other.projects)),
                    overlapping_write_paths=overlapping_write_paths,
                    other_source_file=other.source_file,
                )
            )
            continue

        interactions.append(
            ClaimInteraction(
                severity="informational",
                reason="same project has another active claim with no overlapping write paths",
                other_agent=other.agent,
                other_scope=other.scope,
                other_claim_type=other.claim_type,
                projects=sorted(set(candidate.projects) & set(other.projects)),
                overlapping_write_paths=[],
                other_source_file=other.source_file,
            )
        )
    return ClaimCheckResult(candidate=candidate, interactions=interactions)


def build_candidate_claim(
    *,
    agent: str,
    project: str,
    scope: str,
    intent: str,
    plan_ref: str | None = None,
    claim_type: str | None = None,
    write_paths: list[str] | None = None,
    read_paths: list[str] | None = None,
    worktree_path: str | None = None,
    repo_root: str | None = None,
    branch: str | None = None,
    session_name: str | None = None,
    broader_goal: str | None = None,
    tracker_path: str | None = None,
    session_id: str | None = None,
    heartbeat_at: str | None = None,
    status: str = "active",
    parent_scope: str | None = None,
    notes: str | None = None,
    claimed_at: str | None = None,
    expires_at: str | None = None,
    updated_at: str | None = None,
    work_unit_id: str | None = None,
    work_graph_path: str | None = None,
    work_graph_sha256: str | None = None,
    approval_revisions: tuple[str, ...] = (),
    parallel_root_authorized: bool = False,
) -> ClaimRecord:
    """Build a normalized candidate claim from CLI or test inputs."""
    normalized_write_paths = [_normalize_repo_path(path) for path in (write_paths or [])]
    normalized_read_paths = [_normalize_repo_path(path) for path in (read_paths or [])]
    resolved_session_id = resolve_session_id(agent, session_id)
    resolved_claim_type = claim_type or ("write" if normalized_write_paths else "program")
    if resolved_claim_type not in CLAIM_TYPES:
        raise ValueError(f"Unsupported claim type: {resolved_claim_type}")
    if resolved_claim_type == "write" and not normalized_write_paths:
        raise ValueError("Write claims require at least one --write-path.")
    return ClaimRecord(
        agent=agent,
        claimed_at=claimed_at,
        expires_at=expires_at,
        projects=[project],
        scope=scope,
        intent=intent,
        claim_type=resolved_claim_type,
        write_paths=normalized_write_paths,
        read_paths=normalized_read_paths,
        worktree_path=worktree_path,
        repo_root=repo_root,
        branch=branch,
        session_name=session_name,
        broader_goal=broader_goal,
        tracker_path=tracker_path,
        session_id=resolved_session_id,
        heartbeat_at=heartbeat_at,
        status=status,
        updated_at=updated_at,
        parent_scope=parent_scope,
        notes=notes,
        plan_ref=plan_ref,
        source_file=None,
        schema_version=3,
        work_unit_id=work_unit_id,
        work_graph_path=work_graph_path,
        work_graph_sha256=work_graph_sha256,
        approval_revisions=approval_revisions,
        parallel_root_authorized=parallel_root_authorized,
    )


def create_claim(
    agent: str,
    project: str,
    scope: str,
    intent: str,
    plan_ref: str | None = None,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    claim_type: str | None = None,
    write_paths: list[str] | None = None,
    read_paths: list[str] | None = None,
    worktree_path: str | None = None,
    repo_root: str | None = None,
    branch: str | None = None,
    session_name: str | None = None,
    broader_goal: str | None = None,
    tracker_path: str | None = None,
    session_id: str | None = None,
    status: str = "active",
    parent_scope: str | None = None,
    notes: str | None = None,
    work_graph_path: str | None = None,
    work_unit_id: str | None = None,
    allow_parallel: bool = False,
    require_native_session_binding: bool = False,
) -> tuple[bool, str]:
    """Create a new claim after checking for hard conflicts."""
    now = datetime.now(timezone.utc)
    if require_native_session_binding:
        validate_native_session_binding(agent, session_id)
    resolved_claim_type = claim_type or ("write" if write_paths else "program")
    work_graph_sha256: str | None = None
    approval_revisions: tuple[str, ...] = ()
    if write_paths and plan_ref:
        if not repo_root:
            raise ValueError("Plan-bound write ownership requires --repo-root for canonical work-unit validation")
        if not work_graph_path or not work_unit_id:
            raise ValueError("Plan-bound write ownership requires --work-graph and --work-unit-id")
        work_graph_sha256, approval_revisions = resolve_canonical_work_unit_binding(
            repo_root=repo_root,
            plan_ref=plan_ref,
            work_graph_path=work_graph_path,
            work_unit_id=work_unit_id,
        )
    candidate = build_candidate_claim(
        agent=agent,
        project=project,
        scope=scope,
        intent=intent,
        plan_ref=plan_ref,
        claim_type=resolved_claim_type,
        write_paths=write_paths,
        read_paths=read_paths,
        worktree_path=worktree_path,
        repo_root=repo_root,
        branch=branch,
        session_name=session_name,
        broader_goal=broader_goal,
        tracker_path=tracker_path,
        session_id=session_id,
        heartbeat_at=now.isoformat(),
        status=status,
        parent_scope=parent_scope,
        notes=notes,
        work_unit_id=work_unit_id,
        work_graph_path=_normalize_repo_path(work_graph_path) if work_graph_path else None,
        work_graph_sha256=work_graph_sha256,
        approval_revisions=approval_revisions,
        parallel_root_authorized=allow_parallel,
        claimed_at=now.isoformat(),
        expires_at=(now + timedelta(hours=ttl_hours)).isoformat(),
        updated_at=now.isoformat(),
    )
    validate_claim_for_creation(candidate)

    with claim_registry_lock():
        registry_digest_before = _registry_digest(CLAIMS_DIR)
        claim_path = CLAIMS_DIR / _claim_filename(agent, project, scope)
        if claim_path.exists():
            raw_existing = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
            existing = (
                normalize_claim(raw_existing, source_file=str(claim_path)) if isinstance(raw_existing, dict) else None
            )
            if existing and existing.status == SESSION_ENDED_STATUS:
                raise ValueError(
                    "Existing claim is session_ended; use session-resume/takeover "
                    "or sanctioned closeout instead of overwriting it."
                )
        active_claims = check_claims(project)
        validate_no_preserved_lane_conflict(
            candidate,
            claims=list_claims(include_inactive=True),
        )
        validate_claim_hierarchy_for_creation(candidate, active_claims=active_claims)
        validate_session_root_for_creation(candidate, active_claims=check_claims())
        check_result = evaluate_claim(candidate, active_claims=active_claims)
        if check_result.hard_conflicts:
            formatted = "; ".join(
                f"{item.other_agent} ({item.other_scope}: {', '.join(item.overlapping_write_paths)})"
                for item in check_result.hard_conflicts
            )
            return False, (
                f"CONFLICT: active write claim overlap in '{project}' — {formatted}. "
                "This is a path-local integration wait, not a whole-goal blocker: "
                "continue claim-compatible work or record the required reconciliation "
                "obligation before deferring the overlapping authority surface."
            )

        CLAIMS_DIR.mkdir(parents=True, exist_ok=True)
        claim_payload = candidate.to_dict()
        claim_payload.pop("source_file", None)
        claim_payload.pop("project", None)
        _atomic_write_claim(claim_path, claim_payload)
        _projection_path, projection_digest_after = refresh_prewrite_authority_projection(CLAIMS_DIR)
        record_claim_mutation(
            operation="create",
            claims_dir=CLAIMS_DIR,
            registry_digest_before=registry_digest_before,
            target_project=project,
            target_scope=scope,
            target_claim_path=claim_path,
            session_id=candidate.session_id,
            projection_digest_after=projection_digest_after,
        )
    return True, (f"Claimed: {agent} → {project}:{scope} [{candidate.claim_type}] (expires in {ttl_hours}h)")


def hydrate_missing_session_ids(
    *,
    agent: str,
    project: str,
    session_id: str | None = None,
    scope: str | None = None,
    branch: str | None = None,
) -> tuple[int, list[str], str]:
    """Fill in missing session IDs for matching live claims.

    This is an explicit remediation tool for older live claims that were created
    before automatic session capture was wired into the v2 claim surface.
    """

    resolved_session_id = resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise ValueError(
            "Unable to resolve a session ID. Pass --session-id explicitly or run from a supported tool runtime."
        )

    updated_scopes: list[str] = []
    now = datetime.now(timezone.utc).isoformat()
    with claim_registry_lock(CLAIMS_DIR):
        if not CLAIMS_DIR.exists():
            return 0, [], resolved_session_id
        for claim_file in CLAIMS_DIR.glob("*.yaml"):
            try:
                data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            claim = normalize_claim(data, source_file=str(claim_file))
            if claim is None or not claim.is_live():
                continue
            if claim.agent != agent:
                continue
            if project not in claim.projects:
                continue
            if scope and claim.scope != scope:
                continue
            if branch and claim.branch != branch:
                continue
            if claim.session_id:
                continue
            data["session_id"] = resolved_session_id
            data["heartbeat_at"] = now
            data["updated_at"] = now
            _atomic_write_claim(claim_file, data)
            updated_scopes.append(claim.scope)
        if updated_scopes:
            refresh_prewrite_authority_projection(CLAIMS_DIR)
    return len(updated_scopes), sorted(updated_scopes), resolved_session_id


def heartbeat_claims(
    *,
    agent: str,
    project: str,
    session_id: str | None = None,
    scope: str | None = None,
    branch: str | None = None,
    claims_dir: Path | None = None,
    require_exact_session: bool = False,
) -> tuple[int, list[str], str, str]:
    """Refresh heartbeat metadata for matching live claims owned by one session."""

    resolved_session_id = resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise ValueError(
            "Unable to resolve a session ID. Pass --session-id explicitly or run from a supported tool runtime."
        )

    resolved_claims_dir = claims_dir or CLAIMS_DIR
    heartbeat_at = datetime.now(timezone.utc).isoformat()
    updated_claims: list[tuple[Path, ClaimRecord]] = []
    # Lifecycle hooks run concurrently across sessions. Keep the canonical
    # heartbeat write and its derived projection refresh in the same registry
    # critical section as every other live-claim mutation.
    with claim_registry_lock(resolved_claims_dir):
        registry_digest_before = _registry_digest(resolved_claims_dir)
        if not resolved_claims_dir.exists():
            return 0, [], resolved_session_id, heartbeat_at
        for claim_file in resolved_claims_dir.glob("*.yaml"):
            try:
                data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            claim = normalize_claim(data, source_file=str(claim_file))
            if claim is None or not claim.is_live():
                continue
            if claim.agent != agent:
                continue
            if project not in claim.projects:
                continue
            if scope and claim.scope != scope:
                continue
            if branch and claim.branch != branch:
                continue
            if require_exact_session and claim.session_id != resolved_session_id:
                continue
            if not require_exact_session and claim.session_id and claim.session_id != resolved_session_id:
                continue
            data["session_id"] = resolved_session_id
            data["heartbeat_at"] = heartbeat_at
            data["updated_at"] = heartbeat_at
            _atomic_write_claim(claim_file, data)
            updated_claims.append((claim_file, claim))
        if updated_claims:
            _projection_path, projection_digest_after = refresh_prewrite_authority_projection(resolved_claims_dir)
            for claim_file, claim in updated_claims:
                record_claim_mutation(
                    operation="heartbeat",
                    claims_dir=resolved_claims_dir,
                    registry_digest_before=registry_digest_before,
                    target_project=claim.primary_project(),
                    target_scope=claim.scope,
                    target_claim_path=claim_file,
                    session_id=resolved_session_id,
                    projection_digest_after=projection_digest_after,
                )
    updated_scopes = [claim.scope for _path, claim in updated_claims]
    return len(updated_scopes), sorted(updated_scopes), resolved_session_id, heartbeat_at


def end_session_claims(
    *,
    agent: str,
    session_id: str | None = None,
    reason: str = "session ended",
    claims_dir: Path | None = None,
) -> tuple[int, list[str], str, str]:
    """Retire exact-session live ownership without deleting recovery state."""

    resolved_session_id = resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise ValueError(
            "Unable to resolve a session ID. Pass --session-id explicitly or run from a supported tool runtime."
        )
    resolved_claims_dir = claims_dir or CLAIMS_DIR
    ended_at = datetime.now(timezone.utc).isoformat()
    ended_claims: list[tuple[Path, ClaimRecord]] = []
    with claim_registry_lock(resolved_claims_dir):
        registry_digest_before = _registry_digest(resolved_claims_dir)
        if not resolved_claims_dir.exists():
            return 0, [], resolved_session_id, ended_at
        for claim_file in resolved_claims_dir.glob("*.yaml"):
            try:
                data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(data, dict):
                continue
            claim = normalize_claim(data, source_file=str(claim_file))
            if claim is None or not claim.is_live() or claim.agent != agent or claim.session_id != resolved_session_id:
                continue
            data["previous_status"] = claim.status
            data["status"] = SESSION_ENDED_STATUS
            data["session_end_reason"] = reason.strip() or "session ended"
            data["session_ended_at"] = ended_at
            data["updated_at"] = ended_at
            _atomic_write_claim(claim_file, data)
            ended_claims.append((claim_file, claim))
        if ended_claims:
            _projection_path, projection_digest_after = refresh_prewrite_authority_projection(resolved_claims_dir)
            for claim_file, claim in ended_claims:
                record_claim_mutation(
                    operation="session_end",
                    claims_dir=resolved_claims_dir,
                    registry_digest_before=registry_digest_before,
                    target_project=claim.primary_project(),
                    target_scope=claim.scope,
                    target_claim_path=claim_file,
                    session_id=resolved_session_id,
                    projection_digest_after=projection_digest_after,
                )
    ended_labels = [f"{claim.primary_project()}:{claim.scope}" for _path, claim in ended_claims]
    return len(ended_labels), sorted(ended_labels), resolved_session_id, ended_at


def release_claim(agent: str, project: str, scope: str) -> tuple[bool, str]:
    """Release an existing claim."""
    filename = _claim_filename(agent, project, scope)
    path = CLAIMS_DIR / filename
    with claim_registry_lock(CLAIMS_DIR):
        if path.exists():
            registry_digest_before = _registry_digest(CLAIMS_DIR)
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            claim = normalize_claim(raw, source_file=str(path)) if isinstance(raw, dict) else None
            path.unlink()
            _projection_path, projection_digest_after = refresh_prewrite_authority_projection(CLAIMS_DIR)
            record_claim_mutation(
                operation="release",
                claims_dir=CLAIMS_DIR,
                registry_digest_before=registry_digest_before,
                target_project=project,
                target_scope=scope,
                target_claim_path=path,
                session_id=claim.session_id if claim else None,
                projection_digest_after=projection_digest_after,
            )
            return True, f"Released: {agent} → {project}:{scope}"
    return False, f"No claim found for {agent} → {project}:{scope}"


def complete_claims_for_plan(
    *,
    project: str,
    plan_ref: str,
    note: str | None = None,
) -> tuple[int, list[str]]:
    """Mark matching live claims completed and return the affected scopes.

    This is the lifecycle-closeout path for finished lanes: claims stop being
    active coordination input, but the YAML records remain on disk as audit
    history with an explicit `completed` status.
    """

    now = datetime.now(timezone.utc).isoformat()
    completed_claims: list[tuple[Path, ClaimRecord]] = []
    with claim_registry_lock(CLAIMS_DIR):
        registry_digest_before = _registry_digest(CLAIMS_DIR)
        if not CLAIMS_DIR.exists():
            return 0, []
        for claim_file in CLAIMS_DIR.glob("*.yaml"):
            try:
                data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            claim = normalize_claim(data, source_file=str(claim_file))
            if claim is None or not claim.is_live():
                continue
            if project not in claim.projects:
                continue
            if claim.plan_ref != plan_ref:
                continue
            data["status"] = "completed"
            data["updated_at"] = now
            if note:
                existing_notes = data.get("notes")
                if isinstance(existing_notes, str) and existing_notes.strip():
                    if note not in existing_notes:
                        data["notes"] = f"{existing_notes.rstrip()} | {note}"
                else:
                    data["notes"] = note
            _atomic_write_claim(claim_file, data)
            completed_claims.append((claim_file, claim))
        if completed_claims:
            _projection_path, projection_digest_after = refresh_prewrite_authority_projection(CLAIMS_DIR)
            for claim_file, claim in completed_claims:
                record_claim_mutation(
                    operation="closeout",
                    claims_dir=CLAIMS_DIR,
                    registry_digest_before=registry_digest_before,
                    target_project=claim.primary_project(),
                    target_scope=claim.scope,
                    target_claim_path=claim_file,
                    session_id=claim.session_id,
                    projection_digest_after=projection_digest_after,
                )
    completed_scopes = [claim.scope for _path, claim in completed_claims]
    return len(completed_scopes), sorted(completed_scopes)


def prune_expired() -> int:
    """Remove expired claims and return the number pruned."""
    now = datetime.now(timezone.utc)
    removed_claims: list[tuple[Path, ClaimRecord | None]] = []
    with claim_registry_lock(CLAIMS_DIR):
        registry_digest_before = _registry_digest(CLAIMS_DIR)
        if not CLAIMS_DIR.exists():
            return 0
        for claim_file in CLAIMS_DIR.glob("*.yaml"):
            try:
                data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            expires_at = _parse_iso_datetime(data.get("expires_at") if isinstance(data, dict) else None)
            if expires_at is not None and expires_at < now:
                claim = normalize_claim(data, source_file=str(claim_file)) if isinstance(data, dict) else None
                claim_file.unlink()
                removed_claims.append((claim_file, claim))
        if removed_claims:
            _projection_path, projection_digest_after = refresh_prewrite_authority_projection(CLAIMS_DIR)
            for claim_file, claim in removed_claims:
                record_claim_mutation(
                    operation="prune",
                    claims_dir=CLAIMS_DIR,
                    registry_digest_before=registry_digest_before,
                    target_project=claim.primary_project() if claim else None,
                    target_scope=claim.scope if claim else None,
                    target_claim_path=claim_file,
                    session_id=claim.session_id if claim else None,
                    projection_digest_after=projection_digest_after,
                )
    return len(removed_claims)


def prune_stale() -> tuple[int, list[str]]:
    """Remove stale live claims and return the removal count plus scope labels."""
    removed_claims: list[tuple[Path, ClaimRecord]] = []
    with claim_registry_lock(CLAIMS_DIR):
        registry_digest_before = _registry_digest(CLAIMS_DIR)
        if not CLAIMS_DIR.exists():
            return 0, []
        for claim_file in CLAIMS_DIR.glob("*.yaml"):
            try:
                data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            claim = normalize_claim(data, source_file=str(claim_file))
            if claim is None or not claim.is_live():
                continue
            liveness_issues = claim_liveness_issues(claim)
            proven_stale_liveness = [issue for issue in liveness_issues if issue != "missing_session_heartbeat"]
            if not (claim_lifecycle_issues(claim) or proven_stale_liveness):
                continue
            claim_file.unlink()
            removed_claims.append((claim_file, claim))
        if removed_claims:
            _projection_path, projection_digest_after = refresh_prewrite_authority_projection(CLAIMS_DIR)
            for claim_file, claim in removed_claims:
                record_claim_mutation(
                    operation="prune",
                    claims_dir=CLAIMS_DIR,
                    registry_digest_before=registry_digest_before,
                    target_project=claim.primary_project(),
                    target_scope=claim.scope,
                    target_claim_path=claim_file,
                    session_id=claim.session_id,
                    projection_digest_after=projection_digest_after,
                )
    removed_labels = [f"{claim.primary_project()}:{claim.scope}" for _path, claim in removed_claims]
    return len(removed_labels), sorted(removed_labels)


def prune_completed() -> tuple[int, list[str]]:
    """Remove claims already marked complete/completed.

    This is intentionally narrower than ``prune_expired``: it never removes a
    live active/blocked/handoff claim solely because its TTL elapsed. Use it for
    housekeeping completed claim history after the claim's audit value has been
    captured elsewhere.
    """

    archive_candidates: list[
        tuple[
            Path,
            bytes,
            ClaimRecord,
            claim_mutation_receipts.CompletedClaimArchiveReceiptV1,
        ]
    ] = []
    removed_claims: list[tuple[Path, ClaimRecord]] = []
    with claim_registry_lock(CLAIMS_DIR):
        if not CLAIMS_DIR.exists():
            return 0, []
        for claim_file in sorted(CLAIMS_DIR.glob("*.yaml")):
            try:
                source_bytes = claim_file.read_bytes()
                data = yaml.safe_load(source_bytes.decode("utf-8"))
            except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
                raise CompletedClaimArchiveError(
                    error_code="invalid_completed_claim_source",
                    source_path=str(claim_file),
                    cause=exc,
                ) from exc
            if not isinstance(data, dict):
                invalid_mapping = ValueError("claim YAML must decode to a mapping")
                raise CompletedClaimArchiveError(
                    error_code="invalid_completed_claim_source",
                    source_path=str(claim_file),
                    cause=invalid_mapping,
                ) from invalid_mapping
            claim = normalize_claim(data, source_file=str(claim_file))
            if claim is None:
                invalid_claim = ValueError("claim YAML does not satisfy the claim identity contract")
                raise CompletedClaimArchiveError(
                    error_code="invalid_completed_claim_source",
                    source_path=str(claim_file),
                    cause=invalid_claim,
                ) from invalid_claim
            if claim.status.strip().lower() not in COMPLETED_STATUSES:
                continue
            try:
                archive_receipt = claim_mutation_receipts.build_completed_claim_archive_receipt(
                    source_kind="live_prune",
                    source_path=claim_file,
                    source_bytes=source_bytes,
                    writer=_LOADED_WRITER_IDENTITY,
                )
            except ValueError as exc:
                raise CompletedClaimArchiveError(
                    error_code="invalid_completed_claim_source",
                    source_path=str(claim_file),
                    cause=exc,
                ) from exc
            archive_candidates.append((claim_file, source_bytes, claim, archive_receipt))

        for claim_file, _source_bytes, _claim, archive_receipt in archive_candidates:
            try:
                claim_mutation_receipts.append_completed_claim_archive_receipt(archive_receipt)
            except (OSError, ValueError) as exc:
                raise CompletedClaimArchiveError(
                    error_code="completed_claim_archive_write_failed",
                    source_path=str(claim_file),
                    cause=exc,
                ) from exc

        for claim_file, source_bytes, _claim, _archive_receipt in archive_candidates:
            try:
                current_bytes = claim_file.read_bytes()
            except OSError as exc:
                raise CompletedClaimArchiveError(
                    error_code="completed_claim_source_changed_before_prune",
                    source_path=str(claim_file),
                    cause=exc,
                ) from exc
            if current_bytes != source_bytes:
                changed_source = ValueError("claim source bytes changed after archive persistence and before prune")
                raise CompletedClaimArchiveError(
                    error_code="completed_claim_source_changed_before_prune",
                    source_path=str(claim_file),
                    cause=changed_source,
                ) from changed_source

        for claim_file, source_bytes, claim, archive_receipt in archive_candidates:
            try:
                if claim_file.read_bytes() != source_bytes:
                    raise ValueError("claim source bytes changed immediately before prune")
            except (OSError, ValueError) as exc:
                raise CompletedClaimArchiveError(
                    error_code="completed_claim_source_changed_before_prune",
                    source_path=str(claim_file),
                    cause=exc,
                ) from exc
            registry_digest_before = _registry_digest(CLAIMS_DIR)
            claim_file.unlink()
            _projection_path, projection_digest_after = refresh_prewrite_authority_projection(CLAIMS_DIR)
            record_claim_mutation(
                operation="prune",
                claims_dir=CLAIMS_DIR,
                registry_digest_before=registry_digest_before,
                target_project=claim.primary_project(),
                target_scope=claim.scope,
                target_claim_path=claim_file,
                session_id=claim.session_id,
                projection_digest_after=projection_digest_after,
                archive_transaction_id=archive_receipt.prune_binding.transaction_id,
            )
            removed_claims.append((claim_file, claim))
    removed_labels = [f"{claim.primary_project()}:{claim.scope}" for _path, claim in removed_claims]
    return len(removed_labels), sorted(removed_labels)


def backfill_completed_claim_archive(
    *,
    source_claim_snapshot: Path,
    expected_source_sha256: str,
    prune_event_id: str,
) -> tuple[claim_mutation_receipts.CompletedClaimArchiveReceiptV1, bool]:
    """Archive one legacy completed claim using exact bytes and prune provenance."""

    resolved_snapshot = source_claim_snapshot.expanduser().resolve()
    source_bytes = resolved_snapshot.read_bytes()
    observed_source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if observed_source_sha256 != expected_source_sha256:
        raise ValueError(
            f"source SHA-256 mismatch: expected={expected_source_sha256} observed={observed_source_sha256}"
        )

    mutation_receipts = claim_mutation_receipts.load_receipts()
    matching_events = [event for event in mutation_receipts if event.event_id == prune_event_id]
    if len(matching_events) != 1:
        raise ValueError(
            "legacy completed-claim backfill requires exactly one historical prune "
            f"event for event_id={prune_event_id!r}"
        )
    prune_event = matching_events[0]
    if not prune_event.target_claim_path:
        raise ValueError("historical prune event is missing its target claim path")
    historical_claim_path = Path(prune_event.target_claim_path).expanduser().resolve()
    receipt = claim_mutation_receipts.build_completed_claim_archive_receipt(
        source_kind="legacy_reconciliation",
        source_path=historical_claim_path,
        source_bytes=source_bytes,
        prune_event_id=prune_event.event_id,
        writer=_LOADED_WRITER_IDENTITY,
    )
    expected_filename = _claim_filename(
        receipt.agent,
        receipt.project,
        receipt.scope,
    )
    if historical_claim_path.name != expected_filename:
        raise ValueError(
            "historical prune event path does not match the completed claim identity: "
            f"expected filename={expected_filename!r} "
            f"observed={historical_claim_path.name!r}"
        )
    claim_mutation_receipts.validate_completed_claim_archive_prune_binding(
        receipt,
        mutation_receipts=mutation_receipts,
    )
    _archive_path, appended = claim_mutation_receipts.append_completed_claim_archive_receipt(receipt)
    persisted = [
        candidate
        for candidate in claim_mutation_receipts.load_completed_claim_archive_receipts()
        if candidate.archive_id == receipt.archive_id
    ]
    if len(persisted) != 1:
        raise ValueError(
            f"completed-claim archive did not retain exactly one validated receipt for archive_id={receipt.archive_id}"
        )
    return persisted[0], appended


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for coordination-claim management."""
    parser = argparse.ArgumentParser(description="Cross-brain coordination claims")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Check for active claims")
    group.add_argument("--claim", action="store_true", help="Create a new claim")
    group.add_argument("--release", action="store_true", help="Release an existing claim")
    group.add_argument("--list", action="store_true", help="List all active claims")
    group.add_argument("--prune", action="store_true", help="Remove expired claims")
    group.add_argument(
        "--prune-stale",
        action="store_true",
        help="Remove mechanically stale live claims whose lifecycle state is no longer truthful.",
    )
    group.add_argument(
        "--prune-completed",
        action="store_true",
        help="Remove valid YAML claims already marked complete/completed; never prunes live claims.",
    )
    group.add_argument(
        "--backfill-completed-claim-archive",
        action="store_true",
        help="Archive one legacy completed claim from exact snapshot bytes and an applied prune event.",
    )
    group.add_argument(
        "--hydrate-session-ids",
        action="store_true",
        help="Fill in missing session_id metadata for matching live claims.",
    )
    group.add_argument(
        "--heartbeat",
        action="store_true",
        help="Refresh heartbeat metadata for matching live claims owned by the current session.",
    )

    parser.add_argument("--agent", help="Agent brain name (claude-code, codex, openclaw)")
    parser.add_argument("--project", help="Project name")
    parser.add_argument("--scope", help="Scope path or identifier")
    parser.add_argument("--intent", help="What the agent intends to do")
    parser.add_argument("--plan", help="Plan reference (e.g., Plan #28)")
    parser.add_argument("--ttl-hours", type=float, default=DEFAULT_TTL_HOURS, help="Claim TTL in hours")
    parser.add_argument("--claim-type", choices=sorted(CLAIM_TYPES), help="Claim category")
    parser.add_argument("--write-path", action="append", default=[], help="Repo-relative write path")
    parser.add_argument("--read-path", action="append", default=[], help="Repo-relative read path")
    parser.add_argument("--worktree-path", help="Worktree path for this claim")
    parser.add_argument("--repo-root", help="Canonical repository root for readiness validation")
    parser.add_argument("--branch", help="Branch for this claim")
    parser.add_argument("--session-id", help="Session identifier")
    parser.add_argument(
        "--session-name",
        help="Human-readable broader-goal session name; required for live program/write/research claims",
    )
    parser.add_argument("--status", default="active", help="Claim status (default: active)")
    parser.add_argument("--parent-scope", help="Parent/broad-scope identifier")
    parser.add_argument(
        "--allow-parallel",
        action="store_true",
        help="Explicitly authorize an additional root for this runtime session.",
    )
    parser.add_argument("--notes", help="Freeform notes")
    parser.add_argument(
        "--work-graph",
        help="Repository-relative canonical work graph required for plan-bound write ownership.",
    )
    parser.add_argument(
        "--work-unit-id",
        help="Exact ready work-unit ID required for plan-bound write ownership.",
    )
    parser.add_argument(
        "--source-claim-snapshot",
        type=Path,
        help="Exact completed-claim YAML snapshot used for legacy archive reconciliation.",
    )
    parser.add_argument(
        "--expected-source-sha256",
        help="Operator-reviewed SHA-256 of --source-claim-snapshot.",
    )
    parser.add_argument(
        "--prune-event-id",
        help="Existing applied claim-mutation event ID for the legacy prune.",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    return parser.parse_args(argv)


def _render_check_output(
    *,
    claims: list[ClaimRecord],
    project: str | None,
    candidate: ClaimRecord | None,
) -> dict[str, Any]:
    """Build a structured report for list/check operations."""
    enforcement_issues = [issue for claim in claims for issue in claim_enforcement_issues(claim)]
    payload: dict[str, Any] = {
        "project": project,
        "has_high_severity_issues": bool(enforcement_issues),
        "enforcement_issues": enforcement_issues,
        "claims": [
            {
                **claim.to_dict(),
                "health_status": claim_runtime_status(
                    claim,
                    active_claims=claims,
                ),
                "health_issues": coordination_health_issues(
                    claim,
                    active_claims=claims,
                ),
                "lifecycle_issues": claim_lifecycle_issues(claim),
                "liveness_issues": claim_liveness_issues(claim),
                "enforcement_issues": claim_enforcement_issues(claim),
            }
            for claim in claims
        ],
        "unregistered_claim_files": unregistered_claim_files(),
    }
    if candidate is not None:
        prospective_claims = [claim for claim in claims if not _same_claim(claim, candidate)] + [candidate]
        payload["check"] = {
            **evaluate_claim(candidate, active_claims=claims).to_dict(),
            "candidate_health_status": claim_runtime_status(
                candidate,
                active_claims=prospective_claims,
            ),
            "candidate_health_issues": coordination_health_issues(
                candidate,
                active_claims=prospective_claims,
            ),
            "candidate_lifecycle_issues": claim_lifecycle_issues(candidate),
            "candidate_liveness_issues": claim_liveness_issues(candidate),
        }
    return payload


def _render_mutation_audit_failure(exc: MutationAuditError, *, as_json: bool) -> int:
    """Report an already-applied mutation whose receipt could not be persisted."""

    if as_json:
        print(json.dumps(exc.to_dict(), indent=2, sort_keys=True))
    else:
        print(str(exc), file=sys.stderr)
    return 1


def _render_completed_claim_archive_failure(
    exc: CompletedClaimArchiveError,
    *,
    as_json: bool,
) -> int:
    """Report an archive-before-prune failure that left claim YAML unchanged."""

    if as_json:
        print(json.dumps({"ok": False, **exc.to_dict()}, indent=2, sort_keys=True))
    else:
        print(str(exc), file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    """Run the CLI for cross-brain coordination claim management."""
    args = parse_args(argv)

    if args.check:
        claims = check_claims(args.project)
        candidate = None
        if args.project and (args.claim_type or args.write_path or args.scope or args.agent):
            candidate = build_candidate_claim(
                agent=args.agent or "candidate",
                project=args.project,
                scope=args.scope or "preview",
                intent=args.intent or "preview active coordination interactions",
                plan_ref=args.plan,
                claim_type=args.claim_type,
                write_paths=args.write_path,
                read_paths=args.read_path,
                worktree_path=args.worktree_path,
                repo_root=args.repo_root,
                branch=args.branch,
                session_name=args.session_name,
                session_id=args.session_id,
                status=args.status,
                parent_scope=args.parent_scope,
                notes=args.notes,
                parallel_root_authorized=args.allow_parallel,
            )
        if args.json:
            print(json.dumps(_render_check_output(claims=claims, project=args.project, candidate=candidate), indent=2))
            return 1 if any(claim_enforcement_issues(claim) for claim in claims) else 0
        if not claims:
            print("No active claims.")
            return 0
        for claim in claims:
            print(f"  [{claim.agent}] {claim.primary_project()}:{claim.scope} [{claim.claim_type}] — {claim.intent}")
            print(f"    expires: {claim.expires_at}")
            if claim.write_paths:
                print(f"    write_paths: {', '.join(claim.write_paths)}")
            for issue in claim_enforcement_issues(claim):
                print(
                    f"HIGH: {issue['code']}: {issue['message']}",
                    file=sys.stderr,
                )
        if candidate is not None:
            result = evaluate_claim(candidate, active_claims=claims)
            if not result.interactions:
                print("No interactions for candidate claim.")
            else:
                print("Candidate interactions:")
                for item in result.interactions:
                    overlaps = ", ".join(item.overlapping_write_paths) or "none"
                    print(
                        f"  - {item.severity}: {item.other_agent} {item.other_scope} "
                        f"({item.reason}; overlap={overlaps})"
                    )
        return 1 if any(claim_enforcement_issues(claim) for claim in claims) else 0

    if args.list:
        claims = check_claims()
        if args.json:
            print(json.dumps(_render_check_output(claims=claims, project=args.project, candidate=None), indent=2))
            return 0
        unregistered = unregistered_claim_files()
        if unregistered:
            print(
                f"⚠ {len(unregistered)} claim file(s) in unregistered format — invisible to "
                "coordination tooling; refile via `make claim` / --claim:",
                file=sys.stderr,
            )
            for path in unregistered:
                print(f"    {path}", file=sys.stderr)
        if not claims:
            print("No active claims.")
            return 0
        for claim in claims:
            print(f"  [{claim.agent}] {claim.primary_project()}:{claim.scope} [{claim.claim_type}] — {claim.intent}")
        return 0

    if args.claim:
        if not all([args.agent, args.project, args.scope, args.intent]):
            raise SystemExit("--claim requires --agent, --project, --scope, --intent")
        try:
            ok, msg = create_claim(
                args.agent,
                args.project,
                args.scope,
                args.intent,
                args.plan,
                args.ttl_hours,
                claim_type=args.claim_type,
                write_paths=args.write_path,
                read_paths=args.read_path,
                worktree_path=args.worktree_path,
                repo_root=args.repo_root,
                branch=args.branch,
                session_name=args.session_name,
                session_id=args.session_id,
                status=args.status,
                parent_scope=args.parent_scope,
                notes=args.notes,
                work_graph_path=args.work_graph,
                work_unit_id=args.work_unit_id,
                allow_parallel=args.allow_parallel,
                require_native_session_binding=True,
            )
        except MutationAuditError as exc:
            return _render_mutation_audit_failure(exc, as_json=args.json)
        except ValueError as exc:
            if args.json:
                print(json.dumps({"ok": False, "message": str(exc)}, indent=2))
            else:
                print(str(exc))
            return 1
        if args.json:
            print(json.dumps({"ok": ok, "message": msg}, indent=2))
        else:
            print(msg)
        return 0 if ok else 1

    if args.release:
        if not all([args.agent, args.project, args.scope]):
            raise SystemExit("--release requires --agent, --project, --scope")
        try:
            ok, msg = release_claim(args.agent, args.project, args.scope)
        except MutationAuditError as exc:
            return _render_mutation_audit_failure(exc, as_json=args.json)
        if args.json:
            print(json.dumps({"ok": ok, "message": msg}, indent=2))
        else:
            print(msg)
        return 0 if ok else 1

    if args.prune:
        try:
            removed = prune_expired()
        except MutationAuditError as exc:
            return _render_mutation_audit_failure(exc, as_json=args.json)
        if args.json:
            print(json.dumps({"pruned": removed}, indent=2))
        else:
            print(f"Expired claims pruned: {removed}")
        return 0

    if args.prune_stale:
        try:
            removed, removed_scopes = prune_stale()
        except MutationAuditError as exc:
            return _render_mutation_audit_failure(exc, as_json=args.json)
        payload = {"pruned": removed, "removed_scopes": removed_scopes}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Stale claims pruned: {removed}")
            if removed_scopes:
                print("Removed scopes: " + ", ".join(removed_scopes))
        return 0

    if args.prune_completed:
        try:
            removed, removed_scopes = prune_completed()
        except CompletedClaimArchiveError as exc:
            return _render_completed_claim_archive_failure(
                exc,
                as_json=args.json,
            )
        except MutationAuditError as exc:
            return _render_mutation_audit_failure(exc, as_json=args.json)
        payload = {"pruned": removed, "removed_scopes": removed_scopes}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Completed claims pruned: {removed}")
            if removed_scopes:
                print("Removed scopes: " + ", ".join(removed_scopes))
        return 0

    if args.backfill_completed_claim_archive:
        if not all(
            [
                args.source_claim_snapshot,
                args.expected_source_sha256,
                args.prune_event_id,
            ]
        ):
            raise SystemExit(
                "--backfill-completed-claim-archive requires "
                "--source-claim-snapshot, --expected-source-sha256, and "
                "--prune-event-id"
            )
        try:
            receipt, appended = backfill_completed_claim_archive(
                source_claim_snapshot=args.source_claim_snapshot,
                expected_source_sha256=args.expected_source_sha256,
                prune_event_id=args.prune_event_id,
            )
        except (OSError, ValueError) as exc:
            payload = {
                "ok": False,
                "error_code": "completed_claim_archive_backfill_failed",
                "error": str(exc),
            }
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(str(exc), file=sys.stderr)
            return 1
        payload = {
            "ok": True,
            "archive_id": receipt.archive_id,
            "receipt_sha256": receipt.receipt_sha256,
            "archive_path": str(claim_mutation_receipts.DEFAULT_COMPLETED_CLAIM_ARCHIVE_PATH.expanduser().resolve()),
            "appended": appended,
            "source_kind": receipt.source_kind,
            "prune_event_id": receipt.prune_binding.mutation_event_id,
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            action = "appended" if appended else "already present"
            print(f"Completed-claim archive receipt {receipt.archive_id} {action} at {payload['archive_path']}")
        return 0

    if args.hydrate_session_ids:
        if not all([args.agent, args.project]):
            raise SystemExit("--hydrate-session-ids requires --agent and --project")
        try:
            updated_count, updated_scopes, resolved_session_id = hydrate_missing_session_ids(
                agent=args.agent,
                project=args.project,
                session_id=args.session_id,
                scope=args.scope,
                branch=args.branch,
            )
        except MutationAuditError as exc:
            return _render_mutation_audit_failure(exc, as_json=args.json)
        except ValueError as exc:
            if args.json:
                print(json.dumps({"ok": False, "message": str(exc)}, indent=2))
            else:
                print(str(exc))
            return 1
        payload = {
            "ok": True,
            "updated_count": updated_count,
            "updated_scopes": updated_scopes,
            "session_id": resolved_session_id,
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                f"Hydrated {updated_count} claim(s) for {args.agent}:{args.project} "
                f"with session_id={resolved_session_id}"
            )
        return 0

    if args.heartbeat:
        if not all([args.agent, args.project]):
            raise SystemExit("--heartbeat requires --agent and --project")
        try:
            updated_count, updated_scopes, resolved_session_id, heartbeat_at = heartbeat_claims(
                agent=args.agent,
                project=args.project,
                session_id=args.session_id,
                scope=args.scope,
                branch=args.branch,
            )
        except MutationAuditError as exc:
            return _render_mutation_audit_failure(exc, as_json=args.json)
        except ValueError as exc:
            if args.json:
                print(json.dumps({"ok": False, "message": str(exc)}, indent=2))
            else:
                print(str(exc))
            return 1
        payload = {
            "ok": True,
            "updated_count": updated_count,
            "updated_scopes": updated_scopes,
            "session_id": resolved_session_id,
            "heartbeat_at": heartbeat_at,
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                f"Heartbeated {updated_count} claim(s) for {args.agent}:{args.project} "
                f"with session_id={resolved_session_id} at {heartbeat_at}"
            )
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
