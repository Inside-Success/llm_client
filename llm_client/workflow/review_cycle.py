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
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from llm_client.workflow.adversarial_review import (
    AdversarialReview,
    AdversarialReviewV1,
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
    "failed",
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
        cost = max(float(cost_usd), 0.0)
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


def parse_review_payload(payload: AdversarialReviewV1 | dict[str, Any]) -> AdversarialReviewV1:
    """Parse a review payload into the canonical schema version it declares."""
    if isinstance(payload, AdversarialReviewV1):
        return payload
    if "profile_annotations" in payload:
        return AdversarialReview.model_validate(payload)
    return AdversarialReviewV1.model_validate(payload)


def classify_actionable_findings(review: AdversarialReviewV1 | dict[str, Any]) -> ActionableClassification:
    """Split review findings into auto-apply candidates and discussion items."""
    parsed = parse_review_payload(review)
    payload = parsed.model_dump()
    actionable: list[ActionableFinding] = []
    skipped: list[SkippedFinding] = []

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
    for item in correctness:
        severity = str(item.get("severity", "warn"))
        evidence_ref = f"{item.get('file_path', '')}:{item.get('line', '')}"
        if severity == "high":
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

    annotations = payload.get("profile_annotations", []) or []
    for item in annotations:
        kind = item.get("kind")
        if kind == "optimum_gap":
            linked = item.get("linked_finding_index")
            linked_item = correctness[linked] if isinstance(linked, int) and linked < len(correctness) else None
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
