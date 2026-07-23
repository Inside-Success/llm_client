# Plan #109: Billing-Identity Observability

**Status:** ⏸️ Deferred
**Type:** implementation
**Priority:** Medium
**Blocked By:** A funded provider account for a live reconciliation control
**Blocks:** Exact reconciliation of provider-dashboard spend by model, route,
and project

---

## Gap

**Current:** `llm_calls` records model, project, task, trace, token use,
reported cost, retries, cache status, and selected execution path.  One shared
database can therefore reconstruct local model spend, but it cannot assign a
call to the exact provider billing account or credential that paid for it.

**Target:** Every provider-backed call carries a non-secret, stable
`billing_identity` suitable for grouping and reconciliation.  The value is a
configured public credential label when one exists, otherwise a keyed
fingerprint of the selected credential.  Plaintext credentials must never be
persisted.

**Why:** Multiple projects and direct/OpenRouter routes currently write into a
shared ledger.  Without billing identity, the local ledger cannot be reconciled
with a particular OpenRouter account dashboard's "Other" row.

## References Reviewed

- `llm_client/io_log.py:730-1055` — `llm_calls` schema and additive migration
- `docs/plans/97_lossless-structured-output-attempt-observability.md` —
  observability integrity and raw-data retention boundary
- `docs/guides/model-selection.md:85-118` — route identity and observed-model
  decision records
- `CLAUDE.md` — observability-first, fail-loud, and plan requirements

## Files Affected

- `llm_client/io_log.py` — additive `billing_identity` column, index, write
  and query projections
- provider-routing/runtime modules — select and pass an identity without
  retaining a credential
- `tests/test_io_log.py` and provider-runtime tests — persistence, migration,
  and non-leakage controls
- `docs/guides/advanced-usage.md` — operator configuration and reconciliation
  guidance
- generated API reference only if a public query surface changes

## Plan

1. Define a typed `BillingIdentity` contract: provider, non-secret label or
   stable fingerprint, and identity source.
2. Add an additive SQLite migration and index; old databases remain readable.
3. Derive the identity once from the selected route/credential and attach it
   to every final call and relevant attempt event.
4. Add a cost-by-billing-identity query/report alongside the existing cost
   reports.
5. Prove a live, read-only provider-dashboard reconciliation for one funded
   account and a bounded time window.

## Required Tests

| Test | What it verifies |
| --- | --- |
| old database migrates additively | Existing local observability remains readable |
| two configured credential identities group separately | Dashboard reconciliation can distinguish routes |
| plaintext credential is absent from SQLite, snapshots, logs, and errors | Observability does not create a secret leak |
| missing identity fails loudly or records explicit `unknown` | No silent attribution claim |
| report totals group back to existing overall total | Accounting remains consistent |

## Acceptance Criteria

- [ ] Every provider-backed call has a queryable billing identity.
- [ ] No plaintext credential reaches persistence or diagnostics.
- [ ] Existing databases migrate without loss.
- [ ] A funded-account live control reconciles a dashboard time window to the
  ledger, including the provider dashboard's residual/"Other" amount.

## Deferral Note

Documented 2026-07-22 after a model-spend investigation found a shared-ledger
total of $105.35 while the relevant OpenRouter dashboard showed $80.00.  This
is a trace-attribution gap, not a lack of call tracing.  Do not implement this
as a substitute for routing the retired GPT-5.5 and GPT-5.4 Mini models away
from active workloads.
