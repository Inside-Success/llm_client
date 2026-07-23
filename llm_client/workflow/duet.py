"""Implementer/reviewer duet workflow.

Sequences four stages -- plan, plan_review, implement, implement_review --
where any stage can be assigned to either ``claude-code`` or ``codex/*`` via
``DuetRoles``. Reviewer stages return a structured ``verdict`` that drives
LangGraph conditional edges deterministically. Implementer stages emit a
markdown narrative plus a JSON sidecar so the reviewer sees both prose
reasoning and machine-checkable atoms.

Context transfer between stages is via durable artifacts on disk -- no tool
transcripts. The next stage's prompt receives the prior artifacts and a
workspace path; the agent re-reads the workspace fresh.

Architecture layered across Plans #29-32 + followups:

- Plan #29 (this file's core) -- chassis: schemas, prompts, nodes, routers,
  builder. Followup commit 47c0821 resolves ``claude-code/<alias>`` to full
  Anthropic model IDs in ``sdk/agents_claude.py``.
- Plan #30 -- autonomous hardening: ``task["workspace_path"]`` threaded into
  all four node call sites as ``cwd=``; ``PlanReviewBlocker.evidence_path``
  required; typed ``CorrectnessFinding(file_path, line, claim, severity)``;
  ``python -m llm_client duet-review`` CLI subcommand for review-only mode.
  Followup commit 2e1741d aliases ``cwd`` <-> ``working_directory`` at the
  agent SDK route boundary (the codex adapter reads ``working_directory``).
- Plan #31 -- TaskFamily abstraction: chassis split from profiles via
  ``duet_base.py`` (PlanReviewBase, ImplementReviewBase, TaskFamily) and
  ``duet_registry.py``. Built-in profiles ``generic`` and
  ``plan_doc_review`` ship under ``llm_client.workflow.profiles``.
- Plan #32 -- ``twin_update`` profile encoding PCM v2's 5 layers plus the
  Twin Fidelity rubric's three axes; small chassis addition
  ``DuetTask.extra: dict[str, Any]`` as the per-task profile-extension hook.

For the per-plan design rationale, see ``docs/plans/29_*.md`` through
``docs/plans/32_*.md`` (each plan has a Completion Log section).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Callable, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from llm_client.workflow.config import WorkflowConfig
from llm_client.workflow.context import WorkflowContext
from llm_client.workflow.duet_base import (
    DuetVerdict,
    ImplementReviewBase,
    PlanReviewBase,
    TaskFamily,
)

logger = logging.getLogger(__name__)
# Defaults use the ChatGPT-account-compatible codex model. The API-only
# ``codex/gpt-5-codex`` model gives stronger code performance but errors on
# ChatGPT-account auth ("The 'gpt-5-codex' model is not supported when using
# Codex with a ChatGPT account."). Operators with API auth can override per
# stage via ``DuetRoles(plan="codex/gpt-5-codex", ...)``.
DEFAULT_PLAN_MODEL = "codex/gpt-5.4"
DEFAULT_PLAN_REVIEW_MODEL = "claude-code/sonnet"
DEFAULT_IMPLEMENT_MODEL = "codex/gpt-5.4"
DEFAULT_IMPLEMENT_REVIEW_MODEL = "claude-code/sonnet"

# Codex agent calls legitimately take minutes — codex auto-explores the
# workspace (sed reads, glob walks) before answering. The framework-wide
# ``call_llm`` default of 60s is appropriate for stateless OpenAI/Anthropic
# calls but produces spurious ``CODEX_TIMEOUT`` on duet stages. The codex
# SDK's own internal default is 300s; match it here.
DEFAULT_DUET_STAGE_TIMEOUT_S = 300

# Default ``codex_transport="sdk"`` in-process SDK can hit a Pydantic
# ValidationError when it sees ``FileChangeItem.status="in_progress"`` from
# a streaming codex turn while the local SDK schema still only accepts
# ``completed|failed``. ``codex_transport="auto"`` keeps SDK as primary but
# falls back to CLI on this known transport-compatibility issue. See
# llm_client.sdk.agents._is_codex_sdk_parse_validation_error for detection.
# Harmless on non-codex stages (claude-code/* adapters ignore the kwarg).
DEFAULT_DUET_CODEX_TRANSPORT = "auto"

STAGES = ("plan", "plan_review", "implement", "implement_review")


class DuetTask(BaseModel):
    """The task the duet is asked to plan, implement, and review.

    Persisted to ``<run_dir>/task.json`` at the start of a run.

    The ``extra`` dict is the profile-extension hook: domain profiles (e.g.
    ``twin_update``) stash per-task params (``customer``, ``ai``, ``ticket_id``,
    ``complaint_text``, ``customer_constraints``, etc.) here without forking
    the chassis task schema. Chassis code ignores ``extra``; profile
    ``context_loader`` callables consume it.
    """

    task_id: str
    title: str
    goal: str
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    workspace_path: str
    base_commit_sha: str | None = None
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class DuetRoles(BaseModel):
    """Per-stage model assignment.

    Defaults to ``codex/gpt-5.4`` for implement stages and
    ``claude-code/sonnet`` for review stages. Override per stage as needed.
    Operators with Codex API auth (not ChatGPT-account auth) can switch
    implement stages to ``codex/gpt-5-codex`` for stronger code performance.
    """

    plan: str = DEFAULT_PLAN_MODEL
    plan_review: str = DEFAULT_PLAN_REVIEW_MODEL
    implement: str = DEFAULT_IMPLEMENT_MODEL
    implement_review: str = DEFAULT_IMPLEMENT_REVIEW_MODEL

    def for_stage(self, stage: str) -> str:
        """Resolve the model string assigned to ``stage``.

        Raises ``ValueError`` for unknown stage names so callers get a loud
        error rather than a silent fallback to the default model.
        """
        if stage not in STAGES:
            raise ValueError(f"Unknown duet stage: {stage!r}. Valid: {STAGES}")
        return str(getattr(self, stage))


class PlanStepAtom(BaseModel):
    """One step of an implementer-authored plan.

    Plans decompose a task into a small number of these atoms so the reviewer
    can score each step independently and so dependency ordering is explicit.
    ``acceptance_check`` should be a sentence the reviewer can later confirm
    or deny against the implementation diff.
    """

    step_id: str
    description: str
    files_touched: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    acceptance_check: str = ""


class PlanArtifact(BaseModel):
    """Sidecar JSON for a plan; the narrative lives in ``plan.md``."""

    plan_id: str
    task_id: str
    author_model: str
    steps: list[PlanStepAtom]
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    risks: list[dict[str, str]] = Field(default_factory=list)
    estimated_diff_size_loc: int | None = None
    estimated_files_changed: int | None = None


class Nit(BaseModel):
    """A non-blocking finding the reviewer noticed but doesn't block on.

    Typed (not a free-form dict) so the schema is OpenAI strict-mode
    compatible. ``location`` should be a file path, line range, or section
    name; empty when the nit is general.
    """

    model_config = ConfigDict(extra="forbid")

    claim: str
    location: str = ""
    suggested_fix: str = ""


class UnverifiedClaim(BaseModel):
    """A claim from the plan that the reviewer could not verify.

    Distinct from ``Nit`` (which is the reviewer's own observation) and from
    ``PlanReviewBlocker`` (which has a citation). Use when the reviewer
    cannot confirm or refute a planner assertion from the available evidence.
    """

    model_config = ConfigDict(extra="forbid")

    claim: str
    reason_unverified: str = ""


class ContractViolation(BaseModel):
    """A way the implementation breaks one of the task's stated constraints.

    ``evidence_path`` is required so contract violations are falsifiable.
    Free-text scope-drift goes into ``scope_drift_findings`` instead.
    """

    model_config = ConfigDict(extra="forbid")

    constraint: str
    violation: str
    evidence_path: str


class PlanReviewBlocker(BaseModel):
    """A blocker flagged in plan review.

    ``evidence_path`` is required so reviewer verdicts are falsifiable: a
    blocker without a citation is opinion, not evidence. Reviewers that
    genuinely cannot cite a source should downgrade to a ``nit`` or to an
    ``unverified_claim`` instead of emitting a blocker.
    """

    model_config = ConfigDict(extra="forbid")

    step_id: str | None = None
    claim: str
    evidence_path: str
    suggested_fix: str = ""


class PlanReview(PlanReviewBase):
    """Generic plan-review schema; the default for the duet chassis.

    Subclassed by domain profiles that need extra fields. The router only
    branches on ``verdict`` (inherited from ``PlanReviewBase``), so subclass
    additions don't break control flow.
    """

    model_config = ConfigDict(extra="forbid")

    blockers: list[PlanReviewBlocker] = Field(default_factory=list)
    nits: list[Nit] = Field(default_factory=list)
    unverified_claims: list[UnverifiedClaim] = Field(default_factory=list)
    missing_acceptance_checks: list[str] = Field(default_factory=list)
    scope_creep_findings: list[str] = Field(default_factory=list)


class ImplementFileChange(BaseModel):
    """One file the implementer touched, with line-count deltas + intent.

    Surfaced in the implement sidecar so the reviewer can scan the diff shape
    without re-deriving it. ``intent`` is the implementer's one-line
    justification — the reviewer treats it as the implementer's claim, not as
    independent evidence.
    """

    path: str
    plus_loc: int = 0
    minus_loc: int = 0
    intent: str = ""


class ImplementCommit(BaseModel):
    """A single git commit produced by the implement stage."""

    sha: str
    message: str


class ImplementDeviation(BaseModel):
    """A plan step the implementer chose to do differently, with the reason.

    The reviewer uses these to distinguish "intentional plan revision" from
    "implementer drift." Empty list means the implementation followed the
    plan as written.
    """

    step_id: str
    what_changed: str
    why: str


class ImplementDecision(BaseModel):
    """A single one-line entry in the implementer's decisions journal."""

    decision: str
    rejected_alternative: str = ""
    why: str = ""


class ImplementArtifact(BaseModel):
    """Sidecar JSON for an implementation; narrative in ``implement.md``."""

    implement_id: str
    plan_id: str
    head_commit_sha: str | None = None
    base_commit_sha: str | None = None
    files_changed: list[ImplementFileChange] = Field(default_factory=list)
    commits: list[ImplementCommit] = Field(default_factory=list)
    deviations_from_plan: list[ImplementDeviation] = Field(default_factory=list)
    decisions: list[ImplementDecision] = Field(default_factory=list)
    tests_added: list[str] = Field(default_factory=list)
    tests_run: dict[str, int] = Field(default_factory=dict)
    known_gaps: list[str] = Field(default_factory=list)
    followups_for_next_cycle: list[str] = Field(default_factory=list)


class CorrectnessFinding(BaseModel):
    """A code-level finding from implementation review.

    Required ``file_path`` + ``line`` make the finding falsifiable: a reader
    can open the citation and check the claim. Reviewers that cannot cite a
    specific line should use ``unverified_test_claims`` or a free-text
    ``scope_drift_findings`` entry instead.
    """

    model_config = ConfigDict(extra="forbid")

    file_path: str
    line: int
    claim: str
    severity: Literal["info", "warn", "high"] = "warn"


class ImplementReview(ImplementReviewBase):
    """Generic implementation-review schema; the default for the duet chassis."""

    model_config = ConfigDict(extra="forbid")

    correctness_findings: list[CorrectnessFinding] = Field(default_factory=list)
    contract_violations: list[ContractViolation] = Field(default_factory=list)
    unverified_test_claims: list[str] = Field(default_factory=list)
    missing_followups_from_plan: list[str] = Field(default_factory=list)
    scope_drift_findings: list[str] = Field(default_factory=list)


class DuetSignoff(BaseModel):
    """Terminal record of a duet run: verdict, cycle counts, artifact index.

    Persisted to ``<run_dir>/signoff.json`` at the workflow's terminal node.
    The authoritative source for "what was the final verdict and where are
    the artifacts" once the LangGraph state is gone. ``artifacts_index``
    values are filenames relative to ``run_dir``.
    """

    task_id: str
    final_verdict: DuetVerdict
    total_plan_cycles: int
    total_implement_cycles: int
    trace_id: str
    final_commit_sha: str | None = None
    artifacts_index: dict[str, str] = Field(default_factory=dict)


class DuetState(TypedDict, total=False):
    """LangGraph state for the duet workflow."""

    task: dict[str, Any]
    run_dir: str
    plan_cycle: int
    implement_cycle: int
    plan_md: str
    plan_sidecar: dict[str, Any]
    plan_review: dict[str, Any]
    implement_md: str
    implement_sidecar: dict[str, Any]
    implement_review: dict[str, Any]
    final_verdict: DuetVerdict
    error: str
    _wf_trace_id: str
    _wf_max_budget: float
    _wf_task_prefix: str
    _wf_current_stage: str


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


_IMPLEMENTER_RESPONSE_FORMAT = """
Respond with a markdown narrative followed by a single fenced JSON sidecar.

The narrative explains your reasoning, key decisions, and (for implement
stages) what you changed and why. The sidecar is the machine-checkable atom
view. Format the sidecar exactly like this at the end of your reply:

```json
{ "...": "..." }
```

The JSON must validate against the schema described in the prompt. If the
schema cannot be satisfied, explain why in the narrative and emit a JSON
object with only the field ``error`` populated.
""".strip()


def _task_brief(task: dict[str, Any]) -> str:
    lines = [
        f"task_id: {task.get('task_id', '?')}",
        f"title: {task.get('title', '?')}",
        f"goal: {task.get('goal', '?')}",
        f"workspace_path: {task.get('workspace_path', '?')}",
    ]
    if task.get("success_criteria"):
        lines.append("success_criteria:")
        lines.extend(f"  - {c}" for c in task["success_criteria"])
    if task.get("constraints"):
        lines.append("constraints:")
        lines.extend(f"  - {c}" for c in task["constraints"])
    if task.get("allowed_paths"):
        lines.append(f"allowed_paths: {task['allowed_paths']}")
    if task.get("forbidden_paths"):
        lines.append(f"forbidden_paths: {task['forbidden_paths']}")
    return "\n".join(lines)


def _family_context_blocks(family: TaskFamily | None, task: dict[str, Any]) -> list[str]:
    """Render ``family.context_loader(task)`` as ``## <label>`` markdown blocks.

    Returns an empty list when no family is provided or the loader emits
    nothing. Each entry's content is rendered verbatim — the loader owns
    formatting.
    """
    if family is None:
        return []
    blocks = family.context_loader(task)
    if not blocks:
        return []
    rendered: list[str] = []
    for label, content in blocks.items():
        rendered.extend(["", f"## {label}", content])
    return rendered


def _plan_prompt(
    task: dict[str, Any],
    prior_review: dict[str, Any] | None = None,
    family: TaskFamily | None = None,
) -> list[dict[str, Any]]:
    system = (
        "You are the planner in an implementer/reviewer duet. Produce a plan "
        "the reviewer can audit. Keep steps concrete and acceptance checks "
        "machine-verifiable where possible."
    )
    user_parts = [
        "## Task",
        _task_brief(task),
        *_family_context_blocks(family, task),
        "",
        "## Schema for the JSON sidecar",
        json.dumps(PlanArtifact.model_json_schema(), indent=2),
        "",
        _IMPLEMENTER_RESPONSE_FORMAT,
    ]
    if prior_review:
        user_parts.extend([
            "",
            "## Prior plan review (revise on these blockers before reproposing)",
            json.dumps(prior_review, indent=2),
        ])
    if family and family.plan_prompt_addendum:
        user_parts.append(family.plan_prompt_addendum)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def _plan_review_prompt(
    task: dict[str, Any],
    plan_md: str,
    plan_sidecar: dict[str, Any],
    family: TaskFamily | None = None,
) -> list[dict[str, Any]]:
    system = (
        "You are the reviewer in an implementer/reviewer duet. Your output is "
        "consumed by an automatic router, so the verdict must be one of: pass, "
        "revise, block. Use 'block' only when the plan should not proceed without "
        "human re-scoping. Do not edit any files."
    )
    user_parts = [
        "## Task",
        _task_brief(task),
        *_family_context_blocks(family, task),
        "",
        "## Plan narrative",
        plan_md,
        "",
        "## Plan sidecar (JSON)",
        json.dumps(plan_sidecar, indent=2),
        "",
        "Return a PlanReview JSON object. Groundedness rules: every blocker "
        "MUST include an evidence_path (e.g. 'docs/plans/...md#section' or "
        "'file.py:LL-LL') — a blocker without a citation is opinion, not "
        "evidence, and the router treats it as a process error. If you "
        "cannot cite a source, downgrade to a nit or an unverified_claim. "
        "Field shapes (all object lists are typed Pydantic models — see "
        "the schema for required fields): blockers[] take PlanReviewBlocker "
        "(claim + evidence_path + suggested_fix); nits[] take Nit "
        "(claim + optional location + optional suggested_fix; non-blocking "
        "reviewer observations); unverified_claims[] take UnverifiedClaim "
        "(claim + reason_unverified; things the plan asserts that you "
        "could not check from the available artifacts).",
    ]
    if family and family.plan_review_prompt_addendum:
        user_parts.append(family.plan_review_prompt_addendum)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def _implement_prompt(
    task: dict[str, Any],
    plan_md: str,
    plan_sidecar: dict[str, Any],
    prior_review: dict[str, Any] | None = None,
    family: TaskFamily | None = None,
) -> list[dict[str, Any]]:
    system = (
        "You are the implementer in an implementer/reviewer duet. Make the "
        "smallest change that satisfies the plan and its acceptance checks. "
        "Write a one-line entry in the decisions journal whenever you reject "
        "an alternative the reviewer might wonder about."
    )
    user_parts = [
        "## Task",
        _task_brief(task),
        *_family_context_blocks(family, task),
        "",
        "## Approved plan (narrative)",
        plan_md,
        "",
        "## Approved plan (sidecar)",
        json.dumps(plan_sidecar, indent=2),
        "",
        "## Schema for the JSON sidecar of your response",
        json.dumps(ImplementArtifact.model_json_schema(), indent=2),
        "",
        _IMPLEMENTER_RESPONSE_FORMAT,
    ]
    if prior_review:
        user_parts.extend([
            "",
            "## Prior implementation review (address these before reproposing)",
            json.dumps(prior_review, indent=2),
        ])
    if family and family.implement_prompt_addendum:
        user_parts.append(family.implement_prompt_addendum)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def _implement_review_prompt(
    task: dict[str, Any],
    plan_md: str,
    implement_md: str,
    implement_sidecar: dict[str, Any],
    family: TaskFamily | None = None,
) -> list[dict[str, Any]]:
    system = (
        "You are the reviewer in an implementer/reviewer duet. Your output is "
        "consumed by an automatic router; verdict must be one of: pass, revise, "
        "block. Inspect the workspace via your file-reading tools to verify the "
        "diff matches the narrative. Do not edit any files."
    )
    user_parts = [
        "## Task",
        _task_brief(task),
        *_family_context_blocks(family, task),
        "",
        "## Approved plan",
        plan_md,
        "",
        "## Implementer narrative",
        implement_md,
        "",
        "## Implementer sidecar (JSON)",
        json.dumps(implement_sidecar, indent=2),
        "",
        "Return an ImplementReview JSON object. Groundedness rules: every "
        "correctness_findings entry MUST have file_path (str) and line (int) — "
        "the schema enforces this and ungrounded findings will fail "
        "validation. If you cannot cite a specific line, use "
        "unverified_test_claims (list[str]) or scope_drift_findings "
        "(list[str]) instead. Field shapes (typed Pydantic models — see "
        "the schema for required fields): correctness_findings[] take "
        "CorrectnessFinding (file_path + line + claim + severity); "
        "contract_violations[] take ContractViolation (constraint + "
        "violation + evidence_path; reference one of the task's stated "
        "constraints by name in 'constraint'). Severity defaults to "
        "'warn'; use 'high' only when the finding would break correctness "
        "or a stated contract.",
    ]
    if family and family.implement_review_prompt_addendum:
        user_parts.append(family.implement_review_prompt_addendum)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


# ---------------------------------------------------------------------------
# Implementer response parser
# ---------------------------------------------------------------------------


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)


