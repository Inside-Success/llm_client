# Plan #29: Implementer/Reviewer Duet Workflow

**Status:** In Progress
**Type:** implementation
**Priority:** Medium
**Blocked By:** None
**Blocks:** None

---

## Gap

**Current:** `llm_client` can route the same call interface to either `claude-code` or `codex/*` agent SDKs, and provides a LangGraph-backed workflow layer with shared trace/budget context. There is no built-in pattern for running one agent as implementer and a different agent as reviewer across plan and implementation stages with structured handoff between them.

**Target:** A `build_duet_workflow()` factory in `llm_client/workflow/duet.py` that wires four stages (`plan`, `plan_review`, `implement`, `implement_review`) as a LangGraph workflow with:
- Per-stage role assignment (which model plays each role) with overridable defaults.
- Structured reviewer output (`verdict ∈ {pass, revise, block}`) that drives `conditional_edges` deterministically.
- `max_revise_cycles=1` per review gate (start conservative; humans handle deeper loops).
- Durable artifacts written to a run directory; each stage's prompt consumes only prior artifacts plus the workspace path — no tool-trace replay.
- Implementer stages produce a short `decisions[]` journal so reviewer sees rejected approaches, not just the diff.

**Why:** Pair-of-agents has measurable upside on plan-quality and contract-violation catch-rate, but doing it ad hoc means inconsistent context transfer, no observability rollup, and no escape valve when the reviewer is stuck. A small library affordance over the existing workflow substrate makes the pattern reusable across consumer repos.

---

## References Reviewed

- `llm_client/sdk/agents.py:55-80,410-545` — `_parse_agent_model`, `_route_call`, `_route_acall`, `_route_call_structured`. Confirms both `claude-code` and `codex/*` accept the same `LLMCallResult` interface for sync, async, stream, and structured output.
- `llm_client/workflow/builder.py:58-175` — `build_workflow()` LangGraph wrapper with node-stage injection, validation, and checkpointing. Duet builds on this directly.
- `llm_client/workflow/context.py:28-163` — `WorkflowContext` carries `trace_id`, `max_budget`, `task_prefix`, `stage` through state with `call_llm()` / `call_llm_structured()` wrappers that auto-inject contracts. No changes needed; duet nodes use it as-is.
- `llm_client/workflow/config.py:27-91` — `StageConfig` and `WorkflowConfig` for per-stage model + retry settings. Reused for duet's role config.
- `llm_client/agent/agent_planning.py:19-279` — intra-agent `PlanState` for MCP loops. Different scope from cross-agent duet, but the `compact` plan-formatting pattern informs the duet plan-artifact schema.
- `tests/test_workflow_builder.py:34-80` — established pattern for langgraph-gated unit tests using `TypedDict` state and stub node functions. Duet tests follow the same shape.

---

## Files Affected

- `llm_client/workflow/duet.py` (create) — schemas, role config, prompt builders, node functions, `build_duet_workflow()`.
- `llm_client/workflow/__init__.py` (modify) — export `build_duet_workflow` and the public schemas.
- `tests/test_workflow_duet.py` (create) — offline unit tests with stub LLM (monkeypatch `WorkflowContext.call_llm` / `call_llm_structured`).
- `docs/plans/29_implementer_reviewer_duet.md` (this file).
- `docs/plans/CLAUDE.md` (modify) — append row to the plan index.

Out of scope for this plan (deliberately):
- A CLI front-end (`python -m llm_client duet ...`). Library function first; CLI can land in a follow-up once real-task evidence accrues.
- Multi-worktree variant (each stage in its own worktree). Single worktree only.
- Integration tests against live `claude-code` / `codex` (cost + non-determinism). Deferred to a smoke harness.
- Per-stage prompt YAML files in `prompts/`. Inline string templates only for v1; promote to `prompts/` if the prompts stabilize.

---

## Plan

### Steps

