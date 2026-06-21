"""Tests for deterministic review-cycle contracts."""

from __future__ import annotations

from pathlib import Path

from llm_client.workflow.adversarial_review import AdversarialReview, ReviewAnnotation
from llm_client.workflow.duet import ContractViolation, CorrectnessFinding, Nit, UnverifiedClaim
from llm_client.workflow.review_cycle import (
    BudgetLedger,
    ReviewCycleSignoff,
    ReviewCycleTask,
    actionable_finding_digest,
    build_artifact_index,
    classify_actionable_findings,
    write_json_artifact,
    write_text_artifact,
)


def test_review_cycle_task_defaults_run_dir(tmp_path: Path) -> None:
    task = ReviewCycleTask(
        task_id="methodology-loop",
        artifact_paths=["paper.md"],
        workspace_path=str(tmp_path),
    )
    assert task.run_dir() == tmp_path / "runs" / "review-cycle" / "methodology-loop"


def test_actionable_classifier_excludes_warn_spurious_uncertain_and_nits() -> None:
    review = AdversarialReview(
        artifact_label="paper",
        verdict="concerns",
        summary="summary",
        correctness_findings=[
            CorrectnessFinding(file_path="paper.md", line=1, claim="high defect", severity="high"),
            CorrectnessFinding(file_path="paper.md", line=2, claim="warn concern", severity="warn"),
        ],
        contract_violations=[
            ContractViolation(
                constraint="must cite evidence",
                violation="missing evidence citation",
                evidence_path="paper.md:3",
            )
        ],
        nits=[Nit(claim="rename section")],
        unverified_claims=[UnverifiedClaim(claim="unclear source", reason_unverified="not cited")],
        profile_annotations=[
            ReviewAnnotation(
                annotation_id="og1",
                kind="optimum_gap",
                claim="quality lever",
                linked_finding_index=0,
                validity_loss_without_change="The paper cannot identify false positives.",
            ),
            ReviewAnnotation(
                annotation_id="sp1",
                kind="spurious",
                claim="add conventional table",
                why_rejected_or_uncertain="No validity gain.",
            ),
            ReviewAnnotation(
                annotation_id="u1",
                kind="uncertain",
                claim="maybe add appendix",
                why_rejected_or_uncertain="Need source artifact.",
            ),
        ],
    )

    classification = classify_actionable_findings(review)

    assert [item.kind for item in classification.actionable] == [
        "contract_violation",
        "correctness_high",
        "optimum_gap",
    ]
    skipped_kinds = [item.kind for item in classification.skipped]
    assert "correctness_non_high" in skipped_kinds
    assert "spurious" in skipped_kinds
    assert "uncertain" in skipped_kinds
    assert "nit" in skipped_kinds
    assert "unverified" in skipped_kinds


def test_actionable_digest_is_stable_under_reordering() -> None:
    review = AdversarialReview(
        artifact_label="paper",
        verdict="concerns",
        summary="summary",
        correctness_findings=[
            CorrectnessFinding(file_path="paper.md", line=10, claim="  - Fix   Alpha", severity="high"),
            CorrectnessFinding(file_path="paper.md", line=20, claim="Fix Beta", severity="high"),
        ],
    )
    classification = classify_actionable_findings(review)
    reversed_digest = actionable_finding_digest(list(reversed(classification.actionable)))
    assert classification.digest == reversed_digest


def test_budget_ledger_tracks_exhaustion() -> None:
    ledger = BudgetLedger(max_budget=1.5)
    ledger.add_call(cycle=1, call_kind="review", model="m1", cost_usd=0.75)
    assert ledger.total_spent == 0.75
    assert not ledger.is_exhausted()
    ledger.add_call(cycle=1, call_kind="apply", model="m2", cost_usd=0.8)
    assert ledger.total_spent == 1.55
    assert ledger.is_exhausted()


def test_artifact_writers_and_index(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "review-cycle" / "task"
    signoff = ReviewCycleSignoff(
        task_id="task",
        final_status="pass",
        cycles_completed=1,
        final_verdict="pass",
        stop_reason="review passed",
        budget_spent_usd=0.1,
        actionable_count=0,
        discussion_queue_count=0,
        artifact_index={},
    )

    write_json_artifact(run_dir, "signoff.json", signoff)
    write_text_artifact(run_dir, "apply_1.md", "No changes needed.")
    index = build_artifact_index(run_dir)

    assert index == {"apply_1.md": "apply_1.md", "signoff.json": "signoff.json"}
    assert (run_dir / "signoff.json").read_text()
