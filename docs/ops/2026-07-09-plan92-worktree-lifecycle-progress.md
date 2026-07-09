# Plan #92 progress: worktree lifecycle governance

## Mission

Adopt the approved in-repo and merge-or-disposition policy in `llm_client`,
then reduce historical worktree clutter without losing unique branch history.

## Acceptance criteria

- [x] Installed creator defaults to `<repo>/worktrees/<branch>/`.
- [x] `worktrees/` is ignored.
- [x] Installed closeout refuses clean unmerged branches by default.
- [ ] Governance slice is merged and pushed before its worktree is removed.
- [ ] Historical worktree actions match the disposition report.
- [ ] Unique historical branch tips remain resolvable.
- [ ] Canonical checkout ends clean on `main` with `main == origin/main`.

## Current phase

Commit, merge, push, and close the governance lane before historical cleanup.

## Completed

- 2026-07-09: Confirmed there were no active coordination claims for
  `llm_client` before creating this lane.
- 2026-07-09: Created the claimed lane at
  `llm_client/worktrees/worktree-lifecycle-governance-20260709` from `main`.
  The retired installed creator required an explicit `WORKTREE_DIR` override.
- 2026-07-09: Inventoried 21 pre-existing registrations plus this active lane.
  All 20 existing historical checkouts are clean; one temporary registration
  is missing and prunable. Seven historical tips are ancestors of `main`, four
  non-ancestor tips have no patch unique to the branch, and nine branches have
  patches unique relative to `main`.
- 2026-07-09: Installed the canonical merge-or-disposition framework and added
  three consumer controls. Initial downstream Ruff verification exposed an
  omitted compatibility-facade suppression in the framework after Plan #59 had
  been marked complete.
- 2026-07-09: Corrected the canonical source and its mirrors, added a test that
  installs and lints the complete worktree-only output closure, merged the fix
  to `enforced-planning/main`, and reinstalled with zero drift. The canonical
  focused suite passes 44 tests; the consumer suite passes 3 tests; the exact
  portable Python closure passes Ruff.
- 2026-07-09: Logged the partial-scope verification gap in `project-meta` and
  filed the pending `derived-propagation-verification-closure` proposal.
- 2026-07-09: A broad `make lint` probe reports 317 existing errors across
  product and test code. The exact Plan #92 consumer/installer closure is green;
  repository-wide lint debt is tracked separately as LLM-001.

## Next

1. Commit, push, merge, and close this lane through the new gate.
2. Execute the recorded historical checkout removals, preserving unique refs.
3. Reconcile the final inventory and update project-meta coverage.
