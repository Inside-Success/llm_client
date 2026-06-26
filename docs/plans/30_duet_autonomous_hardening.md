# Plan #30: Duet Autonomous Hardening

**Status:** ✅ Complete (2026-05-22)
**Type:** implementation
**Priority:** High
**Blocked By:** Plan #29
**Blocks:** Plan #31 (TaskFamily abstraction)

---

## Gap

**Current:** Plan #29 landed a working implementer/reviewer duet chassis. A duet-on-itself self-review run against the Plan #29 plan doc + implementation surfaced two blockers and the absence of any callable surface for another agent to use the reviewer. Evidence is in `runs/plan-29-duet-review/plan_review.json` (verdict: `revise`) and `runs/plan-29-duet-review/implement_review.json` (verdict: `pass` with 7 findings, including the cwd gap and the ungrounded-blocker gap).

**Target:** Three tightening changes that take the duet from "Brian-supervised dogfood" to "another agent can safely invoke this":

1. Thread `task.workspace_path` into every `ctx.call_llm*` site as `cwd=` so the agent SDK inspects the intended tree, not whatever directory the harness was launched from.
2. Make reviewer schemas refuse ungrounded findings — `PlanReviewBlocker.evidence_path` required, `correctness_findings: list[CorrectnessFinding]` with required `file_path` + `line`.
3. Add a `python -m llm_client duet-review` CLI subcommand so other agents have a documented invocation surface rather than copy-pasting the runs/ script template.

**Why:** Without (1) the reviewer silently inspects the wrong tree when invoked from anywhere other than the workspace root. Without (2) a `block` verdict is indistinguishable from opinion. Without (3) every caller hand-rolls a script and the duet has no agent-callable contract. All three are pre-requisites for handing this to another agent in another session.

---

## References Reviewed

- `runs/plan-29-duet-review/plan_review.json` — the self-review that flagged Blockers A (cwd) and B (ungrounded findings). Verdict `revise`, 2 blockers, 4 nits.
- `runs/plan-29-duet-review/implement_review.json` — companion `pass` verdict confirming Plan #29 impl matches the plan; flagged the same cwd and schema gaps as `correctness_findings`.
- `llm_client/workflow/duet.py:465-559` — the four node factories (`plan`, `plan_review`, `implement`, `implement_review`) where `cwd` needs threading.
- `llm_client/workflow/duet.py:122-205` — `PlanReviewBlocker` + `ImplementReview` schemas, where the groundedness fields land.
- `llm_client/cli/cost.py:1-110` + `llm_client/__main__.py:1-60` — the established CLI subcommand pattern (`register_parser(subparsers)` + `cmd_<name>` handler).
- `llm_client/sdk/agents_claude.py:104-115` — the existing `cwd` pass-through in `_build_agent_options` (already there; just needs the caller to set it).
- `tests/test_cli_smoke.py:7-28` — established CLI help-smoke pattern that the duet-review subcommand piggybacks on.
- `tests/test_workflow_duet.py:46-141` — established stub-harness pattern; extended to capture call kwargs so the cwd test is offline.

---

## Files Affected

- `llm_client/workflow/duet.py` (modify) — thread `cwd=task['workspace_path']` into all four node call sites; tighten `PlanReviewBlocker.evidence_path` to required; add `CorrectnessFinding` model; change `ImplementReview.correctness_findings` type; update prompt addenda to surface groundedness rules.
- `llm_client/workflow/__init__.py` (modify) — export `CorrectnessFinding`.
- `llm_client/cli/duet.py` (create) — `cmd_duet_review` handler + `register_parser`.
- `llm_client/__main__.py` (modify) — register the `duet-review` subcommand.
- `tests/test_workflow_duet.py` (modify) — capture `call_kwargs` on the harness, add `test_duet_threads_workspace_path_as_cwd`, `test_plan_review_blocker_requires_evidence_path`, `test_correctness_finding_requires_file_and_line`, `test_implement_review_rejects_ungrounded_correctness_findings`.
- `tests/test_cli_smoke.py` (modify) — extend the help-smoke list with `duet-review --help`.
- `docs/plans/30_duet_autonomous_hardening.md` (this file).
- `docs/plans/CLAUDE.md` (modify) — append index row.

