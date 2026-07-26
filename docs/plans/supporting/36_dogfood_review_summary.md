# Supporting Evidence: Plan #36 Dogfood Review Summary

This file is the tracked, redacted evidence note for the dogfood review that
shaped Plan #36. The raw review artifacts are local run outputs and are not
committed.

## Review 1 - Initial Consolidation Plan

Verdict: blocker.

High-confidence findings integrated into Plan #36:

- Historical PR artifacts had been pushed to GitHub and required containment
  beyond deleting files from the branch tip. GitHub issue #30 tracked stale
  commit/blob purge and was closed on 2026-06-22 by private-only acceptance.
- A quality-optimal whitepaper review must not create a parallel defect schema.
  It should preserve `AdversarialReview` and add only a typed profile annotation
  extension if the profile needs extra rationale fields.
- Any automated review/apply loop needs explicit convergence, budget, and
  fix-verification contracts before implementation.
- OpenClaw task-report schemas are orchestration records, not review verdicts.
  OpenClaw should schedule `llm_client` review commands and store artifact
  references rather than replacing its report schemas with `AdversarialReview`.
- Legacy dialogue/debate code should not be archived until extraction notes
  preserve the useful concepts and identify the replacement `llm_client`
  surface.

## Review 2 - Plan #36 Draft

Raw local artifact: `runs/dogfood-plan36-review/review.json`.

Verdict: concerns.

High-confidence findings integrated before implementation:

- Define the `ReviewAnnotation` fields, including a stable link to the
  canonical finding and the profile-specific validity-loss text.
- Restrict auto-apply to true high-confidence findings; default `warn`
  correctness findings must not be applied automatically.
- Define the repeated-actionable-finding digest used as the anti-spin stop
  condition.
- Make cross-project legacy archive source locations explicit.
- Keep release gates scoped: the existing repo remains private-only unless
  issue #30 is reopened and purged, or a fresh clean public repo is created;
  Plan #36's own feature release is gated by its tests, dogfood review, and
  optional live schema smoke.

## Review 3 - Plan #37 Execution Spine

Raw local artifact: `runs/dogfood-plan37-review/review.json`.

Verdict: concerns.

High-confidence findings integrated before commit:

- Cross-repo OpenClaw and legacy archive work must not contradict the stop
  condition for moving/deleting sibling-repo code. The spine now allows
  additive sibling-repo branch work with baseline capture, but stops before
  irreversible moves/deletes.
- Pushes are safe only after verifying the target repo is the private
  `BrianMills2718/llm_client` remote under the issue #30 private-only
  acceptance policy.
- Live-model gates can block final completion. The spine now defines an
  offline-complete/live-blocked state instead of pretending the plan is done.
- Future test files are expected not to exist before their creation phase; the
  spine now says to run only existing focused tests until each phase creates its
  new tests.
- The private issue #30 grep pattern must be fetched from the private issue body
  into ignored local scratch state, not embedded in tracked docs.
- The repeated-failure circuit breaker now has a concrete digest and ledger.

## Review 4 - Phase 6 Plan #36 Dogfood

Raw local artifact: `runs/dogfood-phase6-plan36/review.json`.

Verdict: concerns.

High-confidence findings integrated:

- `ReviewAnnotation` requirements were ambiguous about whether every
  `optimum_gap` is actionable. Plan #36 now states that every `optimum_gap`
  requires a linked canonical finding and concrete validity-loss rationale.
- The runner's diff guard needed to compare against the pre-apply `HEAD`
  snapshot, including committed apply changes. The implementation now diffs
  against that snapshot and has a regression test for committed apply diffs.
- Plan #36 now lists all durable runner artifacts, including preflight status,
  terminal discussion queue, and budget ledger outputs.
- OpenClaw integration defaults to a sidecar artifact-reference file rather
  than assuming direct report-output schema changes.
- Legacy extraction notes now have a minimum concept checklist before archive
  or tombstone work.

## Review 5 - Phase 6 Plan #37 Dogfood

Raw local artifact: `runs/dogfood-phase6-plan37/review.json`.

Verdict: concerns.

High-confidence findings integrated:

- Repeated-failure digests now define `normalized_top_error`, so the
  three-strike circuit breaker has a stable key.
- Live-gate failures now apply at any phase that requires live models, CI, or
  service access, not only after offline implementation is finished.
- Push safety now verifies both GitHub repo privacy and the actual configured
  push remote before pushing this branch or sibling-repo branches.
- Rendered quality-optimal sections now have an explicit canonical-field
  mapping in Plan #37.
- The review-cycle terminal aggregate `discussion_queue.json` is now covered by
  an offline regression test.
- Phase 9 no longer embeds hardcoded host paths in tracked instructions.

## Review 6 - Quality-Optimal Methodology Fixture

Raw local artifacts:

- `runs/dogfood-quality-methodology/seeded_whitepaper.md`
- `runs/dogfood-quality-methodology/review.json`
- `runs/dogfood-quality-methodology/review.md`

Verdict: blocker, as expected for the seeded-defect fixture.

Observed calibration result:

- The profile flagged the formal/procedure contradiction where the methodology
  defines time and modality as required claim fields but deletes dates and
  modality before comparison.
- The profile produced concrete `[OPTIMUM-GAP]` items with explicit answers to
  "what is wrong without this?"
- The profile also emitted `[SPURIOUS]` for presentation-only additions that do
  not improve claim-equivalence validity.

## Review 7 - Live Review-Cycle Dogfood

Raw local artifacts are in a temporary repo recorded outside this branch.

Result:

- First attempt found a real live-boundary defect: a model emitted an
  `uncertain` profile annotation without `why_rejected_or_uncertain`, and strict
  post-parse validation crashed before signoff.
- The fix adds a permissive LLM response schema and canonical normalization.
  Malformed `uncertain` or `spurious` annotations receive repair rationales;
  invalid `optimum_gap` annotations are converted to non-actionable discussion
  items.
- Retry completed one bounded cycle with `max_cycles` status. The implementer
  edited only the declared artifact file and corrected the seeded time and
  factuality defect.

## Review 8 - Final PR Diff Gate

Raw local artifacts:

- `runs/final-plan37-review/review.json`
- `runs/final-plan37-review/review_after_fixes.json`
- `runs/final-plan37-review/review_current_head.json`
- `runs/final-plan37-review/review_after_signoff_cli_fixes.json`
- `runs/final-plan37-review/review_after_runner_artifact_fix.json`
- `runs/final-plan37-review/review_after_renderer_hook_fix.json`
- `runs/final-plan37-review/review_final_cleanup.json`

Result:

- Early final-gate reviews found real defects in untracked-file diffing,
  duplicate `optimum_gap` actionables, budget/pass precedence, negative cost
  handling, CLI success semantics, signoff artifact indexing, ignored-file
  detection, default run-dir enforcement, and quality renderer severity
  mapping.
- Each blocker or contract violation was fixed with focused regression tests
  before continuing.
- The terminal blocker-focused review returned `verdict: pass`, with no
  contract violations and no unresolved blockers.
- Final local gates: full offline sweep passed 116 tests; gated live schema
  smoke passed 10 tests after schema hardening; GitHub PR check
  `observability-switches` passed.
