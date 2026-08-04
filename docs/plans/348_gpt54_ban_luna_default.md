# Plan #348: GPT-5.4 Ban and Luna Default

**Status:** Complete (2026-08-04)
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** consistent ecosystem model selection

---

## Gap

**Current:** GPT-5.4 remains executable through raw, OpenRouter, and Codex
aliases and is still selected by maintained workflow defaults and registry
entries. The stated preference for GPT-5.6 Luna is advisory rather than
enforced.

**Target:** Every GPT-5.4 family route fails before dispatch, no packaged model
or maintained default selects it, and GPT-5.6 Luna replaces GPT-5.4 wherever
the same maintained execution surface can use Luna.

**Why:** A model prohibition must be a shared-client invariant. Documentation
alone cannot prevent old aliases and defaults from silently reviving it.

## References Reviewed

- `CLAUDE.md` and `llm_client/CLAUDE.md`
- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md`
- `docs/plans/110_provider-capabilities-opus-ban.md`
- `docs/plans/117_explicit_reasoning_policy.md`
- Existing hard-block, allowlist, registry, provider-policy, and workflow defaults

## Files Affected

- Shared model policy, provider policy, runtime hard-block, and static audit
- Packaged registry and maintained workflow/CLI defaults
- Focused policy, registry, routing, and workflow tests
- Active model-selection documentation and ADR

## Plan

1. Add an unconditional GPT-5.4 family hard block and static-audit rule.
2. Remove GPT-5.4 routes from the exact execution allowlist, capability table,
   provider aliases, and packaged registry.
3. Make Luna the shared execution default and replace GPT-5.4 workflow/CLI
   defaults with the Codex Luna route.
4. Update active docs and deterministic tests.
5. Run focused policy/workflow gates, then the feasible broader suite.

## Acceptance Criteria

- [x] Raw, provider-qualified, Codex, Mini, and Nano GPT-5.4 routes fail before dispatch.
- [x] Fallback chains containing GPT-5.4 fail before the primary executes.
- [x] No GPT-5.4 route remains allowlisted, configurable, packaged, or selected by a maintained default.
- [x] Luna is the shared default and the maintained Codex workflow default.
- [x] Static audit rejects GPT-5.4 despite ordinary override metadata.
- [x] Focused tests and repository validation pass.

## Verification Evidence

- Focused policy, routing, registry, client-ban, and workflow suite: 356 passed,
  23 skipped, 10 deselected.
- Broader offline suite excluding the unavailable legacy LangGraph checkpoint
  module: 2,020 passed, 47 skipped, 12 deselected. Five inherited failures
  remained in observability metadata, lifecycle ordering, coupling-policy
  fixtures, and a subprocess missing Pydantic; none touched this slice.
- Strict relationship validation, JSON parsing, changed production-file lint,
  and `git diff --check` passed.
