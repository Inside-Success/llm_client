# Plan #110: Provider Capabilities and Opus Ban

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Cybernetic simulator DeepSeek V4 Flash max-reasoning sample

---

## Gap

**Current:** `reasoning_effort` is silently ignored outside a hard-coded
OpenAI/Anthropic family check; OpenRouter Broadcast does not receive the
client's required trace identity; and Opus remains selectable through the
registry and several workspace-agent defaults.

**Target:** Forward normalized controls generically, project trace identity into
OpenRouter's native Broadcast envelope, retain local observability as
cross-provider execution evidence, and hard-ban Opus across every runtime and
selection lane.

**Why:** `llm_client` should expose commodity provider capability rather than
reimplement it or make each consumer add provider branches. A model ban must be
an invariant, not a UI preference.

---

## References Reviewed

- `CLAUDE.md`, package/subtree instructions, and `docs/plans/TEMPLATE.md`.
- `llm_client/execution/completion_runtime.py` — current family-gated reasoning
  forwarding.
- `llm_client/utils/openrouter.py` — current OpenRouter route-evidence header.
- `llm_client/langfuse_callbacks.py` — required task/trace metadata projection.
- `llm_client/execution/call_contracts.py` — hard-block policy boundary.
- `llm_client/model_policy_audit.py` and
  `llm_client/data/default_model_registry.json` — static policy/selection.
- `docs/adr/0007-observability-contract-boundary.md`,
  `docs/adr/0010-cross-project-runtime-substrate.md`, and
  `docs/adr/0015-provider-governance-and-shared-coordination.md`.
- OpenRouter API parameter, reasoning-token, Broadcast, Auto Router, provider
  selection, preset, fallback, and Guardrail documentation.
- DeepSeek V4 thinking-mode documentation.
- LiteLLM DeepSeek reasoning documentation and the retained upstream V4 effort
  loss issue.

The zero-spend dependency probe reproduced the upstream seam: direct DeepSeek
collapsed graded effort to a thinking toggle, while OpenRouter rejected
`reasoning_effort` unless it appeared in `allowed_openai_params`. Plan 110
therefore declares the normalized control at the OpenRouter transport boundary;
it does not add a DeepSeek application branch. The adversarial audit also found
two vendor-routing seams: OpenRouter may ignore unsupported parameters unless
`provider.require_parameters` is true, and account-side Auto Router/presets can
replace an explicit model after `llm_client`'s pre-dispatch check.

---

## Modality

Deductive. Provider request shapes, ban behavior, metadata precedence, and
failure semantics are externally documented and testable before implementation.
The later question of whether max reasoning improves the cybernetic simulation
is exploratory and remains in that project's live instrument.

---

## Files Affected

- `llm_client/execution/completion_runtime.py`
- `llm_client/utils/openrouter.py`
- `llm_client/execution/call_contracts.py`
- `llm_client/model_policy_audit.py`
- `llm_client/data/default_model_registry.json`
- workflow/CLI modules that currently default to `claude-code/opus`
- focused tests for provider kwargs, runtime policy, registry, and workflows
- `docs/guides/model-selection.md`, API docs if the generated public surface
  changes, ADR/index/plan/concern documentation

---

## Risk-Ordered Slices

### Slice 1 — Prove generic reasoning transport and the complete Opus invariant

**Advances:** DeepSeek V4 Flash max reasoning becomes expressible through the
existing public option; Opus cannot execute through any supported lane.

**Vertical scope:** provider-call preparation, OpenRouter trace projection,
runtime ban, static audit, registry, workflow defaults, docs, and deterministic
tests.

**De-risks:** silent parameter loss and incomplete bans hidden behind agent
aliases/defaults, fallback legs, or opaque account-side model selection.

**Success:** focused tests prove exact provider kwargs and trace merge,
parameter-capable OpenRouter routing, pre-dispatch raw/agent/fallback Opus
rejection, rejection of opaque model selectors, no selectable Opus registry
entry, and non-Opus defaults.

**Audit:** search every active source/config/default for Opus; attack caller
trace precedence, explicit OpenRouter API-base routing, async/structured paths,
and unsupported-provider behavior.

