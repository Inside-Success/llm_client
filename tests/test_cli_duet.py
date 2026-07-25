"""End-to-end CLI tests for the ``duet-review`` subcommand.

The duet-review CLI resolves a ``--task-family`` to a registered profile and
threads ``family.plan_review_schema`` (and ``family.implement_review_schema``)
into ``call_llm_structured``. Plan #31's self-review surfaced that no test
exercised the threading path through ``cmd_duet_review``; this module closes
that gap by monkeypatching ``call_llm_structured`` at its source and asserting
the resolved schema arrives at the structured call.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from llm_client.workflow.duet import PlanReview
from llm_client.workflow.profiles.plan_doc_review import PlanDocPlanReview


def _make_cli_args(
    plan_doc: Path,
    workspace: Path,
    out: Path,
    *,
    task_family: str = "generic",
    customer: str | None = None,
    ai: str | None = None,
    ticket_id: str | None = None,
    complaint_file: str | None = None,
    customer_constraints: str | None = None,
    published_prod_qa_artifact: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        plan_doc=str(plan_doc),
        workspace=str(workspace),
        out=str(out),
        task_title="cli-smoke",
        task_goal="exercise --task-family threading",
        task_id="cli-smoke",
        plan_id="plan-cli-smoke",
        success_criteria=None,
        constraints=None,
        reviewer_model="stub-model",
        task_family=task_family,
        impl_base=None,
        impl_head="HEAD",
        impl_files=None,
        max_budget=1.0,
        timeout=30,
        customer=customer,
        ai=ai,
        ticket_id=ticket_id,
        complaint_file=complaint_file,
        customer_constraints=customer_constraints,
        published_prod_qa_artifact=published_prod_qa_artifact,
    )


class _StubReview:
    """Stub that satisfies the chassis's ``review.model_dump()`` call + the
    field accesses that ``cmd_duet_review`` makes for the summary print.
    """

    def __init__(self) -> None:
        self._payload: dict = {
            "verdict": "pass",
            "reviewer_summary": "stub",
            "reviewer_model": "",
            "blockers": [],
            "nits": [],
            "unverified_claims": [],
            "missing_acceptance_checks": [],
            "scope_creep_findings": [],
            "correctness_findings": [],
            "contract_violations": [],
            "unverified_test_claims": [],
            "missing_followups_from_plan": [],
            "scope_drift_findings": [],
            "template_section_misses": [],
            "references_unverified": [],
            "acceptance_criteria_unmeasurable": [],
        }

    def model_dump(self) -> dict:
        return dict(self._payload)


@pytest.fixture
def cli_setup(tmp_path: Path):
    plan_doc = tmp_path / "plan.md"
    plan_doc.write_text("# Test plan\n\nMinimal content for CLI threading.\n", encoding="utf-8")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    out_root = tmp_path / "out"
    return plan_doc, workspace, out_root


def test_cli_default_task_family_threads_generic_planreview_schema(
    cli_setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ``--task-family`` flag → CLI must use the registered ``generic``
    profile, which means ``PlanReview`` is the schema passed to
    ``call_llm_structured``.
    """
    from llm_client.cli.duet import cmd_duet_review

    plan_doc, workspace, out_root = cli_setup
    captured: dict = {}

    def fake_call_llm_structured(model, messages, response_model, **kwargs):
        captured["model"] = model
        captured["schema"] = response_model
        return _StubReview(), _StubReview()

    monkeypatch.setattr("llm_client.call_llm_structured", fake_call_llm_structured)

    args = _make_cli_args(plan_doc, workspace, out_root / "default")
    cmd_duet_review(args)

    assert captured["schema"] is PlanReview
    assert captured["model"] == "stub-model"