Out of scope (deliberately):
- TaskFamily / profile refactor (Plan #31). Hardening the chassis first means the refactor splits a sound chassis, not a buggy one.
- `permission_mode` threading for reviewer stages (reviewer-can-edit risk). Reviewer-don't-edit is still prompt-only enforcement.
- Cumulative `max_budget` ledger (Notes nit from self-review). Still per-call only.
- Per-stage `plan_review.json` patching when cycle-cap promotes revise→block (Notes nit). Downstream readers should consult `signoff.json` as authoritative.
- Skill or AGENTS.md surface for autonomous agents. Will follow once the CLI shape is exercised on a non-self task.

---

## Plan

### Steps

1. Thread `cwd=task["workspace_path"]` into the `ctx.call_llm(...)` and `ctx.call_llm_structured(...)` sites in `_make_plan_node`, `_make_plan_review_node`, `_make_implement_node`, `_make_implement_review_node`.
2. Make `PlanReviewBlocker.evidence_path` a required field (drop the `= None` default).
3. Add `CorrectnessFinding` Pydantic model with required `file_path: str`, `line: int`, `claim: str`, and `severity: Literal["info","warn","high"] = "warn"`.
4. Change `ImplementReview.correctness_findings: list[CorrectnessFinding]` (was `list[dict[str, str]]`).
5. Update `_plan_review_prompt` user message to state the groundedness rule for blockers (must have `evidence_path`; downgrade to nit/unverified_claim if no citation).
6. Update `_implement_review_prompt` user message to state the groundedness rule for `correctness_findings` (schema-enforced `file_path` + `line`; downgrade to `unverified_test_claims` or `scope_drift_findings` if no line citation).
7. Export `CorrectnessFinding` from `llm_client.workflow.__init__` and add to `duet.__all__`.
8. Add the harness `call_kwargs` capture and `test_duet_threads_workspace_path_as_cwd` test asserting all four stages receive `cwd=workspace`.
9. Add schema-validation tests: `test_plan_review_blocker_requires_evidence_path`, `test_correctness_finding_requires_file_and_line`, `test_implement_review_rejects_ungrounded_correctness_findings`.
10. Create `llm_client/cli/duet.py` with `cmd_duet_review` handler + `register_parser`. Modes: plan-review only (default) or plan + implement review (when `--impl-base` is set). Synthesizes `implement.md` and `implement.json` sidecar from `git log --oneline` + `git diff --numstat` so the reviewer sees the diff shape without needing a hand-authored implement_md.
11. Register the subcommand in `llm_client/__main__.py`.
12. Extend `tests/test_cli_smoke.py` to assert `duet-review --help` exits 0 and prints usage.
13. Plan index row in `docs/plans/CLAUDE.md`.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_workflow_duet.py` | `test_duet_threads_workspace_path_as_cwd` | All four stages receive `cwd=task['workspace_path']` (offline; reads `harness.call_kwargs`). |
| `tests/test_workflow_duet.py` | `test_plan_review_blocker_requires_evidence_path` | Constructing a `PlanReviewBlocker` without `evidence_path` raises `pydantic.ValidationError`. |
| `tests/test_workflow_duet.py` | `test_correctness_finding_requires_file_and_line` | Required fields are enforced individually. |
| `tests/test_workflow_duet.py` | `test_implement_review_rejects_ungrounded_correctness_findings` | A loose dict missing `line` cannot pass as a `CorrectnessFinding` inside `ImplementReview`. |
| `tests/test_cli_smoke.py` | `test_cli_help_smoke` | `duet-review --help` is wired and exits 0. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_workflow_duet.py::*` (12 cases incl. new ones) | Chassis regression; new schemas must not break existing flows. |
| `tests/test_workflow_builder.py` | LangGraph wiring unchanged. |
| `tests/test_agents.py::TestBuildAgentOptions` | Alias resolution from Plan #29 followup still works. |

---

## Acceptance Criteria

- [ ] All required tests pass.
- [ ] Existing duet + workflow + agents test suites still pass.
- [ ] `python -m llm_client duet-review --help` exits 0 and prints usage including `--plan-doc`, `--workspace`, `--out`, `--reviewer-model`, `--impl-base`.
- [ ] `PlanReviewBlocker` and `CorrectnessFinding` both refuse ungrounded payloads at validation time.
- [ ] `cwd` propagation verified by offline harness assertion.

---

## Completion Log

| Commit | What |
|--------|------|
| `9b1f0f1` | Plan #30: cwd threading into all 4 `ctx.call_llm` sites; `PlanReviewBlocker.evidence_path` required; new typed `CorrectnessFinding(file_path, line, claim, severity)`; `python -m llm_client duet-review` CLI subcommand. 5 new tests + extended CLI smoke. Must-pass set: 30/30 green; broader sweep at the time was 146 passed (the plan body originally said "47/47" — that's the must-pass subset, not the broader regression sweep — caught and corrected by Plan #31 self-review). |
| `2e1741d` | **Followup**: `cwd` ↔ `working_directory` alias at the SDK route boundary. Caught by Plan #30 self-review noticing the codex adapter reads `working_directory`, not `cwd`. New `_normalize_workspace_kwargs()` at route entry; 7 new tests including 2 end-to-end route-boundary captures. |

Dogfood verdict v1 (`runs/plan-30-review/`, before the followup): `revise` — 1 blocker (the codex cwd gap), 4 nits, 3 unverified claims. Verdict v2 (`runs/plan-30-review-v2/`, after the followup): `pass` with the cwd path verified end-to-end.

---

## Notes

**Design decisions**

- **`evidence_path: str` (required) instead of `Optional[str]`.** A reviewer that can't cite a source should downgrade to `nit` or `unverified_claim`, not emit a `block`. Forcing the field at validation time means the router can trust a `block` verdict to be evidence-backed.
- **`CorrectnessFinding` as a typed model.** The prior `list[dict[str, str]]` shape let a reviewer return arbitrary keys; the new model enforces `file_path` + `line` so a finding is always a citation. `severity: Literal[...]` keeps the value space tight without proliferating sub-types.
- **CLI is review-only by default.** Most callers will have a plan and an implementation already; they want the reviewer halves, not the full implementer-reviewer loop. The full duet remains available via `build_duet_workflow()`.
- **`--impl-base` triggers the implement-review stage instead of a separate `--full` flag.** The presence of a base ref *is* the signal that a diff exists and the implement review is meaningful.
- **`implement.md` is auto-synthesized from git log + diffstat.** Hand-authored summaries are nice but bog down CLI use; auto-synthesis lets the reviewer focus on the diff while still having the narrative shape the prompt expects.

**Risks**

- The reviewer self-reports `reviewer_model` as a free-text string when called directly via `call_llm_structured` (observed in self-review: `"claude (duet self-review)"` for plan_review vs. `"claude-code/opus"` for impl_review). The CLI overwrites the field with the requested model string before persistence, but consumers of raw review JSON from non-CLI invocations should trust `DuetRoles`/`--reviewer-model`, not the artifact field.
- Auto-synthesized `implement.md` may underweight a complex change with multiple intents. Callers with stronger summaries can pre-populate `<run-dir>/implement.md` before invoking; the CLI will overwrite it though. A `--keep-implement-md` flag is a follow-up if this becomes a real pain point.
- The CLI calls `call_llm_structured` directly rather than going through the LangGraph workflow. That means none of the chassis's cycle/router logic applies — the CLI is a one-shot review, not a duet loop. This is intentional: the LangGraph loop is for *implementing*, the CLI is for *reviewing what already exists*.

**Follow-ups not in scope**

- Skill or AGENTS.md entry pointing other agents at the CLI (will follow once the CLI shape is validated on a non-self task).
- Cumulative budget ledger across cycles.
- `permission_mode="default"` for reviewer stages so they cannot edit the workspace.
- Promote the per-stage `plan_review.json` to carry a `promoted_to_block` marker when the router cycle-cap fires.
