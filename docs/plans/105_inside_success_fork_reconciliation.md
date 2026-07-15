# Plan #105: Personal and Inside Success Fork Reconciliation

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** A single current `llm_client` line for personal and Inside Success consumers

---

## Goal

Preserve the user's success criterion: **"make sure the inside success version
and my personal version on brianmills2718 github are up to date."**

The personal repository is the canonical code line. Reconcile both repositories'
unique history into that line, adapt the useful Inside Success runtime fixes to
the currently declared dependencies, prove the combined result, then advance
both GitHub `main` branches to the same verified commit without rewriting
history.

## Gap

**Current:** Personal `main` contains 58 commits absent from Inside Success,
including Plans 97-104. Inside Success contains five commits absent from the
personal repository, including one substantive concurrency/cost patch. The
local personal checkout also contains three merge commits not on either remote.
The fork patch's tests import `instructor.v2`, which is unavailable under the
declared `instructor>=1.14.0` dependency and the installed 1.14.5 environment;
its cost validator also rejects a legitimate provider-reported `$0` call.

**Target:** Both GitHub `main` branches identify the same verified commit,
personal Plans 97-104 and all unique ancestry remain reachable, the reviewed
fork functionality works against the supported dependency range, and the local
personal branch is not silently discarded.

**Why:** Consumers currently see different behavior depending on which GitHub
organization or sibling checkout they use. A silent overwrite would either
lose current personal work or retain an unexecutable fork patch.

## Modality and Boundaries

This is a deductive migration: Git ancestry, dependency compatibility, cost
ordering, and SQLite serialization have deterministic consequences and can be
verified without exploratory product work.

- `BrianMills2718/llm_client` owns the canonical implementation.
- `Inside-Success/llm_client` is synchronized to the verified canonical commit.
- The dirty `inside-success` application checkout is a consumer and is not
  modified by this plan.
- No force push, reset, rebase of shared history, dependency-major upgrade, or
  public API redesign is in scope.
- Organization-specific README simplification is not adopted as canonical
  content; its commit remains reachable through reconciled ancestry.

## Runtime Contracts

1. Cost source precedence is provider-reported value, then LiteLLM-computed
   value, then configured fallback estimate.
2. A provider-reported cost is a finite real number greater than or equal to
   zero. Booleans, strings, mocks, negative values, NaN, and infinities are not
   cost evidence.
3. Sync and async Instructor client construction is serialized through the
   public `instructor.from_litellm` seam. Production code and tests must not
   require version-private `instructor.v2` modules.
4. Reads on the shared SQLite connection use the same lock as writes so
   concurrent budget queries and call logging cannot overlap statements.
5. Model identity, replay, raw-artifact, stream lifecycle, and observability
   payload contracts remain unchanged.

## References Reviewed

- Inside Success commit `7950d80` and its focused source/tests — the substantive
  fork functionality and original failure evidence.
- Personal `origin/main` at `3f46adb` — the current canonical Plans 97-104 line.
- Local personal `main` at `d26b57e` — three additional merge commits to retain.
- `pyproject.toml` — declares `instructor>=1.14.0`; environment has 1.14.5.
- `docs/adr/0001-model-identity-v0.md` — requested/resolved identity contract.
- `docs/adr/0004-result-model-semantics-migration.md` — fixed result identity.
- `docs/adr/0007-observability-contract-boundary.md` — canonical query boundary.
- `docs/adr/0009-long-thinking-background-polling.md` — Responses constraints.
- `docs/adr/0012-shared-data-plane-boundary.md` — bounded metadata ownership.
- `docs/adr/0013-stream-lifecycle-heartbeat-observability.md` — lifecycle separation.
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` — replay invariants.

## Files Affected

- `ISSUES.md` (modify)
- `docs/plans/105_inside_success_fork_reconciliation.md` (create)
- `docs/plans/CLAUDE.md` (modify)
- `CHANGELOG.md` (modify)
- `docs/API_REFERENCE.html` (regenerate)
- `docs/API_REFERENCE.md` (regenerate)
- `docs/adr/0001-model-identity-v0.md` (reverify)
- `docs/adr/0002-routing-config-precedence.md` (reverify)
- `docs/adr/0003-warning-taxonomy.md` (reverify)
- `docs/adr/0004-result-model-semantics-migration.md` (reverify)
- `docs/adr/0007-observability-contract-boundary.md` (reverify)
- `docs/adr/0009-long-thinking-background-polling.md` (reverify)
- `docs/adr/0010-cross-project-runtime-substrate.md` (reverify)
- `docs/adr/0012-shared-data-plane-boundary.md` (reverify)
- `docs/adr/0013-stream-lifecycle-heartbeat-observability.md` (reverify)
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` (reverify)
- `llm_client/execution/responses_runtime.py` (modify)
- `llm_client/execution/structured_runtime.py` (modify)
- `llm_client/observability/query.py` (modify)
- `llm_client/utils/cost_utils.py` (modify)
- `tests/test_cost_source_ordering.py` (create)
- `tests/test_io_log.py` (modify)
- `tests/test_structured_thread_safety.py` (create)

