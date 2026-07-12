# Plan #97: Lossless structured-output attempt observability

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** DIGIMON Plan #110 trace-bound recovery

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
   later slices in DIGIMON Plan #110.

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

## Failure handling

| Failure | Action |
|---|---|
| attempt table unavailable/migration failure | raise observability integrity error |
| raw artifact store unavailable | persist hash with null ref; do not claim raw replayability |
| unknown taxonomy value | Pydantic validation failure before write |
| write succeeds but readback count mismatches | binding failure; block completion |
| provider route cannot be proven | store null; never guess |

## References Reviewed

- DIGIMON Plan #110
- `llm_client/execution/structured_runtime.py`
- `llm_client/io_log.py`
- `llm_client/observability/events.py`, `query.py`, `replay.py`
- `tests/test_io_log.py`, `tests/test_client.py`
- ADRs 0001, 0002, 0003, 0004, 0007, 0009, 0010, 0012, 0013, 0014
- OpenRouter structured-output documentation