**Cleanup:** remove obsolete family detection imports/comments, update generated
API docs only if the public surface changes, and triage the concern register.

**Done when:** focused and full feasible gates pass, audit findings are
dispositioned, cleanup is complete, and concerns are triaged.

### Slice 2 — Bind the downstream max-reasoning experiment

**Advances:** the cybernetic simulator's accepted preview binds
`deepseek-v4-flash` plus max reasoning rather than model name alone.

**Vertical scope:** downstream active-system configuration, preview digest,
trace evidence, and a zero-spend provider-payload test.

**De-risks:** claiming “max” when the provider request or durable evidence does
not prove it.

**Success:** a zero-spend test shows `reasoning_effort="max"` reaches the exact
OpenRouter request and the simulator preview/trace identity binds it.

**Audit:** reject default/high effort, omitted effort, mismatched preview, and
unobservable execution.

**Cleanup:** keep provider knowledge in `llm_client`; downstream configuration
contains only the normalized control.

**Done when:** downstream gates pass, no paid call has occurred, audit findings
are dispositioned, and both concern registers are triaged.

---

## Required Tests

| Test File | Test | What It Verifies |
|---|---|---|
| `tests/test_provider_kwargs.py` | DeepSeek reasoning, capability-required provider routing, Broadcast metadata, and opaque-selector cases | Generic parameter forwarding, fail-loud capability handling, policy-safe payloads, and caller-preserving trace projection |
| `tests/test_client.py` | Opus raw, workspace-agent, fallback, Auto Router, and preset cases | Every runtime and selection lane fails before dispatch |
| `tests/test_model_policy_audit.py` | Opus with override acceptance | Static ban cannot be bypassed |
| `tests/test_models.py` | packaged registry and max tier | Opus is absent and a non-banned tier resolves |
| workflow/CLI focused tests | default model assertions | No executable default selects Opus |

Existing provider, replay, observability, agent, model, and workflow tests must
remain green.

---

## Acceptance Criteria

- [x] DeepSeek/OpenRouter `reasoning_effort="max"` is not silently discarded.
- [x] OpenRouter routes carrying normalized controls require provider support
      rather than allowing unsupported parameters to be ignored.
- [x] OpenRouter Broadcast metadata receives task/trace identity without
      overriding caller fields.
- [x] Local observability remains authoritative and unchanged.
- [x] All explicit Opus routes, aliases, and fallback legs are hard-blocked
      before dispatch; opaque OpenRouter model selectors are rejected.
- [x] Registry, audit, workflows, CLI help, and active examples do not select
      Opus.
- [x] Focused tests and feasible repository gates pass.
- [x] Slice 1 adversarial audit, cleanup, and concern triage are complete.
- [ ] Slice 2 binds and verifies the downstream simulator configuration.

## Slice 1 Verification Evidence

- Plan gate: 341 tests passed.
- Broader affected surface: 560 tests passed, 10 deselected.
- Exact installed-LiteLLM, zero-network normalization test preserves
  `reasoning_effort="max"` for the OpenRouter DeepSeek request.
- OpenRouter provider sorting remains caller-controlled while
  `require_parameters=true` is enforced for normalized controls; explicit
  opt-out fails before dispatch.
- Auto Router, presets, auto-router plugins, and Opus-bearing provider model
  arrays fail before dispatch. Fixed explicit models remain supported.
- Strict relationship validation, generated API-reference refresh, JSON/YAML
  parsing, focused Ruff, and `git diff --check` pass.
- Active-tree audit leaves `opus` only in the hard-ban implementation,
  historical context-budget recognition, and negative policy documentation.
- Repository-wide collection remains blocked by absent optional
  `data_contracts` and `prompt_eval` packages. Strict repository mypy and the
  AGENTS symlink validator retain the documented baseline failures
  LLM-VERIFY-015 and LLM-VERIFY-014; none is caused by Slice 1.

---

## Reframe Gate

- Generic normalized-control forwarding is an **architecture invariant**.
- The Opus prohibition is a **policy invariant**.
- OpenRouter Broadcast enablement and destinations are **operator policy** and
  stay account-side.
- The value of max reasoning for simulation fidelity is an **empirical
  parameter** evaluated only by the downstream bounded experiment.
