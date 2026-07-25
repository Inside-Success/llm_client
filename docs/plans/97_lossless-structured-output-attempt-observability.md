# Plan #97: Lossless structured-output attempt observability

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** DIGIMON Plan #111 trace-bound recovery

---

## Gap

**Current:** `acall_llm_structured` logs one final `llm_calls` row. When an
internal attempt fails validation and a later attempt succeeds, only the final
row and `retry_count` survive. The failed raw response, typed validation issues,
and recovery decision are lost.

**Target:** Persist one ordered metadata-first record for every structured
generation attempt before normalization or retry. Return/query bounded typed
summaries, retain only hashes plus optional artifact references for raw content,
and preserve the existing final logical-call record.

**Why:** Eventual success and first-attempt validity are different facts.
Without attempt records, schema/provider diagnosis is impossible and consuming
traces can accidentally hide recovered defects.

## Requirements and boundaries

1. `llm_client` owns attempt classification, persistence, retry/fallback
   mechanics, and typed summaries.
2. The existing `llm_calls` row remains the logical-call/result record;
   `structured_attempts` is a child event table keyed by a stable logical call id.
3. Raw content is represented by SHA-256 plus nullable artifact reference; it is
   not inlined by default (ADRs 0007, 0012, 0014).
4. Attempt persistence occurs before parse/normalization decisions.
5. Persistence failure is not silently ignored on this integrity path.
6. Slice 1 covers native JSON-schema validation only. Instructor/Responses paths,
   normalization events, fallback consolidation, and DIGIMON projection remain
   later slices in DIGIMON Plan #111.

## Contract notebook

`docs/plans/supporting/97_structured_attempt_contract.ipynb` concretizes the
request, attempt, issue, and readback payloads before production implementation.

## Derived contracts

| Type | Producer → consumer | Required fields |
|---|---|---|
| `StructuredAttemptWrite` | structured runtime → observability | call id, trace/task, ordinal, model, execution path, schema hash, raw hash, outcome, failure class, issues, recovery decision |
| `StructuredValidationIssue` | Pydantic adapter → attempt write | location tuple, stable code, bounded message |
| `StructuredAttemptSummary` | observability query → caller/trace | attempt id/order, outcome/class, model/path, hashes/ref, issue count, recovery |

Allowed Slice-1 outcomes are `validated` and `validation_failed`; allowed
failure class is `missing_required` or `schema_validation`; allowed recovery is
`none`, `retry`, or `exhausted`. Unknown enum values fail validation.

## Files Affected

