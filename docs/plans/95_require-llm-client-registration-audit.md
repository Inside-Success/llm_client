# Plan #95: Require llm_client Registration Audit

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Cross-project enforcement of shared LLM routing

---

## Gap

**Current:** `model_policy_audit` can find raw model literals and unaccepted
model overrides, but it cannot distinguish a project that routes LLM work
through `llm_client` from a project that calls provider SDKs directly without
shared budgets, observability, model policy, or Fable/default enforcement.

**Target:** Add an opt-in audit mode that flags direct provider SDK usage in
production Python code unless the file records an explicit registration
exception.

**Why:** The ecosystem can require production/shared LLM calls to pass through
`llm_client` only if the violation is visible and machine-checkable before it
becomes a hard CI gate.

---

## References Reviewed

- `CLAUDE.md` — shared-infrastructure rule: all LLM work through `llm_client`.
- `llm_client/llm_client/model_policy_audit.py` — current audit scanner.
- `tests/test_model_policy_audit.py` — existing audit contract tests.
- `docs/guides/model-selection.md` — tier-vs-agent-lane distinction.
- `docs/plans/94_model-tier-taxonomy-and-fable-ban.md` — prior model-policy slice.

---

## Files Affected

- `llm_client/model_policy_audit.py` (modify)
- `tests/test_model_policy_audit.py` (modify)
- `docs/guides/model-selection.md` (modify)
- `docs/plans/CLAUDE.md` (modify)

---

## Plan

### Steps

1. Add `scan_paths(..., require_llm_client=True)` and CLI
   `--require-llm-client`.
2. Flag direct provider SDK imports/calls in production Python files.
3. Allow explicit file-level `llm_client_registration_exception` records with
   `accepted_by`, `reason`, and `category`.
4. Keep raw model literal scanning behavior unchanged.
5. Document the staged enforcement policy and exception categories.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_model_policy_audit.py` | `test_require_llm_client_flags_direct_provider_import` | Direct OpenAI import is a registration violation only in opt-in mode. |
| `tests/test_model_policy_audit.py` | `test_require_llm_client_flags_direct_litellm_call` | Direct LiteLLM completion call is a registration violation. |
| `tests/test_model_policy_audit.py` | `test_require_llm_client_allows_llm_client_usage` | Proper `llm_client` calls are allowed. |
| `tests/test_model_policy_audit.py` | `test_require_llm_client_allows_registration_exception` | Explicit exception metadata suppresses registration violations. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_model_policy_audit.py` | Audit scanner behavior is the full blast radius. |

---

## Acceptance Criteria

- [x] `--require-llm-client` flags direct provider SDK usage.
- [x] Default audit behavior remains backward compatible.
- [x] Explicit registration exceptions are supported and provenance-bearing.
- [x] Docs explain production enforcement and exception categories.
- [x] Focused tests pass.

---

## Verification Evidence

- `pytest -q tests/test_model_policy_audit.py` — passed, 14 tests on 2026-07-25.
- `python -m py_compile llm_client/model_policy_audit.py` — passed.
- `python -m llm_client.model_policy_audit --require-llm-client tests/test_model_policy_audit.py` — passed, `MODEL POLICY OK`.
- `git diff --check` — passed.

---

## Notes

This is visibility-first. Do not auto-migrate projects in this slice. Do not
ban benchmark fixtures, provider SDK demos, or `llm_client` internals; require
exception metadata instead so the debt is reviewable.
