# Plan #351: Cross-Project Model Experiment Records

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Reusable evidence-based model routing across projects

---

## Gap

**Current:** `llm_client` records experiment runs and items in shared
observability, but its guide shows an obsolete API and does not define the
minimum durable evidence needed to reuse a model comparison outside the project
that ran it. Curated `runs/` artifacts have no shared record shape.

**Target:** Correct the experiment API guide, define a small versioned JSON
record for cross-project model comparisons, and retain one real comparison as
the reference instance. Bulk datasets and task-specific outputs remain with
their owning projects and are referenced by logical URI plus digest.

**Why:** A model recommendation is only reusable when future consumers can
recover the exact task, route, reasoning effort, dataset, contracts, retries,
latency, cost scope, artifacts, decision, and claim limits. A prose conclusion
without those fields invites false generalization.

---

## References Reviewed

- `llm_client/observability/experiments.py` — authoritative experiment lifecycle API.
- `docs/guides/experiment-observability.md` — existing, stale adoption guide.
- `docs/guides/model-selection.md` — model decision-card guidance.
- `docs/adr/0012-shared-data-plane-boundary.md` — metadata and stable-reference ownership.
- `docs/ECOSYSTEM_TOP_DOWN_ARCHITECTURE.md` — `llm_client` versus `prompt_eval` ownership.
- `runs/README.md` — curated evidence policy.
- `docs/plans/347_openrouter_response_cache_controls.md` — existing exact-response cache boundary.
- Process Tracing Plan 038 Luna and DeepSeek retained artifacts — first reference record.
- `CLAUDE.md` and `docs/plans/CLAUDE.md` — repository conventions.

---

## Files Affected

- `docs/guides/experiment-observability.md` (modify)
- `docs/schemas/model-experiment-record-v1.schema.json` (create)
- `runs/README.md` (modify)
- `runs/model-experiments/process-tracing-revolution-adjudication-2026-08-12/record.json` (create)
- `docs/plans/CLAUDE.md` (modify)
- `docs/plans/351_cross_project_model_experiment_records.md` (create)

---

## Plan

1. Correct examples to the current keyword-only experiment API.
2. Define the minimum cross-project record and explicit evidence boundaries.
3. Retain the signed-off Process Tracing comparison without copying its bulk corpus.
4. Validate the example against the schema and verify every referenced digest.

---

## Required Tests

| Check | What It Verifies |
|---|---|
| JSON Schema validation of the retained record | The reference instance satisfies the reusable contract. |
| `sha256sum -c` against owning artifacts | Stable references identify the exact retained evidence. |
| Focused documentation inspection | Examples match the current keyword-only API. |

---

## Acceptance Criteria

- [x] The guide uses the current public API.
- [x] The record separates observed billing from time-sensitive list pricing.
- [x] Retry-inclusive cost, latency, token, cache, and contract outcomes are explicit.
- [x] The decision and non-claims are first-class fields.
- [x] Bulk task data remains with its owner and is referenced by digest.
- [x] The retained record validates and all artifact digests match.

---

## Notes

This plan does not change the SQLite schema or move evaluation aggregation from
`prompt_eval`. The committed JSON record is a portable decision card; shared
SQLite remains the query surface for run/item telemetry.
