# Plan #119: Runtime Cost Governance

**Status:** In Progress
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** Trustworthy real-time cost control and cross-provider spend analysis

## Outcome

An operator receives a truthful budget status with each `llm_client` result and
can group recorded spend by billing semantics. DeepSeek V4 Flash remains the
sole no-justification execution default; all other routes remain fail-closed
behind the existing exact allowlist and recorded `model_justification`.

This does **not** claim provider-invoice reconciliation. That remains Plan 109:
it requires a non-secret billing identity and a funded provider-dashboard
control.

## Current / Target

| Target behavior | Current state | Owning boundary | Acceptance |
| --- | --- | --- | --- |
| Non-default route is explicit | Existing runtime allowlist requires `model_justification` | `model_execution_policy` | Unchanged focused policy tests pass |
| Trace budget is visible before it is exhausted | Only a pre-dispatch hard stop after prior spend reaches the cap | call contract / returned result | Threshold warning is returned before dispatch and after a completed call |
| Zero is not confused with unknown | `cost_source` and `billing_mode` exist, but reporting collapses their meaning | observability / cost CLI | Report separates priced, free/subscription, and unavailable accounting |
| Operator can identify cost drivers | CLI only groups project/model/caller/task/trace | cost CLI | CLI groups by model, project, task, billing mode, and cost source |

## Scope and invariants

- No provider call, retry, model substitution, or silent fallback is added.
- `max_budget=0` remains explicit unlimited mode and reports that fact; it has
  no threshold warning.
- Thresholds are deterministic percentages of the declared trace budget.
- A provider response whose price cannot be determined is `unknown`, never
  represented as a free call merely because its numeric cost is zero.
- No credential values or credential fingerprints are stored in this plan;
  Plan 109 owns billing identity.

## Risk-ordered slices

1. Add typed budget-status evaluation and return warning records at configured
   trace thresholds (50%, 80%, 100%); retain the existing hard block at 100%.
   Cover text, structured, and stream entry paths with deterministic tests.
2. Tighten cost-source/billing-mode normalization and extend `llm-client cost`
   reporting with accounting-state totals and explicit unpriced counts.
3. Add a `cost watch` operator surface backed by persisted alerts/rate windows,
   after its notification channel and cross-process SQLite behavior are proven.
4. Extend Plan 109 with a non-secret billing identity and a funded account
   reconciliation control. This is intentionally not fabricated from local
   model strings.

## Required checks

- `pytest -q tests/test_call_contracts.py tests/test_result_finalization.py tests/test_model_execution_policy.py`
- Focused text, structured, stream, observability, and cost-CLI tests added by
  the corresponding slice.
- `python scripts/meta/check_plan_tests.py --plan 119`
- `git diff --check`

## Sources consulted

- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md`
- Plans 109, 115, 116, and 117
- `llm_client/core/model_execution_policy.py`
- `llm_client/execution/call_contracts.py`
- `llm_client/io_log.py`, `llm_client/observability/query.py`, and
  `llm_client/cli/cost.py`

## Landscape disposition

Inline / extend: the repository already has a typed execution policy, a
cross-provider ledger, cost provenance fields, and a CLI. This plan adds the
missing enforcement and presentation at those boundaries rather than adding a
second telemetry system.
