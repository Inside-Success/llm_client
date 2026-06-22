# Plan #36: Intermodel Review Consolidation and Whitepaper Loop

**Status:** Complete
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Public Release:** Existing-repo public release remains blocked unless issue #30 is reopened and purged, or a fresh clean public repo is created; private-only implementation accepted on 2026-06-22
**Blocks:** OpenClaw scheduling integration, legacy intermodel-dialogue archival

---

## Gap

**Current:** PR #29 packages the core collaboration primitives in `llm_client`:
`duet-review`, `review-artifact`, `deliberate-task`, `TaskFamily` profiles,
deliberation verifier ledgers, and the barrier/anonymization protocol. Brian's
current highest-value manual workflow is still outside the package: a Codex
instance writes a methodology white paper, a stronger browser ChatGPT session
reviews it with a quality-optimal prompt, then Codex applies high-confidence
corrections and repeats until the paper converges.

The first dogfood review of the consolidation plan found one release blocker
and four design defects:

- Sensitive historical PR artifacts were pushed. Brian accepted private-only
  distribution on 2026-06-22, so the existing repo stays private unless the
  stale object is purged or a fresh clean public repo is created.
- The quality-optimal review prompt introduces `DEFECT`, `OPTIMUM-GAP`,
  `SPURIOUS`, and `UNCERTAIN` buckets without reconciling them with the
  existing `AdversarialReview` contract.
- The proposed loop has no convergence, budget, or fix-verification contract.
- OpenClaw's task-report schemas were conflated with review verdict schemas.
- Legacy `consensus_system` / `agent_ontology` ideas were marked for archive
  without concrete extraction artifacts.

A 2026-06-22 live review-cycle dogfood pass found two follow-up contract drifts:
the rendered `[OPTIMUM-GAP]` bucket was not severity-aligned with the
auto-apply gate, and the Python bytecode/cache edit-guard carve-out was hidden
in runner code instead of declared on `ReviewCycleTask`. Both are now explicit
in this plan, code, and tests.

**Target:** Make `llm_client` the canonical runtime for intermodel review while
keeping orchestration, evaluation, and archive ownership explicit:

- `llm_client` owns review schemas, review profiles, local synchronous review
  cycles, durable run artifacts, and model/provider routing.
- `prompt_eval` owns frozen-case evaluation for review prompts, model pairs,
  false-positive rate, and convergence quality.
- OpenClaw / `moltbot` owns scheduling and task-report orchestration only; it
  calls `llm_client` commands and stores their artifact references, but its
  task-report schemas are not replaced by `AdversarialReview`.
- Legacy dialogue/debate code is archived only after a named extraction note
  preserves the useful concepts and the current replacement surface.

**Why:** The goal is not another one-off reviewer prompt. The goal is a
repeatable, agent-drivable workflow that removes browser paste lag while keeping
the existing typed review contract and observability discipline.

---

## References Reviewed

- `docs/guides/agent-collaboration.md` - current public guide for `duet-review`,
  `review-artifact`, and `deliberate-task`.
- `docs/plans/29_implementer_reviewer_duet.md` - asymmetric
  implementer/reviewer chassis and revise-cycle cap.
- `docs/plans/31_task_family_abstraction.md` - profile pattern: chassis owns
  wiring, profiles own schema/prompt/context additions.
- `docs/plans/33_deliberation_workflow.md` - symmetric two-agent deliberation
  when no reviewer/implementer role split exists.
- `docs/plans/34_deliberation_verifier_adjudicator.md` - pure-Python verifier
  ledger and convergence gating.
- `docs/plans/35_deliberation_within_round_barrier_protocol.md` - barrier,
  anonymization, and model-pairing risk check.
- `llm_client/cli/review_artifact.py` - standalone `AdversarialReview` schema
  and prompt currently live inside the CLI module.
- `docs/plans/36_dogfood_review_summary.md` - redacted summary of the
  dogfood reviews that produced this plan's blocker/defect list.
- GitHub issue #30 - closed on 2026-06-22 by private-only acceptance; reopen
  only if making the existing repository public again.

---

## Files Affected

- `docs/guides/agent-collaboration.md` (modify) - remove stale sensitive-run
  references and add the new whitepaper loop once implemented.
