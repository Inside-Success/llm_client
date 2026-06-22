"""Tests for the implementer/reviewer duet workflow.

Stubs the LLM calls at the ``WorkflowContext`` integration seam so the LangGraph
wiring, routers, cycle gating, role assignment, and artifact persistence can be
exercised offline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

try:
    import langgraph  # noqa: F401

    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False

pytestmark = pytest.mark.skipif(not HAS_LANGGRAPH, reason="langgraph not installed")

from llm_client.workflow.duet import (  # noqa: E402
    CorrectnessFinding,
    DuetRoles,
    DuetTask,
    ImplementReview,
    PlanReview,
    PlanReviewBlocker,
    _parse_implementer_response,
    build_duet_workflow,
)
from llm_client.workflow.duet_base import ImplementReviewBase, PlanReviewBase  # noqa: E402


@dataclass
class _StubResult:
    content: str
    usage: dict[str, Any] = field(default_factory=dict)
    cost: float = 0.0
    model: str = "stub"


def _plan_response(reason: str = "v1") -> str:
    sidecar = {
        "plan_id": f"plan_{reason}",
        "task_id": "t1",
        "author_model": "ignored-rewritten-by-node",
        "steps": [
            {
                "step_id": "s1",
                "description": "Add docstring to foo.py",
                "files_touched": ["foo.py"],
                "depends_on": [],
                "acceptance_check": "foo.py has module docstring",
            }
        ],
    }
    return f"# Plan ({reason})\n\nWe will add a docstring.\n\n```json\n{json.dumps(sidecar)}\n```"


def _impl_response(reason: str = "v1") -> str:
    sidecar = {
        "implement_id": f"impl_{reason}",
        "plan_id": "plan_v1",
        "files_changed": [{"path": "foo.py", "plus_loc": 1, "minus_loc": 0, "intent": "add docstring"}],
        "decisions": [{"decision": "use module docstring", "rejected_alternative": "class docstring", "why": "module-level fits"}],
    }
    return f"# Impl ({reason})\n\nAdded the docstring.\n\n```json\n{json.dumps(sidecar)}\n```"


class _DuetHarness:
    """Captures stub call sequence and asserts role assignment."""

    def __init__(self) -> None:
        self.call_log: list[tuple[str, str]] = []  # (kind, model)
        self.call_kwargs: list[tuple[str, dict[str, Any]]] = []  # (kind, kwargs)
        self.plan_responses: list[str] = []
        self.impl_responses: list[str] = []
        self.plan_reviews: list[PlanReview] = []
        self.impl_reviews: list[ImplementReview] = []

    def call_llm(self, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> _StubResult:
        # The implementer prompt format is the most reliable kind discriminator.
        user_blob = messages[-1]["content"]
        if "Schema for the JSON sidecar of your response" in user_blob:
            kind = "implement"
            queue = self.impl_responses
        else:
            kind = "plan"
            queue = self.plan_responses
        self.call_log.append((kind, model))
        self.call_kwargs.append((kind, dict(kwargs)))
        if not queue:
            raise AssertionError(f"No stub {kind} response queued for model {model}")
        return _StubResult(content=queue.pop(0), model=model)

    def call_llm_structured(
        self,
        model: str,
        messages: list[dict[str, Any]],
        response_model: type,
        **kwargs: Any,
    ) -> tuple[Any, _StubResult]:
        # Accept any schema that inherits from the duet review base classes
        # so profile-specialized subclasses (e.g. PlanDocPlanReview) route to
        # the right queue.
        if isinstance(response_model, type) and issubclass(response_model, PlanReviewBase):
            kind = "plan_review"
            queue = self.plan_reviews
        elif isinstance(response_model, type) and issubclass(response_model, ImplementReviewBase):
            kind = "implement_review"
            queue = self.impl_reviews
        else:
            raise AssertionError(f"Unexpected response_model: {response_model}")
        self.call_log.append((kind, model))
        self.call_kwargs.append((kind, dict(kwargs)))
        if not queue:
            raise AssertionError(f"No stub {kind} response queued for model {model}")
        return queue.pop(0), _StubResult(content="", model=model)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> _DuetHarness:
    h = _DuetHarness()

    def fake_call_llm(model: str, messages: list[dict[str, Any]], **kwargs: Any) -> _StubResult:
        return h.call_llm(model, messages, **kwargs)

    def fake_call_llm_structured(
        model: str,
        messages: list[dict[str, Any]],
        response_model: type,
        **kwargs: Any,
    ) -> tuple[Any, _StubResult]:
        return h.call_llm_structured(model, messages, response_model, **kwargs)

    # WorkflowContext.call_llm imports these lazily, so we patch the symbol in
    # the source module.
    monkeypatch.setattr("llm_client.core.client.call_llm", fake_call_llm)
    monkeypatch.setattr("llm_client.core.client.call_llm_structured", fake_call_llm_structured)
    return h


def _task(workspace: Path) -> DuetTask:
    return DuetTask(
        task_id="t1",
        title="Add docstring",
        goal="Add a module-level docstring to foo.py",
        success_criteria=["foo.py imports without error", "module docstring present"],
        constraints=["do not change function signatures"],
        workspace_path=str(workspace),
    )


def _run(app: Any, initial_state: dict[str, Any], thread_id: str) -> dict[str, Any]:
    return app.invoke(initial_state, config={"configurable": {"thread_id": thread_id}})


def test_duet_happy_path_both_reviewers_pass(harness: _DuetHarness, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    harness.plan_responses = [_plan_response("v1")]
    harness.plan_reviews = [PlanReview(verdict="pass", reviewer_summary="lgtm")]
    harness.impl_responses = [_impl_response("v1")]
    harness.impl_reviews = [ImplementReview(verdict="pass", reviewer_summary="lgtm")]

    app, init = build_duet_workflow(
        run_dir=run_dir,
        task=_task(tmp_path / "ws"),
        trace_id="t-happy",
        max_budget=1.0,
    )
    result = _run(app, init, "t-happy")

    assert result["final_verdict"] == "pass"
    assert [k for k, _ in harness.call_log] == ["plan", "plan_review", "implement", "implement_review"]
    assert (run_dir / "signoff.json").exists()


def test_duet_revise_plan_once_then_pass(harness: _DuetHarness, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    harness.plan_responses = [_plan_response("v1"), _plan_response("v2")]
    harness.plan_reviews = [
        PlanReview(verdict="revise", reviewer_summary="add an acceptance check"),
        PlanReview(verdict="pass", reviewer_summary="lgtm"),
    ]
    harness.impl_responses = [_impl_response("v1")]
    harness.impl_reviews = [ImplementReview(verdict="pass", reviewer_summary="lgtm")]

    app, init = build_duet_workflow(
        run_dir=run_dir,
        task=_task(tmp_path / "ws"),
        trace_id="t-revise",
        max_budget=1.0,
    )
    result = _run(app, init, "t-revise")

    assert result["final_verdict"] == "pass"
    kinds = [k for k, _ in harness.call_log]
    assert kinds == ["plan", "plan_review", "plan", "plan_review", "implement", "implement_review"]
    assert result["plan_cycle"] == 2


def test_duet_plan_review_block_halts(harness: _DuetHarness, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    harness.plan_responses = [_plan_response("v1")]
    harness.plan_reviews = [PlanReview(verdict="block", reviewer_summary="needs rescope")]

    app, init = build_duet_workflow(
        run_dir=run_dir,
        task=_task(tmp_path / "ws"),
        trace_id="t-block",
        max_budget=1.0,
    )
    result = _run(app, init, "t-block")

    assert result["final_verdict"] == "block"
    kinds = [k for k, _ in harness.call_log]
    assert "implement" not in kinds
    assert (run_dir / "signoff.json").exists()
    signoff = json.loads((run_dir / "signoff.json").read_text())
    assert signoff["final_verdict"] == "block"


def test_duet_second_revise_promoted_to_block(harness: _DuetHarness, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    harness.plan_responses = [_plan_response("v1"), _plan_response("v2")]
    harness.plan_reviews = [
        PlanReview(verdict="revise", reviewer_summary="round 1"),
        PlanReview(verdict="revise", reviewer_summary="round 2"),
    ]

    app, init = build_duet_workflow(
        run_dir=run_dir,
        task=_task(tmp_path / "ws"),
        trace_id="t-cap",
        max_budget=1.0,
        max_revise_cycles=1,
    )
    result = _run(app, init, "t-cap")

    assert result["final_verdict"] == "block"
    assert result["plan_cycle"] == 2
    kinds = [k for k, _ in harness.call_log]
    assert kinds.count("plan") == 2
    assert "implement" not in kinds


def test_duet_uses_role_assignment(harness: _DuetHarness, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    harness.plan_responses = [_plan_response("v1")]
    harness.plan_reviews = [PlanReview(verdict="pass")]
    harness.impl_responses = [_impl_response("v1")]
    harness.impl_reviews = [ImplementReview(verdict="pass")]

    roles = DuetRoles(
        plan="claude-code/opus",
        plan_review="codex/gpt-5-codex",
        implement="claude-code/opus",
        implement_review="codex/gpt-5-codex",
    )
    app, init = build_duet_workflow(
        run_dir=run_dir,
        task=_task(tmp_path / "ws"),
        trace_id="t-roles",
        max_budget=1.0,
        roles=roles,
    )
    _run(app, init, "t-roles")

    by_kind = dict(harness.call_log)
    assert by_kind["plan"] == "claude-code/opus"
    assert by_kind["plan_review"] == "codex/gpt-5-codex"
    assert by_kind["implement"] == "claude-code/opus"
    assert by_kind["implement_review"] == "codex/gpt-5-codex"


def test_duet_persists_artifacts_to_run_dir(harness: _DuetHarness, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    harness.plan_responses = [_plan_response("v1")]
    harness.plan_reviews = [PlanReview(verdict="pass")]
    harness.impl_responses = [_impl_response("v1")]
    harness.impl_reviews = [ImplementReview(verdict="pass")]

    app, init = build_duet_workflow(
        run_dir=run_dir,
        task=_task(tmp_path / "ws"),
        trace_id="t-artifacts",
        max_budget=1.0,
    )
    _run(app, init, "t-artifacts")

    expected = {
        "task.json",
        "plan.md",
        "plan.json",
        "plan_review.json",
        "implement.md",
        "implement.json",
        "implement_review.json",
        "signoff.json",
    }
    actual = {p.name for p in run_dir.iterdir()}
    assert expected.issubset(actual), f"missing artifacts: {expected - actual}"


def test_duet_threads_workspace_path_as_cwd(harness: _DuetHarness, tmp_path: Path) -> None:
    """Every stage must receive cwd=task.workspace_path so the agent SDK inspects
    the right tree. Without this, reviewer "inspect the workspace" prompts
    silently misfire when the duet is invoked from anywhere other than the
    workspace root.
    """
    run_dir = tmp_path / "run"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    harness.plan_responses = [_plan_response("v1")]
    harness.plan_reviews = [PlanReview(verdict="pass")]
    harness.impl_responses = [_impl_response("v1")]
    harness.impl_reviews = [ImplementReview(verdict="pass")]

    app, init = build_duet_workflow(
        run_dir=run_dir,
        task=_task(workspace),
        trace_id="t-cwd",
        max_budget=1.0,
    )
    _run(app, init, "t-cwd")

    expected_cwd = str(workspace)
    saw = {kind: kwargs.get("cwd") for kind, kwargs in harness.call_kwargs}
    assert saw == {
        "plan": expected_cwd,
        "plan_review": expected_cwd,
        "implement": expected_cwd,
        "implement_review": expected_cwd,
    }


def test_duet_task_accepts_extra_field() -> None:
    """DuetTask.extra is the profile-extension hook that domain profiles
    (twin_update, eval_audit) use for per-task params like customer/ai/ticket.
    Verify it round-trips through model_dump() without losing data.
    """
    task = DuetTask(
        task_id="t",
        title="t",
        goal="t",
        workspace_path="/ws",
        extra={"customer": "tony", "ai": "genius", "ticket_id": "STENO-1"},
    )
    dumped = task.model_dump()
    assert dumped["extra"] == {"customer": "tony", "ai": "genius", "ticket_id": "STENO-1"}

    # Default is empty dict; chassis code can rely on `.get("extra") or {}`.
    bare = DuetTask(task_id="t", title="t", goal="t", workspace_path="/ws")
    assert bare.extra == {}


def test_duet_default_task_family_is_generic(harness: _DuetHarness, tmp_path: Path) -> None:
    """When task_family is unspecified, ``build_duet_workflow`` must resolve to
    ``generic`` and produce the same behavior as before Plan #31. Verified by
    checking the structured-call response_model is the generic ``PlanReview``.
    """
    captured_schemas: list[type] = []
    original = harness.call_llm_structured

    def capture_schema(model, messages, response_model, **kwargs):
        captured_schemas.append(response_model)
        return original(model, messages, response_model, **kwargs)

    harness.call_llm_structured = capture_schema  # type: ignore[assignment]

    run_dir = tmp_path / "run"
    harness.plan_responses = [_plan_response("v1")]
    harness.plan_reviews = [PlanReview(verdict="pass")]
    harness.impl_responses = [_impl_response("v1")]
    harness.impl_reviews = [ImplementReview(verdict="pass")]

    app, init = build_duet_workflow(
        run_dir=run_dir,
        task=_task(tmp_path / "ws"),
        trace_id="t-generic-default",
        max_budget=1.0,
        # no task_family= passed
    )
    _run(app, init, "t-generic-default")

    assert captured_schemas == [PlanReview, ImplementReview]


def test_duet_with_plan_doc_review_profile_uses_specialized_schema(
    harness: _DuetHarness, tmp_path: Path
) -> None:
    """``task_family='plan_doc_review'`` must route the plan_review call to
    the specialized ``PlanDocPlanReview`` schema while keeping the generic
    ``ImplementReview`` for the implementation review.
    """
    from llm_client.workflow.profiles.plan_doc_review import PlanDocPlanReview

    captured_schemas: list[type] = []
    original = harness.call_llm_structured

    def capture_schema(model, messages, response_model, **kwargs):
        captured_schemas.append(response_model)
        return original(model, messages, response_model, **kwargs)

    harness.call_llm_structured = capture_schema  # type: ignore[assignment]

    run_dir = tmp_path / "run"
    harness.plan_responses = [_plan_response("v1")]
    harness.plan_reviews = [PlanDocPlanReview(verdict="pass")]
    harness.impl_responses = [_impl_response("v1")]
    harness.impl_reviews = [ImplementReview(verdict="pass")]

    app, init = build_duet_workflow(
        run_dir=run_dir,
        task=_task(tmp_path / "ws"),
        trace_id="t-plan-doc-review",
        max_budget=1.0,
        task_family="plan_doc_review",
    )
    _run(app, init, "t-plan-doc-review")

    assert captured_schemas == [PlanDocPlanReview, ImplementReview]


def test_duet_unknown_task_family_raises_at_build_time(tmp_path: Path) -> None:
    """Mistyped or missing profile name must fail loud, not silently fall back."""
    with pytest.raises(KeyError, match="not registered"):
        build_duet_workflow(
            run_dir=tmp_path / "run",
            task=_task(tmp_path / "ws"),
            trace_id="t-unknown",
            max_budget=1.0,
            task_family="this_profile_does_not_exist",
        )


def test_plan_review_blocker_requires_evidence_path() -> None:
    """A blocker without evidence_path must fail validation before reaching the
    router. Reviewer verdicts must be falsifiable.
    """
    import pydantic

    # Valid blocker
    blocker = PlanReviewBlocker(claim="x", evidence_path="docs/plan.md#step-3")
    assert blocker.evidence_path == "docs/plan.md#step-3"

    # Missing evidence_path → ValidationError
    with pytest.raises(pydantic.ValidationError, match="evidence_path"):
        PlanReviewBlocker(claim="x")


def test_correctness_finding_requires_file_and_line() -> None:
    """A correctness finding without file_path + line is unfalsifiable opinion."""
    import pydantic

    # Valid finding
    finding = CorrectnessFinding(file_path="x.py", line=42, claim="off by one")
    assert finding.severity == "warn"  # default

    # Missing file_path
    with pytest.raises(pydantic.ValidationError, match="file_path"):
        CorrectnessFinding(line=42, claim="x")  # type: ignore[call-arg]

    # Missing line
    with pytest.raises(pydantic.ValidationError, match="line"):
        CorrectnessFinding(file_path="x.py", claim="x")  # type: ignore[call-arg]


def test_implement_review_rejects_ungrounded_correctness_findings() -> None:
    """correctness_findings is now list[CorrectnessFinding], not list[dict[str, str]].

    Loose dicts that omit file_path or line are rejected by the schema, so
    reviewers cannot smuggle in opinion-as-code-finding.
    """
    import pydantic

    # Valid review
    review = ImplementReview(
        verdict="pass",
        correctness_findings=[
            CorrectnessFinding(file_path="x.py", line=10, claim="ok"),
        ],
    )
    assert review.correctness_findings[0].file_path == "x.py"

    # Loose dict missing line → ValidationError
    with pytest.raises(pydantic.ValidationError, match="line"):
        ImplementReview(
            verdict="pass",
            correctness_findings=[{"file_path": "x.py", "claim": "no line"}],  # type: ignore[list-item]
        )


def test_parse_implementer_response_missing_fence_raises() -> None:
    with pytest.raises(ValueError, match="missing fenced JSON sidecar"):
        _parse_implementer_response("just a narrative, no json fence")


def test_parse_implementer_response_invalid_json_raises() -> None:
    with pytest.raises(ValueError, match="parse implementer JSON sidecar"):
        _parse_implementer_response("narrative\n\n```json\n{not valid json}\n```")