def _parse_implementer_response(content: str) -> tuple[str, dict[str, Any]]:
    """Split an implementer reply into (markdown_narrative, json_sidecar).

    Implementer stages must end with a fenced ``json`` block. Anything before
    the last fenced block is the narrative; the fenced block parses as JSON.

    Raises:
        ValueError: if no fenced JSON sidecar is found or it fails to parse.
    """
    matches = list(_JSON_FENCE_RE.finditer(content))
    if not matches:
        raise ValueError(
            "Implementer response missing fenced JSON sidecar. "
            "Expected a final ```json ... ``` block."
        )
    last = matches[-1]
    narrative = content[: last.start()].rstrip()
    sidecar_raw = last.group(1)
    try:
        sidecar = json.loads(sidecar_raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse implementer JSON sidecar: {exc}") from exc
    if not isinstance(sidecar, dict):
        raise ValueError(
            f"Implementer JSON sidecar must be an object, got {type(sidecar).__name__}"
        )
    return narrative, sidecar


# ---------------------------------------------------------------------------
# Artifact persistence
# ---------------------------------------------------------------------------


def _persist_text(run_dir: str, name: str, content: str) -> str:
    path = Path(run_dir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def _persist_json(run_dir: str, name: str, payload: dict[str, Any]) -> str:
    path = Path(run_dir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Node factories
# ---------------------------------------------------------------------------


def _make_plan_node(roles: DuetRoles, family: TaskFamily) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def plan_node(state: dict[str, Any]) -> dict[str, Any]:
        ctx = WorkflowContext.current(state, stage="plan")
        task = state["task"]
        prior_review = state.get("plan_review") if state.get("plan_cycle", 0) > 0 else None
        messages = _plan_prompt(task, prior_review=prior_review, family=family)
        result = ctx.call_llm(
            roles.plan,
            messages,
            timeout=DEFAULT_DUET_STAGE_TIMEOUT_S,
            codex_transport=DEFAULT_DUET_CODEX_TRANSPORT,
            cwd=task["workspace_path"],
        )
        narrative, sidecar = _parse_implementer_response(result.content)
        sidecar.setdefault("plan_id", f"plan_{state.get('plan_cycle', 0)}")
        sidecar.setdefault("task_id", task.get("task_id", "?"))
        sidecar["author_model"] = roles.plan
        run_dir = state["run_dir"]
        _persist_text(run_dir, "plan.md", narrative)
        _persist_json(run_dir, "plan.json", sidecar)
        return {"plan_md": narrative, "plan_sidecar": sidecar}

    return plan_node


def _make_plan_review_node(roles: DuetRoles, family: TaskFamily) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def plan_review_node(state: dict[str, Any]) -> dict[str, Any]:
        ctx = WorkflowContext.current(state, stage="plan_review")
        task = state["task"]
        messages = _plan_review_prompt(task, state["plan_md"], state["plan_sidecar"], family=family)
        review, _meta = ctx.call_llm_structured(
            roles.plan_review,
            messages,
            family.plan_review_schema,
            timeout=DEFAULT_DUET_STAGE_TIMEOUT_S,
            codex_transport=DEFAULT_DUET_CODEX_TRANSPORT,
            cwd=task["workspace_path"],
        )
        payload = review.model_dump()
        payload["reviewer_model"] = roles.plan_review
        _persist_json(state["run_dir"], "plan_review.json", payload)
        return {"plan_review": payload, "plan_cycle": state.get("plan_cycle", 0) + 1}

    return plan_review_node


def _make_implement_node(roles: DuetRoles, family: TaskFamily) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def implement_node(state: dict[str, Any]) -> dict[str, Any]:
        ctx = WorkflowContext.current(state, stage="implement")
        task = state["task"]
        prior_review = state.get("implement_review") if state.get("implement_cycle", 0) > 0 else None
        messages = _implement_prompt(
            task,
            state["plan_md"],
            state["plan_sidecar"],
            prior_review=prior_review,
            family=family,
        )
        result = ctx.call_llm(
            roles.implement,
            messages,
            timeout=DEFAULT_DUET_STAGE_TIMEOUT_S,
            codex_transport=DEFAULT_DUET_CODEX_TRANSPORT,
            cwd=task["workspace_path"],
        )
        narrative, sidecar = _parse_implementer_response(result.content)
        sidecar.setdefault("implement_id", f"impl_{state.get('implement_cycle', 0)}")
        sidecar.setdefault("plan_id", state["plan_sidecar"].get("plan_id", "?"))
        run_dir = state["run_dir"]
        _persist_text(run_dir, "implement.md", narrative)
        _persist_json(run_dir, "implement.json", sidecar)
        return {"implement_md": narrative, "implement_sidecar": sidecar}

    return implement_node


def _make_implement_review_node(roles: DuetRoles, family: TaskFamily) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def implement_review_node(state: dict[str, Any]) -> dict[str, Any]:
        ctx = WorkflowContext.current(state, stage="implement_review")
        task = state["task"]
        messages = _implement_review_prompt(
            task,
            state["plan_md"],
            state["implement_md"],
            state["implement_sidecar"],
            family=family,
        )
        review, _meta = ctx.call_llm_structured(
            roles.implement_review,
            messages,
            family.implement_review_schema,
            timeout=DEFAULT_DUET_STAGE_TIMEOUT_S,
            codex_transport=DEFAULT_DUET_CODEX_TRANSPORT,
            cwd=task["workspace_path"],
        )
        payload = review.model_dump()
        payload["reviewer_model"] = roles.implement_review
        _persist_json(state["run_dir"], "implement_review.json", payload)
        return {"implement_review": payload, "implement_cycle": state.get("implement_cycle", 0) + 1}

    return implement_review_node


def _make_signoff_node(verdict: DuetVerdict) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def signoff_node(state: dict[str, Any]) -> dict[str, Any]:
        task = state["task"]
        run_dir = state["run_dir"]
        artifacts = {
            "task": "task.json",
            "plan_md": "plan.md" if state.get("plan_md") else "",
            "plan_sidecar": "plan.json" if state.get("plan_sidecar") else "",
            "plan_review": "plan_review.json" if state.get("plan_review") else "",
            "implement_md": "implement.md" if state.get("implement_md") else "",
            "implement_sidecar": "implement.json" if state.get("implement_sidecar") else "",
            "implement_review": "implement_review.json" if state.get("implement_review") else "",
        }
        signoff = DuetSignoff(
            task_id=task.get("task_id", "?"),
            final_verdict=verdict,
            total_plan_cycles=state.get("plan_cycle", 0),
            total_implement_cycles=state.get("implement_cycle", 0),
            trace_id=state.get("_wf_trace_id", ""),
            artifacts_index={k: v for k, v in artifacts.items() if v},
        )
        _persist_json(run_dir, "signoff.json", signoff.model_dump())
        return {"final_verdict": verdict}

    return signoff_node


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------


def _make_plan_review_router(max_revise_cycles: int) -> Callable[[dict[str, Any]], str]:
    def plan_review_router(state: dict[str, Any]) -> str:
        review = state.get("plan_review") or {}
        verdict = review.get("verdict", "block")
        if verdict == "pass":
            return "implement"
        if verdict == "revise":
            # plan_cycle has already been incremented in the review node
            if state.get("plan_cycle", 0) > max_revise_cycles:
                return "signoff_block"
            return "plan"
        return "signoff_block"

    return plan_review_router


def _make_implement_review_router(max_revise_cycles: int) -> Callable[[dict[str, Any]], str]:
    def implement_review_router(state: dict[str, Any]) -> str:
        review = state.get("implement_review") or {}
        verdict = review.get("verdict", "block")
        if verdict == "pass":
            return "signoff_pass"
        if verdict == "revise":
            if state.get("implement_cycle", 0) > max_revise_cycles:
                return "signoff_block"
            return "implement"
        return "signoff_block"

    return implement_review_router


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_duet_workflow(
    *,
    run_dir: str | Path,
    task: DuetTask | dict[str, Any],
    trace_id: str,
    max_budget: float,
    roles: DuetRoles | None = None,
    max_revise_cycles: int = 1,
    task_prefix: str = "duet",
    task_family: str = "generic",
    checkpointer: Any | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Build a compiled LangGraph app for the implementer/reviewer duet.

    Args:
        run_dir: Directory for durable artifacts (created if missing).
        task: The duet task. Accepts either a DuetTask or a plain dict.
        trace_id: Shared trace_id across all LLM calls in the run.
        max_budget: USD budget for the entire run (passed through WorkflowContext).
        roles: Per-stage model assignment. Defaults applied if None.
        max_revise_cycles: How many ``revise`` verdicts each gate allows before
            promoting to ``block``. Defaults to 1 (i.e. one retry).
        task_prefix: Task-label prefix for observability. Defaults to ``"duet"``.
        task_family: Registered profile name. Defaults to ``"generic"``. Lookup
            via ``llm_client.workflow.duet_registry.get_task_family``; unknown
            names raise ``KeyError``.
        checkpointer: LangGraph checkpointer. Defaults to InMemorySaver.

    Returns:
        (compiled_app, initial_state). Caller invokes
        ``compiled_app.invoke(initial_state, config={"configurable": {"thread_id": ...}})``.

    Raises:
        ImportError: if ``langgraph`` is not installed.
        KeyError: if ``task_family`` is not registered.
    """
    from llm_client.workflow.builder import build_workflow

    # Ensure built-in profiles are registered before resolving by name.
    import llm_client.workflow.profiles  # noqa: F401
    from llm_client.workflow.duet_registry import get_task_family

    task_obj = task if isinstance(task, DuetTask) else DuetTask(**task)
    task_dict = task_obj.model_dump()

    run_dir_path = Path(run_dir)
    run_dir_path.mkdir(parents=True, exist_ok=True)
    _persist_json(str(run_dir_path), "task.json", task_dict)

    resolved_roles = roles or DuetRoles()
    resolved_family = get_task_family(task_family)

    plan_node = _make_plan_node(resolved_roles, resolved_family)
    plan_review_node = _make_plan_review_node(resolved_roles, resolved_family)
    implement_node = _make_implement_node(resolved_roles, resolved_family)
    implement_review_node = _make_implement_review_node(resolved_roles, resolved_family)
    signoff_pass_node = _make_signoff_node("pass")
    signoff_block_node = _make_signoff_node("block")

    plan_review_router = _make_plan_review_router(max_revise_cycles)
    implement_review_router = _make_implement_review_router(max_revise_cycles)

    config = WorkflowConfig.from_dict({
        "task_prefix": task_prefix,
        "max_budget": max_budget,
    })

    app = build_workflow(
        state_schema=DuetState,
        config=config,
        nodes={
            "plan": plan_node,
            "plan_review": plan_review_node,
            "implement": implement_node,
            "implement_review": implement_review_node,
            "signoff_pass": signoff_pass_node,
            "signoff_block": signoff_block_node,
        },
        edges=[
            ("plan", "plan_review"),
            ("implement", "implement_review"),
        ],
        conditional_edges={
            "plan_review": plan_review_router,
            "implement_review": implement_review_router,
        },
        entry_point="plan",
        finish_points=["signoff_pass", "signoff_block"],
        checkpointer=checkpointer,
    )

    ctx = WorkflowContext(
        trace_id=trace_id,
        max_budget=max_budget,
        task_prefix=task_prefix,
    )
    initial_state: dict[str, Any] = ctx.inject_into_state({
        "task": task_dict,
        "run_dir": str(run_dir_path),
        "plan_cycle": 0,
        "implement_cycle": 0,
    })

    return app, initial_state


__all__ = [
    "ContractViolation",
    "Nit",
    "UnverifiedClaim",
    "DuetVerdict",
    "DuetTask",
    "DuetRoles",
    "PlanStepAtom",
    "PlanArtifact",
    "CorrectnessFinding",
    "PlanReview",
    "PlanReviewBlocker",
    "ImplementArtifact",
    "ImplementFileChange",
    "ImplementCommit",
    "ImplementDecision",
    "ImplementDeviation",
    "ImplementReview",
    "DuetSignoff",
    "DuetState",
    "build_duet_workflow",
]
