# Plan #112: Provider Usage-Detail Observability

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Exact hidden-reasoning attribution in downstream cost experiments

---

## Frame

Preserve bounded, provider-reported token-usage details through the runtime and
SQLite observability boundary so downstream experiments can distinguish visible
completion tokens from reasoning and cache accounting when the provider exposes
those facts.

## Gap

**Current:** Completion and Responses paths normalize only aggregate prompt,
completion, and total token counts (plus partial prompt-cache counts). SQLite
persists only the three aggregates. OpenRouter can return
`completion_tokens_details.reasoning_tokens`, but the client currently discards
it.

**Target:** Runtime results retain normalized prompt/completion detail mappings,
including top-level convenience counts for reasoning and cache tokens. SQLite
stores queryable scalar counts plus the bounded details JSON. Existing databases
migrate additively and old callers remain compatible.

**Why:** A downstream qualitative-coding run observed 72.7% more billed
completion tokens than were present in visible JSON. Aggregate counts prove a
cost discrepancy, not its cause. The shared runtime should preserve provider
accounting facts rather than force consumers to infer hidden reasoning.

## Modality Diagnosis

Deductive. Provider-reported token counts are runtime facts. This plan does not
infer missing historical details, classify model quality, or store provider
reasoning content.

## Semantic Boundary

- Preserve bounded numeric token-detail metadata, not hidden reasoning text.
- Do not relabel an aggregate residual as reasoning.
- Do not retrofit historical rows whose detail payload was discarded.
- Do not change model selection or reasoning policy.

## Risk-Ordered Slices

### Slice 1 — Preserve runtime usage details

Add failing Completion and Responses tests for nested prompt/completion token
details, then normalize those mappings without changing existing aggregate keys.

**Done when:** reasoning, cached, and cache-creation counts survive in result
usage; missing and model-object details remain compatible.

### Slice 2 — Persist and migrate accounting details

Add SQLite columns for `reasoning_tokens`, `cached_tokens`,
`cache_creation_tokens`, and `usage_details`; populate them for live and JSONL
import paths and migrate existing databases idempotently.

**Done when:** fresh and legacy databases expose the columns, exact values are
queryable, bounded details round-trip, and old aggregate-only records still log.

### Slice 3 — Adversarial audit and cleanup

Attack malformed/non-numeric details, callback parity, raw-content leakage,
schema migration, and JSONL import. Update the observability ADR and concern
register only as required by findings.

**Done when:** focused runtime/observability tests and affected lint gates pass,
the provider response does not leak reasoning content into usage metadata, and
all findings are fixed or registered.

## Files Affected

- `llm_client/utils/cost_utils.py`
- `llm_client/execution/responses_runtime.py`
- `llm_client/io_log.py`
- `llm_client/observability/query.py`
- `llm_client/litellm_observer_callback.py`
- `tests/test_client.py`
- `tests/test_model_identity_contract.py`
- `tests/test_io_log.py`
- `tests/test_litellm_observer_callback.py`
- `docs/adr/0007-observability-contract-boundary.md`
- `docs/plans/CLAUDE.md`
- this plan

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What it verifies |
|---|---|---|
| `tests/test_client.py` | `test_extracts_bounded_provider_usage_details` | Completion details and scalar reasoning/cache counts survive without content |
| `tests/test_model_identity_contract.py` | `test_responses_usage_preserves_bounded_token_details` | Responses output reasoning and input cache details survive |
| `tests/test_io_log.py` | `test_writes_provider_usage_details_to_sqlite` | Fresh SQLite values and query API round-trip |
| `tests/test_io_log.py` | `test_migrate_adds_trace_id` | Legacy schemas receive additive detail columns |
| `tests/test_io_log.py` | `test_import_calls_preserves_usage_details` | Detail accounting survives JSONL import |
| `tests/test_litellm_observer_callback.py` | `test_standard_logging_object_preserves_bounded_usage_details` | Catch-all callback retains counts without content |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|---|---|
| `tests/test_client.py` | Completion runtime compatibility |
| `tests/test_model_identity_contract.py` | Completion/Responses identity and extraction compatibility |
| `tests/test_io_log.py` | JSONL, SQLite, migration, and query compatibility |
| `tests/test_structured_runtime.py` | Structured Completion usage compatibility |
| `tests/test_text_runtime.py` | Text Completion usage compatibility |
| `tests/test_cost_source_ordering.py` | Provider billing precedence remains unchanged |

## Acceptance Criteria

- [ ] Provider-reported reasoning tokens are retained when present.
- [ ] Prompt cache and cache-creation details remain compatible.
- [ ] SQLite stores queryable scalar counts and bounded token-detail JSON.
- [ ] Existing databases migrate additively and idempotently.
- [ ] Historical aggregate-only records remain unchanged and valid.
- [ ] No reasoning text or arbitrary response body is persisted as usage detail.
- [ ] Focused tests, changed-surface lint, relationship validation, and adversarial audit pass.

## Rollback

Remove the additive runtime detail keys and SQLite columns/writes. Existing
databases may retain unused nullable columns; aggregate accounting remains
compatible.
