# Plan #346: Production LLM Call Receipt

**Status:** In Progress  
**Type:** implementation  
**Priority:** Critical  
**Blocked By:** None  
**Blocks:** Team-Brains Hermes observability adapter

---

## Gap

**Current:** `llm_client` durably records model calls, but consumers copy
subsets of the ledger into project-specific telemetry shapes.

**Target:** Expose one typed, queryable receipt for each terminal call so
second-brain services can reference shared execution evidence. Other runtimes
can map actual per-call evidence into the same contract without claiming that
session aggregates are call-level facts.

**Why:** One truthful contract removes duplicated telemetry logic while keeping
runtime-specific collection at the runtime boundary.

---

## References Reviewed

- `CLAUDE.md` — public-surface, planning, and generated-doc rules.
- `docs/adr/0007-observability-contract-boundary.md` — canonical observability
  ownership and bounded metadata.
- `docs/adr/0010-cross-project-runtime-substrate.md` — shared runtime ownership.
- `docs/adr/0012-shared-data-plane-boundary.md` — hashes and references rather
  than copied bulk content.
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` — request
  fingerprints are distinct from prompt hashes and receipts are not provider
  attestation.

---

## Files Affected

- `llm_client/observability/call_receipts.py` (create)
- `llm_client/observability/query.py`
- `llm_client/observability/__init__.py`
- `llm_client/__init__.py`
- `tests/test_call_receipts.py` (create)
- `tests/test_public_surface.py`
- `docs/API_REFERENCE.md` and `docs/API_REFERENCE.html` (generated)
- `docs/plans/CLAUDE.md`

---

## Plan

1. Define a frozen receipt that distinguishes provider calls from session
   aggregates and requires explicit reasons for missing terminal timing.
2. Project existing SQLite terminal rows into receipts by trace or logical call
   identity without copying prompts, responses, or exception text.
3. Export the contract and query from the public package and regenerate API
   documentation.
4. Add a Team-Brains adapter in a dependent change after this public contract
   is available from the company package pin.

---

## Required Tests

| Test | What It Verifies |
|---|---|
| terminal timing contract | missing timing fails unless the gap is explicit |
| terminal-row projection | tokens, timing, cost, hashes, and status round-trip |
| negative content control | prompt and response text never enter the receipt |
| public surface | receipt type and query remain importable |

---

## Acceptance Criteria

- [x] Typed receipt and exact-identity query exist.
- [x] Missing observations are explicit and never fabricated.
- [x] Request fingerprints are not mislabeled as prompt hashes.
- [x] Receipts contain no prompt, response, or dynamic exception text.
- [x] Focused tests, lint, generated API docs, and diff checks pass.
- [ ] Team-Brains maps Hermes per-call evidence and labels session-only evidence
      as aggregate.

## Non-Goals

- A second ledger, dashboard, provider router, or agent-tracing platform.
- Reconstructing observations absent from historical records.
- Rewriting Hermes internals.
