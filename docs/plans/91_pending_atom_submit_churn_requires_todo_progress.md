# Plan #91: Pending-Atom Submit Churn Requires TODO Progress

**Status:** Implemented; downstream verification pending
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** DIGIMON Phase 2 controller anti-churn verification

## Gap

The shared MCP turn runtime currently treats repeated `submit_answer`
rejections with `reason_code=pending_atoms` plus
`requires_forced_terminal_path=true` as a signal to force final answer
acceptance. In DIGIMON this produces a misleading path:

- unresolved semantic-plan atoms remain pending,
- normal submit was never accepted,
- but the loop escalates into forced-final submission anyway.

That is the wrong shared policy for this failure family. Pending atoms indicate
the controller still owes semantic progress, not that the runtime should accept
an ungrounded final answer.

## Target

When `submit_answer` is rejected for pending atoms, the shared runtime should:

1. require new evidence before retry when requested,
2. require TODO-state progress before retry,
3. suppress repeated submit attempts until those conditions are satisfied,
4. avoid converting this state directly into `CONTROL_CHURN_THRESHOLD_EXCEEDED`
   forced-final acceptance.

## Acceptance

- [x] Focused agent tests show repeated pending-atom submit retries are suppressed
  until TODO progress occurs.
- [x] The runtime no longer emits `SUBMIT_FORCED_ACCEPT_FORCED_FINAL` for this
  specific rejection family.
- [x] Existing submit-evidence gating tests still pass.
- [ ] A governed DIGIMON replay confirms the shared behavior on the original
  unresolved-hop failure family.

## Canonical implementation evidence

The shared implementation is on `main` through these commits:

- `0fda376` — gate pending-atom submit churn on TODO progress;
- `1c10156` — preserve repair guidance across control suppression;
- `f349655` — stop repeated suppressed submit churn earlier;
- `db6a6c2` — land the TODO-progress behavior on mainline.

Focused verification on `main` at `5a3369e`:

```text
pytest -q tests/test_mcp_agent.py \
  -k 'pending_atom_submit_rejections_require_todo_progress or repeated_submit_suppressions_without_todo_progress'
2 passed, 107 deselected
```

The remaining work is downstream acceptance, not another shared-runtime
implementation.

## Files

- `llm_client/agent/mcp_turn_tools.py`
- `llm_client/agent/mcp_turn_outcomes.py`
- `llm_client/agent/mcp_turn_execution.py`
- `tests/test_mcp_agent.py`
