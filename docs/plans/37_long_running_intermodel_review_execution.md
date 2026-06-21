# Plan #37: Long-Running Execution Spine for Intermodel Review

**Status:** In Progress
**Type:** execution
**Priority:** Critical
**Blocked By:** Plan #36 accepted as the target architecture
**Blocks:** Continuous implementation of Plan #36 without one-step reassessment stalls

---

## Mission

Implement Plan #36 end to end as a continuous, verified sequence. Do not stop
after a single phase just because that phase passes. Stop only for a real
blocker listed below. Otherwise, commit the verified increment, update this
tracker, and move to the next phase.

The goal is a production-usable intermodel review system:

- `review-artifact` has canonical schemas and review profiles.
- `quality_optimal_whitepaper` replaces Brian's browser paste-review loop for
  methodology white papers.
- `review-cycle` can review, apply high-confidence fixes, verify, and repeat
  with bounded convergence and cost.
- OpenClaw can schedule the loop without owning review semantics.
- Legacy intermodel dialogue code is archived only after extracting durable
  prior-art notes.

---

## Real Stop Conditions

Stop only when one of these occurs:

1. **Public-release gate:** GitHub issue #30 is unresolved and the next action
   would make `llm_client` public or publish the sensitive branch elsewhere.
2. **Irreversible shared-state action:** force-push, delete/move another repo's
   code, change repo visibility, drop data, or merge to a shared default branch.
   Ordinary additive edits in a sibling repo are allowed only after creating a
   dedicated branch in that repo, capturing its baseline status, and verifying
   the push remote and repository visibility for that sibling repo.
3. **Schema choice not pre-made:** a required `AdversarialReview` compatibility
   decision cannot be handled by schema v1/v2 support or permissive parsing.
4. **Cross-project archive risk:** moving `utils/consensus_system/` or
   `agent_ontology/agents/debate_agent.py` would break live imports and no
   tombstone/non-moving archive path is viable.
5. **Repeated same failure:** the same implementation/test failure digest
   recurs three times without new information. The digest is SHA-256 of
   `{phase_id, command, failing_test_node_or_script, normalized_top_error}` and
   is recorded in ignored `runs/plan37/failure_ledger.json`.
   `normalized_top_error` is the first semantically specific error line after
   removing timestamps, `/tmp/...` paths, workspace absolute prefixes, memory
   addresses like `0x...`, UUIDs, and repeated whitespace. If no specific line
   exists, use the failing test node or script name.
6. **Credential/budget blocker for live gates:** any required live
   `review-artifact`, `review-cycle`, prompt-evaluation, schema-smoke, or CI
   gate cannot run because model credentials, service access, budget, or CI
   infrastructure are unavailable. Commit all verified offline work, mark the
   current phase `Blocked` with `live-gate-unavailable:<phase>`, and resume
   from that gate later.

Everything else is not a stop condition. Record the issue in this plan or a
follow-up issue, choose the safer documented path, and continue.

---

## Continuous Execution Rules

- Start every run by reading this file, Plan #36, and issue #30.
- Capture baseline `git status --short --branch` before edits.
- Keep changes small enough that tests identify the failing layer.
- After each verified increment:
  - run the phase's required tests;
  - commit with `[Plan #37]` or `[Plan #36]` prefix;
  - push the branch only after verifying the remote owner is
    `BrianMills2718/llm_client`, `git remote get-url --push origin` targets
    that same repo, and `gh repo view ... --json visibility,isPrivate`
    reports private visibility while issue #30 is unresolved;
  - update the tracker table below.
- Commit-prefix routing: implementation changes for Plan #36 use `[Plan #36]`;
  tracker, execution-spine, and long-running protocol docs use `[Plan #37]`.
  Sibling-repo adapter or tombstone commits also use `[Plan #36]` unless that
  repo's local convention explicitly rejects bracketed plan prefixes; record
  the convention in the commit body when it differs.
- Run adversarial review after architecture-affecting phases and before marking
  the whole plan complete.
- Do not archive or delete legacy code until extraction notes are committed.
- Keep all run outputs in ignored `runs/` unless they are redacted, curated, and
  intentionally force-added.
- After editing `CLAUDE.md` or generated instruction mirrors in this repo, run
  the repo's documented render/check command if available; otherwise document
  that no renderer exists on this branch.

---

## Execution Tracker

