# Post-validation structured-attempt integrity

**Date:** 2026-07-13
**Plan:** #97
**Status:** Root cause confirmed; repair verified

## Question

Can a native structured-output call issue another provider request after its
response has already been recorded as `validated`, and if so, where should the
retry boundary end?

## Investigation atoms

| Atom | Finding | Evidence |
|---|---|---|
| P1 | A post-validation exception can currently re-enter the retry kernel. | `structured_runtime.py` records `validated` before usage/cost extraction, result construction, `after_call`, cache persistence, and final call logging; all remain inside the retry closure. |
| P2 | The child ledger then has no recovery decision for the retried attempt. | `attempt_validated=True` suppresses `execution_failed`, so the ordinal is never added to `_recovery_pending`; the retry kernel still retries retryable exceptions. |
| P3 | Model fallback can duplicate the same defect. | `run_sync_with_fallback` and `run_async_with_fallback` currently fall back on every exception from a model execution closure. |
| P4 | Moving `validated` later would make the ledger continuous but misclassify local finalization as provider execution and may repeat an already-valid generation. | The failure occurs after schema validation and can originate in a hook, cache, or observability sink; another provider generation cannot repair those failures. |
| P5 | The truthful boundary is: schema validation terminates provider-attempt recovery; local finalization fails loud without retry or fallback. | This preserves the meaning of `validated`, avoids duplicate provider work, and leaves the final logical-call error record responsible for the local failure. |

## Assumptions and controls

| Assumption | Confidence | Control |
|---|---|---|
| `validated` denotes typed response validity, not successful completion of every caller-side side effect. | High | Existing event name and Plan #97 contract; add an explicit plan statement. |
| A failing post-call hook is representative of the entire post-validation finalization region. | High | It executes after result construction and before cache/log completion; add both sync and async public-path tests. |
| Retrying or switching models cannot repair a deterministic local finalization failure. | High | Assert one provider call despite retry and fallback being configured. |
| The private boundary error must not leak as the public cause. | High | Unwrap before terminal logging and `wrap_error`. |

## Intended invariant

For a native-schema ordinal:

- before `validated`, a retry/fallback decision must be represented by
  `recovery_decided`;
- after `validated`, the provider attempt is terminal and no retry or model
  fallback is permitted;
- failures in post-validation finalization propagate through the logical-call
  error path with their original cause.

## Verification required

1. A sync `after_call` timeout with retries and fallback configured invokes the
   provider exactly once and ends at `started -> received -> validated`.
2. The async path has the identical invariant.
3. Existing timeout, validation-repair, fallback, and terminal-failure histories
   remain unchanged.
4. The retry/fallback kernel tests cover the new non-fallback predicate.

## Verification result

- The four new negative controls failed before implementation: the fallback
  kernel rejected `should_fallback`, while sync and async public calls each made
  four provider requests (one retry on each of two models).
- After repair, all four pass and each public path makes exactly one provider
  request with `started -> received -> validated`.
- Focused attempt/kernel suite: 25 passed.
- Wider structured/observability/replay suite: 174 passed.
- Full repository suite: 1,636 passed, 3 declared skips, 11 deselections.
- Ruff passes on all changed code/test files. Strict mypy reports no diagnostic
  in either changed runtime module, but its import-following invocation remains
  red on unrelated baseline errors recorded as LLM-VERIFY-015.
