"""Tests for deterministic review-cycle contracts."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from llm_client.workflow.adversarial_review import AdversarialReview, ReviewAnnotation
from llm_client.workflow.duet import ContractViolation, CorrectnessFinding, Nit, UnverifiedClaim
from llm_client.workflow.review_cycle import (
    ActionableClassification,
    ApplyAttempt,
    BudgetLedger,
    ReviewCallResult,
    ReviewCycleError,
    ReviewCycleSignoff,
    ReviewCycleTask,
    actionable_finding_digest,
    build_artifact_index,
    classify_actionable_findings,
    run_review_cycle,
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
            CorrectnessFinding(file_path="paper.md", line=4, claim="unlinked high defect", severity="high"),
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
    assert [item.claim for item in classification.actionable] == [
        "missing evidence citation",
        "unlinked high defect",
        "quality lever",
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


def test_actionable_digest_unicode_normalizes_equivalent_text() -> None:
    composed = classify_actionable_findings(
        AdversarialReview(
            artifact_label="paper",
            verdict="concerns",
            summary="summary",
            correctness_findings=[
                CorrectnessFinding(file_path="paper.md", line=1, claim="Cafe\u0301 defect", severity="high")
            ],
        )
    )
    compatibility = classify_actionable_findings(
        AdversarialReview(
            artifact_label="paper",
            verdict="concerns",
            summary="summary",
            correctness_findings=[
                CorrectnessFinding(file_path="paper.md", line=1, claim="Café defect", severity="high")
            ],
        )
    )

    assert composed.digest == compatibility.digest


def test_budget_ledger_tracks_exhaustion() -> None:
    ledger = BudgetLedger(max_budget=1.5)
    ledger.add_call(cycle=1, call_kind="review", model="m1", cost_usd=0.75)
    assert ledger.total_spent == 0.75
    assert not ledger.is_exhausted()
    ledger.add_call(cycle=1, call_kind="apply", model="m2", cost_usd=0.8)
    assert ledger.total_spent == 1.55
    assert ledger.is_exhausted()


def test_budget_ledger_rejects_negative_cost() -> None:
    ledger = BudgetLedger(max_budget=1.0)

    try:
        ledger.add_call(cycle=1, call_kind="review", model="m1", cost_usd=-0.01)
    except ValueError as exc:
        assert "non-negative" in str(exc)
    else:
        raise AssertionError("expected ValueError for negative cost")


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


def _init_repo(tmp_path: Path) -> Path:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace, check=True)
    (workspace / "paper.md").write_text("Initial paper\n", encoding="utf-8")
    subprocess.run(["git", "add", "paper.md"], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=workspace, check=True, capture_output=True)
    return workspace


def _high_review(claim: str = "Fix missing validity proof") -> AdversarialReview:
    return AdversarialReview(
        artifact_label="paper.md",
        verdict="concerns",
        summary="summary",
        correctness_findings=[
            CorrectnessFinding(
                file_path="paper.md",
                line=1,
                claim=claim,
                severity="high",
            )
        ],
    )


def _pass_review() -> AdversarialReview:
    return AdversarialReview(artifact_label="paper.md", verdict="pass", summary="ok")


def _non_actionable_review() -> AdversarialReview:
    return AdversarialReview(
        artifact_label="paper.md",
        verdict="concerns",
        summary="only discussion items remain",
        correctness_findings=[
            CorrectnessFinding(file_path="paper.md", line=1, claim="warn-only concern", severity="warn")
        ],
        nits=[Nit(claim="rename a heading")],
    )


def test_review_cycle_pass_writes_signoff(tmp_path: Path) -> None:
    workspace = _init_repo(tmp_path)
    task = ReviewCycleTask(
        task_id="pass",
        artifact_paths=["paper.md"],
        workspace_path=str(workspace),
        out_dir=str(tmp_path / "run-pass"),
    )

    def reviewer(_task: ReviewCycleTask, cycle: int) -> ReviewCallResult:
        return ReviewCallResult(review=_pass_review(), cost_usd=0.1, model="reviewer")

    signoff = run_review_cycle(task, reviewer=reviewer)

    assert signoff.final_status == "pass"
    assert signoff.cycles_completed == 1
    assert signoff.artifact_index["signoff.json"] == "signoff.json"
    persisted = json.loads((task.run_dir() / "signoff.json").read_text(encoding="utf-8"))
    assert persisted["artifact_index"]["signoff.json"] == "signoff.json"
    assert (task.run_dir() / "signoff.json").is_file()
    assert (task.run_dir() / "review_1.json").is_file()


def test_review_cycle_writes_terminal_discussion_queue(tmp_path: Path) -> None:
    workspace = _init_repo(tmp_path)
    task = ReviewCycleTask(
        task_id="discussion-queue",
        artifact_paths=["paper.md"],
        workspace_path=str(workspace),
        out_dir=str(tmp_path / "run-discussion-queue"),
    )

    def reviewer(_task: ReviewCycleTask, cycle: int) -> ReviewCallResult:
        return ReviewCallResult(review=_non_actionable_review(), cost_usd=0.1, model="reviewer")

    signoff = run_review_cycle(task, reviewer=reviewer)
    queue = json.loads((task.run_dir() / "discussion_queue.json").read_text(encoding="utf-8"))

    assert signoff.final_status == "non_actionable_remaining"
    assert signoff.discussion_queue_count == 2
    assert {item["kind"] for item in queue} == {"correctness_non_high", "nit"}
    assert json.loads((task.run_dir() / "discussion_queue_1.json").read_text(encoding="utf-8")) == queue


def test_review_cycle_stops_when_apply_makes_no_diff(tmp_path: Path) -> None:
    workspace = _init_repo(tmp_path)
    task = ReviewCycleTask(
        task_id="no-diff",
        artifact_paths=["paper.md"],
        workspace_path=str(workspace),
        out_dir=str(tmp_path / "run-no-diff"),
    )

    def reviewer(_task: ReviewCycleTask, cycle: int) -> ReviewCallResult:
        return ReviewCallResult(review=_high_review(), cost_usd=0.1, model="reviewer")

    def implementer(
        _task: ReviewCycleTask,
        cycle: int,
        classification: ActionableClassification,
    ) -> ApplyAttempt:
        return ApplyAttempt(narrative="No change.", cost_usd=0.1, model="impl")

    signoff = run_review_cycle(task, reviewer=reviewer, implementer=implementer)

    assert signoff.final_status == "no_diff"
    assert (task.run_dir() / "apply_1.md").read_text() == "No change."


def test_review_cycle_default_run_dir_does_not_count_as_apply_diff(tmp_path: Path) -> None:
    workspace = _init_repo(tmp_path)
    task = ReviewCycleTask(
        task_id="default-run-dir-no-diff",
        artifact_paths=["paper.md"],
        workspace_path=str(workspace),
    )

    def reviewer(_task: ReviewCycleTask, cycle: int) -> ReviewCallResult:
        return ReviewCallResult(review=_high_review(), cost_usd=0.1, model="reviewer")

    def implementer(
        _task: ReviewCycleTask,
        cycle: int,
        classification: ActionableClassification,
    ) -> ApplyAttempt:
        return ApplyAttempt(narrative="No change.", cost_usd=0.1, model="impl")

    signoff = run_review_cycle(task, reviewer=reviewer, implementer=implementer)

    assert signoff.final_status == "no_diff"
    assert (task.run_dir() / "signoff.json").is_file()


def test_review_cycle_default_run_dir_allows_declared_apply_diff(tmp_path: Path) -> None:
    workspace = _init_repo(tmp_path)
    task = ReviewCycleTask(
        task_id="default-run-dir-change",
        artifact_paths=["paper.md"],
        workspace_path=str(workspace),
        max_cycles=1,
    )

    def reviewer(_task: ReviewCycleTask, cycle: int) -> ReviewCallResult:
        return ReviewCallResult(review=_high_review(), cost_usd=0.1, model="reviewer")

    def implementer(
        _task: ReviewCycleTask,
        cycle: int,
        classification: ActionableClassification,
    ) -> ApplyAttempt:
        with (workspace / "paper.md").open("a", encoding="utf-8") as handle:
            handle.write("Allowed change\n")
        return ApplyAttempt(narrative="Changed declared file.", cost_usd=0.1, model="impl")

    signoff = run_review_cycle(task, reviewer=reviewer, implementer=implementer)
    diff = (task.run_dir() / "diff_1.patch").read_text(encoding="utf-8")

    assert signoff.final_status == "max_cycles"
    assert "Allowed change" in diff
    assert "apply_1.md" not in diff


def test_review_cycle_detects_untracked_allowed_artifact_diff(tmp_path: Path) -> None:
    workspace = _init_repo(tmp_path)
    task = ReviewCycleTask(
        task_id="new-file",
        artifact_paths=["paper.md", "appendix.md"],
        workspace_path=str(workspace),
        out_dir=str(tmp_path / "run-new-file"),
        max_cycles=1,
    )

    def reviewer(_task: ReviewCycleTask, cycle: int) -> ReviewCallResult:
        return ReviewCallResult(review=_high_review(), cost_usd=0.1, model="reviewer")

    def implementer(
        _task: ReviewCycleTask,
        cycle: int,
        classification: ActionableClassification,
    ) -> ApplyAttempt:
        (workspace / "appendix.md").write_text("New appendix\n", encoding="utf-8")
        return ApplyAttempt(narrative="Created appendix.", cost_usd=0.1, model="impl")

    signoff = run_review_cycle(task, reviewer=reviewer, implementer=implementer)
    diff = (task.run_dir() / "diff_1.patch").read_text(encoding="utf-8")

    assert signoff.final_status == "max_cycles"
    assert "appendix.md" in diff
    assert "New appendix" in diff


def test_review_cycle_stops_on_repeated_finding_digest(tmp_path: Path) -> None:
    workspace = _init_repo(tmp_path)
    task = ReviewCycleTask(
        task_id="repeat",
        artifact_paths=["paper.md"],
        workspace_path=str(workspace),
        out_dir=str(tmp_path / "run-repeat"),
        max_cycles=3,
    )

    def reviewer(_task: ReviewCycleTask, cycle: int) -> ReviewCallResult:
        return ReviewCallResult(review=_high_review(), cost_usd=0.1, model="reviewer")

    def implementer(
        _task: ReviewCycleTask,
        cycle: int,
        classification: ActionableClassification,
    ) -> ApplyAttempt:
        with (workspace / "paper.md").open("a", encoding="utf-8") as handle:
            handle.write(f"Applied {cycle}\n")
        return ApplyAttempt(narrative="Changed.", cost_usd=0.1, model="impl")

    signoff = run_review_cycle(task, reviewer=reviewer, implementer=implementer)

    assert signoff.final_status == "repeated_digest"
    assert signoff.cycles_completed == 2


def test_review_cycle_fails_on_undeclared_file_edit(tmp_path: Path) -> None:
    workspace = _init_repo(tmp_path)
    task = ReviewCycleTask(
        task_id="illegal",
        artifact_paths=["paper.md"],
        workspace_path=str(workspace),
        out_dir=str(tmp_path / "run-illegal"),
    )

    def reviewer(_task: ReviewCycleTask, cycle: int) -> ReviewCallResult:
        return ReviewCallResult(review=_high_review(), cost_usd=0.1, model="reviewer")

    def implementer(
        _task: ReviewCycleTask,
        cycle: int,
        classification: ActionableClassification,
    ) -> ApplyAttempt:
        (workspace / "other.md").write_text("illegal\n", encoding="utf-8")
        subprocess.run(["git", "add", "other.md"], cwd=workspace, check=True)
        return ApplyAttempt(narrative="Changed undeclared file.", cost_usd=0.1, model="impl")

    try:
        run_review_cycle(task, reviewer=reviewer, implementer=implementer)
    except ReviewCycleError as exc:
        assert "undeclared" in str(exc)
    else:
        raise AssertionError("expected ReviewCycleError")


def test_review_cycle_fails_on_undeclared_ignored_file_edit(tmp_path: Path) -> None:
    workspace = _init_repo(tmp_path)
    (workspace / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-m", "ignore ignored dir"], cwd=workspace, check=True, capture_output=True)
    task = ReviewCycleTask(
        task_id="illegal-ignored",
        artifact_paths=["paper.md"],
        workspace_path=str(workspace),
        out_dir=str(tmp_path / "run-illegal-ignored"),
    )

    def reviewer(_task: ReviewCycleTask, cycle: int) -> ReviewCallResult:
        return ReviewCallResult(review=_high_review(), cost_usd=0.1, model="reviewer")

    def implementer(
        _task: ReviewCycleTask,
        cycle: int,
        classification: ActionableClassification,
    ) -> ApplyAttempt:
        ignored_dir = workspace / "ignored"
        ignored_dir.mkdir()
        (ignored_dir / "secret.txt").write_text("ignored but illegal\n", encoding="utf-8")
        return ApplyAttempt(narrative="Changed ignored undeclared file.", cost_usd=0.1, model="impl")

    try:
        run_review_cycle(task, reviewer=reviewer, implementer=implementer)
    except ReviewCycleError as exc:
        assert "ignored/secret.txt" in str(exc)
    else:
        raise AssertionError("expected ReviewCycleError")


def test_review_cycle_runtime_cache_carve_out_is_task_declared(tmp_path: Path) -> None:
    assert "runtime_cache_carveouts" in ReviewCycleTask.model_json_schema()["properties"]

    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    workspace = _init_repo(allowed_root)
    (workspace / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-m", "ignore bytecode cache"], cwd=workspace, check=True, capture_output=True)
    task = ReviewCycleTask(
        task_id="bytecode-cache",
        artifact_paths=["paper.md"],
        workspace_path=str(workspace),
        out_dir=str(tmp_path / "run-bytecode-cache"),
    )

    def reviewer(_task: ReviewCycleTask, cycle: int) -> ReviewCallResult:
        return ReviewCallResult(review=_high_review(), cost_usd=0.1, model="reviewer")

    def implementer(
        _task: ReviewCycleTask,
        cycle: int,
        classification: ActionableClassification,
    ) -> ApplyAttempt:
        cache_dir = workspace / "pkg" / "__pycache__"
        cache_dir.mkdir(parents=True)
        (cache_dir / "mod.cpython-312.pyc").write_bytes(b"bytecode cache")
        return ApplyAttempt(narrative="Runtime created bytecode cache.", cost_usd=0.1, model="impl")

    signoff = run_review_cycle(task, reviewer=reviewer, implementer=implementer)

    assert signoff.final_status == "no_diff"
    assert (workspace / "pkg" / "__pycache__" / "mod.cpython-312.pyc").is_file()

    strict_root = tmp_path / "strict"
    strict_root.mkdir()
    strict_workspace = _init_repo(strict_root)
    (strict_workspace / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=strict_workspace, check=True)
    subprocess.run(
        ["git", "commit", "-m", "ignore bytecode cache"],
        cwd=strict_workspace,
        check=True,
        capture_output=True,
    )
    strict_task = ReviewCycleTask(
        task_id="bytecode-cache-strict",
        artifact_paths=["paper.md"],
        workspace_path=str(strict_workspace),
        out_dir=str(tmp_path / "run-bytecode-cache-strict"),
        runtime_cache_carveouts=[],
    )

    def strict_implementer(
        _task: ReviewCycleTask,
        cycle: int,
        classification: ActionableClassification,
    ) -> ApplyAttempt:
        cache_dir = strict_workspace / "pkg" / "__pycache__"
        cache_dir.mkdir(parents=True)
        (cache_dir / "mod.cpython-312.pyc").write_bytes(b"bytecode cache")
        return ApplyAttempt(narrative="Runtime created bytecode cache.", cost_usd=0.1, model="impl")

    try:
        run_review_cycle(strict_task, reviewer=reviewer, implementer=strict_implementer)
    except ReviewCycleError as exc:
        assert "pkg/__pycache__/mod.cpython-312.pyc" in str(exc)
    else:
        raise AssertionError("expected ReviewCycleError")


def test_review_cycle_fails_on_modified_preexisting_ignored_file(tmp_path: Path) -> None:
    workspace = _init_repo(tmp_path)
    (workspace / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-m", "ignore ignored dir"], cwd=workspace, check=True, capture_output=True)
    ignored_dir = workspace / "ignored"
    ignored_dir.mkdir()
    (ignored_dir / "secret.txt").write_text("before\n", encoding="utf-8")
    task = ReviewCycleTask(
        task_id="modified-ignored",
        artifact_paths=["paper.md"],
        workspace_path=str(workspace),
        out_dir=str(tmp_path / "run-modified-ignored"),
    )

    def reviewer(_task: ReviewCycleTask, cycle: int) -> ReviewCallResult:
        return ReviewCallResult(review=_high_review(), cost_usd=0.1, model="reviewer")

    def implementer(
        _task: ReviewCycleTask,
        cycle: int,
        classification: ActionableClassification,
    ) -> ApplyAttempt:
        (ignored_dir / "secret.txt").write_text("after\n", encoding="utf-8")
        return ApplyAttempt(narrative="Changed ignored undeclared file.", cost_usd=0.1, model="impl")

    try:
        run_review_cycle(task, reviewer=reviewer, implementer=implementer)
    except ReviewCycleError as exc:
        assert "ignored/secret.txt" in str(exc)
    else:
        raise AssertionError("expected ReviewCycleError")


def test_review_cycle_allows_quoted_declared_status_path(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace, check=True)
    artifact = workspace / "paper with space.md"
    artifact.write_text("Initial paper\n", encoding="utf-8")
    subprocess.run(["git", "add", "paper with space.md"], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=workspace, check=True, capture_output=True)
    task = ReviewCycleTask(
        task_id="quoted-path",
        artifact_paths=["paper with space.md"],
        workspace_path=str(workspace),
        out_dir=str(tmp_path / "run-quoted-path"),
        max_cycles=1,
    )

    def reviewer(_task: ReviewCycleTask, cycle: int) -> ReviewCallResult:
        return ReviewCallResult(review=_high_review(), cost_usd=0.1, model="reviewer")

    def implementer(
        _task: ReviewCycleTask,
        cycle: int,
        classification: ActionableClassification,
    ) -> ApplyAttempt:
        with artifact.open("a", encoding="utf-8") as handle:
            handle.write("Allowed change\n")
        return ApplyAttempt(narrative="Changed declared file.", cost_usd=0.1, model="impl")

    signoff = run_review_cycle(task, reviewer=reviewer, implementer=implementer)

    assert signoff.final_status == "max_cycles"


def test_review_cycle_detects_committed_apply_diff(tmp_path: Path) -> None:
    workspace = _init_repo(tmp_path)
    task = ReviewCycleTask(
        task_id="committed",
        artifact_paths=["paper.md"],
        workspace_path=str(workspace),
        out_dir=str(tmp_path / "run-committed"),
        max_cycles=1,
    )

    def reviewer(_task: ReviewCycleTask, cycle: int) -> ReviewCallResult:
        return ReviewCallResult(review=_high_review(), cost_usd=0.1, model="reviewer")

    def implementer(
        _task: ReviewCycleTask,
        cycle: int,
        classification: ActionableClassification,
    ) -> ApplyAttempt:
        with (workspace / "paper.md").open("a", encoding="utf-8") as handle:
            handle.write("Committed apply\n")
        subprocess.run(["git", "add", "paper.md"], cwd=workspace, check=True)
        subprocess.run(["git", "commit", "-m", "apply"], cwd=workspace, check=True, capture_output=True)
        return ApplyAttempt(narrative="Committed change.", cost_usd=0.1, model="impl")

    signoff = run_review_cycle(task, reviewer=reviewer, implementer=implementer)

    assert signoff.final_status == "max_cycles"
    assert "Committed apply" in (task.run_dir() / "diff_1.patch").read_text()


def test_review_cycle_stops_on_budget_after_review(tmp_path: Path) -> None:
    workspace = _init_repo(tmp_path)
    task = ReviewCycleTask(
        task_id="budget",
        artifact_paths=["paper.md"],
        workspace_path=str(workspace),
        out_dir=str(tmp_path / "run-budget"),
        max_budget=0.1,
    )

    def reviewer(_task: ReviewCycleTask, cycle: int) -> ReviewCallResult:
        return ReviewCallResult(review=_high_review(), cost_usd=0.2, model="reviewer")

    signoff = run_review_cycle(task, reviewer=reviewer)

    assert signoff.final_status == "budget_exhausted"
    assert signoff.budget_spent_usd == 0.2


def test_review_cycle_pass_takes_precedence_over_budget_after_review(tmp_path: Path) -> None:
    workspace = _init_repo(tmp_path)
    task = ReviewCycleTask(
        task_id="pass-budget",
        artifact_paths=["paper.md"],
        workspace_path=str(workspace),
        out_dir=str(tmp_path / "run-pass-budget"),
        max_budget=0.1,
    )

    def reviewer(_task: ReviewCycleTask, cycle: int) -> ReviewCallResult:
        return ReviewCallResult(review=_pass_review(), cost_usd=0.2, model="reviewer")

    signoff = run_review_cycle(task, reviewer=reviewer)

    assert signoff.final_status == "pass"
    assert signoff.budget_spent_usd == 0.2
