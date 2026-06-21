"""Deterministic core for bounded review/apply/review cycles.

This module holds the non-LLM contracts for Plan #36's ``review-cycle``:
typed task/signoff records, deterministic actionable-finding classification,
stable anti-spin digests, cumulative budget ledgers, and durable artifact
writes. The live reviewer/implementer calls are layered on top of these
contracts so tests can prove loop safety without model credentials.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from llm_client.workflow.adversarial_review import (
    AdversarialReviewV1,
    adversarial_review_schema,
    adversarial_review_response_schema,
    build_review_prompt,
    get_review_profile,
    normalize_adversarial_review_response,
    resolve_review_schema_version,
)

ActionableKind = Literal["contract_violation", "correctness_high", "optimum_gap"]
SkippedKind = Literal[
    "correctness_non_high",
    "nit",
    "spurious",
    "uncertain",
    "unverified",
    "invalid_optimum_gap",
]
ReviewCycleStopReason = Literal[
    "pass",
    "non_actionable_remaining",
    "no_diff",
    "repeated_digest",
    "max_cycles",
    "budget_exhausted",
]


class ReviewCycleTask(BaseModel):
    """Configuration for one local review cycle run."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(description="Stable run identifier used in trace IDs and paths.")
    artifact_paths: list[str] = Field(description="Files the implementer may edit by default.")
    workspace_path: str = Field(description="Repository/workspace root for agent calls and diffs.")
    review_profile: str = Field(default="generic", description="Registered review profile name.")
    reviewer_model: str = Field(default="claude-code/opus", description="Model used for review calls.")
    implementer_model: str = Field(default="codex/gpt-5.4", description="Model used for apply calls.")
    max_cycles: int = Field(default=3, ge=1, description="Maximum review/apply iterations.")
    max_budget: float = Field(default=10.0, ge=0.0, description="Cumulative run budget in USD.")
    per_call_max_budget: float = Field(default=2.0, ge=0.0, description="Per LLM call budget in USD.")
    out_dir: str | None = Field(
        default=None,
        description="Optional artifact directory; defaults to runs/review-cycle/<task_id>.",
    )
    allow_workspace_wide_edits: bool = Field(
        default=False,
        description="When false, any undeclared file edit fails the cycle.",
    )

    def run_dir(self) -> Path:
        """Return the directory where durable run artifacts should be written."""
        if self.out_dir:
            return Path(self.out_dir)
        return Path(self.workspace_path) / "runs" / "review-cycle" / self.task_id


class ActionableFinding(BaseModel):
    """A finding the runner may present to the implementer for automatic apply."""

    model_config = ConfigDict(extra="forbid")

    kind: ActionableKind = Field(description="Actionable finding category.")
    claim: str = Field(description="Normalized human-readable claim to fix.")
    evidence_ref: str = Field(description="File/line or evidence path grounding the claim.")
    severity: str = Field(description="Severity used by the auto-apply gate.")
    payload: dict[str, Any] = Field(description="Original review payload for traceability.")


class SkippedFinding(BaseModel):
    """A finding intentionally not auto-applied."""

    model_config = ConfigDict(extra="forbid")

    kind: SkippedKind = Field(description="Skipped finding category.")
    claim: str = Field(description="Review claim that was skipped.")
    reason: str = Field(description="Why this item is not safe to auto-apply.")
    payload: dict[str, Any] = Field(description="Original review payload for traceability.")


class ActionableClassification(BaseModel):
    """Deterministic split between auto-apply candidates and discussion items."""

    model_config = ConfigDict(extra="forbid")

    actionable: list[ActionableFinding] = Field(default_factory=list, description="Safe auto-apply candidates.")
    skipped: list[SkippedFinding] = Field(default_factory=list, description="Items routed to discussion.")
    digest: str = Field(description="Stable digest of actionable candidates.")


class BudgetLedgerEntry(BaseModel):
    """One model-call cost entry in a review-cycle run."""

    model_config = ConfigDict(extra="forbid")

    cycle: int = Field(description="Cycle number, one-based.")
    call_kind: Literal["review", "apply"] = Field(description="Which model-call stage spent budget.")
    model: str = Field(description="Model requested for this call.")
    cost_usd: float = Field(ge=0.0, description="Cost attributed to this call.")
    cumulative_usd: float = Field(ge=0.0, description="Cumulative cost after this entry.")


