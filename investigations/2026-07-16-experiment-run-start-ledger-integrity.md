# Experiment Run Start Ledger Integrity

**Date:** 2026-07-16
**Scope:** Shared llm_client experiment-run start persistence used by Plan 0141
execution traces. No provider dispatch, model call, or Plan 0141 semantic result
was changed.

## Questions

| ID | Question | Status |
|---|---|---|
| A1 | Can one reused run_id leave contradictory start evidence? | Answered |
| A2 | Is the defect in a project runner or the shared substrate? | Answered |
| A3 | Does the repair prevent concurrent duplicate starts? | Answered |

## Evidence

### A1: Reproduction

Against llm_client main before this change, two sequential calls to
start_run(dataset="probe", model="model", run_id="same-run") both returned
"same-run". The JSONL experiment log contained two run_start records while
SQLite's unique experiment_runs.run_id index contained one row.

### A2: Root cause

llm_client/observability/experiments.py::start_run appended the JSONL run_start
record before inserting the canonical SQLite row, then caught and suppressed
every database exception. A duplicate-key error therefore looked like success
to the caller after a second JSONL record had already been emitted.

### A3: Repair and verification

The repaired path inserts the canonical SQLite row through the existing
io_log._run_db_write serialization helper before starting timers or appending
JSONL. A duplicate run_id now raises sqlite3.IntegrityError; no second JSONL
record is emitted.

tests/test_experiment_log.py::TestStartRun::test_concurrent_duplicate_run_id_fails_before_second_jsonl_start
starts two threads on one run_id and proves exactly one success, one duplicate
error, one SQLite row, and one JSONL start record.

Focused verification passed:

- 66 passed, 1 skipped: tests/test_experiment_log.py
- 4 passed: tests/test_io_log_compat.py
- focused Ruff and strict mypy on the changed module and test
- strict relationships validation

The repository-wide make check did not reach tests because its existing Ruff
step reports 307 unrelated violations across agent, SDK, and test modules. This
repair removes the two unused imports in this touched module but does not claim
the repository-wide lint gate is green.

## Impact

This is experiment-ledger integrity, not an authorization or cost control. It
prevents a run schedule from appearing to have two independently started
attempts when the canonical run store only accepted one. Existing Plan 0141
D5/D6 records remain historical evidence; they are not rewritten by this repair.

## Assumptions Register

| # | Assumption | Confidence | Verification | Round | Status |
|---|---|---|---|---|---|
| 1 | SQLite is the canonical experiment-run index. | High | Schema declares run_id TEXT NOT NULL UNIQUE; ADR 0010 assigns shared run persistence to llm_client. | 1 | Confirmed |
| 2 | Serializing this insert with the existing helper is compatible with the shared connection. | High | Concurrent regression test passes using _run_db_write. | 1 | Confirmed |
| 3 | JSONL append failures remain best-effort behavior. | High | Existing behavior retained after canonical insert; this repair changes only duplicate-run handling. | 1 | Confirmed |

## Remaining Boundary

The fix makes one local shared ledger reject duplicate starts. It does not by
itself decide which future Plan 0141 coordinates should replace already-consumed
zero-item or terminal attempts; that is schedule authority in the Plan 0141
lane.