- `llm_client/workflow/adversarial_review.py` (created; Plan #37 follow-up aligned high-severity optimum-gap rendering) - move
  `AdversarialReview`, finding imports, prompt builder, and review-profile
  registry out of the CLI.
- `llm_client/cli/review_artifact.py` (modified) - delegate schema/prompt/profile
  resolution to `workflow.adversarial_review`; add `--review-profile`.
- `llm_client/workflow/review_cycle.py` (created; Plan #37 follow-up added typed runtime-cache carve-outs) - synchronous local loop runner
  for review -> apply -> verify -> repeat.
- `llm_client/cli/review_cycle.py` (created) - `review-cycle` subcommand.
- `llm_client/__main__.py` (modified) - register `review-cycle`.
- `tests/test_cli_review_artifact.py` (modified) - profile flag and schema
  relocation coverage.
- `tests/test_workflow_adversarial_review.py` (created) - review-profile
  registry, profile annotation schema, prompt mapping, and severity-aligned
  quality-optimal rendering tests.
- `tests/test_workflow_review_cycle.py` (created; Plan #37 follow-up added runtime-cache contract coverage) - loop convergence, budget,
  artifact persistence, high-confidence apply gating, and artifact edit guards.
- `tests/test_cli_review_cycle.py` (created) - CLI parsing and builder threading.
- `docs/plans/36_dogfood_review_summary.md` (create) - tracked,
  redacted evidence note for the reviews that shaped this plan.
- `docs/plans/36_prior_art_consensus_system.md` (create) - extracted
  concepts from legacy consensus-system code before archive.
- `docs/plans/36_prior_art_agent_ontology_debate.md` (create) - extracted
  concepts from generated debate-agent code before archive.
- `docs/plans/CLAUDE.md` (modify) - keep Plan #36 indexed.

Out of scope:

- Replacing OpenClaw task-report schemas.
- Building a web UI.
- N-agent deliberation beyond the two-agent chassis already in Plan #33.
- Treating browser-only ChatGPT UI settings as an API dependency. The loop
  uses API/agent models available through `llm_client`; model choice stays
  configurable.

---

## Plan

### Phase 0 - Release Gate and Containment

1. Keep the existing `llm_client` repository private. Brian explicitly accepted
   private-only distribution on 2026-06-22. Do not make this repository public
   unless issue #30 is reopened and the stale object is purged, or a fresh clean
   public repo is created from a sanitized tree.
2. Verify the current PR tree contains no sensitive run directory names or
   private identifiers from issue #30. Keep the exact private grep pattern in
   the issue, not in tracked repo docs.
3. Add a PR comment with the final sanitized head, issue #30 link, and the
   private-only/public-release policy.

### Phase 1 - Canonicalize `AdversarialReview`

4. Move the `AdversarialReview` schema and base prompt from
   `cli/review_artifact.py` into `workflow/adversarial_review.py`.
5. Add `ReviewProfile`, `register_review_profile`, `get_review_profile`, and
   `list_review_profiles`. This is separate from `TaskFamily` because it is
   for standalone artifact review, not duet plan/implement stages.
6. Add built-in profiles:
   - `generic` - current `review-artifact` behavior.
   - `quality_optimal_whitepaper` - Brian's north-star whitepaper review
     prompt, expressed as prompt addenda over the canonical schema.
7. Add one generic optional field to `AdversarialReview`:
   `profile_annotations: list[ReviewAnnotation]`.
   `ReviewAnnotation` has these fields:
   - `annotation_id: str`
   - `kind: Literal["optimum_gap", "spurious", "uncertain"]`
   - `claim: str`
   - `evidence_path: str | None`
   - `linked_finding_index: int` - index into the same review's
     `correctness_findings`; required for every `kind == "optimum_gap"`.
   - `validity_loss_without_change: str` - required for every
     `optimum_gap`; answers "what does the paper get wrong today without this?"
   - `why_rejected_or_uncertain: str` - required for `spurious` and
     `uncertain`.
   Defects stay in `correctness_findings` and `contract_violations`.
   `profile_annotations` carries only the profile-specific rationale that the
   canonical finding schema does not express.
   Backward compatibility rule: older consumers that ignore unknown optional
   fields can continue reading the JSON; consumers that mirror the old
   `extra="forbid"` schema must either pin `--review-schema-version 1` or
   update to schema version 2 before reading profile annotations.
   Live parse rule: model output is parsed through a permissive response schema
   and then normalized into the canonical schema before JSON is written or
   findings are classified. Canonical `ReviewAnnotation` stays strict, but
   malformed live profile annotations become non-actionable discussion items:
   missing `why_rejected_or_uncertain` receives an explicit repair note, and an
   invalid `optimum_gap` missing a non-negative `linked_finding_index` or
   `validity_loss_without_change` is converted to `uncertain`.
8. `review-artifact --review-profile quality_optimal_whitepaper` renders the
   user's desired sections from canonical JSON:
   - `[DEFECT]` = every `contract_violations` entry plus each
     `correctness_findings` item with `severity == "high"` whose index is not
     claimed by the first `profile_annotations.kind == "optimum_gap"` for that
     `linked_finding_index`.
   - `[OPTIMUM-GAP]` = for each first-seen
     `profile_annotations.kind == "optimum_gap"` with a non-`None`
     `linked_finding_index` whose linked correctness finding has
     `severity == "high"`, render the linked
     `correctness_findings[linked_finding_index].claim` together with
     `validity_loss_without_change`; later duplicate annotations for the same
     index do not appear here.
   - `[SPURIOUS]` = `profile_annotations.kind == "spurious"`.
   - `[UNCERTAIN]` = `unverified_claims`,
     `profile_annotations.kind == "uncertain"`, `optimum_gap` annotations
     linked to non-high-severity correctness findings, non-high-severity
     `correctness_findings` not rendered in `[OPTIMUM-GAP]`, and discussion
     repairs for malformed `optimum_gap` annotations that either point outside
     the `correctness_findings` array or duplicate an already-claimed
     `linked_finding_index`.

### Phase 2 - Synchronous Whitepaper Review Cycle

9. Implement `build_review_cycle()` in `workflow/review_cycle.py`. V1 is a
   local synchronous runner, not an OpenClaw job:
   `review -> classify_actionable_findings -> implementer_apply -> rerun_review`.
10. Inputs are a Pydantic `ReviewCycleTask`: artifact file paths, workspace,
    review profile, reviewer model, implementer model, max cycles, total
    max budget, per-call max budget, stop policy, output directory, and
    runtime-cache carve-outs. V1's default `runtime_cache_carveouts` value is
    `["python_bytecode"]`, covering `__pycache__/`, `*.pyc`, and `*.pyo`; tasks
    may set it to `[]` to fail on all ignored runtime cache writes.
    The runner enforces cumulative budget with an in-run accumulator of
    `ReviewCallResult.cost_usd` and `ApplyAttempt.cost_usd` values, persisted
    as `BudgetLedgerEntry.cost_usd` / `cumulative_usd` in
    `budget_ledger.json`; observability DB queries are diagnostic only because
    not every failed local call is guaranteed to be queryable at stop time.
11. The high-confidence apply gate is deterministic:
    - apply only `contract_violations`, `correctness_findings.severity == "high"`,
      and `optimum_gap` annotations whose `linked_finding_index` points to a
      high-severity correctness finding and whose
      `validity_loss_without_change` is non-empty;
    - route default `warn` correctness findings to `discussion_queue.json`
      unless a later verifier or human explicitly promotes them;
    - never auto-apply `spurious`, `uncertain`, `nits`, or unverified claims;
    - write all skipped items to `discussion_queue.json`.
12. The implementer is instructed to edit only the declared artifact files.
    The runner snapshots `HEAD` and `git status --short` before each apply,
    computes the working-tree diff against that `HEAD` snapshot after the
    implementer returns, and
    fails loud if any touched path is outside the declared artifact list unless
    the task config explicitly allows workspace-wide edits or the touched path
    matches a task-declared `runtime_cache_carveouts` class. A dirty pre-flight
    tree is allowed only when the dirt is confined to declared artifact paths
    and is recorded in `preflight_status.txt`.
13. The loop stops when one of these occurs:
    - review verdict is `pass` or only non-actionable findings remain;
    - no artifact diff occurs after an apply attempt;
    - the normalized actionable-finding digest repeats;
    - max cycles is reached;
    - cumulative `max_budget` is exhausted.
    The digest input is the sorted JSON list of actionable candidates after
    the gate in step 11. Each item is `{kind, evidence_ref, severity, claim}`,
    where `evidence_ref` is `file_path:line` for correctness findings or
    `evidence_path` for contract violations; actionable `optimum_gap`
    annotations use `evidence_path` when it is non-empty and otherwise fall
    back to the linked correctness finding's `file_path:line`. Normalize by
    lowercasing, trimming, collapsing whitespace, and removing Markdown list
    markers from `claim`, then hash the JSON with SHA-256.
14. Every cycle writes `review_<n>.json`, `apply_<n>.md`,
    `apply_<n>.json`, `diff_<n>.patch`, `discussion_queue_<n>.json`; the run
    also writes `preflight_status.txt`, `discussion_queue.json`,
    `budget_ledger.json`, and terminal `signoff.json`.

### Phase 3 - Verification and Evaluation

15. Add offline tests for the profile registry, schema mapping, deterministic
    high-confidence classification, stop conditions, and undeclared-file guard.
16. Add a gated live smoke:
    `LLM_CLIENT_INTEGRATION=1 pytest tests/test_workflow_schema_smoke.py -q`
    remains explicitly optional for local development but required before
    publicly distributing the branch's new review-cycle feature.
17. Create a frozen case set under `prompt_eval` before claiming that one model
    pair or review profile is better than another. Minimum v1 cases:
    two known-good methodology sections, two known-defective methodology
    sections, and two spurious-completeness traps.
18. Compare `generic` vs `quality_optimal_whitepaper`, solo review vs review
    cycle, and candidate reviewer models on false positives, missed defects,
    and actionable-finding stability.

### Phase 4 - OpenClaw / Moltbot Integration

19. Add an OpenClaw task adapter that shells out to:
    `python -m llm_client review-cycle --task-file ...`.
20. Store `review-cycle` artifact paths in OpenClaw task reports. Do not change
    `graph_task_report.schema.json` or `flat_task_report.schema.json` except
    to add optional artifact-reference fields if a separate schema review
    proves they are needed. V1 defaults to writing a sidecar
    `review_cycle_artifacts.json` and linking only the sidecar path from the
    OpenClaw report; direct `outputs.review_cycle_signoff_path` is a later
    optimization only after the OpenClaw schema accepts it.
21. Migrate or remove only the old OpenClaw review-cycle wrapper scripts after
    the adapter can reproduce their current reports.

### Phase 5 - Archive Legacy Dialogue Code

22. Inspect legacy candidates before moving anything:
    - source: ecosystem sibling `utils/consensus_system/`
    - source: ecosystem sibling `agent_ontology/agents/debate_agent.py`
23. Create the two extraction notes listed in Files Affected. Each note must
    name the specific idea kept, why it matters, and the `llm_client` surface
    that supersedes it.
    Minimum checklist:
    - convergence / disagreement representation
    - opinion-dynamics or confidence reporting
    - debate turn topology
    - summarization / synthesis artifact shape
    - any evaluation metric not already covered by `AdversarialReview`,
      `deliberate-task`, or `review-cycle`
24. Move legacy code to `PROJECTS_DEFERRED/intermodel-dialogue-legacy/` or add
    an `ARCHIVED_BY_PLAN_36.md` tombstone in place if moving would break
    imports. No deletion before extraction notes exist.

---

## Required Tests

### New Tests

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_workflow_adversarial_review.py` | `test_schema_v1_preserves_original_strict_shape` | Default/generic schema behavior does not drift. |
| `tests/test_workflow_adversarial_review.py` | `test_schema_v2_accepts_profile_annotations` | The profile extension stays inside `AdversarialReview`; defects are not a parallel schema. |
| `tests/test_workflow_adversarial_review.py` | `test_quality_optimal_profile_only_renders_high_severity_optimum_gaps` | Rendered `[OPTIMUM-GAP]` output matches the high-confidence apply gate. |
| `tests/test_workflow_adversarial_review.py` | `test_review_annotation_optimum_gap_requires_link_and_validity_loss` | Profile annotations are typed and closed. |
| `tests/test_cli_review_artifact.py` | `test_cmd_review_artifact_threads_quality_profile` | `--review-profile` reaches prompt/schema construction. |
| `tests/test_workflow_review_cycle.py` | `test_actionable_classifier_excludes_warn_spurious_uncertain_and_nits` | The loop never auto-applies rejected/uncertain advice. |
| `tests/test_workflow_review_cycle.py` | `test_review_cycle_stops_on_repeated_finding_digest` | Repeated reviewer output terminates instead of spinning. |
| `tests/test_workflow_review_cycle.py` | `test_review_cycle_stops_when_apply_makes_no_diff` | Failed apply is visible and terminal. |
| `tests/test_workflow_review_cycle.py` | `test_review_cycle_fails_on_undeclared_file_edit` | Artifact-only tasks cannot silently edit other files. |
| `tests/test_workflow_review_cycle.py` | `test_review_cycle_runtime_cache_carve_out_is_task_declared` | Bytecode/cache exclusions are explicit task-schema behavior, not a hidden undeclared-edit exception. |
| `tests/test_workflow_review_cycle.py` | `test_review_cycle_pass_writes_signoff` | Every terminal run is inspectable from disk. |
| `tests/test_cli_review_cycle.py` | `test_cli_review_cycle_threads_task_file` | CLI parses the task and calls the runner with typed config. |

### Existing Tests

| Test Pattern | Why |
|--------------|-----|
| `tests/test_cli_review_artifact.py` | Existing standalone review CLI must remain compatible. |
| `tests/test_cli_duet.py` and `tests/test_workflow_duet.py` | Duet profiles and review schemas are shared dependency surfaces. |
| `tests/test_workflow_deliberate.py` and `tests/test_workflow_deliberate_verifier.py` | Deliberation remains a sibling, not a casualty of consolidation. |
| `tests/test_cli_smoke.py` | New `review-cycle --help` must be registered. |

---

## Acceptance Criteria

- [x] GitHub issue #30 is resolved, or the repo is explicitly kept private and
      the sanitized branch stays marked private-only.
- [x] A local grep for the private issue #30 evidence patterns returns no hits
      in the current PR tree; the exact pattern is not repeated in tracked docs.
- [x] `review-artifact` still works without `--review-profile`; `generic` is
      the default.
- [x] Schema version 1 JSON output remains available, or every known
      `AdversarialReview` consumer is updated to tolerate the optional
      `profile_annotations` field.
- [x] `quality_optimal_whitepaper` produces the requested rendered sections
      without replacing the canonical `AdversarialReview` JSON contract, and
      `[OPTIMUM-GAP]` uses the same high-severity threshold as the actionable
      gate.
- [x] `review-cycle` has typed config, deterministic stop conditions, a total
      budget guard, durable per-cycle artifacts, and task-declared runtime
      cache carve-outs for ignored bytecode churn.
- [x] No OpenClaw task-report schema is replaced by `AdversarialReview`.
- [x] Legacy archive extraction notes exist before any legacy code is moved or
      tombstoned.
- [x] Offline test sweep exits 0:
      `pytest tests/test_workflow_adversarial_review.py tests/test_cli_review_artifact.py tests/test_workflow_review_cycle.py tests/test_cli_review_cycle.py tests/test_cli_smoke.py tests/test_workflow_duet.py tests/test_workflow_deliberate.py tests/test_workflow_deliberate_verifier.py -q`.
      Rerun on the Plan #37 pilot branch after the dogfood fixes:
      `118 passed in 53.40s`.
- [x] Gated live schema smoke is documented and run before any public release:
      `LLM_CLIENT_INTEGRATION=1 pytest tests/test_workflow_schema_smoke.py -q`.
- [x] PR comment posted with sanitized head SHA, issue #30 link, and the
      public-distribution gate.
- [x] A new `review-artifact` dogfood run against this plan returns no blocker
      findings, or every blocker is tracked as a new plan/update before
      implementation begins. The 2026-06-22 live `review-cycle` dogfood run
      reached `max_cycles` with contract blockers; those blockers were
      converted into the Plan #37 follow-up fixes described above.

---

## Notes

**Design decisions**

- **ReviewProfile, not TaskFamily.** `TaskFamily` is bound to the duet's
  plan/implement review stages. Standalone artifact review needs the same
  chassis/profile idea but a different state machine and schema surface.
- **One canonical JSON contract.** The quality-optimal prompt can render
  `[DEFECT]`, `[OPTIMUM-GAP]`, `[SPURIOUS]`, and `[UNCERTAIN]` for human
  readability, but downstream systems consume `AdversarialReview` plus one
  typed annotation extension field. The rendered `[UNCERTAIN]` bucket is
  intentionally broader than `unverified_claims`: it also carries non-high
  correctness discussion items and malformed/duplicate `optimum_gap` repairs
  so the readable output does not silently drop non-actionable correctness
  tension.
- **Local synchronous loop first.** OpenClaw scheduling is useful after the
  loop contract is real. Starting with a local runner lets tests cover the
  convergence and artifact rules without queue semantics in the way.
- **Budget guard is safety, not optimization.** The whitepaper prompt treats
  compute cost as unconstrained for quality critique. The runner still needs a
  configurable total budget so an automation bug fails loud instead of running
  indefinitely.

**Risks**

- **Profile overfitting.** The quality-optimal prompt may become excellent for
  methodology papers but noisy for code plans. Mitigation: keep it opt-in and
  evaluate it on a frozen prompt_eval case set before changing defaults.
- **Implementer over-edits.** An agent applying review findings may rewrite
  more than the artifact. Mitigation: declared artifact path guard and
  terminal failure on undeclared diffs.
- **Reviewer convergence illusion.** A repeated clean review can mean the paper
  is good or the reviewer has stabilized on its own blind spot. Mitigation:
  preserve reviewer model choice and compare model pairs in `prompt_eval`.

**Follow-ups not in scope**

- Browser ChatGPT UI automation.
- Public hosted service.
- Full OpenClaw dashboard integration.
- LLM-semantic verification of every whitepaper claim.
