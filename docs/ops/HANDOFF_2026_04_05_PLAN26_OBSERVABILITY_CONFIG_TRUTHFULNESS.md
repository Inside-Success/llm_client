# Handoff: 2026-04-05 Plan 26 Observability Config Truthfulness

## Scope

Continue and finish the `llm_client` Plan 26 slice in the clean worktree:

- worktree: `/home/brian/worktrees/llm-client-observability-config-truthfulness`
- repo: `/home/brian/projects/llm_client`
- branch: `plan26-observability-config-truthfulness`
- base HEAD when this handoff was written: `38a00cf86cd06e06957b88c9b9f0a398958733f1`

The goal of this slice is:

1. make `io_log` observability config truthful after import,
2. isolate tests away from the shared global observability DB by default,
3. update repo planning/docs so Plan 25 is recorded as complete and Plan 26 is captured explicitly.

## What Is Already Done

### Code changes are implemented in the worktree

These files are already modified and staged:

- `CLAUDE.md`
- `docs/ops/SPRINT_2026_04_05_PLAN25_PROVIDER_GOVERNANCE.md`
- `docs/ops/SPRINT_2026_04_05_PLAN26_OBSERVABILITY_CONFIG_TRUTHFULNESS.md` (new)
- `docs/plans/01_master-roadmap.md`
- `docs/plans/25_provider-governance-and-shared-coordination.md`
- `docs/plans/26_observability-config-truthfulness-and-test-isolation.md` (new)
- `docs/plans/CLAUDE.md`
- `llm_client/cli/backfill.py`
- `llm_client/cli/common.py`
- `llm_client/io_log.py`
- `tests/conftest.py`
- `tests/test_io_log.py`

### Summary of the implementation

`llm_client/io_log.py`
- `LLM_CLIENT_DATA_ROOT` and `LLM_CLIENT_DB_PATH` are now resolved dynamically when no explicit override is set.
- `_data_root`, `_project`, and `_db_path` now behave as explicit runtime overrides instead of import-time cached defaults.
- added `_get_data_root()` and `_get_db_path()`
- added `_db_conn_path` and changed `_get_db()` so it closes/reopens the SQLite connection when the effective DB path changes
- `LLM_CLIENT_PROJECT` is now respected dynamically unless an explicit `_project` override is present
- retained `configure(...)` behavior for explicit overrides

`llm_client/cli/common.py`
- `get_db_path()` now uses `io_log._get_db_path()` instead of reading stale `_db_path`

`llm_client/cli/backfill.py`
- data-root scanning now uses `io_log._get_data_root()`

`tests/conftest.py`
- tests still set `LLM_CLIENT_LOG_ENABLED=0`
- tests now also set `LLM_CLIENT_DATA_ROOT`, `LLM_CLIENT_DB_PATH`, and `LLM_CLIENT_PROJECT` to temp values so accidental re-enable paths do not touch the shared global DB

`tests/test_io_log.py`
- added regression coverage for:
  - env-backed data root changing after import
  - env-backed DB path changing after import and forcing reconnection
  - CLI DB-path resolution using the effective runtime config
- existing post-import `LLM_CLIENT_LOG_ENABLED=0` regression remains in place

### Planning/docs changes are implemented in the worktree

- Plan 25 is marked complete in the plan doc/index and sprint tracker
- Plan 26 exists and is documented
- roadmap now records Plan 26 as the follow-up slice and then returns the repo to maintenance mode
- `CLAUDE.md` points to the Plan 26 sprint tracker

## Verification Already Run

These all passed from the Plan 26 worktree:

```bash
cd /home/brian/worktrees/llm-client-observability-config-truthfulness
pytest tests/test_io_log.py -q
# result: 71 passed in 3.62s

pytest tests/test_client.py::TestAsyncResponsesAPIRouting::test_async_gpt5_routes_to_aresponses -q --timeout=30
# result: 1 passed in 2.13s

pytest tests/test_client.py -k "codex or routing" -q
# result: 11 passed, 226 deselected in 2.67s

python scripts/meta/validate_relationships.py --strict
# result: Relationships validation passed.

git diff --check
# result: clean
```

## The Exact Place Work Stopped

I attempted to commit with:

```bash
git add CLAUDE.md \
  docs/ops/SPRINT_2026_04_05_PLAN25_PROVIDER_GOVERNANCE.md \
  docs/ops/SPRINT_2026_04_05_PLAN26_OBSERVABILITY_CONFIG_TRUTHFULNESS.md \
  docs/plans/01_master-roadmap.md \
  docs/plans/25_provider-governance-and-shared-coordination.md \
  docs/plans/26_observability-config-truthfulness-and-test-isolation.md \
  docs/plans/CLAUDE.md \
  llm_client/cli/backfill.py \
  llm_client/cli/common.py \
  llm_client/io_log.py \
  tests/conftest.py \
  tests/test_io_log.py

git commit -m "[Plan #26] Make observability config truthful after import"
```

