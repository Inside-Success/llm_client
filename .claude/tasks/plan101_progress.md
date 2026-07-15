# Plan 101 Progress

## Mission

Expose a provider-free, typed, fail-loud read of the authoritative terminal
structured attempt persisted by `llm_client`. This unblocks onto-canon6 Plan
0141 without authorizing a model call or trusting caller-authored lifecycle
events.

## Acceptance Criteria

- A successful structured call can be read by trace/logical-call identity with
  requested and resolved model, selected attempt, evidence hashes, lineage, and
  an authority digest.
- Missing, nonterminal, incomplete, ambiguous, mismatched, or tampered records
  fail loud.
- Public structured-attempt events without the matching durable terminal call
  row cannot produce an authoritative receipt.
- All proof is provider-free through typed fixtures and repository tests.
- Public API documentation and plan status match the shipped contract.

## Current Slice

1. [done] Audit current persistence schemas and lifecycle writers.
2. [done] Freeze the plan and negative controls.
3. [done] Add failing tests, then the smallest typed reader.
4. [in progress] Run repository-wide verification before integration.

## Focused Evidence

- 100 selected-attempt, public-surface, structured-attempt, and replay tests pass.
- The real public structured runtime produces a readable joined receipt with a
  mocked provider transport and real temporary SQLite persistence.
- Ruff on changed canonical modules/tests and `git diff --check` pass.
- No provider call was made.