def test_cli_plan_doc_review_threads_specialized_schema(
    cli_setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--task-family plan_doc_review`` must reach ``call_llm_structured``
    with the specialized ``PlanDocPlanReview`` schema, not the generic one.

    Closes the CLI-threading acceptance-criterion gap surfaced by Plan #31's
    self-review (runs/plan-31-review/plan_review.json:acceptance_criteria_unmeasurable).
    """
    from llm_client.cli.duet import cmd_duet_review

    plan_doc, workspace, out_root = cli_setup
    captured: dict = {}

    def fake_call_llm_structured(model, messages, response_model, **kwargs):
        captured["schema"] = response_model
        captured["cwd"] = kwargs.get("cwd")
        return _StubReview(), _StubReview()

    monkeypatch.setattr("llm_client.call_llm_structured", fake_call_llm_structured)

    args = _make_cli_args(plan_doc, workspace, out_root / "plan-doc", task_family="plan_doc_review")
    cmd_duet_review(args)

    assert captured["schema"] is PlanDocPlanReview
    # cwd must equal the resolved workspace (Plan #30 hardening contract).
    # Compare with both sides resolved to handle pytest tmp_path symlink quirks.
    assert Path(captured["cwd"]).resolve() == workspace.resolve()


def test_cli_twin_update_flags_route_to_task_extra(
    cli_setup, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``--customer / --ai / --ticket-id / --complaint-file / --customer-constraints
    / --published-prod-qa-artifact`` must flow into ``task.extra`` where the
    twin_update profile's context_loader consumes them.
    """
    from llm_client.cli.duet import cmd_duet_review

    plan_doc, workspace, out_root = cli_setup
    complaint_file = tmp_path / "complaint.txt"
    complaint_file.write_text("Twin says 'um' every other sentence.\n", encoding="utf-8")

    captured_task: dict = {}

    def fake_call_llm_structured(model, messages, response_model, **kwargs):
        # The CLI persists the task before calling; re-read it from disk so
        # we can inspect the actual JSON shape.
        return _StubReview(), _StubReview()

    monkeypatch.setattr("llm_client.call_llm_structured", fake_call_llm_structured)

    args = _make_cli_args(
        plan_doc,
        workspace,
        out_root / "twin",
        task_family="twin_update",
        customer="tony",
        ai="genius",
        ticket_id="STENO-1234",
        complaint_file=str(complaint_file),
        customer_constraints="no medical advice; no political takes",
        published_prod_qa_artifact="customer_files/tony/QA.yaml",
    )
    cmd_duet_review(args)

    import json
    task_path = out_root / "twin" / "task.json"
    captured_task = json.loads(task_path.read_text(encoding="utf-8"))
    extra = captured_task["extra"]
    assert extra["customer"] == "tony"
    assert extra["ai"] == "genius"
    assert extra["ticket_id"] == "STENO-1234"
    assert "um" in extra["complaint_text"]
    assert extra["customer_constraints"] == ["no medical advice", "no political takes"]
    assert extra["published_prod_qa_artifact_path"] == "customer_files/tony/QA.yaml"


def test_cli_complaint_file_missing_exits_with_clear_error(
    cli_setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing --complaint-file path must surface a clear sys.exit(2)
    instead of crashing inside the context loader.
    """
    from llm_client.cli.duet import cmd_duet_review

    plan_doc, workspace, out_root = cli_setup
    args = _make_cli_args(
        plan_doc,
        workspace,
        out_root / "missing",
        task_family="twin_update",
        complaint_file="/tmp/this_file_does_not_exist_xyz.txt",
    )
    with pytest.raises(SystemExit) as exc_info:
        cmd_duet_review(args)
    assert exc_info.value.code == 2


def test_cli_no_twin_update_flags_leaves_extra_empty(
    cli_setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generic profile calls (no twin-update flags) must produce an empty extra,
    so non-twin tasks aren't burdened with an unrelated dict.
    """
    from llm_client.cli.duet import cmd_duet_review

    plan_doc, workspace, out_root = cli_setup

    def fake_call_llm_structured(model, messages, response_model, **kwargs):
        return _StubReview(), _StubReview()

    monkeypatch.setattr("llm_client.call_llm_structured", fake_call_llm_structured)

    args = _make_cli_args(plan_doc, workspace, out_root / "bare")
    cmd_duet_review(args)

    import json
    task = json.loads((out_root / "bare" / "task.json").read_text(encoding="utf-8"))
    assert task["extra"] == {}


def test_cli_unknown_task_family_raises(cli_setup) -> None:
    """A bogus profile name must surface a clear KeyError before any LLM call.

    The registry has no silent fallback to ``generic``.
    """
    from llm_client.cli.duet import cmd_duet_review

    plan_doc, workspace, out_root = cli_setup
    args = _make_cli_args(
        plan_doc, workspace, out_root / "bogus", task_family="this_does_not_exist"
    )
    with pytest.raises(KeyError, match="not registered"):
        cmd_duet_review(args)
