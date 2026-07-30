# Plan #340: Codex GPT-5.6 Luna Subscription Route

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Cybernetic Influence subscription-backed live simulation

---

## Gap

**Current:** The Codex CLI accepts `gpt-5.6-luna` with ChatGPT authentication,
but the shared exact-model allowlist stops `codex/gpt-5.6-luna` before the
existing Codex structured-output adapter can dispatch it.

**Target:** Admit the exact Codex Luna route with explicit low, medium, or high
reasoning, preserve subscription billing and isolated CLI transport, and prove
the Cybernetic Influence participant and narrator schemas before that project
advertises the route.

**Why:** The user wants the simulator to consume included Codex subscription
usage instead of OpenRouter, starting with Luna at medium reasoning and without
silent fallback or automatic model escalation.

---

## References Reviewed

- `CLAUDE.md` — repository workflow and shared-runtime boundary.
- `docs/adr/0001-model-identity-v0.md` and
  `docs/adr/0004-result-model-semantics-migration.md` — requested and executed
  model identity.
- `docs/adr/0002-routing-config-precedence.md` — explicit caller policy wins.
- `docs/adr/0003-warning-taxonomy.md` — failures remain failures.
- `docs/adr/0009-long-thinking-background-polling.md` — effort-dependent
  execution behavior.
- `docs/adr/0010-cross-project-runtime-substrate.md` — shared provider/agent
  transport ownership.
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` — retained
  call identity and replay semantics.
- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md` and
  `docs/plans/117_explicit_reasoning_policy.md` — exact allowlisting and
  explicit effort.
- `llm_client/sdk/agents_codex.py` — current CLI structured-output and isolated
  Codex-home implementation.
- Current OpenAI Codex manual, observed 2026-07-29 — `gpt-5.6-luna` is a
  subscription model intended for clear, repeatable, high-volume work.

---

## Files Affected

- `llm_client/core/model_execution_policy.py`
- `llm_client/route_certification.py`
- `llm_client/route_certification_runtime.py`
- `llm_client/__init__.py`
- `tests/test_model_execution_policy.py`
- `tests/test_codex_luna_subscription.py`
- `docs/guides/codex-integration.md`
- `docs/plans/CLAUDE.md`
- `docs/plans/340_codex_luna_subscription_route.md`

---

## Plan

1. Add only `codex/gpt-5.6-luna` to the exact execution allowlist and bind its
   explicit reasoning contract.
2. Add deterministic policy and adapter-command tests proving medium effort and
   the exact underlying model reach Codex CLI without provider fallback.
3. Run one real ChatGPT-authenticated structured-output call through the shared
   client and retain its trace.
4. Let Cybernetic Influence own schema-specific advertisement and deployment
   certification; do not make Luna a shared task-tier default.

---

## Required Tests

| Test | What it proves |
|---|---|
| focused model-policy tests | Luna is admitted only with justification and a supported explicit effort |
| focused Codex adapter tests | `codex/gpt-5.6-luna` becomes `--model gpt-5.6-luna` and medium effort reaches the CLI |
| real structured probe | ChatGPT-authenticated Luna returns locally valid structured output with subscription billing |

---

## Acceptance Criteria

- [x] The exact model and medium effort pass shared pre-dispatch policy.
- [x] Unsupported or omitted effort still fails before dispatch.
- [x] No fallback model or OpenRouter route is introduced.
- [x] A real structured Luna result validates and records subscription billing.
- [x] Focused tests, formatting checks, and documentation checks pass.

## Verification Evidence

- `tests/test_model_execution_policy.py` plus the existing Codex adapter suite:
  167 passed; the focused Luna transport test also passes.
- Real trace
  `llm_client/plan339/codex-luna/structured-probe/20260729` returned the typed
  value `{"status":"ok","total":42}` through `codex_cli` with requested,
  resolved, and executed identity `codex/gpt-5.6-luna`.
- The retained observability row records `subscription_included`, observed
  cost `$0`, 12,645 input tokens, and 19 output tokens.
- The real call set `codex_transport="cli"`, medium reasoning, read-only
  sandboxing, an isolated MCP-free Codex home, and no fallback model.
- A downstream Coordination schema exposed a provider rejection of Pydantic's
  discriminated `oneOf` union. The Codex projector now performs the same
  provably-disjoint literal-union projection used by strict OpenAI-compatible
  routes; 441 focused client, structured-runtime, and agent tests pass.
- The Qualitative Coding research-report schema exposed the same union with
  defaulted discriminator fields. Strict normalization now runs before the
  disjoint-union projection, so those discriminator fields participate in the
  proof; the exact report schema projects to supported `anyOf` and a live Luna
  call returned validated output.

## Non-Claims

- This does not establish Luna as the best model for every workload.
- This does not make Codex subscription auth a general OpenAI API credential.
- This does not make Luna a global task-tier default.
- Cybernetic Influence must still certify its exact participant and narrator
  contracts before displaying the route as runnable.
