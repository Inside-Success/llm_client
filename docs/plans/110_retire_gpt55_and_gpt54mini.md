# Plan #110: Retire GPT-5.5 and GPT-5.4 Mini

**Status:** 🚧 In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Spend-control migration in Greer, DIGIMON, Process Tracing, and
Inside Success

---

## Gap

**Current:** GPT-5.5 and GPT-5.4 Mini remain selectable in the registry and
are not runtime-blocked.  A July 22 spend audit found $19.45 of GPT-5.5 calls,
principally Greer semantic proposal/carrier/review work, and $8.21 of GPT-5.4
Mini calls, principally Process Tracing and DIGIMON work.

**Target:** Both retired model families fail loudly in every `llm_client`
execution path and in the cross-project literal audit.  The registry no longer
advertises them.  Active callers move to an explicit GPT-5.6 route appropriate
to their task; historical evidence remains unchanged.

**Why:** Artificial Analysis' current comparison reports GPT-5.6 Sol Medium
above GPT-5.5 Medium at the same listed price, while GPT-5.4 Mini's current
general score is below the available GPT-5.6 Luna/Terra alternatives.  Keeping
them as defaults or fallbacks creates predictable spend without a supported
capability rationale.

## References Reviewed

- `llm_client/execution/call_contracts.py:605-770` — hard-block mechanism
- `llm_client/model_policy_audit.py:50-350` — literal denylist audit
- `llm_client/data/default_model_registry.json:77-420` — active registry
- `docs/plans/94_model-tier-taxonomy-and-fable-ban.md` — prior ban pattern
- `onto-canon6/investigations/2026-07-22-model-spend-and-retirement.md` —
  local spend and route evidence

## Files Affected

- `llm_client/execution/call_contracts.py`
- `llm_client/model_policy_audit.py`
- `llm_client/data/default_model_registry.json`
- `tests/test_client.py`, `tests/test_model_policy_audit.py`, and registry tests
- `docs/guides/model-selection.md`
- downstream active-default patches in Greer, DIGIMON, and Inside Success

## Plan

1. Add exact family patterns to the shared runtime hard-block and literal
   policy-audit denylist, with actionable GPT-5.6 replacements.
2. Remove the retired routes from the packaged registry.
3. Add deterministic tests for bare and provider-prefixed rejection, audit
   rejection despite generic override metadata, and absence from the registry.
4. Replace live defaults and fallbacks in the downstream callers; do not
   rewrite historical receipts or evidence.
5. Run focused tests and a no-network import/configuration regression for each
   migrated caller.  A live task-quality comparison is a later gate, not a
   reason to keep an obsolete default active.

## Acceptance Criteria

- [ ] Bare and provider-prefixed GPT-5.5/GPT-5.4 Mini fail before provider
  dispatch.
- [ ] Neither family is present in the selectable registry.
- [ ] Cross-project literal audit rejects either family even with ordinary
  override acceptance.
- [ ] Known live defaults/fallbacks are migrated; historical artifacts stay
  intact.
- [ ] Focused tests pass.

