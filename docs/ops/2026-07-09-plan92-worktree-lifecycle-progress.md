# Plan #92 progress: worktree lifecycle governance

## Mission

Adopt the approved in-repo and merge-or-disposition policy in `llm_client`,
then reduce historical worktree clutter without losing unique branch history.

## Acceptance criteria

- [x] Installed creator defaults to `<repo>/worktrees/<branch>/`.
- [x] `worktrees/` is ignored.
- [x] Installed closeout refuses clean unmerged branches by default.
- [x] Governance slice is merged and pushed before its worktree is removed.
- [x] Historical worktree actions match the disposition report.
- [x] Unique historical branch tips remain resolvable.
- [x] Canonical checkout ends clean on `main` with `main == origin/main`.

## Current phase

Complete. This evidence lane is the final temporary checkout and closes through
the installed merge gate after its completion record lands.

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
- 2026-07-09: Governance commit `ab0193e` merged through PR #37; `origin/main`
  advanced to `52ca5f7`. The claimed governance worktree and both temporary
  remote branches were removed after merge evidence passed the new gate.
- 2026-07-09: Revalidated and removed 18 clean historical checkouts. All 13
  non-ancestor branches still resolve. The parent `llm_client-reviewmain`
  checkout was deliberately retained when removal of its nested checkout
  exposed a tracked mode-`160000` gitlink; the parent was restored clean before
  this claimed follow-up was created.
- 2026-07-09: Gitlink cleanup commit `0ba7a39` merged through PR #38 as
  `617d0fc`; its claimed lane closed with merged disposition evidence and its
  remote topic branch was deleted.
- 2026-07-09: Removed the now-clean `llm_client-reviewmain` checkout, pruned the
  missing temporary registration, switched the canonical root from
  `fix/instructor-retry-unwrapping` to `main`, and preserved that unique branch
  at both local and `origin/*` refs.
- 2026-07-09: Deleted only five local branches proven ancestor-merged:
  `brian/agent-collab-package`, `reconcile-main-with-origin-20260405`,
  `merge-anomaly-phase18-20260405`, `merge-anomaly-phase20-20260405`, and the
  subsequently discovered clean `codebase-memory-usage-ledger-20260709` lane.
- 2026-07-09: Final reconciliation before this evidence lane: canonical root
  clean on `main`, `main == origin/main == 617d0fc`, no missing registrations,
  and all 13 deliberately retained non-ancestor branch tips still resolve.

## Next

1. Merge and close this final evidence lane through the installed gate.
2. Re-grade project-meta Plan #212 lifecycle coverage from the live consumer
   evidence.