| Phase | Status | Commit | Verification | Notes |
|-------|--------|--------|--------------|-------|
| 0. Containment and baseline | Complete | 8dccac9 | issue #30 open; repo private; sensitive-pattern grep clean; branch baseline clean | Must stay private until issue #30 resolved or accepted |
| 1. Canonical `AdversarialReview` module | Complete | 01ff820 | `tests/test_workflow_adversarial_review.py tests/test_cli_review_artifact.py tests/test_cli_smoke.py -q` => 26 passed | Schema/prompt moved out of CLI with compatibility shims |
| 2. Review profiles and schema compatibility | Complete | 01ff820 | v1/v2 schema tests; default CLI compatibility tests | `generic` default, `quality_optimal_whitepaper` opt-in |
| 3. `review-artifact` profile CLI | Complete | 01ff820 | CLI threading tests; rendered-section tests; `review-artifact --help` exposes profile flags | Human sections rendered from canonical JSON |
| 4. Review-cycle core contracts | Complete | 21a21c2 | `tests/test_workflow_review_cycle.py tests/test_workflow_adversarial_review.py tests/test_cli_review_artifact.py tests/test_cli_smoke.py -q` => 31 passed | Deterministic classifier, digest, budget ledger, and artifact writes |
| 5. Review-cycle implementer loop | Complete | 0b8382b | `tests/test_workflow_review_cycle.py tests/test_cli_review_cycle.py tests/test_workflow_adversarial_review.py tests/test_cli_review_artifact.py tests/test_cli_smoke.py -q` => 39 passed at commit 0b8382b; current sweep tracked in Phase 6 | Declared artifact paths enforced by default |
| 6. Dogfood on Plan #36/37 docs | In Progress | - | `review-artifact` output has no blockers, or blockers tracked and fixed | Use generic for code/project plans; quality profile for methodology fixture |
| 7. prompt_eval frozen case set | Pending | - | case files + runner smoke pass | No claims of superiority before this |
| 8. OpenClaw adapter | Pending | - | adapter smoke; no task-report schema replacement | Store signoff path as artifact reference |
| 9. Legacy extraction notes | Pending | - | notes committed before move/tombstone | Sources: ecosystem `utils`, `agent_ontology` |
| 10. Cleanup and full verification | Pending | - | offline sweep; optional live schema smoke; PR comment | Ready except public-release gate |

Status values: `Pending`, `In Progress`, `Blocked`, `Complete`.

---

## Phase Details

### Phase 0 - Containment and Baseline

Tasks:

1. Confirm PR #29 head and issue #30 state.
2. Confirm repo visibility is private while issue #30 is unresolved.
3. Fetch the private issue #30 body with
   `gh issue view 30 --repo BrianMills2718/llm_client --json body --jq .body`
   and extract the sensitive path/identifier list from that issue into a local
   ignored shell variable or scratch file under `runs/plan37/`. Do not repeat
   the exact private pattern in tracked docs. Delete any
   `runs/plan37/sensitive_pattern*` scratch file before session handoff.
4. Run `git status --short --branch` and record any pre-existing dirt.
5. Confirm push safety with
   `git remote get-url --push origin` and
   `gh repo view BrianMills2718/llm_client --json visibility,isPrivate`.

Success criteria:

- Branch is clean before implementation edits.
- Current tree has no known sensitive run artifacts.
- PR comment states that public distribution is gated on issue #30.
- Pushes go only to the verified private `BrianMills2718/llm_client` remote
  until issue #30 is resolved.

### Phase 1 - Canonical `AdversarialReview` Module

Tasks:

1. Create `llm_client/workflow/adversarial_review.py`.
2. Move `AdversarialReview`, `ReviewAnnotation`, prompt construction, and
   profile registry there.
3. Keep `llm_client/cli/review_artifact.py` as a thin CLI adapter.

Success criteria:

- Existing `review-artifact` CLI behavior is unchanged with default options.
- Existing `tests/test_cli_review_artifact.py` pass.
- New `tests/test_workflow_adversarial_review.py` cover schema construction,
  profile registration, unknown profile errors, and v1/v2 output compatibility.
  This test file is expected not to exist before this phase creates it; a
  "file not found" result before creation is not a failure signal.

### Phase 2 - Profiles and Compatibility

Tasks:

1. Register `generic` and `quality_optimal_whitepaper`.
2. Add `--review-schema-version {1,2}` as the explicit compatibility mode for
   strict old JSON consumers; permissive consumers may continue using `auto`.
3. Ensure `ReviewAnnotation` enforces:
   - `optimum_gap` requires `linked_finding_index` and
     `validity_loss_without_change`;
   - `spurious` and `uncertain` require `why_rejected_or_uncertain`.

Success criteria:

- `generic` is default and produces the same fields as today.
- `quality_optimal_whitepaper` does not fork the canonical schema.
- Schema v1 consumers can still get output without `profile_annotations`, or
  tests prove known consumers parse schema v2 permissively.

### Phase 3 - Profile-Aware `review-artifact`

Tasks:

