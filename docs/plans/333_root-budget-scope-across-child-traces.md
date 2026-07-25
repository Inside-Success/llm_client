# Plan #333: root budget scope across child traces

**Status:** Complete (2026-07-25)
**Type:** implementation  <!-- implementation | design -->
**Priority:** High
**Blocked By:** None
**Blocks:** Plan #334 concurrent root-budget reservations

---

## Gap

**Current:** Plan #332 blocks an exact trace when settled spend plus its
declared reservation reaches `max_budget`. Distinct descendants such as
`query/planner` and `query/operator` therefore still receive independent
budgets.

**Target:** Public calls may declare a `budget_scope_trace_id`. The client
validates that it is the call trace or a slash-delimited ancestor, then applies
existing settled-cost and reservation checks to that scope's trace-prefix
aggregate. Bounded scoped calls are sequential within one process: a second
in-flight child fails loudly until the first reaches a terminal boundary.
Omitting the field preserves exact-trace behavior.

**Why:** One user-visible request can cap combined planner, operator, rerank,
and synthesis cost without each project maintaining a parallel cost ledger.

---

## References Reviewed

> **REQUIRED:** Cite specific code/docs reviewed before planning.

- `llm_client/core/client.py` - public entrypoints
- `llm_client/execution/call_contracts.py` - Plan #332 reservation check
- `llm_client/execution/call_wrappers.py` - shared public-call envelope
- `llm_client/observability/query.py` - existing exact and prefix cost queries
- `llm_client/execution/*_runtime.py` - internal call paths that repeat checks
- `CLAUDE.md` - project conventions

**Landscape disposition:** inline / extend. Reuse the maintained trace-prefix
cost query and Plan #332 reservation semantics; no new ledger or provider path.

---

## Files Affected

> **REQUIRED:** Declare upfront what files will be touched.

- `llm_client/core/client.py` (modify)
- `llm_client/execution/call_contracts.py` (modify)
- `llm_client/execution/call_wrappers.py` and runtime paths (modify)
- focused call-contract and text-runtime tests (modify)
- generated API reference and this plan (modify)

---

## Plan

### Steps

1. Define scope validation and aggregate cost lookup while retaining
   reservation and exact-trace defaults.
2. Thread the resolved scope through public text/structured and streaming
   paths without forwarding it to model providers.
3. Add root-plus-child, reservation, malformed-scope, concurrent-child, and
   provider-stripping checks. Regenerate the API reference.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_call_contracts.py` | `test_check_budget_aggregates_root_scope_and_descendants` | A child call is charged to the root scope |
| `tests/test_call_contracts.py` | `test_budget_scope_must_be_a_nonempty_trace_ancestor` | Unrelated scopes fail before dispatch |
| `tests/test_call_contracts.py` | `test_budget_scope_rejects_concurrent_child_dispatch_and_releases` | A second active child cannot race the shared settled-cost check |
| `tests/test_text_runtime.py` | `test_text_runtime_keeps_budget_scope_out_of_provider_kwargs` | Scope remains client-only |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_call_contracts.py` | Existing exact-trace reservation behavior stays intact |
| `tests/test_client_lifecycle.py` | Public call lifecycle remains intact |

---

## Acceptance Criteria

- [ ] A root and descendant aggregate settled spend plus the declared reservation.
- [ ] Malformed or unrelated scopes fail loudly before dispatch.
- [ ] A bounded scope cannot dispatch concurrent children in one process.
- [ ] Omitted scope preserves exact-trace behavior; zero remains unlimited.
- [ ] Scope metadata is not forwarded to a provider.
- [ ] Focused tests and generated API reference pass.

---

## Notes

**Non-goals:** This does not coordinate budgets across processes or predict an
in-flight provider call's final cost; the scope guard is explicitly a
process-local sequential admission control. It does not alter provider fallback
policy or wire DIGIMON before shared-contract review.

## Completion Evidence

- Personal upstream PR #103 merged as `2b627ff`.
- Plan gate: 33 tests passed.
- Focused runtime tests: 27 passed.
- Focused Ruff, generated API reference, and `git diff --check` passed.
- Plan #334 is the explicit successor for concurrent and cross-process scope
  admission. The earlier reference to “DIGIMON Plan #36” was incorrect:
  DIGIMON Plan #36 owns assertion-node SQLite import, not budget enforcement.