class BudgetLedger(BaseModel):
    """Cumulative in-run budget ledger."""

    model_config = ConfigDict(extra="forbid")

    max_budget: float = Field(ge=0.0, description="Run budget cap in USD.")
    entries: list[BudgetLedgerEntry] = Field(default_factory=list, description="Cost entries.")

    @property
    def total_spent(self) -> float:
        """Return cumulative spend, using entries as the source of truth."""
        if not self.entries:
            return 0.0
        return self.entries[-1].cumulative_usd

    def add_call(self, *, cycle: int, call_kind: Literal["review", "apply"], model: str, cost_usd: float) -> None:
        """Append one model-call cost to the ledger."""
        cost = float(cost_usd)
        if cost < 0:
            raise ValueError("Review-cycle cost entries must be non-negative.")
        cumulative = self.total_spent + cost
        self.entries.append(
            BudgetLedgerEntry(
                cycle=cycle,
                call_kind=call_kind,
                model=model,
                cost_usd=cost,
                cumulative_usd=cumulative,
            )
        )

    def is_exhausted(self) -> bool:
        """Return true when cumulative spend has reached or exceeded the cap."""
        return self.total_spent >= self.max_budget


class ReviewCycleSignoff(BaseModel):
    """Terminal record for a review-cycle run."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(description="ReviewCycleTask.task_id.")
    final_status: ReviewCycleStopReason = Field(description="Why the loop stopped.")
    cycles_completed: int = Field(ge=0, description="Number of completed review cycles.")
    final_verdict: str = Field(description="Final reviewer verdict when available.")
    stop_reason: str = Field(description="Human-readable stop reason.")
    budget_spent_usd: float = Field(ge=0.0, description="Total in-run spend.")
    actionable_count: int = Field(ge=0, description="Actionable candidates in the terminal cycle.")
    discussion_queue_count: int = Field(ge=0, description="Skipped/discussion items in the terminal cycle.")
    artifact_index: dict[str, str] = Field(default_factory=dict, description="Run artifact paths relative to run_dir.")


class ReviewCallResult(BaseModel):
    """Reviewer output plus cost metadata."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    review: AdversarialReviewV1 = Field(description="Structured review payload.")
    cost_usd: float = Field(default=0.0, ge=0.0, description="Cost attributed to this review call.")
    model: str = Field(default="", description="Model used for this review call.")


class ApplyAttempt(BaseModel):
    """Implementer apply-call result."""

    model_config = ConfigDict(extra="forbid")

    narrative: str = Field(description="Human-readable apply result.")
    sidecar: dict[str, Any] = Field(default_factory=dict, description="Machine-readable apply details.")
    cost_usd: float = Field(default=0.0, ge=0.0, description="Cost attributed to this apply call.")
    model: str = Field(default="", description="Model used for this apply call.")


class ReviewCycleError(RuntimeError):
    """Raised when a review-cycle safety contract is violated."""


ReviewCallable = Callable[[ReviewCycleTask, int], ReviewCallResult]
ApplyCallable = Callable[[ReviewCycleTask, int, ActionableClassification], ApplyAttempt]


def parse_review_payload(payload: AdversarialReviewV1 | dict[str, Any]) -> AdversarialReviewV1:
    """Parse a review payload into the canonical schema version it declares."""
    return normalize_adversarial_review_response(payload)


