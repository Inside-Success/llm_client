# Plan 101 Progress

## Mission

Expose a provider-free, typed, fail-loud trusted-process receipt for the
terminal structured attempt persisted by `llm_client`. This unblocks
onto-canon6 Plan 0141 without authorizing a model call or claiming independent
provider attestation.

## Acceptance Criteria

- A successful structured call can be read by its returned logical-call identity with
  requested and resolved model, selected attempt, evidence hashes, lineage, and
  a receipt integrity digest.
- Missing, nonterminal, incomplete, ambiguous, mismatched, or tampered records
  fail loud.
- Public structured-attempt events without the matching durable terminal call
  row cannot produce a runtime receipt.
- All proof is provider-free through typed fixtures and repository tests.
- Public API documentation and plan status match the shipped contract.

## Current Slice

1. [done] Audit current persistence schemas and lifecycle writers.
2. [done] Freeze the plan and negative controls.
3. [done] Add failing tests, then the smallest typed reader.
4. [in progress] Independent review and integration; full tests are complete.

## Focused Evidence

- 65 receipt, public-surface, structured-attempt, boundary-schema, and result
  metadata tests pass after the trust-boundary repair.
- The real public structured runtime produces a readable joined receipt with a
  mocked provider transport and real temporary SQLite persistence.
- Ruff on changed canonical modules/tests and `git diff --check` pass.
- Full repository suite: 1,667 passed, 3 skipped, 11 deselected.
- New module: strict mypy passes with imported-module diagnostics silenced.
- Repository baseline remains red at 309 Ruff and 210 mypy findings; recorded
  in `ISSUES.md` and not changed in this plan.
- No provider call was made.

## Independent Review Resolution

Exact commit `385dafe` was rejected because its name overstated independent
authority and its lifecycle checker accepted contradictory recovery/model
histories. The repair:

- renames the contract to trusted-process `RuntimeSelectedAttemptReceipt`;
- disclaims provider attestation, source authentication, signatures, and
  hostile-process security;
- returns `logical_call_id` on actual sync/async `LLMCallResult` objects;
- requires consumers to pin that exact ID rather than discover by trace;
- enforces per-attempt model identity plus retry/fallback/exhaustion semantics;
- covers real public sync/async single, retry, and fallback paths without a
  provider call.