## Plan

1. Commit this plan, issue record, and index before runtime changes.
2. Join the clean canonical branch to both unique histories using explicit
   ancestry-preserving merge commits whose trees retain the reviewed personal
   canonical content.
3. Add the fork functionality through the contracts above, starting with
   negative controls for zero/non-finite cost and dependency-private imports.
4. Run focused cost, concurrency, SQLite, structured-runtime, Responses, and
   observability tests; then the repository's proportional verification suite.
5. Record exact evidence, mark the plan complete, and push the branch.
6. Advance personal `main`, then Inside Success `main`, by normal non-force
   updates. Fetch and re-check ancestry immediately before each update.

## Failure Modes and Next Actions

| Failure | Next action |
|---|---|
| Either remote advances during work | Fetch, review the new delta, and merge it before any push. |
| The ancestry-only merge changes the worktree | Stop; inspect strategy invocation before continuing. |
| Focused test imports `instructor.v2` | Replace the test with a public-seam concurrency control; do not widen dependency requirements. |
| SQLite stress test flakes | Increase deterministic overlap/read-write repetitions and inspect actual errors; do not add retries. |
| Either `main` rejects a normal update | Leave the verified branch pushed and report the exact protection/authentication blocker; never force. |
| Combined full suite exposes a baseline failure | Separate pre-existing baseline from Plan 105 regressions and record exact evidence. |

## Required Tests

### New and Changed Tests

| Test File | Test | What It Verifies |
|---|---|---|
| `tests/test_cost_source_ordering.py` | provider/computed/fallback cases | Identical precedence in Completions and Responses, including valid zero and invalid non-finite inputs. |
| `tests/test_structured_thread_safety.py` | serialized public construction | Concurrent sync/async construction does not overlap and works without private Instructor modules. |
| `tests/test_io_log.py` | concurrent reads and writes | Shared SQLite statements serialize without interface errors. |

### Existing Tests

| Test Pattern | Why |
|---|---|
| `tests/test_responses_runtime.py` | Responses cost and long-running semantics remain intact. |
| `tests/test_structured*.py` | Native/fallback structured behavior and identity remain intact. |
| `tests/test_io_log.py tests/test_observability*.py` | Compatibility and query contracts remain intact. |

## Acceptance Criteria and Evidence

| Criterion | Evidence class | Passing grade |
|---|---|---|
| All personal, local, and Inside Success unique commits remain ancestors of the reconciled commit. | test (`git merge-base --is-ancestor`) | A |
| Provider-reported finite cost `>= 0` wins in both runtime paths; invalid shapes fall through. | source + tests | A |
| Concurrent Instructor construction uses only the supported public API. | source + tests under installed 1.14.5 | A |
| Concurrent SQLite reads/writes complete without errors. | source + stress regression test | A |
| Focused and proportional repository verification pass, with any baseline failure explicitly separated. | test | A |
| Personal and Inside Success GitHub `main` resolve to the same verified commit after a final fetch. | observed remote refs | B |
| No force push or dirty application-checkout mutation occurs. | command/history/status audit | B |

## Rollback

Revert the Plan 105 integration commit(s) with new commits on each affected
remote. Do not rewrite shared history. The pre-reconciliation refs remain
reachable through merge parents and GitHub history.
