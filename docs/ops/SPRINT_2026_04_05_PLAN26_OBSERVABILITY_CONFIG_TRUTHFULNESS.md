# Sprint: 2026-04-05 Plan 26 Observability Config Truthfulness

**Status:** Complete
**Owner:** codex
**Plan:** [../plans/26_observability-config-truthfulness-and-test-isolation.md](../plans/26_observability-config-truthfulness-and-test-isolation.md)
**Mission:** make `llm_client` observability config truthful after import and keep all test verification isolated from the shared global observability DB by default.

## Operating Rules

1. Work only from dedicated worktrees until merge/push time.
2. Commit every verified slice before starting the next one.
3. Record every blocker, concern, or uncertainty in this file, then continue with the safer option unless a real stop condition applies.
4. Do not treat one passing regression as enough; keep going until config truth, test harness isolation, docs, and verification all agree.
5. Merge completed worktree branches into a clean integration branch, publish, then remove completed worktrees.

## Progress

- Phase 0 complete: fresh `origin/main` worktree created after PR #26 so planning and code changes are based on canonical repo truth instead of the dirty local checkout.
- Phase 1 complete: Plan 25/roadmap/index drift corrected so the repo records provider governance as complete and this observability follow-up as the active slice.
- Phase 2 complete: dynamic config resolution added for observability data-root / DB-path behavior.
- Phase 3 complete: the test suite now isolates observability env to temp state and has dedicated regressions for post-import env changes.
- Phase 4 complete: the previously blocked async routing verification lane and the broader routing slice both passed.
- Phase 5 in progress: commit, push, and clean worktree/claim state.

## Next 24 Hours

### Phase 0: Documentation Truth

Goal: make the repo describe the current state accurately before more code lands.

Acceptance:

- Plan 25 is marked complete
- Plan 26 is indexed as the active implementation slice
- `CLAUDE.md` points to this sprint tracker

### Phase 1: Dynamic Observability Config

Goal: env-backed observability settings stay truthful after import unless explicit overrides are set.

Acceptance:

- `LLM_CLIENT_DATA_ROOT` and `LLM_CLIENT_DB_PATH` changes are respected without module reload
- project naming remains stable and truthful under override/env/cwd cases
- CLI helpers use the effective runtime config instead of stale globals

### Phase 2: DB Lifecycle Truthfulness

Goal: one SQLite connection tracks the effective DB path instead of a stale cached path.

Acceptance:

- changing the effective DB path closes and replaces the old connection
- explicit `configure(db_path=...)` keeps working
- no silent fallback writes hit the wrong DB

### Phase 3: Test Harness Isolation

Goal: tests cannot contend with the shared global DB even if logging gets re-enabled accidentally.

Acceptance:

- suite-level fixture points observability env vars at temp paths
- logging remains disabled by default in tests
- dedicated regressions prove temp-state isolation still preserves logger assertions

### Phase 4: Verification

Goal: prove the original blocked lane is actually fixed at the shared-infra level.

Acceptance:

- focused `tests/test_io_log.py` suite passes
- `tests/test_client.py::TestAsyncResponsesAPIRouting::test_async_gpt5_routes_to_aresponses` passes with timeout guard
- broader `tests/test_client.py -k "codex or routing"` slice passes

### Phase 5: Publish And Cleanup

Goal: leave a clean and reversible state.

Acceptance:

- verified changes are committed and pushed
- claim is released
- completed worktree is removed after publish/merge

## Verification Matrix

- `git diff --check`
- `pytest tests/test_io_log.py -q`
- `pytest tests/test_client.py::TestAsyncResponsesAPIRouting::test_async_gpt5_routes_to_aresponses -q --timeout=30`
- `pytest tests/test_client.py -k "codex or routing" -q`

## Concerns And Uncertainties

### 2026-04-05

- The dirty local checkout is not a trustworthy planning surface; all changes for this sprint must stay in the clean worktree until merge/publish.
- There is a stale unrelated coordination claim (`merge-codex-transport-main-20260405`) in the repo. Safe default: avoid that scope and keep this sprint isolated to observability config truthfulness.
- `python scripts/meta/generate_api_reference.py --write` did not finish within a bounded wait during this sprint, but it also produced no artifact diff before exit. Safe default: keep the verified config-isolation change separate and treat API-generation investigation as a follow-up only if a later slice changes public API docs or reproduces the hang deterministically.
