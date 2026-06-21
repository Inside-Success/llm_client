# Plan #36: Intermodel Review Consolidation and Whitepaper Loop

**Status:** In Progress
**Type:** implementation
**Priority:** Critical
**Blocked By:** GitHub issue #30 for any public release; private-only implementation may proceed
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

- Sensitive historical PR artifacts were pushed and remain reachable by old
  commit SHA until GitHub purges them or the repo stays private.
- The quality-optimal review prompt introduces `DEFECT`, `OPTIMUM-GAP`,
  `SPURIOUS`, and `UNCERTAIN` buckets without reconciling them with the
  existing `AdversarialReview` contract.
- The proposed loop has no convergence, budget, or fix-verification contract.
- OpenClaw's task-report schemas were conflated with review verdict schemas.
- Legacy `consensus_system` / `agent_ontology` ideas were marked for archive
  without concrete extraction artifacts.

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
- GitHub issue #30 - tracks stale historical commit/blob purge for PR #29.

---

## Files Affected

- `docs/guides/agent-collaboration.md` (modify) - remove stale sensitive-run
  references and add the new whitepaper loop once implemented.
- `llm_client/workflow/adversarial_review.py` (created; modify in follow-ups) - move
  `AdversarialReview`, finding imports, prompt builder, and review-profile
  registry out of the CLI.
- `llm_client/cli/review_artifact.py` (modified) - delegate schema/prompt/profile
  resolution to `workflow.adversarial_review`; add `--review-profile`.
- `llm_client/workflow/review_cycle.py` (created; modify in follow-ups) - synchronous local loop runner
  for review -> apply -> verify -> repeat.
- `llm_client/cli/review_cycle.py` (created) - `review-cycle` subcommand.
- `llm_client/__main__.py` (modified) - register `review-cycle`.
- `tests/test_cli_review_artifact.py` (modified) - profile flag and schema
  relocation coverage.
- `tests/test_workflow_adversarial_review.py` (created) - review-profile
  registry, profile annotation schema, and prompt mapping tests.
- `tests/test_workflow_review_cycle.py` (created; modify in follow-ups) - loop convergence, budget,
  artifact persistence, and high-confidence apply gating.
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

1. Keep `llm_client` private until GitHub issue #30 is resolved or Brian
   explicitly accepts private-only distribution.
2. Verify the current PR tree contains no sensitive run directory names or
   private identifiers from issue #30. Keep the exact private grep pattern in
   the issue, not in tracked repo docs.
3. Add a PR comment with the final sanitized head, issue #30 link, and the
   public-release gate.

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
8. `review-artifact --review-profile quality_optimal_whitepaper` renders the
   user's desired sections from canonical JSON:
   - `[DEFECT]` = high-impact `correctness_findings` and
     `contract_violations`.
   - `[OPTIMUM-GAP]` = actionable `correctness_findings` linked to
     `profile_annotations.kind == "optimum_gap"`.
   - `[SPURIOUS]` = `profile_annotations.kind == "spurious"`.
   - `[UNCERTAIN]` = `unverified_claims` plus
     `profile_annotations.kind == "uncertain"`.

### Phase 2 - Synchronous Whitepaper Review Cycle

9. Implement `build_review_cycle()` in `workflow/review_cycle.py`. V1 is a
   local synchronous runner, not an OpenClaw job:
   `review -> classify_actionable_findings -> implementer_apply -> rerun_review`.
10. Inputs are a Pydantic `ReviewCycleTask`: artifact file paths, workspace,
    review profile, reviewer model, implementer model, max cycles, total
    max budget, per-call max budget, stop policy, and output directory.
    The runner enforces cumulative budget with an in-run accumulator of
    `LLMCallResult.cost` values and writes `budget_ledger.json`; observability
    DB queries are diagnostic only because not every failed local call is
    guaranteed to be queryable at stop time.
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
    the task config explicitly allows workspace-wide edits. A dirty pre-flight
    tree is allowed only when the dirt is confined to declared artifact paths
    and is recorded in `preflight_status.json`.