The commit was blocked by doc-coupling, which was correct. The hook reported:

- changed source: `llm_client/io_log.py`
- required ADR updates:
  - `docs/adr/0003-warning-taxonomy.md`
  - `docs/adr/0007-observability-contract-boundary.md`
  - `docs/adr/0010-cross-project-runtime-substrate.md`
  - `docs/adr/0012-shared-data-plane-boundary.md`
  - `docs/adr/0013-stream-lifecycle-heartbeat-observability.md`
  - `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md`

I then updated those six ADR verification-context lines. Those edits are now
present but **unstaged**.

## Current Git State

As of this handoff:

### Staged files

```text
CLAUDE.md
docs/ops/SPRINT_2026_04_05_PLAN25_PROVIDER_GOVERNANCE.md
docs/ops/SPRINT_2026_04_05_PLAN26_OBSERVABILITY_CONFIG_TRUTHFULNESS.md
docs/plans/01_master-roadmap.md
docs/plans/25_provider-governance-and-shared-coordination.md
docs/plans/26_observability-config-truthfulness-and-test-isolation.md
docs/plans/CLAUDE.md
llm_client/cli/backfill.py
llm_client/cli/common.py
llm_client/io_log.py
tests/conftest.py
tests/test_io_log.py
```

### Unstaged files

```text
docs/adr/0003-warning-taxonomy.md
docs/adr/0007-observability-contract-boundary.md
docs/adr/0010-cross-project-runtime-substrate.md
docs/adr/0012-shared-data-plane-boundary.md
docs/adr/0013-stream-lifecycle-heartbeat-observability.md
docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md
```

## What The Next Agent Should Do

1. Stage the six ADR files:

```bash
cd /home/brian/worktrees/llm-client-observability-config-truthfulness
git add \
  docs/adr/0003-warning-taxonomy.md \
  docs/adr/0007-observability-contract-boundary.md \
  docs/adr/0010-cross-project-runtime-substrate.md \
  docs/adr/0012-shared-data-plane-boundary.md \
  docs/adr/0013-stream-lifecycle-heartbeat-observability.md \
  docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md
```

2. Re-run the same commit:

```bash
git commit -m "[Plan #26] Make observability config truthful after import"
```

3. If the hook blocks again, read the exact hook output and fix only the newly reported coupling or generation issue. Do not discard the staged work.

4. After commit succeeds, push the branch:

```bash
git push -u origin plan26-observability-config-truthfulness
```

5. Open a PR. Suggested title:

```text
[Plan #26] Make observability config truthful after import
```

6. Wait for CI. If green, merge through the normal repo path.

7. After merge:
- release the claim
- remove the worktree
- verify `origin/main` advanced

## Claim / Coordination State

Active claims list at handoff time:

- `merge-codex-transport-main-20260405` — stale unrelated claim, no worktree
- `plan26-observability-config-truthfulness` — this work, currently still claimed

Relevant command:

```bash
python /home/brian/projects/llm_client/scripts/meta/worktree-coordination/check_claims.py --list
```

Release command to run after merge/publish:

```bash
python /home/brian/projects/llm_client/scripts/meta/worktree-coordination/check_claims.py \
  --release \
  --id plan26-observability-config-truthfulness \
  --commit <merged-or-published-commit>
```

## Concerns / Uncertainties

1. I previously tried `python scripts/meta/generate_api_reference.py --write` manually and it appeared to hang without producing a diff. I documented that concern in the Plan 26 sprint tracker. The git commit hook got far enough to run doc-coupling checks, so do not assume the generator is permanently broken; re-evaluate based on actual hook behavior after the ADR files are staged.

2. The dirty main checkout at `/home/brian/projects/llm_client` is not trustworthy planning truth. Keep working in the clean Plan 26 worktree until merge/publish is done.

3. The local coordination claim ages printed oddly (`[NO WORKTREE]` despite the active worktree). I did not attempt to repair the claim subsystem itself. Treat that as non-blocking unless release fails.

## If You Need A Fast Resume Script

```bash
cd /home/brian/worktrees/llm-client-observability-config-truthfulness
git status --short --branch
git add \
  docs/adr/0003-warning-taxonomy.md \
  docs/adr/0007-observability-contract-boundary.md \
  docs/adr/0010-cross-project-runtime-substrate.md \
  docs/adr/0012-shared-data-plane-boundary.md \
  docs/adr/0013-stream-lifecycle-heartbeat-observability.md \
  docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md
git commit -m "[Plan #26] Make observability config truthful after import"
```