def classify_actionable_findings(review: AdversarialReviewV1 | dict[str, Any]) -> ActionableClassification:
    """Split review findings into auto-apply candidates and discussion items."""
    parsed = parse_review_payload(review)
    payload = parsed.model_dump()
    actionable: list[ActionableFinding] = []
    skipped: list[SkippedFinding] = []

    annotations = payload.get("profile_annotations", []) or []
    for item in payload.get("contract_violations", []):
        actionable.append(
            ActionableFinding(
                kind="contract_violation",
                claim=str(item.get("violation", "")),
                evidence_ref=str(item.get("evidence_path", "")),
                severity="high",
                payload=item,
            )
        )

    correctness = payload.get("correctness_findings", [])
    valid_optimum_gap_links: set[int] = set()
    emitted_optimum_gap_links: set[int] = set()
    for item in annotations:
        if item.get("kind") != "optimum_gap":
            continue
        linked = item.get("linked_finding_index")
        if type(linked) is not int or linked < 0 or linked >= len(correctness):
            continue
        linked_item = correctness[linked]
        if (
            linked_item.get("severity") == "high"
            and str(item.get("validity_loss_without_change", "")).strip()
        ):
            valid_optimum_gap_links.add(linked)

    for index, item in enumerate(correctness):
        severity = str(item.get("severity", "warn"))
        evidence_ref = f"{item.get('file_path', '')}:{item.get('line', '')}"
        if severity == "high":
            if index not in valid_optimum_gap_links:
                actionable.append(
                    ActionableFinding(
                        kind="correctness_high",
                        claim=str(item.get("claim", "")),
                        evidence_ref=evidence_ref,
                        severity=severity,
                        payload=item,
                    )
                )
        else:
            skipped.append(
                SkippedFinding(
                    kind="correctness_non_high",
                    claim=str(item.get("claim", "")),
                    reason="Only high-severity correctness findings auto-apply.",
                    payload=item,
                )
            )

    for item in annotations:
        kind = item.get("kind")
        if kind == "optimum_gap":
            linked = item.get("linked_finding_index")
            linked_item = correctness[linked] if type(linked) is int and 0 <= linked < len(correctness) else None
            if linked in emitted_optimum_gap_links:
                skipped.append(
                    SkippedFinding(
                        kind="invalid_optimum_gap",
                        claim=str(item.get("claim", "")),
                        reason="Duplicate optimum_gap annotation for the same correctness finding.",
                        payload=item,
                    )
                )
                continue
            if (
                linked_item is not None
                and linked_item.get("severity") == "high"
                and str(item.get("validity_loss_without_change", "")).strip()
            ):
                actionable.append(
                    ActionableFinding(
                        kind="optimum_gap",
                        claim=str(item.get("claim", "")),
                        evidence_ref=str(
                            item.get("evidence_path")
                            or f"{linked_item.get('file_path', '')}:{linked_item.get('line', '')}"
                        ),
                        severity="high",
                        payload=item,
                    )
                )
                emitted_optimum_gap_links.add(linked)
            else:
                skipped.append(
                    SkippedFinding(
                        kind="invalid_optimum_gap",
                        claim=str(item.get("claim", "")),
                        reason="Optimum gap is not linked to a high-severity correctness finding.",
                        payload=item,
                    )
                )
        elif kind == "spurious":
            skipped.append(
                SkippedFinding(
                    kind="spurious",
                    claim=str(item.get("claim", "")),
                    reason=str(item.get("why_rejected_or_uncertain", "")),
                    payload=item,
                )
            )
        elif kind == "uncertain":
            skipped.append(
                SkippedFinding(
                    kind="uncertain",
                    claim=str(item.get("claim", "")),
                    reason=str(item.get("why_rejected_or_uncertain", "")),
                    payload=item,
                )
            )

    for item in payload.get("nits", []):
        skipped.append(
            SkippedFinding(
                kind="nit",
                claim=str(item.get("claim", "")),
                reason="Nits never auto-apply.",
                payload=item,
            )
        )
    for item in payload.get("unverified_claims", []):
        skipped.append(
            SkippedFinding(
                kind="unverified",
                claim=str(item.get("claim", "")),
                reason=str(item.get("reason_unverified", "Unverified claim.")),
                payload=item,
            )
        )

    return ActionableClassification(
        actionable=actionable,
        skipped=skipped,
        digest=actionable_finding_digest(actionable),
    )


def normalize_digest_text(value: str) -> str:
    """Normalize review text for stable anti-spin digests."""
    text = re.sub(r"^\s*[-*+]\s+", "", value.strip())
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def actionable_finding_digest(findings: list[ActionableFinding]) -> str:
    """Return a stable SHA-256 digest for actionable candidates."""
    items = [
        {
            "kind": finding.kind,
            "evidence_ref": normalize_digest_text(finding.evidence_ref),
            "severity": normalize_digest_text(finding.severity),
            "claim": normalize_digest_text(finding.claim),
        }
        for finding in findings
    ]
    encoded = json.dumps(sorted(items, key=lambda item: json.dumps(item, sort_keys=True)), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def write_json_artifact(run_dir: Path, name: str, payload: BaseModel | dict[str, Any] | list[Any]) -> Path:
    """Write one JSON artifact and return its path."""
    run_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, BaseModel):
        data = payload.model_dump()
    else:
        data = payload
    path = run_dir / name
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return path


