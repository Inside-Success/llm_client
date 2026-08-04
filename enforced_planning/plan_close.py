"""Plan-owned lane inventory and fail-closed atomic closeout."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict

from enforced_planning import coordination_claims, session_lifecycle


class StrictContract(BaseModel):
    """Base contract that rejects unknown enforcement fields."""

    model_config = ConfigDict(extra="forbid")


class PlanCloseLaneV1(StrictContract):
    """One lane considered by a plan close operation."""

    lane_id: str
    agent: str
    branch: str | None
    worktree_path: str | None
    claim_identity: str
    session_identity: str | None
    terminal_disposition: str | None
    merge_or_recovery_evidence: dict[str, Any]


class PlanCloseResultV1(StrictContract):
    """Atomic closeout result submitted before a plan status transition."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    qualified_plan_id: str
    submitted_revision: str
    success: bool
    lanes: list[PlanCloseLaneV1]
    actions_performed: list[str]
    failures: list[str]
    final_plan_status_transition: Literal["eligible", "blocked"]


Preflight = Callable[[coordination_claims.ClaimRecord], dict[str, Any] | Exception]
Closer = Callable[[coordination_claims.ClaimRecord], dict[str, Any]]


def _split_qualified_plan_id(value: str) -> tuple[str, int]:
    """Parse the strict project#number identity used by plan lifecycle gates."""
    project, separator, raw_number = value.partition("#")
    if not separator or not project.strip() or not raw_number.isdigit():
        raise ValueError("qualified plan identity must use project#number")
    return project.strip().lower().replace("_", "-"), int(raw_number)


def _claim_matches_plan(
    claim: coordination_claims.ClaimRecord,
    *,
    project: str,
    plan_number: int,
) -> bool:
    """Return whether one live claim belongs to the qualified plan."""
    if project not in {
        item.lower().replace("_", "-") for item in claim.projects
    }:
        return False
    normalized = coordination_claims.normalize_plan_identity(claim.plan_ref)
    return normalized in {f"{project}#{plan_number}", f"Plan #{plan_number}"}