1. Add `--review-profile`.
2. Render the quality-optimal human sections from canonical JSON.
3. Keep JSON output authoritative; rendered text is a view.
4. Map rendered quality sections deterministically: `[DEFECT]` is
   `contract_violations` plus `correctness_findings` not linked to an
   `optimum_gap`; `[OPTIMUM-GAP]` is a `correctness_findings` entry linked by
   `profile_annotations.kind == "optimum_gap"`; `[SPURIOUS]` is
   `profile_annotations.kind == "spurious"`; `[UNCERTAIN]` is
   `unverified_claims` plus `profile_annotations.kind == "uncertain"`.

Success criteria:

- CLI tests prove `--review-profile` reaches prompt/profile resolution.
- Render tests prove `[DEFECT]`, `[OPTIMUM-GAP]`, `[SPURIOUS]`, and
  `[UNCERTAIN]` are derived from canonical fields.
- Unknown profile fails loud before any LLM call.

Adversarial review gate:

- Run `review-artifact` against the profile implementation plan/diff.
- Fix all blocker findings before Phase 4.

### Phase 4 - Review-Cycle Core Contracts

Tasks:

1. Create `ReviewCycleTask`, `ReviewCycleSignoff`, budget ledger, finding
   digest, actionable classifier, and artifact writer.
2. Implement stop policies without live LLM calls.
3. Add tests for budget exhaustion, repeated digest, no actionable findings,
   no diff after apply, and max cycles.

Success criteria:

- The digest is deterministic and stable under finding reordering.
- Default `warn` correctness findings are not auto-applied.
- Every terminal state writes `signoff.json`.

### Phase 5 - Review-Cycle Implementer Loop

Tasks:

1. Wire reviewer call, deterministic classifier, implementer call, diff guard,
   and next-cycle review.
2. Enforce declared artifact paths by default.
3. Write `preflight_status.txt`, `review_N.json`, `apply_N.md`,
   `apply_N.json`, `diff_N.patch`, `discussion_queue_N.json`, and
   `budget_ledger.json` under `runs/review-cycle/<task_id>/`.
4. Write a terminal aggregate `discussion_queue.json` containing every skipped
   item across all cycles. Per-cycle queues remain the audit trail.

Success criteria:

- Offline stubbed loop tests cover pass, repeat, budget, no-diff, and dirty
  preflight cases.
- Offline stubbed loop tests assert that terminal `discussion_queue.json`
  aggregates every skipped item across the run.
- The runner fails loud if undeclared files change.
- A local dry run on a toy markdown artifact completes with a sane signoff.

### Phase 6 - Dogfood Review

Tasks:

1. Run the new `review-artifact --review-profile quality_optimal_whitepaper`
   against a methodology-whitepaper fixture. Run the `generic` profile against
   Plan #36 and this Plan #37 unless a prior evaluation shows
   `quality_optimal_whitepaper` is calibrated for code/project plans.
2. Run at least one `review-cycle` on a copy of a plan document with a seeded
   defect.
3. Integrate high-confidence findings; route uncertain findings to a discussion
   queue or follow-up issue.

Success criteria:

- No blocker findings remain unaddressed.
- If concerns remain, each has an owner: fixed now, tracked follow-up, or
  explicitly rejected as spurious with rationale.

### Phase 7 - prompt_eval Case Set

Tasks:

1. Add a frozen case set in `prompt_eval` for methodology whitepaper review:
   two known-good sections, two known-defective sections, two spurious-addition
   traps.
2. Add a runner or documented command that compares review profiles/model pairs.
3. Record baseline results.

Success criteria:

- Evaluation command is agent-drivable.
- Results include false positives, missed defects, and actionable-finding
  stability.
- No model/profile superiority claim is made without this evidence.

### Phase 8 - OpenClaw Adapter

Tasks:

1. Open a sibling-repo branch in OpenClaw / `moltbot` for adapter work, capture
   baseline status there, verify its push remote and visibility, and
   commit/push adapter changes in that repo. If the repo cannot be identified,
   the remote cannot be verified, visibility is unsafe for the issue #30 gate,
   or it is dirty in conflicting files, create a handoff issue instead of
   editing blindly.
2. Add or update OpenClaw adapter to invoke
   `python -m llm_client review-cycle --task-file ...`.
3. Store a sidecar `review_cycle_artifacts.json` path by default; only write
   `outputs.review_cycle_signoff_path` after report-schema validation proves
   the field is accepted.
4. Do not replace OpenClaw task-report schemas.

Success criteria:

- Adapter smoke test can schedule or simulate a review-cycle task.
- Existing OpenClaw report validation still passes.
- Artifact references point to durable `llm_client` outputs.

### Phase 9 - Legacy Extraction and Archive

Tasks:

1. Inspect `~/projects/utils/consensus_system/`.
2. Inspect `~/projects/agent_ontology/agents/debate_agent.py`.
3. Commit extraction notes in:
   - `docs/plans/36_prior_art_consensus_system.md`
   - `docs/plans/36_prior_art_agent_ontology_debate.md`
