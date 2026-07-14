# Plan 99 Exact Replay Independent Acceptance

**Decision:** ACCEPT

**Review date:** 2026-07-13

**Implementation commit:** `5ed2a1e9ee4209d8e300e2fb1d6cfaf59622cc3a`

**Implementation tree:** `6f0e0ca0fd5ce663c074f75033ddeb1d35cd3523`

**Reviewed branch:** `origin/plan-99-exact-replay-repair`

**Reviewer:** independent read-only agent `/root/execution_plan_audit`

## Scope

This is the fresh exact-commit review required by Plan 99 after two rejected
repairs. It evaluates the effective execution-policy replay contract used by
downstream governed callers. It does not authorize a provider call or approve
onto-canon6 Plan 0141 by itself.

The reviewer verified that the worktree was clean, `HEAD` and the remote branch
both resolved to the implementation commit above, and the tree matched the
recorded tree before executing the review.

## Evidence

| Gate | Result |
|---|---|
| Focused replay, structured-runtime, and helper suite | 61 passed |
| Mandatory `check_plan_tests.py --plan 99` gate | 375 passed |
| Independent adversarial subset | 35 passed |
| Scoped Ruff | passed |
| `git diff --check` | passed |
| Worktree integrity after review | clean |

The four public APIs, synchronous and asynchronous text and structured calls,
round-tripped real timeout-disabled snapshots through their public runtimes.
Original and replayed snapshots were identical, and provider-visible kwargs
other than observability metadata were identical.

The reviewer independently confirmed that replay rejects these cases before
provider dispatch:

- non-JSON-native or lossy values, including paths, tuples, sets, non-finite
  floats, invalid mapping keys, opaque objects, and legacy/current diagnostic
  substitutions;
- false-empty `unsupported_keys` metadata;
- persisted fingerprint drift and malformed envelopes;
- v2-to-v1 downgrade and cross-kind reinterpretation;
- missing controls, structured schema drift, and lost text execution mode.

## Decision Basis

No blocking correctness finding remained. The implementation satisfies Plan
99's exact effective retry, fallback, cache, timeout, structured-mode, and text
execution-mode replay requirement at the public runtime boundary.

Strict mypy still reports 10 findings in `observability/replay.py`. This is
existing repository debt and is one fewer than the pre-repair baseline; the
accepted implementation introduced no observed type-check regression.

## Downstream Binding Rule

Downstream plans must pin both this exact implementation commit/tree and the
later evidence-only commit containing this review record. They must verify that
the replay runtime source did not change between those commits. Plan 0141 must
then pass its own pinned dependency and combined-contract review before any
model/provider call is authorized.
