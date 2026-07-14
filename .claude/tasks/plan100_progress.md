# Plan 100 Progress

## Mission

Implement and certify budget-complete call snapshot v3 on exact Plan 97 commit
`d74b8ea`, then enable a separately governed DoDAF successor diagnostic.

## Acceptance

- [x] Preserve the active Plan 97 commit in a separate child worktree and claim.
- [x] Complete required reading and write requirements through schema before code.
- [x] Add failing v3 builder, fingerprint, historical-read, and replay controls.
- [x] Implement v3 and pass text/structured sync/async producer controls.
- [x] Run focused and full shared-runtime gates and adversarial audit.
- [x] Commit and push the exact shared revision for integration review.
- [ ] Pin the exact revision in a new DoDAF successor plan.
- [ ] Execute at most one page-11 diagnostic and verify its complete full trace.
- [ ] Close the exact DoDAF terminal without quality or rerun overclaim.

## Current Phase

Plan 100 Slice 3: publish/integrate the exact shared revision, then pin it in
the DoDAF successor.

## Constraints

- Do not modify the Plan 97 worktree or discard commit `d74b8ea`.
- No provider call during shared repair.
- V2 semantics remain historical and unchanged.
- Captured original budget is never reused as fresh replay authorization.
- Every later DoDAF LLM call requires full-trace verification before meaning.

## Durable Log

- 2026-07-14: Coordination checker found no conflict for a child claim based on
  Plan 97. Worktree `plan-100-budget-snapshot-v3` starts at exact `d74b8ea`.
- 2026-07-14: Investigation selected closed snapshot v3 with required
  `request.control.max_budget`, full-envelope identity, historical v1/v2 reads,
  and a separately supplied fresh replay budget.
- 2026-07-14: The six declared controls were observed red (11 failures, one
  historical compatibility pass), then passed after implementation (12 passes).
- 2026-07-14: Full replay tests passed (62); Plan 97 structured-attempt and
  execution-kernel tests passed (25). Targeted Ruff passed. Strict mypy reached
  the pre-existing `llm_client/parsing_utils.py:139` no-Any-return error outside
  this change; no type error in the modified boundary was reported first.
- 2026-07-14: Repository tests passed under the repository virtual environment:
  1,648 passed, 3 skipped, 11 deselected. `make test-quick` itself used
  `/usr/bin/python` because a per-worktree `.venv` was absent and failed during
  collection; the same named test passed under the repository `.venv` before
  the complete suite did.
- 2026-07-14: Repository-wide lint/type gates remain baseline-red (309 Ruff,
  209 mypy errors across unrelated files); targeted Ruff is clean and all
  changed-runtime behavior is covered by passing tests. Bounded audit found no
  PoC blocker and retained the diagnostic-only unsupported-snapshot exception.
- 2026-07-14: Implementation commit `0b69776` is pushed on
  `origin/plan-100-budget-snapshot-v3`, preserving Plan 97 commit `d74b8ea`.
