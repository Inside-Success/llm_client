# Plan #92: Worktree lifecycle governance and cleanup

**Status:** Complete
**Type:** implementation
**Priority:** Critical
**Blocked By:** project-meta Plan #212; enforced-planning Plan #59
**Blocks:** Safe historical worktree cleanup

---

## Gap

**Current:** `llm_client` has historical worktrees in four retired sibling or
home-directory layouts. Its installed creator still defaults to
`<repo>_worktrees`, `.gitignore` does not ignore `worktrees/`, and closeout can
delete a clean branch without proving merge or an explicit disposition.

**Target:** New worktrees default to `<repo>/worktrees/<branch>/`; the directory
is ignored; closeout validates merge or a durable explicit disposition before
mutation; every historical checkout has a recorded, evidence-backed action.

**Why:** A clean checkout is not proof that committed work is integrated.
Cleanup must reduce checkout clutter without destroying unique branch history.

---

## References Reviewed

- `CLAUDE.md` and repository-root `AGENTS.md` — local workflow and policy.
- `Makefile` and `scripts/meta/worktree-coordination/create_worktree.py` —
  installed worktree entrypoints and retired sibling default.
- `scripts/meta/session_close.py` and `enforced_planning/session_lifecycle.py` —
  installed closeout behavior before propagation.
- `docs/plans/22_capability-ownership-and-sanctioned-worktree-alignment.md` —
  prior sanctioned-worktree rollout.
- `project-meta/policy/registry.yaml` — canonical location and lifecycle policy.
- `enforced-planning/docs/plans/59_worktree-lifecycle-disposition-enforcement.md`
  — verified portable implementation and controls.
- `git worktree list --porcelain`, ancestry, `git cherry`, upstream, and status
  evidence captured in the companion disposition report.
- `agent-memory recall 'active decisions worktree lifecycle session close'
  --project llm_client` — no conflicting active decision was returned.

---

## Files Affected

- `.gitignore`
- `ISSUES.md`
- `Makefile`
- `enforced_planning/coordination_claims.py`
- `enforced_planning/doc_authority.py`
- `enforced_planning/session_lifecycle.py`
- `enforced_planning/worktree_lifecycle.yaml`
- `enforced_planning/worktree_paths.py`
- `scripts/meta/check_coordination_claims.py`
- `scripts/meta/session_close.py`
- `scripts/meta/session_finish.py`
- `scripts/meta/session_heartbeat.py`
- `scripts/meta/session_start.py`
- `scripts/meta/session_status.py`
- `scripts/meta/worktree-coordination/create_worktree.py`
- `scripts/meta/worktree-coordination/safe_worktree_remove.py`
- `tests/test_worktree_lifecycle_governance.py`
- `worktrees/codex-review-prompts-as-assets-20260624` (remove stale gitlink)
- `docs/ops/2026-07-09-worktree-disposition-report.md`
- `docs/ops/2026-07-09-plan92-worktree-lifecycle-progress.md`
- `docs/plans/CLAUDE.md`

---

## Plan

| Step | What | Status |
|---|---|---|
| 1 | Inventory every registered checkout and grade its recovery evidence. | Complete |
| 2 | Record intended disposition before cleanup. | Complete |
| 3 | Install the canonical worktree lifecycle framework and ignore `worktrees/`. | Complete |
| 4 | Add consumer controls for location, vocabulary, and CLI propagation. | Complete |
| 5 | Merge and push the governance slice; close its worktree through the new gate. | Complete |
| 6 | Remove clean historical checkouts while retaining unique branches. | Complete |
| 7 | Restore the canonical checkout to `main` and verify the final inventory. | Complete |

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|---|---|---|
| `tests/test_worktree_lifecycle_governance.py` | `test_installed_creator_defaults_inside_repo` | Consumer default is `<repo>/worktrees` |
| same | `test_installed_closeout_exposes_disposition_contract` | Consumer CLI exposes explicit disposition evidence |
| same | `test_lifecycle_vocabulary_is_installed` | Fail-loud lifecycle vocabulary is present |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|---|---|
| governance test plus installed CLI smoke checks | Consumer propagation works |
| canonical enforced-planning Plan #59 suite | Behavior is already controlled with real Git repositories |

---

## Acceptance Criteria

| Criterion | Evidence class | Grade | Result |
|---|---|---:|---|
| New default is in-repo and ignored | test | A | Three consumer tests pass; creator resolves `<repo>/worktrees` |
| Clean unmerged closeout fails before mutation | test | A | Canonical 44-test real-Git lifecycle/installer set passes |
| Merged and pushed closeout succeeds | observed | B | Governance and gitlink lanes closed with merged disposition evidence |
| Every historical checkout has a disposition | observed | B | Report reconciled; 20 clean historical checkouts removed and one missing registration pruned |
| Unique historical commits remain recoverable | observed | B | All 13 non-ancestor branch tips resolve after checkout removal |
| Canonical checkout is clean `main` | observed | B | Root is clean `main`; `main == origin/main == 617d0fc` before final evidence merge |

---

## Decisions

- Worktree lifecycle and branch lifecycle are separate. Removing a clean
  historical checkout does not authorize deleting its unique branch.
- Branches with commits not patch-equivalent to `main` are retained for human
  intent review. No speculative historical merge is part of this plan.
- Patch-equivalent but non-ancestor branches are also retained in this first
  cleanup; equivalence proves content integration, not author intent.
- The one missing temporary checkout is pruned only after its registration is
  recorded.
- The nested review checkout was also committed as a mode-`160000` gitlink.
  Its branch tip remains retained; the dead gitlink is removed from `main` as a
  tracked cleanup artifact.
- Consumer verification checks the exact worktree-only installer closure. A
  broader ad hoc scan of unrelated legacy `scripts/meta` files is outside this
  plan and is not presented as a failure of the propagated surface.
- `make lint` currently reports 317 pre-existing repository-wide findings;
  issue LLM-001 records that separate gate debt.
