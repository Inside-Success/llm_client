# Plan #36 Dogfood Review Summary

This file is the tracked, redacted evidence note for the dogfood review that
shaped Plan #36. The raw review artifacts are local run outputs and are not
committed.

## Review 1 - Initial Consolidation Plan

Verdict: blocker.

High-confidence findings integrated into Plan #36:

- Historical PR artifacts had been pushed to GitHub and required containment
  beyond deleting files from the branch tip. GitHub issue #30 now tracks stale
  commit/blob purge, and the repo is private until that is resolved or accepted
  as private-only.
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
- Keep release gates scoped: issue #30 gates public distribution of the
  sanitized branch; Plan #36's own feature release is gated by its tests,
  dogfood review, and optional live schema smoke.

## Review 3 - Plan #37 Execution Spine

Raw local artifact: `runs/dogfood-plan37-review/review.json`.

Verdict: concerns.

High-confidence findings integrated before commit:

- Cross-repo OpenClaw and legacy archive work must not contradict the stop
  condition for moving/deleting sibling-repo code. The spine now allows
  additive sibling-repo branch work with baseline capture, but stops before
  irreversible moves/deletes.
- Pushes are safe only after verifying the target repo is the private
  `BrianMills2718/llm_client` remote while issue #30 remains unresolved.
- Live-model gates can block final completion. The spine now defines an
  offline-complete/live-blocked state instead of pretending the plan is done.
- Future test files are expected not to exist before their creation phase; the
  spine now says to run only existing focused tests until each phase creates its
  new tests.
- The private issue #30 grep pattern must be fetched from the private issue body
  into ignored local scratch state, not embedded in tracked docs.
- The repeated-failure circuit breaker now has a concrete digest and ledger.
