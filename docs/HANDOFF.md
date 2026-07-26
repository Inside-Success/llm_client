# Handoff: `llm_client` runtime follow-up relevant to DIGIMON

Updated: 2026-07-25
Canonical revision checked: `5a3369e`

## Current Posture

- Personal `main` is clean and synchronized with `origin/main`.
- Plan `#91` is implemented in the shared runtime; only a governed downstream
  DIGIMON replay remains.
- Plan `#94` still owns the undefined task-configured technical-output ceiling.
- Plans `#121`, `#122`, `#124`, and `#334` are merged and await the downstream
  acceptance named in the plan index.
- Plan `#35` remains intentionally blocked on the optional Phase 6 decision.

## Relevant Finished Work

- Provider exhaustion classification is materially better than it was during the
  failed DIGIMON rebuild attempts.
- Routing now suppresses recently exhausted models instead of re-probing them
  on every chunk.
- Long retry windows now fail over rather than sleeping for hours inside a
  single batch call.
- Tool decorator metadata now includes:
  - `goal`
  - `complexity`
  - `routing hints`

The new tool metadata is implemented and tested, but downstream consumers have
not yet been broadly updated to exploit it.

## Remaining Work

### 1. Verify Plan `#91` in DIGIMON

Plan: `docs/plans/91_pending_atom_submit_churn_requires_todo_progress.md`

Canonical implementation commits:

- `0fda376`
- `1c10156`
- `f349655`
- `db6a6c2`

Focused tests pass: pending-atom submit retries are suppressed until TODO
progress occurs, and the runtime no longer emits forced-final acceptance for
this family. The remaining acceptance item is a governed DIGIMON replay on the
original unresolved-hop failure family.

### 2. The new tool-routing metadata is landed but not yet widely consumed

Commits:

- `2308465` goal metadata
- `3739578` complexity/routing metadata

What is still unfinished:

- deciding which downstream planners/runtimes should use the new metadata first;
- validating that the metadata helps routing choices instead of just enriching
  the registry surface;
- documenting the intended consumer contract more explicitly if these fields are
  now considered stable substrate.

This is not a blocker for DIGIMON recovery, but it is open follow-through.

### 3. DIGIMON rebuild resilience is improved, not fully proved

The retry/failover code is in much better shape, but one thing still lacks a
full end-to-end proof:

- a successful complete long GraphRAG rebuild under real provider pressure,
  with quotas rotating and fallback legs degrading in different ways.

The code changes are real. The remaining uncertainty is operational proof, not
obvious missing implementation.

## Recommended Next Steps

1. Run the Plan `#91` governed downstream replay in DIGIMON; do not add an
   app-local duplicate of the shared controller behavior.
2. Bound Plan `#94`'s output-ceiling contract before assigning implementation.
3. After the next real long-running DIGIMON rebuild or benchmark batch, review
   whether any remaining provider failure mode still belongs in shared runtime.
4. Decide whether `goal` / `complexity` / routing metadata should be treated as
   stable planner contract or as experimental substrate hints.

## Read First

1. `CLAUDE.md`
2. `docs/plans/01_master-roadmap.md`
3. `docs/plans/CLAUDE.md`
4. `docs/plans/91_pending_atom_submit_churn_requires_todo_progress.md`
5. `llm_client/tools/decorator.py`
6. `tests/test_tool_decorator.py`

## Verification State

The tool-metadata commits already include test coverage in
`tests/test_tool_decorator.py`. This handoff update itself is documentation-only
and does not change code behavior.

## Bottom Line

`llm_client` is not the main blocker anymore. The critical GraphRAG quota and
retry fixes are already landed. The two unfinished truths are:

1. Plan `#91` still needs to land if DIGIMON’s submit-churn family stays live.
2. The new tool-routing metadata exists, but its real consumer contract is not
   yet fully operationalized.