1. Schemas (`duet.py`): Pydantic models for `DuetTask`, `PlanArtifact` (sidecar), `PlanReview`, `ImplementArtifact` (sidecar), `ImplementReview`, `DuetSignoff`. Reviewer schemas use `Literal["pass", "revise", "block"]` for `verdict` so routers can branch deterministically.
2. Role config (`duet.py`): `DuetRoles` Pydantic model with defaults `plan=codex/gpt-5.4`, `plan_review=claude-code/opus`, `implement=codex/gpt-5.4`, `implement_review=claude-code/opus`. Caller can override per stage. (Defaults switched from `codex/gpt-5-codex` to `codex/gpt-5.4` on 2026-05-19: `gpt-5-codex` requires Codex API auth and errors on ChatGPT-account auth, which is the common local-dev setup. Operators with API auth can override back to `codex/gpt-5-codex` for stronger code performance.)
3. Run state (`duet.py`): `DuetState` TypedDict carrying `task` (dict), `run_dir`, `cycle_counts`, `plan_md`, `plan_sidecar`, `plan_review`, `implement_md`, `implement_sidecar`, `implement_review`, `final_verdict`, `error`, plus the `_wf_*` context fields.
4. Prompt builders (`duet.py`): `_plan_prompt(task)`, `_plan_review_prompt(task, plan_md, plan_sidecar)`, `_implement_prompt(task, plan_md, plan_sidecar, prior_review)`, `_implement_review_prompt(task, plan_md, implement_md, implement_sidecar)`. Each returns OpenAI-format messages.
5. Node functions (`duet.py`): `plan_node`, `plan_review_node`, `implement_node`, `implement_review_node`, `signoff_node`. Reviewer nodes use `ctx.call_llm_structured(...)` against the corresponding Pydantic review schema. Implementer nodes use `ctx.call_llm(...)` and parse the model's response into the markdown + sidecar pair via a `_parse_implementer_response` helper that expects a documented format (markdown body with a final ```json sidecar``` fence).
6. Artifact persistence (`duet.py`): `_persist_artifact(run_dir, name, content)` writes both `.md` and `.json` per artifact. Each node persists before returning state.
7. Conditional edges (`duet.py`): `plan_review_router(state)` → `revise_plan` | `proceed_to_implement` | `block`; `implement_review_router(state)` → `revise_implement` | `signoff` | `block`. Cycle counts gate `revise` so a second `revise` verdict promotes to `block` automatically.
8. Builder (`duet.py`): `build_duet_workflow(run_dir, roles, task, trace_id, max_budget, max_revise_cycles=1, checkpointer=None)` returns a compiled LangGraph app. Pre-creates `run_dir` and writes `task.json`.
9. Public exports (`workflow/__init__.py`): add `build_duet_workflow`, `DuetTask`, `DuetRoles`, `PlanReview`, `ImplementReview`, `DuetSignoff`, `DuetVerdict`.
10. Unit tests (`tests/test_workflow_duet.py`): pass-through (review passes both gates), revise-once-then-pass, block-halt at plan review, role assignment correctness, cycle-cap promotes second revise to block, artifact files written to `run_dir`.
11. Plan index update (`docs/plans/CLAUDE.md`).

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_workflow_duet.py` | `test_duet_happy_path_both_reviewers_pass` | Plan→implement→signoff when both reviewers return `verdict=pass`; artifacts on disk. |
| `tests/test_workflow_duet.py` | `test_duet_revise_plan_once_then_pass` | First plan review returns `revise`; second iteration passes; cycle count advances. |
| `tests/test_workflow_duet.py` | `test_duet_plan_review_block_halts` | `verdict=block` at plan review terminates with `final_verdict=block`; no implement node fires. |
| `tests/test_workflow_duet.py` | `test_duet_second_revise_promoted_to_block` | Two consecutive `revise` verdicts at the same gate terminate as `block` due to `max_revise_cycles=1`. |
| `tests/test_workflow_duet.py` | `test_duet_uses_role_assignment` | Each stage invokes the model from `DuetRoles`; reviewer stages call `call_llm_structured`. |
| `tests/test_workflow_duet.py` | `test_duet_persists_artifacts_to_run_dir` | After a run, `task.json`, `plan.md`, `plan.json`, `plan_review.json`, `implement.md`, `implement.json`, `implement_review.json`, `signoff.json` exist. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_workflow_builder.py` | Duet builds on top of `build_workflow`; regression check. |
| `tests/test_workflow_context_config.py` | `WorkflowContext` and `WorkflowConfig` semantics unchanged. |

---

## Acceptance Criteria

- [ ] Required tests pass under `pytest tests/test_workflow_duet.py -q`.
- [ ] Workflow regression tests still pass: `pytest tests/test_workflow_builder.py tests/test_workflow_context_config.py -q`.
- [ ] Reviewer verdict schema is `Literal["pass", "revise", "block"]` — no free-text fallthrough.
- [ ] `max_revise_cycles=1` is the default and a second revise at the same gate promotes to `block`.
- [ ] Artifacts persisted as `.md` (where applicable) and `.json` sidecar to `run_dir`.

---

## Notes

**Design decisions**

- **Markdown + JSON sidecar for implementer artifacts.** Reviewer needs prose to assess reasoning; router needs structured fields. A 10-line lint can catch drift between them in a follow-up.
- **Reviewer default = `claude-code/opus`, deliberately reconsidered after first real tasks.** Sonnet 4.6 is ~5× cheaper and may be plenty; also worth A/B-testing `codex/gpt-5-codex` as reviewer. Confidence on this default is low — treat as a starting point.
- **`max_revise_cycles=1`.** Two revise rounds rarely produce materially better output from the same agent — usually the same answer, harder. Cap at 1; on second failure, terminate as `block` so a human can re-scope.
- **No tool-trace replay.** Replaying transcripts blows context for no signal; the diff is ground truth. Implementer writes a short `decisions[]` journal in the sidecar to preserve the *why* that would otherwise be lost.
- **Single worktree, commit-per-stage.** Reviewer sees `git diff base..head`. Multi-worktree variant deferred.

**Risks**

- **Implementer response parsing.** Asking an agent to return markdown + a JSON fence is brittle. Mitigated by clear prompt format and a strict parser that raises on missing sidecar; the parser failure surfaces as `error` in state instead of corrupting downstream. Real-task evidence will tell us if we need a structured-output retry layer.
- **Cost.** Each cycle is up to 4 LLM calls; worst case (two revises promoted to block) is 6. Budget guard via `max_budget` on the workflow context is the existing safety net.
- **Agent SDK side effects.** The agent stages can edit files in the workspace. Reviewer stages should NOT edit files — enforced via prompt only in v1. If reviewers start touching the tree we'll need `permission_mode="ask"` or read-only kwargs.

**Follow-ups not in scope**

- CLI front-end.
- Human-in-the-loop interrupt after `implement_review` (LangGraph supports it natively; just not wired in v1).
- Per-stage retry/fallback override via `WorkflowConfig`.
- Prompt assets promoted to `prompts/` once stable.