- `llm_client/observability/structured_attempts.py` (new typed write/query seam)
- `llm_client/observability/events.py` and `__init__.py` (thin exports)
- `llm_client/io_log.py` (compatibility persistence + schema migration)
- `llm_client/execution/structured_runtime.py` (native-schema attempt events)
- `tests/test_structured_attempts.py` and structured-runtime tests
- `docs/adr/0001-model-identity-v0.md`
- `docs/adr/0002-routing-config-precedence.md`
- `docs/adr/0003-warning-taxonomy.md`
- `docs/adr/0004-result-model-semantics-migration.md`
- `docs/adr/0007-observability-contract-boundary.md`
- `docs/adr/0009-long-thinking-background-polling.md`
- `docs/adr/0010-cross-project-runtime-substrate.md`
- `docs/adr/0012-shared-data-plane-boundary.md`
- `docs/adr/0013-stream-lifecycle-heartbeat-observability.md`
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md`
- generated API reference only if the public surface changes

## Plan

1. Run the notebook fixture and freeze its example payload/readback.
2. Write positive and negative persistence tests before production changes.
3. Add the typed attempt seam and child-table migration/readback.
4. Instrument the native-schema async and sync attempt closures before parse and
   after validation; preserve final result behavior.
5. Prove fail→success and first-attempt-success fixtures without network calls.
6. Audit for omission, raw-content leakage, enum drift, and swallowed writes.
7. Update coupled ADR verification context, run focused/full checks, commit/push.

## Required Tests

| Test | Evidence |
|---|---|
| valid attempt persists before result | positive control |
| missing-required attempt 0 + valid attempt 1 read back in order | core negative→recovery control |
| omitted attempt causes expected-count/binding assertion to fail | anti-papering control |
| raw body absent while hash/reference remain | data-boundary control |
| unknown outcome/failure/recovery enum rejected | taxonomy control |
| DB migration creates child table/indexes on an old DB | compatibility control |
| persistence error propagates on integrity path | fail-loud control |
| existing structured runtime suite | regression control |

## Acceptance Criteria

| ID | Criterion | Evidence target | Baseline grade |
|---|---|---|---|
| L97-1 | Every native-schema generation has an ordered child record. | source + automated test | D/doc |
| L97-2 | Failed attempt survives a successful retry. | DB readback test | B/observed current gap only |
| L97-3 | Raw body is not inlined; hash/ref are retained. | source + automated test | D/doc |
| L97-4 | Failure taxonomy and validation issues are typed. | source + automated test | D/doc |
| L97-5 | Persistence failure is visible. | automated negative control | D/doc |
| L97-6 | Existing final-call behavior remains compatible. | existing + new tests | C/existing fixture behavior |

Coverage: A=0, B=1, C=1, D=4, F=0. No hard gate is enabled until both signs
of each relevant control pass.

## Slice 1 progress — 2026-07-12

Implemented an append-only `structured_attempt_events` child ledger for native
JSON-schema sync and async calls. Each provider response emits `received` with a
raw SHA-256 before validation. Validation then emits `validated`, or
`validation_failed` with typed Pydantic issues followed by `recovery_decided`.
The persistence seam deliberately propagates database errors; explicit disabled
observability remains an intentional no-op.

Observed no-network controls:

- `pytest -q tests/test_structured_attempts.py --no-cov` → `5 passed`.
- Both sync and async missing-`rationale` fixtures produce exactly
  `received → validation_failed(missing_required) → recovery_decided(retry) →
  received → validated`.
- Metadata readback retains raw SHA-256 but exposes no `raw_content` field.
- Unknown taxonomy values fail Pydantic validation and a simulated database
  failure propagates.

Coverage after Slice 1: L97-1=A, L97-2=A, L97-3=A, L97-4=A, L97-5=A,
L97-6=A on the native-schema scope. Instructor, Responses API, and DIGIMON trace
projection remain explicitly outside this slice.

### Live-boundary correction

DIGIMON E2E trace `f3226e67597d4ac6b2d9f067c994253f` exposed a coverage
gap in the original fixtures: LiteLLM can raise `JSONSchemaValidationError`
*before* `completion`/`acompletion` returns, while retaining the generated body
on `exception.raw_response`. The original tests returned a provider response and
triggered Pydantic validation inside `llm_client`; they therefore did not cover
this dependency-owned validation boundary. Live histories showed attempt ordinal
2 succeeding with ordinals 0 and 1 absent.

The native sync and async closures now recognize the typed LiteLLM exception and
persist `received(raw hash) → validation_failed(schema_validation) →
recovery_decided` before the shared retry engine continues. New sync and async
fixtures raise the real exception type and prove exact `0 failure → 1 success`
readback. `tests/test_structured_attempts.py` now passes 7/7 and Ruff passes.

The earlier A grade for L97-1/L97-2 was premature because it was verified by a
post-return proxy. With the pre-return exception controls added, those grades are
restored for the two observed native-schema failure boundaries; additional
provider exception types remain subject to the explicitly bounded taxonomy.

Pre-landing review disposition:

- Fixed the accidental whole-file formatter expansion; the runtime diff is now
  111 additive lines rather than hundreds of unrelated whitespace changes.
- Added justified provider-mock annotations; the retry engine and real temporary
  SQLite database remain unmocked.
- Resolved the exact binding follow-up: every terminal structured `llm_calls`
  row now carries the same `logical_call_id` as its attempt events. Sync and
  async controls assert equality rather than joining ambiguously on task/trace.

## Failure handling

| Failure | Action |
|---|---|
| attempt table unavailable/migration failure | raise observability integrity error |
| raw artifact store unavailable | persist hash with null ref; do not claim raw replayability |
| unknown taxonomy value | Pydantic validation failure before write |
| write succeeds but readback count mismatches | binding failure; block completion |
| provider route cannot be proven | store null; never guess |

## Slice 3: pre-response transport integrity

DIGIMON trace
`digimon.query.dynamic_trace_gate.bbee180ec88645c5a29fe3a8c41c6749.agentic`
proved that the Slice-1 lifecycle was still partial: a provider timeout consumed
attempt ordinal 0, the retry succeeded at ordinal 1, and the child ledger began
at ordinal 1 because no response existed to trigger `received`. The final
`llm_calls.retry_count=1` and the child history therefore contradicted each
other.

This slice extends the native-schema lifecycle to begin before transport:

- success: `started -> received -> validated`;
- validation recovery: `started -> received -> validation_failed -> recovery_decided`;
- pre-response failure: `started -> execution_failed -> recovery_decided`.

`recovery_decided` is emitted from the shared retry kernel after its actual
retry decision. The structured runtime maps terminal per-model exhaustion to
`fallback` when another configured model remains, otherwise `exhausted`.
Attempt ordinals are logical-call global, not restarted for each fallback
model. Execution failures carry only a bounded typed class and exception type,
never an exception message or provider body.

Required deterministic controls:

1. sync and async timeout-then-success histories begin at ordinal zero;
2. non-retryable and retry-exhausted attempts end in `exhausted`;
3. model fallback uses increasing ordinals and records `fallback`;
4. validation retries retain exactly one recovery decision;
5. deleted/reordered/duplicate lifecycle events fail the consumer continuity
   checker;
6. existing v1 database rows remain readable after additive migration.

The preserved failed DIGIMON trace remains defect evidence. A fresh passing
trace counts only after these controls pass; rerunning until a no-timeout sample
appears is explicitly prohibited.

Implementation evidence (2026-07-13):

- 13 structured-attempt tests pass, including sync/async timeout-to-success,
  non-retryable cross-model fallback with contiguous ordinals, strict terminal
  failure, validation recovery, and additive old-table migration;
- 8 shared retry-kernel tests pass, including decision persistence before a
  user callback that raises;
- 93 structured-runtime/observability/replay tests and 251 client tests pass;
- the full repository suite passes 1,585 tests with 3 declared skips and 11
  deselections;
- Ruff passes on every changed runtime/test module (the legacy `io_log.py`
  facade retains unrelated pre-existing lint debt).

Repository-wide `make check` remains red before tests because clean
`origin/main` and this branch both report the same 315 pre-existing Ruff
violations (LLM-VERIFY-009). That inherited red gate is not counted as evidence
for or against this slice.

Consumer verification remains open: DIGIMON's independent SQLite projection
and continuity checker must migrate to the v2 event shape, pass lifecycle
mutation controls, and bind a fresh real trace before L97-1/L97-2 can be called
closed across the project boundary.

### Post-validation boundary correction — 2026-07-13

An adversarial source audit found a second continuity defect after the Slice 3
transport repair. The native-schema retry closure records `validated` as soon as
Pydantic parsing succeeds, but then performs usage/cost extraction, result
construction, `after_call`, cache persistence, and final call logging inside the
same retry boundary. A retryable exception from any of those local finalization
steps can therefore issue another provider request after the ordinal is already
terminal, without a `recovery_decided` event.

The correction preserves the semantic boundary rather than moving the marker:

- `validated` terminates provider-attempt retry and model fallback;
- post-validation finalization failures remain visible on the logical-call error
  path and retain their original public cause;
- another provider generation is forbidden because it cannot repair a local
  hook, cache, cost-normalization, or observability failure.

Required negative controls configure both retry and model fallback, raise from
post-validation finalization, and prove exactly one sync/async provider call with
the terminal child history `started -> received -> validated`. Existing
pre-validation retry/fallback histories must remain unchanged. Investigation:
`docs/investigations/2026-07-13-postvalidation-structured-attempt-integrity.md`.

Verification evidence:

- all four new controls failed before the repair (the two public paths each made
  four provider calls), then passed with exactly one provider call;
- attempt/retry-kernel suite: 25 passed;
- wider structured/observability/replay suite: 174 passed;
- full repository suite: 1,636 passed, 3 declared skips, 11 deselections;
- Ruff passes on changed code/tests. Strict mypy reports no diagnostic in the
  changed runtime modules, but the import-following command remains red on
  unrelated baseline errors recorded as LLM-VERIFY-015.

## References Reviewed

- DIGIMON Plan #111
- `llm_client/execution/structured_runtime.py`
- `llm_client/io_log.py`
- `llm_client/observability/events.py`, `query.py`, `replay.py`
- `tests/test_io_log.py`, `tests/test_client.py`
- ADRs 0001, 0002, 0003, 0004, 0007, 0009, 0010, 0012, 0013, 0014
- OpenRouter structured-output documentation
