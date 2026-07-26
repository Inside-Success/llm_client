# Plan #96: Registration-Only Audit Fast Path

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Cross-project llm_client registration classification

---

## Gap

**Current:** `model_policy_audit --require-llm-client` checks direct provider
SDK usage, but it also runs the raw model-literal audit. Across the full
workspace that combined scan is too slow for the registration-enforcement
classification pass.

**Target:** Add `--registration-only`, a fast path that scans only production
Python files for direct provider SDK usage and honors
`llm_client_registration_exception`.

**Why:** We need an official, repeatable audit command for the registration
question before classifying and migrating projects.

---

## References Reviewed

- `llm_client/model_policy_audit.py` — scanner implementation and CLI.
- `tests/test_model_policy_audit.py` — scanner behavior tests.
- `docs/plans/95_require-llm-client-registration-audit.md` — prior
  registration-audit slice.
- `docs/guides/model-selection.md` — enforcement guidance and exception
  categories.

---

## Files Affected

- `llm_client/model_policy_audit.py` (modify)
- `tests/test_model_policy_audit.py` (modify)
- `docs/guides/model-selection.md` (modify)
- `docs/plans/CLAUDE.md` (modify)

---

## Plan

### Steps

1. Add `registration_only` to `scan_paths`.
2. Add CLI `--registration-only`; make it imply `--require-llm-client`.
3. In registration-only mode, skip non-Python files and skip raw model-literal
   scanning.
4. Add tests proving the mode flags provider SDK usage, suppresses raw literal
   findings, and keeps normal audit behavior unchanged.
5. Document the fast workspace audit command.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_model_policy_audit.py` | `test_registration_only_flags_provider_but_not_raw_model_literal` | Fast path only emits registration violations. |
| `tests/test_model_policy_audit.py` | `test_registration_only_skips_non_python_config_files` | Fast path ignores YAML/JSON model config. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_model_policy_audit.py` | Full scanner contract for this slice. |

---

## Acceptance Criteria

- [x] `--registration-only` exists and implies registration enforcement.
- [x] Raw model literal checks are skipped only in registration-only mode.
- [x] Non-Python files are skipped in registration-only mode.
- [x] Focused tests pass.

---

## Verification Evidence

- `pytest -q tests/test_model_policy_audit.py` — passed, 14 tests on 2026-07-25.
- `python -m py_compile llm_client/model_policy_audit.py` — passed.
- `python -m llm_client.model_policy_audit --registration-only tests/test_model_policy_audit.py` — passed, `MODEL POLICY OK`.
- `git diff --check` — passed.

---

## Notes

This is a performance/operability slice, not a migration slice. Cross-repo
classification starts after this command lands.
