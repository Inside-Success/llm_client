# Plan #115: Allowed-Model Execution Policy

**Status:** Complete
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** Safe cross-project model-policy enforcement

---

## Gap

**Current:** `llm_client` blocks a few model families but otherwise accepts any
model string. Consumer projects can therefore select an unreviewed or
outclassed model, and a non-default choice has no required justification in the
replay snapshot or routing trace.

**Target:** Add one exact shared allowlist. DeepSeek V4 Flash is the default
model and requires no justification. Every other allowed model requires a
non-empty caller justification that survives call snapshots, replay, and
routing traces. Unknown and GPT-5 Mini-family routes fail before dispatch.
Twin opts into enforcement immediately; other consumers stay in explicit
compatibility mode until audited and migrated.

**Why:** An allowlist fails closed when providers add aliases or projects carry
stale defaults. Recording exceptions makes model choice inspectable without
turning cost telemetry into an authorization gate.

---

## References Reviewed

- `CLAUDE.md`, `llm_client/CLAUDE.md`, and `tests/CLAUDE.md` — repository,
  package, and test rules.
- `docs/plans/94_model-tier-taxonomy-and-fable-ban.md` — current tier and
  staged cross-project enforcement direction.
- `docs/plans/110_provider-capabilities-opus-ban.md` and
  `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md` —
  current pre-dispatch model-policy boundary.
- `docs/guides/model-selection.md` — DeepSeek V4 Flash route evidence and the
  now-superseded no-allowlist statement.
- `llm_client/core/routing.py`, `llm_client/core/client_dispatch.py`, and
  `llm_client/execution/{text,structured,stream}_runtime.py` — shared routing
  and execution seams.
- `llm_client/observability/replay.py` — replay-safe call snapshot contract.
- OpenRouter live model catalog, observed 2026-07-23 — exact
  `deepseek/deepseek-v4-flash` route remains listed.

---

## Design

### Boundary and rules

`llm_client.core.model_execution_policy` owns:

1. the exact canonical allowed-model set;
2. `DEFAULT_EXECUTION_MODEL =
   "openrouter/deepseek/deepseek-v4-flash"`;
3. fail-closed validation after provider canonicalization and before dispatch;
4. the rule that any allowed non-default leg requires one non-empty
   `model_justification`.

The routing resolver consumes the decision and projects it into the routing
trace. Text and structured runtimes also retain `model_policy` and
`model_justification` in the call snapshot so replay reconstructs the same
authorization. These fields are internal controls and never reach a provider.

### Compatibility

`model_policy="compatibility"` preserves existing callers during inventory.
`model_policy="enforce_allowlist"` activates the new contract. New and migrated
production consumers use enforcement; compatibility is a temporary migration
state, not an alternate authorization path. A later cross-project inventory
and consumer migration is required before changing the shared default mode.

### Failure behavior

- unknown model: reject before provider or agent dispatch;
- GPT-5 Mini-family or other omitted route: reject as not allowlisted;
- allowed non-default without justification: reject before dispatch;
- fallback chain containing an unallowed or unjustified leg: reject the whole
  call before the primary executes;
- replay: carry and re-enforce the original policy and justification.

---

## Files Affected

- `llm_client/core/model_execution_policy.py` (create)
- `llm_client/core/client_dispatch.py`
- `llm_client/execution/text_runtime.py`
- `llm_client/execution/structured_runtime.py`
- `llm_client/execution/stream_runtime.py`
- `tests/test_model_execution_policy.py` (create)
- focused routing/replay/runtime tests
- `docs/guides/model-selection.md`
- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md`
- `docs/plans/CLAUDE.md`
- Twin shared-client wrapper, runtime config, tests, and current status/ADR

---

## Required Tests

| Test | What it proves |
|---|---|
| default exact route passes without justification | DeepSeek V4 Flash is the no-exception path |
| allowed alternate plus justification passes | explicit exception is usable and traceable |
| allowed alternate without justification fails | no silent exception |
| unknown and GPT-5 Mini-family routes fail | allowlist is fail-closed |
| invalid fallback rejects before primary dispatch | complete chain is governed |
| snapshot/replay retains policy and justification | exception evidence is durable |
| Twin wrapper selects default and enables enforcement | consumer cannot bypass via local config |
| live Twin canonical and negative replay | integrated route remains operational |

---

## Acceptance Criteria

- [x] Shared exact allowlist and DeepSeek V4 Flash default exist.
- [x] Enforced calls reject unknown and GPT-5 Mini-family routes before dispatch.
- [x] Every allowed non-default route requires and records a justification.
- [x] Fallback legs, text, structured, tools, batches, and streams pass through
      the shared policy boundary.
- [x] Twin contains no independent model denylist and opts into shared
      enforcement.
- [x] Focused and full feasible gates pass.
- [x] Exact deployed Twin canonical and negative probes pass with DeepSeek V4
      Flash.
- [x] Documentation states that compatibility mode is temporary and does not
      claim ecosystem-wide enforcement before consumer migration.

## Verification

- Shared focused policy/routing/runtime/replay gate: `108 passed`.
- Broader feasible shared suite: `1837 passed, 4 skipped`; three unrelated
  environment/baseline failures remained (missing extracted `prompt_eval` and
  one lifecycle test polluted by suite-level heartbeat state). The lifecycle
  test passed in isolation.
- Twin intended suite: `229 passed`, `53 subtests passed`.
- Real default-route canary
  `twin-model-policy-deepseek-v4-flash-canary-20260723` returned the exact
  expected response and retained `model_policy=enforce_allowlist`.
- Mac deployment: Twin `e9f7278`, `llm_client` `a1915aa`.
- Canonical trace `b2a68f7c-8ba3-47ac-87a8-70b1be1c3b64`: DeepSeek V4 Flash,
  enforced policy, no justification, eight validated citations across eight
  videos.
- Negative trace `61031848-3369-44ec-8156-d40bc1b30fb0`: abstained before
  generation.

---

## Non-claims and Next Slice

Passing proves selection-policy enforcement and one deployed route, not that
DeepSeek V4 Flash is universally higher quality. The next separate slice is a
cross-project consumer inventory, justification migration, and default-mode
flip. It must not be inferred from Twin's successful migration.