4. Do not move or delete sibling-repo code autonomously. After extraction notes
   are committed, treat any sibling-repo tombstone as its own verified Phase 9
   checkpoint and either:
   - create a sibling-repo branch that adds `ARCHIVED_BY_PLAN_36.md` tombstones
     while leaving code in place, or
   - stop for explicit approval before moving code to
     `~/projects/PROJECTS_DEFERRED/intermodel-dialogue-legacy/`.

Success criteria:

- Extraction notes name every concept preserved and its replacement surface.
- No imports break.
- No dead duplicate runnable path remains without a tombstone or tracked
  approval to defer the tombstone.

### Phase 10 - Cleanup and Full Verification

Tasks:

1. Remove cruft introduced during implementation.
2. Run the offline sweep from Plan #36.
3. Run gated live smoke if credentials/budget are available.
4. Run final adversarial review over the PR diff.
5. Update docs and PR comment with final status.

Success criteria:

- Offline sweep passes.
- CI passes on the private PR branch. If CI is unavailable, local full offline
  sweep is only offline-complete proof; mark Phase 10 blocked on the live gate
  rather than complete.
- Final adversarial review has no untracked blockers.
- PR remains draft/private-gated if issue #30 is unresolved; otherwise it is
  ready for normal review.

Offline-complete path:

- If all offline implementation/tests pass but live model credentials or budget
  are unavailable, mark the tracker `Blocked` at Phase 10 with reason
  `live-gate-unavailable`, commit all offline-verified work, and do not claim
  final completion. The next run resumes at the live gates.

---

## Adversarial Review Policy

Run adversarial review at these gates:

| Gate | Artifact | Required Outcome |
|------|----------|------------------|
| After Phase 3 | schema/profile diff | no blockers |
| After Phase 5 | review-cycle diff | no blockers; concerns either fixed or tracked |
| After Phase 6 | Plan #36 + Plan #37 dogfood | no blockers |
| Before final handoff | full PR diff | no blockers or explicit tracked exceptions |

Default gate command choices:

- Reviewer model: `claude-code/opus`.
- Review budget: `--max-budget 5` for plan/diff dogfood gates unless a phase
  states a stricter cap.
- Fallback reviewer: `codex/gpt-5.4` only when Claude credentials or service
  access are unavailable; record that fallback in the tracker and treat it as
  lower-confidence evidence.

Review findings handling:

- `contract_violations` and high-severity `correctness_findings` must be fixed
  before continuing unless they are demonstrably false.
- `CorrectnessFinding` entries with `severity="warn"` are fixed when high
  confidence; otherwise tracked in a discussion queue.
- `nits` never block progress unless they expose a test or doc ambiguity.
- `unverified_claims` must either be verified, downgraded to explicit
  uncertainty, or removed.

---

## Test Commands

Focused after schema/profile work:

```bash
PYTHONPATH=. python -m pytest \
  tests/test_workflow_adversarial_review.py \
  tests/test_cli_review_artifact.py \
  tests/test_cli_smoke.py -q
```

Only run commands that reference future test files after the phase that creates
those files. Before that phase, use the existing focused tests named in the
phase success criteria.

Focused after review-cycle work:

```bash
PYTHONPATH=. python -m pytest \
  tests/test_workflow_review_cycle.py \
  tests/test_cli_review_cycle.py \
  tests/test_workflow_adversarial_review.py \
  tests/test_cli_review_artifact.py \
  tests/test_cli_smoke.py -q
```

Full offline sweep:

```bash
PYTHONPATH=. python -m pytest \
  tests/test_workflow_adversarial_review.py \
  tests/test_cli_review_artifact.py \
  tests/test_workflow_review_cycle.py \
  tests/test_cli_review_cycle.py \
  tests/test_cli_smoke.py \
  tests/test_workflow_duet.py \
  tests/test_workflow_deliberate.py \
  tests/test_workflow_deliberate_verifier.py -q
```

Gated live smoke:

```bash
LLM_CLIENT_INTEGRATION=1 PYTHONPATH=. python -m pytest \
  tests/test_workflow_schema_smoke.py -q
```

---

## Completion Criteria

Plan #37 is complete when:

- All Plan #36 acceptance criteria are satisfied or explicitly blocked by issue
  #30 public-release containment.
- `review-artifact --review-profile quality_optimal_whitepaper` works.
- `review-cycle` can run a bounded local review/apply/review loop with durable
  artifacts and deterministic stop conditions.
- OpenClaw has a scheduler adapter or a documented blocked issue.
- Legacy prior-art notes are committed and duplicate runnable code is archived
  or tombstoned.
- Full offline tests pass and CI passes. If CI is unavailable, Plan #37 remains
  blocked at Phase 10 instead of complete.
- Final adversarial review has no unresolved blockers.
