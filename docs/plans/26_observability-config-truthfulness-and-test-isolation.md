# Plan #26: Observability Config Truthfulness and Test Isolation

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** trustworthy env-driven observability overrides and lock-safe test verification across downstream consumers

---

## Gap

**Current:** `llm_client.io_log` now honors `LLM_CLIENT_LOG_ENABLED=0` even when
tests set it after module import, but the rest of the observability config
surface still mixes import-time state with runtime truth:

- `LLM_CLIENT_DATA_ROOT` and `LLM_CLIENT_DB_PATH` are still cached eagerly at import time,
- callers and CLI helpers can still read stale `_db_path` / `_data_root` values,
- tests rely primarily on "logging disabled" rather than also isolating the
  observability destination away from the shared global SQLite DB.

That means a future regression can still reintroduce shared DB contention even
if the original `LOG_ENABLED` bug stays fixed.

**Target:** env-backed observability configuration is truthful after import by
default, explicit `configure()` overrides still work, DB connections follow the
effective path instead of a stale cached one, and the test harness always uses
temporary observability destinations even when logging is re-enabled.

**Why:** observability is shared infrastructure. It must respect runtime policy
changes and protect verification from shared-state interference instead of
depending on one fragile disable switch.

---

## References Reviewed

- `CLAUDE.md` - repo workflow and active sprint rules
- `docs/plans/01_master-roadmap.md` - maintenance-mode execution order
- `docs/plans/21_runtime_durability_followups_from_grounded_research.md` - prior SQLite durability work
- `docs/plans/25_provider-governance-and-shared-coordination.md` - recently completed shared-infra slice
- `docs/ops/SPRINT_2026_04_05_PLAN25_PROVIDER_GOVERNANCE.md` - concrete symptom that triggered this follow-up
- `llm_client/io_log.py` - current observability config and DB lifecycle
- `llm_client/cli/common.py` - CLI DB path resolution
- `llm_client/cli/backfill.py` - JSONL scanning against data-root state
- `tests/conftest.py` - suite-level observability isolation policy
- `tests/test_io_log.py` - logger and DB-path regression surface
- `tests/test_client.py::TestAsyncResponsesAPIRouting::test_async_gpt5_routes_to_aresponses` - previously blocked verification slice

---

## Pre-Made Decisions

1. Do not add a new observability backend. Stay on the SQLite + JSONL design.
2. Keep `configure()` as the explicit runtime override path; env vars remain the
   dynamic default path when no explicit override is set.
3. Treat direct writes to the shared global DB during tests as a harness bug,
   not as acceptable incidental behavior.
4. Keep the public observability API stable. This slice is about config
   truthfulness and isolation, not a surface redesign.
5. Prefer small helper functions over another configuration class; the goal is
   reliable behavior, not abstraction for its own sake.

---

## Files Affected

- `docs/plans/26_observability-config-truthfulness-and-test-isolation.md` (create)
- `docs/plans/CLAUDE.md` (modify)
- `docs/plans/01_master-roadmap.md` (modify)
- `docs/ops/SPRINT_2026_04_05_PLAN26_OBSERVABILITY_CONFIG_TRUTHFULNESS.md` (create)
- `CLAUDE.md` (modify)
- `llm_client/io_log.py` (modify)
- `llm_client/cli/common.py` (modify)
- `llm_client/cli/backfill.py` (modify)
- `tests/conftest.py` (modify)
- `tests/test_io_log.py` (modify)
- supporting ADR verification-context lines if read-gate coupling requires them (modify as needed)

---

## Plan

### Step 1: Make observability config resolution truthful after import

- separate explicit runtime overrides from env/default resolution
- add helpers for effective data-root and DB-path lookup
- keep project detection truthful when env/project overrides change after import

### Step 2: Make DB connection ownership follow the effective path

- ensure the SQLite singleton reconnects when the effective DB path changes
- keep explicit `configure(db_path=...)` behavior intact
- avoid stale connections tied to a previous env/config state

### Step 3: Harden the test harness against shared-state leakage

- isolate tests to temporary observability env vars in `tests/conftest.py`
- keep logging disabled by default during tests
- prove accidental re-enable still writes only to temp state, not the shared global DB

### Step 4: Verify on the previously blocked async routing slice

- rerun the bounded async routing test that previously hit `database is locked`
- verify the fix works because the harness no longer reaches the shared DB path

---

## Required Tests

### New Tests (TDD / Required)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_io_log.py` | `test_data_root_env_change_after_import_is_respected` | JSONL writes follow a new env-backed data root when no explicit override is set |
| `tests/test_io_log.py` | `test_db_path_env_change_after_import_reopens_connection` | SQLite writes follow a new env-backed DB path and do not keep using a stale connection |
| `tests/test_io_log.py` | `test_cli_get_db_path_uses_effective_runtime_config` | CLI helpers read the effective DB path rather than a stale cached global |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `pytest tests/test_io_log.py -q` | observability logging and DB lifecycle stay correct |
| `pytest tests/test_client.py::TestAsyncResponsesAPIRouting::test_async_gpt5_routes_to_aresponses -q --timeout=30` | previously blocked async-routing lane remains green |
| `pytest tests/test_client.py -k "codex or routing" -q` | broader routing verification stays unblocked |
| `git diff --check` | docs/code changes remain syntactically clean |

---

## Acceptance Criteria

- [x] env-backed data-root and DB-path settings are truthful after import unless explicit overrides are set
- [x] the active SQLite connection follows the effective DB path rather than a stale cached path
- [x] test suites isolate observability state away from the shared global DB by default
- [x] the previously blocked async routing slice passes without touching the shared global DB
- [x] roadmap, plan index, and sprint tracker reflect this as the active follow-up instead of leaving it as undocumented fallout

---

## Failure Modes

| Failure Mode | Detection | Response |
|--------------|-----------|----------|
| Dynamic config lookup breaks existing explicit overrides | `tests/test_io_log.py` override/configure assertions fail | keep override variables authoritative and narrow env dynamics to the non-overridden case |
| DB path changes cause connection churn or leaked handles | DB-path regression test fails or file-lock behavior regresses | track the connection path explicitly and close/reopen only when the effective path changes |
| Test isolation hides real observability regressions | logger tests stop asserting file/DB writes meaningfully | keep dedicated logger tests with explicit enablement and temp-state assertions |

---

## Notes

- This is shared-infrastructure hardening, not app-local test cleanup.
- The success condition is not just "no lock right now"; it is "config truth is
  stable enough that the same lock class does not recur from import-order drift."
- Local verification on 2026-04-05:
  - `pytest tests/test_io_log.py -q`
  - `pytest tests/test_client.py::TestAsyncResponsesAPIRouting::test_async_gpt5_routes_to_aresponses -q --timeout=30`
  - `pytest tests/test_client.py -k "codex or routing" -q`