13. The loop stops when one of these occurs:
    - review verdict is `pass` or only non-actionable findings remain;
    - no artifact diff occurs after an apply attempt;
    - the normalized actionable-finding digest repeats;
    - max cycles is reached;
    - cumulative `max_budget` is exhausted.
    The digest input is the sorted JSON list of actionable candidates after
    the gate in step 11. Each item is `{kind, evidence_ref, severity, claim}`,
    where `evidence_ref` is `file_path:line` for correctness findings or
    `evidence_path` for contract violations/annotations. Normalize by
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
| `tests/test_workflow_adversarial_review.py` | `test_generic_review_profile_preserves_current_prompt` | Default `review-artifact` behavior does not drift. |
| `tests/test_workflow_adversarial_review.py` | `test_quality_optimal_profile_maps_to_canonical_schema` | The profile uses `AdversarialReview`; defects are not a parallel schema. |
| `tests/test_workflow_adversarial_review.py` | `test_review_annotation_rejects_unknown_kind` | Profile annotations are typed and closed. |
| `tests/test_cli_review_artifact.py` | `test_cli_threads_review_profile` | `--review-profile` reaches prompt/schema construction. |
| `tests/test_workflow_review_cycle.py` | `test_actionable_classifier_excludes_spurious_and_uncertain` | The loop never auto-applies rejected/uncertain advice. |
| `tests/test_workflow_review_cycle.py` | `test_review_cycle_stops_on_repeated_finding_digest` | Repeated reviewer output terminates instead of spinning. |
| `tests/test_workflow_review_cycle.py` | `test_review_cycle_stops_when_apply_makes_no_diff` | Failed apply is visible and terminal. |
| `tests/test_workflow_review_cycle.py` | `test_review_cycle_fails_on_undeclared_file_edit` | Artifact-only tasks cannot silently edit other files. |
| `tests/test_workflow_review_cycle.py` | `test_review_cycle_writes_signoff_and_cycle_artifacts` | Every cycle is inspectable from disk. |
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

- [ ] GitHub issue #30 is resolved, or the repo is explicitly kept private and
      the sanitized branch stays marked private-only.
- [ ] A local grep for the private issue #30 evidence patterns returns no hits
      in the current PR tree; the exact pattern is not repeated in tracked docs.
- [ ] `review-artifact` still works without `--review-profile`; `generic` is
      the default.
- [ ] Schema version 1 JSON output remains available, or every known
      `AdversarialReview` consumer is updated to tolerate the optional
      `profile_annotations` field.
- [ ] `quality_optimal_whitepaper` produces the requested rendered sections
      without replacing the canonical `AdversarialReview` JSON contract.
- [ ] `review-cycle` has typed config, deterministic stop conditions, a total
      budget guard, and durable per-cycle artifacts.
- [ ] No OpenClaw task-report schema is replaced by `AdversarialReview`.
- [ ] Legacy archive extraction notes exist before any legacy code is moved or
      tombstoned.
- [ ] Offline test sweep exits 0:
      `pytest tests/test_workflow_adversarial_review.py tests/test_cli_review_artifact.py tests/test_workflow_review_cycle.py tests/test_cli_review_cycle.py tests/test_cli_smoke.py tests/test_workflow_duet.py tests/test_workflow_deliberate.py tests/test_workflow_deliberate_verifier.py -q`.
- [ ] Gated live schema smoke is documented and run before any public release:
      `LLM_CLIENT_INTEGRATION=1 pytest tests/test_workflow_schema_smoke.py -q`.
- [ ] PR comment posted with sanitized head SHA, issue #30 link, and the
      public-distribution gate.
- [ ] A new `review-artifact` dogfood run against this plan returns no blocker
      findings, or every blocker is tracked as a new plan/update before
      implementation begins.

---

## Notes

**Design decisions**

- **ReviewProfile, not TaskFamily.** `TaskFamily` is bound to the duet's
  plan/implement review stages. Standalone artifact review needs the same
  chassis/profile idea but a different state machine and schema surface.
- **One canonical JSON contract.** The quality-optimal prompt can render
  `[DEFECT]`, `[OPTIMUM-GAP]`, and `[SPURIOUS]` for human readability, but
  downstream systems consume `AdversarialReview` plus one typed annotation
  extension field.
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