def write_text_artifact(run_dir: Path, name: str, content: str) -> Path:
    """Write one text artifact and return its path."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / name
    path.write_text(content, encoding="utf-8")
    return path


def build_artifact_index(run_dir: Path) -> dict[str, str]:
    """Return a stable artifact index for files directly under ``run_dir``."""
    if not run_dir.exists():
        return {}
    return {path.name: path.name for path in sorted(run_dir.iterdir()) if path.is_file()}


def _run_git(workspace: Path, args: list[str]) -> str:
    """Run a git command in ``workspace`` and return stdout."""
    proc = subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise ReviewCycleError(
            f"git {' '.join(args)} failed in {workspace}: {proc.stderr.strip()}"
        )
    return proc.stdout


def git_status_short(workspace: Path) -> str:
    """Return ``git status --short`` for the workspace."""
    return _run_git(workspace, ["status", "--short"])


def git_diff_text(workspace: Path) -> str:
    """Return unstaged + staged diff text for the workspace."""
    unstaged = _run_git(workspace, ["diff", "--no-ext-diff"])
    staged = _run_git(workspace, ["diff", "--cached", "--no-ext-diff"])
    return unstaged + staged


def git_head(workspace: Path) -> str:
    """Return the current HEAD commit SHA."""
    return _run_git(workspace, ["rev-parse", "HEAD"]).strip()


def git_diff_from_ref(workspace: Path, ref: str, extra_untracked_paths: list[str] | None = None) -> str:
    """Return working-tree diff relative to ``ref``, including untracked files."""
    diff_parts = [_run_git(workspace, ["diff", "--no-ext-diff", ref])]
    untracked_paths = set(git_untracked_paths(workspace))
    if extra_untracked_paths:
        untracked_paths.update(extra_untracked_paths)
    for path in sorted(untracked_paths):
        diff_parts.append(
            _run_git_diff_allow_difference(
                workspace,
                ["diff", "--no-ext-diff", "--no-index", "--", "/dev/null", path],
            )
        )
    return "".join(diff_parts)


def _run_git_diff_allow_difference(workspace: Path, args: list[str]) -> str:
    """Run a git diff command where return code 1 means differences exist."""
    proc = subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        raise ReviewCycleError(
            f"git {' '.join(args)} failed in {workspace}: {proc.stderr.strip()}"
        )
    return proc.stdout


def git_untracked_paths(workspace: Path) -> list[str]:
    """Return untracked, non-ignored paths in the workspace."""
    return sorted(
        path.strip()
        for path in _run_git(workspace, ["ls-files", "--others", "--exclude-standard"]).splitlines()
        if path.strip()
    )


def git_ignored_paths(workspace: Path) -> list[str]:
    """Return ignored, untracked paths in the workspace."""
    return sorted(
        path.strip()
        for path in _run_git(workspace, ["ls-files", "--others", "--ignored", "--exclude-standard"]).splitlines()
        if path.strip()
    )


def git_ignored_path_fingerprints(workspace: Path) -> dict[str, tuple[bool, int, int]]:
    """Return cheap fingerprints for ignored, untracked paths."""
    fingerprints: dict[str, tuple[bool, int, int]] = {}
    for path in git_ignored_paths(workspace):
        full_path = workspace / path
        try:
            stat = full_path.stat()
        except FileNotFoundError:
            continue
        fingerprints[path] = (full_path.is_file(), stat.st_size, stat.st_mtime_ns)
    return fingerprints


def changed_ignored_paths(
    before: dict[str, tuple[bool, int, int]],
    after: dict[str, tuple[bool, int, int]],
) -> list[str]:
    """Return ignored paths created, modified, or deleted between snapshots."""
    paths = set(before) | set(after)
    return sorted(path for path in paths if before.get(path) != after.get(path))


def git_changed_paths(workspace: Path) -> list[str]:
    """Return tracked changed paths from staged and unstaged diffs."""
    names = set()
    for args in (["diff", "--name-only"], ["diff", "--cached", "--name-only"]):
        for line in _run_git(workspace, args).splitlines():
            path = line.strip()
            if path:
                names.add(path)
    return sorted(names)


def git_changed_paths_from_ref(workspace: Path, ref: str) -> list[str]:
    """Return changed paths between ``ref`` and current working tree."""
    return sorted(
        path.strip()
        for path in _run_git(workspace, ["diff", "--name-only", ref]).splitlines()
        if path.strip()
    )


def _status_paths(status: str) -> list[str]:
    """Parse paths from ``git status --short`` output."""
    paths: list[str] = []
    for line in status.splitlines():
        if not line.strip():
            continue
        raw_path = line[3:].strip()
        if '"' in raw_path:
            try:
                parts = shlex.split(raw_path)
            except ValueError:
                parts = []
            if parts:
                raw_path = parts[-1]
        elif " -> " in raw_path:
            raw_path = raw_path.split(" -> ", 1)[1]
        paths.append(raw_path)
    return paths


def _is_allowed_path(path: str, allowed: list[str]) -> bool:
    normalized = path.strip().rstrip("/")
    for allowed_path in allowed:
        prefix = allowed_path.strip().rstrip("/")
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return True
    return False


def ensure_paths_allowed(paths: list[str], allowed_paths: list[str]) -> None:
    """Fail loud if any path falls outside the declared artifact set."""
    illegal = [path for path in paths if not _is_allowed_path(path, allowed_paths)]
    if illegal:
        raise ReviewCycleError(
            "Review cycle touched undeclared path(s): " + ", ".join(sorted(illegal))
        )


def _read_artifacts(task: ReviewCycleTask) -> str:
    """Read declared artifact files into one review body."""
    workspace = Path(task.workspace_path)
    parts: list[str] = []
    for raw_path in task.artifact_paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = workspace / path
        if not path.is_file():
            raise ReviewCycleError(f"Artifact path not found: {path}")
        parts.extend([f"## {raw_path}", path.read_text(encoding="utf-8")])
    return "\n\n".join(parts)


def _cost_from_meta(meta: Any) -> float:
    """Extract marginal cost from an LLM result-like object."""
    for attr in ("marginal_cost", "cost"):
        value = getattr(meta, attr, None)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            cost = float(value)
            if cost < 0:
                raise ReviewCycleError(f"LLM metadata reported negative {attr}: {cost}.")
            return cost
    return 0.0


def default_review_call(task: ReviewCycleTask, cycle: int) -> ReviewCallResult:
    """Run the configured reviewer model for one cycle."""
    from llm_client import call_llm_structured  # type: ignore[attr-defined]

    profile = get_review_profile(task.review_profile)
    schema_version = resolve_review_schema_version(profile, "auto")
    schema = adversarial_review_schema(schema_version)
    response_schema = adversarial_review_response_schema(schema_version)
    messages = build_review_prompt(
        artifact_label=", ".join(task.artifact_paths),
        artifact_body=_read_artifacts(task),
        context_body=f"Review-cycle task {task.task_id}, cycle {cycle}.",
        response_schema=schema,
        profile=profile,
    )
    review, meta = call_llm_structured(
        task.reviewer_model,
        messages,
        response_schema,
        task="review_cycle_review",
        trace_id=f"{task.task_id}/review/{cycle}",
        max_budget=task.per_call_max_budget,
        cwd=task.workspace_path,
        yolo_mode=True,
    )
    return ReviewCallResult(
        review=parse_review_payload(review),
        cost_usd=_cost_from_meta(meta),
        model=task.reviewer_model,
    )


def default_apply_call(
    task: ReviewCycleTask,
    cycle: int,
    classification: ActionableClassification,
) -> ApplyAttempt:
    """Run the configured implementer model for one apply cycle."""
    from llm_client import call_llm  # type: ignore[attr-defined]

    messages = [
        {
            "role": "system",
            "content": (
                "You are applying high-confidence adversarial review findings. "
                "Edit only the declared artifact files. Do not edit any other "
                "workspace files. If a finding cannot be applied confidently, "
                "leave the file unchanged and explain why."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task_id": task.task_id,
                    "cycle": cycle,
                    "artifact_paths": task.artifact_paths,
                    "actionable_findings": [item.model_dump() for item in classification.actionable],
                },
                indent=2,
                sort_keys=True,
            ),
        },
    ]
    result = call_llm(
        task.implementer_model,
        messages,
        task="review_cycle_apply",
        trace_id=f"{task.task_id}/apply/{cycle}",
        max_budget=task.per_call_max_budget,
        cwd=task.workspace_path,
        yolo_mode=True,
    )
    return ApplyAttempt(
        narrative=str(result.content),
        sidecar={"actionable_count": len(classification.actionable)},
        cost_usd=_cost_from_meta(result),
        model=task.implementer_model,
    )


def _write_terminal_artifacts(
    *,
    run_dir: Path,
    signoff: ReviewCycleSignoff,
    discussion_queue: list[SkippedFinding],
    ledger: BudgetLedger,
) -> ReviewCycleSignoff:
    """Persist terminal artifacts and return signoff with artifact index."""
    write_json_artifact(run_dir, "discussion_queue.json", [item.model_dump() for item in discussion_queue])
    write_json_artifact(run_dir, "budget_ledger.json", ledger)
    signoff.artifact_index = {**build_artifact_index(run_dir), "signoff.json": "signoff.json"}
    write_json_artifact(run_dir, "signoff.json", signoff)
    return signoff


def _make_signoff(
    *,
    task: ReviewCycleTask,
    final_status: ReviewCycleStopReason,
    cycles_completed: int,
    final_verdict: str,
    stop_reason: str,
    ledger: BudgetLedger,
    classification: ActionableClassification | None,
) -> ReviewCycleSignoff:
    """Construct a terminal signoff object."""
    return ReviewCycleSignoff(
        task_id=task.task_id,
        final_status=final_status,
        cycles_completed=cycles_completed,
        final_verdict=final_verdict,
        stop_reason=stop_reason,
        budget_spent_usd=ledger.total_spent,
        actionable_count=len(classification.actionable) if classification else 0,
        discussion_queue_count=len(classification.skipped) if classification else 0,
        artifact_index={},
    )


def run_review_cycle(
    task: ReviewCycleTask,
    *,
    reviewer: ReviewCallable | None = None,
    implementer: ApplyCallable | None = None,
) -> ReviewCycleSignoff:
    """Run a bounded local review/apply/review loop."""
    workspace = Path(task.workspace_path)
    run_dir = task.run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    review_call = reviewer or default_review_call
    apply_call = implementer or default_apply_call
    ledger = BudgetLedger(max_budget=task.max_budget)
    discussion_queue: list[SkippedFinding] = []
    seen_digests: set[str] = set()

    preflight_status = git_status_short(workspace)
    write_text_artifact(run_dir, "preflight_status.txt", preflight_status)
    if not task.allow_workspace_wide_edits:
        ensure_paths_allowed(_status_paths(preflight_status), task.artifact_paths)

    last_classification: ActionableClassification | None = None
    last_verdict = ""
    for cycle in range(1, task.max_cycles + 1):
        review_result = review_call(task, cycle)
        ledger.add_call(
            cycle=cycle,
            call_kind="review",
            model=review_result.model or task.reviewer_model,
            cost_usd=review_result.cost_usd,
        )
        review = parse_review_payload(review_result.review)
        last_verdict = review.verdict
        write_json_artifact(run_dir, f"review_{cycle}.json", review)

        classification = classify_actionable_findings(review)
        last_classification = classification
        discussion_queue.extend(classification.skipped)
        write_json_artifact(
            run_dir,
            f"discussion_queue_{cycle}.json",
            [item.model_dump() for item in classification.skipped],
        )

        if last_verdict == "pass":
            signoff = _make_signoff(
                task=task,
                final_status="pass",
                cycles_completed=cycle,
                final_verdict=last_verdict,
                stop_reason="Reviewer verdict passed.",
                ledger=ledger,
                classification=classification,
            )
            return _write_terminal_artifacts(
                run_dir=run_dir,
                signoff=signoff,
                discussion_queue=discussion_queue,
                ledger=ledger,
            )

        if ledger.is_exhausted():
            signoff = _make_signoff(
                task=task,
                final_status="budget_exhausted",
                cycles_completed=cycle,
                final_verdict=last_verdict,
                stop_reason="Cumulative review-cycle budget exhausted after review.",
                ledger=ledger,
                classification=classification,
            )
            return _write_terminal_artifacts(
                run_dir=run_dir,
                signoff=signoff,
                discussion_queue=discussion_queue,
                ledger=ledger,
            )

        if not classification.actionable:
            signoff = _make_signoff(
                task=task,
                final_status="non_actionable_remaining",
                cycles_completed=cycle,
                final_verdict=last_verdict,
                stop_reason="Only non-actionable review findings remain.",
                ledger=ledger,
                classification=classification,
            )
            return _write_terminal_artifacts(
                run_dir=run_dir,
                signoff=signoff,
                discussion_queue=discussion_queue,
                ledger=ledger,
            )

        if classification.digest in seen_digests:
            signoff = _make_signoff(
                task=task,
                final_status="repeated_digest",
                cycles_completed=cycle,
                final_verdict=last_verdict,
                stop_reason="Actionable finding digest repeated.",
                ledger=ledger,
                classification=classification,
            )
            return _write_terminal_artifacts(
                run_dir=run_dir,
                signoff=signoff,
                discussion_queue=discussion_queue,
                ledger=ledger,
            )
        seen_digests.add(classification.digest)

        head_before = git_head(workspace)
        ignored_before = git_ignored_path_fingerprints(workspace)
        diff_before = git_diff_from_ref(workspace, head_before)
        apply_result = apply_call(task, cycle, classification)
        ledger.add_call(
            cycle=cycle,
            call_kind="apply",
            model=apply_result.model or task.implementer_model,
            cost_usd=apply_result.cost_usd,
        )
        write_text_artifact(run_dir, f"apply_{cycle}.md", apply_result.narrative)
        write_json_artifact(run_dir, f"apply_{cycle}.json", apply_result)

        if not task.allow_workspace_wide_edits:
            ignored_after = git_ignored_path_fingerprints(workspace)
            changed_ignored = changed_ignored_paths(ignored_before, ignored_after)
            touched_paths = sorted(
                set(git_changed_paths_from_ref(workspace, head_before))
                | set(git_changed_paths(workspace))
                | set(_status_paths(git_status_short(workspace)))
                | set(changed_ignored)
            )
            ensure_paths_allowed(touched_paths, task.artifact_paths)
        else:
            ignored_after = git_ignored_path_fingerprints(workspace)
            changed_ignored = changed_ignored_paths(ignored_before, ignored_after)
        extra_ignored_files = [
            path
            for path in changed_ignored
            if path in ignored_after and (workspace / path).is_file()
        ]
        diff_after = git_diff_from_ref(workspace, head_before, extra_untracked_paths=extra_ignored_files)
        write_text_artifact(run_dir, f"diff_{cycle}.patch", diff_after)

        if diff_after == diff_before:
            signoff = _make_signoff(
                task=task,
                final_status="no_diff",
                cycles_completed=cycle,
                final_verdict=last_verdict,
                stop_reason="Apply step produced no artifact diff.",
                ledger=ledger,
                classification=classification,
            )
            return _write_terminal_artifacts(
                run_dir=run_dir,
                signoff=signoff,
                discussion_queue=discussion_queue,
                ledger=ledger,
            )

        if ledger.is_exhausted():
            signoff = _make_signoff(
                task=task,
                final_status="budget_exhausted",
                cycles_completed=cycle,
                final_verdict=last_verdict,
                stop_reason="Cumulative review-cycle budget exhausted after apply.",
                ledger=ledger,
                classification=classification,
            )
            return _write_terminal_artifacts(
                run_dir=run_dir,
                signoff=signoff,
                discussion_queue=discussion_queue,
                ledger=ledger,
            )

    signoff = _make_signoff(
        task=task,
        final_status="max_cycles",
        cycles_completed=task.max_cycles,
        final_verdict=last_verdict,
        stop_reason="Maximum review cycles reached.",
        ledger=ledger,
        classification=last_classification,
    )
    return _write_terminal_artifacts(
        run_dir=run_dir,
        signoff=signoff,
        discussion_queue=discussion_queue,
        ledger=ledger,
    )


build_review_cycle = run_review_cycle