def _completed_lane(
    claim: coordination_claims.ClaimRecord,
    *,
    project: str,
) -> PlanCloseLaneV1 | ValueError:
    """Validate durable terminal evidence on an already-completed claim."""
    if not claim.source_file:
        return ValueError("Completed claim is missing its evidence source.")
    try:
        payload = yaml.safe_load(Path(claim.source_file).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return ValueError(f"Unable to read completed-claim evidence: {exc}")
    if not isinstance(payload, dict):
        return ValueError("Completed-claim evidence must be a YAML mapping.")
    disposition = str(payload.get("disposition") or "")
    if disposition == session_lifecycle.MERGED_DISPOSITION:
        if payload.get("merged_to_default") is not True:
            return ValueError("Merged claim lacks merged-to-default evidence.")
    elif disposition in session_lifecycle.RECOVERY_REQUIRED_DISPOSITIONS:
        if not payload.get("recovery_ref"):
            return ValueError("Recovery disposition lacks a durable recovery ref.")
    else:
        return ValueError(
            f"Completed claim lacks an accepted recoverable disposition: {disposition or 'missing'}."
        )
    return PlanCloseLaneV1(
        lane_id=claim.scope,
        agent=claim.agent,
        branch=claim.branch,
        worktree_path=claim.worktree_path,
        claim_identity=f"{claim.agent}:{project}:{claim.scope}",
        session_identity=claim.session_id,
        terminal_disposition=disposition,
        merge_or_recovery_evidence=payload,
    )


def _default_preflight(claim: coordination_claims.ClaimRecord) -> dict[str, Any] | Exception:
    """Run existing merge/disposition checks without mutating lifecycle state."""
    try:
        worktree_path = Path(claim.worktree_path).expanduser() if claim.worktree_path else None
        if worktree_path is not None and worktree_path.exists():
            clean, details = session_lifecycle._worktree_is_clean(str(worktree_path))
            if not clean:
                raise ValueError(f"Worktree is dirty: {details}")
        repo_root = session_lifecycle._resolve_claim_repo_root(claim)
        preflight = session_lifecycle._validate_closeout_preflight(
            repo_root=repo_root,
            branch=claim.branch,
            disposition=session_lifecycle.MERGED_DISPOSITION,
            disposition_reason=None,
            recovery_ref=None,
            allow_discard_unique=False,
            delete_branch=True,
        )
        if not preflight.branch_exists:
            raise ValueError(
                "Branch is missing and the live claim has no independently verified terminal disposition."
            )
        return preflight.to_dict()
    except (OSError, RuntimeError, ValueError) as exc:
        return exc


def _default_closer(claim: coordination_claims.ClaimRecord) -> dict[str, Any]:
    """Close one lane through the canonical session lifecycle."""
    project = claim.primary_project()
    if not project:
        raise ValueError(f"Claim {claim.scope} has no project")
    return session_lifecycle.close_session(
        agent=claim.agent,
        project=project,
        scope=claim.scope,
        worktree_path=claim.worktree_path,
        branch=claim.branch,
        note=f"closed atomically for {claim.plan_ref}",
    )


def close_plan_lanes(
    *,
    qualified_plan_id: str,
    submitted_revision: str,
    claims: list[coordination_claims.ClaimRecord] | None = None,
    preflight: Preflight = _default_preflight,
    closer: Closer = _default_closer,
    dry_run: bool = False,
) -> PlanCloseResultV1:
    """Preflight every live owned lane, then close all or mutate none."""
    project, plan_number = _split_qualified_plan_id(qualified_plan_id)
    candidates = claims if claims is not None else coordination_claims._load_claims()
    matched = sorted(
        (
            claim
            for claim in candidates
            if _claim_matches_plan(claim, project=project, plan_number=plan_number)
        ),
        key=lambda claim: (claim.scope, claim.agent),
    )
    terminal_lanes: list[PlanCloseLaneV1] = []
    owned: list[coordination_claims.ClaimRecord] = []
    failures: list[str] = []
    for claim in matched:
        if claim.status in coordination_claims.COMPLETED_STATUSES:
            terminal = _completed_lane(claim, project=project)
            if isinstance(terminal, ValueError):
                failures.append(f"{claim.scope}: {terminal}")
            else:
                terminal_lanes.append(terminal)
        elif claim.status in coordination_claims.CLOSEABLE_STATUSES:
            owned.append(claim)
        else:
            failures.append(
                f"{claim.scope}: lifecycle status '{claim.status}' is not terminal or closeable"
            )

    preflight_results: dict[str, dict[str, Any]] = {}
    for claim in owned:
        result = preflight(claim)
        if isinstance(result, Exception):
            failures.append(f"{claim.scope}: {result}")
        else:
            preflight_results[claim.scope] = result
    if failures:
        return PlanCloseResultV1(
            qualified_plan_id=qualified_plan_id,
            submitted_revision=submitted_revision,
            success=False,
            lanes=terminal_lanes + [
                PlanCloseLaneV1(
                    lane_id=claim.scope,
                    agent=claim.agent,
                    branch=claim.branch,
                    worktree_path=claim.worktree_path,
                    claim_identity=f"{claim.agent}:{project}:{claim.scope}",
                    session_identity=claim.session_id,
                    terminal_disposition=None,
                    merge_or_recovery_evidence=preflight_results.get(claim.scope, {}),
                )
                for claim in owned
            ],
            actions_performed=[],
            failures=failures,
            final_plan_status_transition="blocked",
        )

    if dry_run:
        return PlanCloseResultV1(
            qualified_plan_id=qualified_plan_id,
            submitted_revision=submitted_revision,
            success=True,
            lanes=terminal_lanes + [
                PlanCloseLaneV1(
                    lane_id=claim.scope,
                    agent=claim.agent,
                    branch=claim.branch,
                    worktree_path=claim.worktree_path,
                    claim_identity=f"{claim.agent}:{project}:{claim.scope}",
                    session_identity=claim.session_id,
                    terminal_disposition=str(
                        preflight_results[claim.scope].get("disposition") or "merged"
                    ),
                    merge_or_recovery_evidence=preflight_results[claim.scope],
                )
                for claim in owned
            ],
            actions_performed=[],
            failures=[],
            final_plan_status_transition="eligible",
        )

    lanes: list[PlanCloseLaneV1] = list(terminal_lanes)
    actions: list[str] = []
    close_failures: list[str] = []
    for claim in owned:
        try:
            result = closer(claim)
        except (OSError, RuntimeError, ValueError) as exc:
            close_failures.append(f"{claim.scope}: {exc}")
            continue
        actions.append(f"{claim.scope}: {result.get('action', 'closed')}")
        lanes.append(
            PlanCloseLaneV1(
                lane_id=claim.scope,
                agent=claim.agent,
                branch=claim.branch,
                worktree_path=claim.worktree_path,
                claim_identity=f"{claim.agent}:{project}:{claim.scope}",
                session_identity=claim.session_id,
                terminal_disposition=str(
                    result.get("disposition")
                    or preflight_results[claim.scope].get("disposition")
                    or "merged"
                ),
                merge_or_recovery_evidence={
                    **preflight_results[claim.scope],
                    **result,
                },
            )
        )

    success = not close_failures
    return PlanCloseResultV1(
        qualified_plan_id=qualified_plan_id,
        submitted_revision=submitted_revision,
        success=success,
        lanes=lanes,
        actions_performed=actions,
        failures=close_failures,
        final_plan_status_transition="eligible" if success else "blocked",
    )
