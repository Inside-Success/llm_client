# Architecture Decision Records

All accepted LLM Client architecture decisions except ADR 0015 (provider governance), which stays at `0015-provider-governance-and-shared-coordination.md` because a hash-pinned codebase-wiki source links to it. The index is [README.md](README.md).

Each section below was a separate file until 2026-10-07. Its anchor is the old file name without `.md`, so an old path such as `docs/adr/0001-model-identity-v0.md` maps to `docs/adr/DECISIONS.md#0001-model-identity-v0`. Section bodies are the original text with headings demoted one level and links to other consolidated records repointed.

## Contents

- [ADR 0001: Model Identity Contract v0](#0001-model-identity-v0)
- [ADR 0002: Routing and Config Precedence](#0002-routing-config-precedence)
- [ADR 0003: Warning Taxonomy](#0003-warning-taxonomy)
- [ADR 0004: Fixed `result.model` Semantics](#0004-result-model-semantics-migration)
- [ADR 0005: `reason_code` Registry Governance](#0005-reason-code-registry-governance)
- [ADR 0006: Foundation `actor_id` Issuance Policy](#0006-actor-id-issuance-policy)
- [ADR 0007: Observability Contract Boundary](#0007-observability-contract-boundary)
- [ADR 0009: Long-Thinking Responses Background Polling](#0009-long-thinking-background-polling)
- [ADR 0010: Cross-Project Runtime and Observability Substrate](#0010-cross-project-runtime-substrate)
- [ADR 0011: Prompt Assets Use Explicit Identity and Lineage](#0011-prompt-assets-explicit-identity)
- [ADR 0012: Shared Data Plane Boundary](#0012-shared-data-plane-boundary)
- [ADR 0013: Stream Lifecycle Heartbeat and Stagnation Observability](#0013-stream-lifecycle-heartbeat-observability)
- [ADR 0014: Call Replay And Divergence Diagnosis Boundary](#0014-call-replay-and-divergence-diagnosis-boundary)
- [ADR 0015: Present LLM Client As Runtime Substrate Evidence](#0015-portfolio-runtime-substrate-scope)
- [ADR 0016: Provider Capability and Vendor Telemetry Boundary](#0016-provider-capability-and-vendor-telemetry-boundary)

---

<a id="0001-model-identity-v0"></a>

## ADR 0001: Model Identity Contract v0

*Originally `docs/adr/0001-model-identity-v0.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/adr/0001-model-identity-v0.md`.*


Status: Accepted
Date: 2026-02-22
Last verified: 2026-07-15
Verification context: Plan 105 serializes public Instructor construction and changes cost-source selection without changing requested, resolved, or executed model identity. Structured runtime, attempt, replay, and raw-artifact controls pass.

### Context

`LLMCallResult.model` is currently used as a public field by callers, but its
effective meaning is not fully uniform across all entrypoints. In some paths it
reflects an executed/resolved model, while in others it may reflect the input
model for a higher-level loop call.

We need a week-1 contract stabilization step that avoids behavioral breakage.

### Decision

1. `LLMCallResult.model` is treated as a legacy field in week 1.
2. Week 1 does not redefine `model` semantics across all paths.
3. We add additive disambiguation fields:
4. `requested_model`: raw caller model input at API boundary.
5. `resolved_model`: best-effort executed model for terminal successful output.
6. `routing_trace`: structured trace of routing/fallback decisions.
7. `resolved_model` is nullable and must be set only when provable.
8. `resolved_model` must never be guessed.

### Rationale

This prevents accidental compatibility breaks while making behavior explicit and
testable. A wrong resolved value is worse than `None`.

### Consequences

Positive:
1. Stabilizes current behavior for downstream consumers.
2. Enables future unification with explicit migration.
3. Improves diagnostics and auditing.

Negative:
1. Temporary dual semantics (`model` + new fields) adds short-term complexity.
2. Some paths may expose `resolved_model=None` until router/kernel extraction.

### Testing Contract

1. Add characterization tests per entrypoint for current `result.model`.
2. Assert `requested_model` always equals caller input.
3. Assert `resolved_model` is correct when provable, else `None`.

### Migration Notes

After router extraction (`resolve_call -> ResolvedCallPlan`) and shared kernel
work, propose a follow-up ADR to unify or deprecate ambiguous `model` usage.

Verification context (2026-07-13): native-schema attempt identity now includes
one logical-call-global ordinal across model fallback. Each event records the
actual model used; final requested/resolved model semantics remain unchanged.

Post-validation finalization failures now stop retry and model fallback, so a
validated response cannot fabricate a later executed-model identity.

Plan 354 removes a duplicate private-runtime terminal lifecycle write. Requested,
resolved, and executed model identities remain unchanged; composed sync/async
structured controls pass.

---

<a id="0002-routing-config-precedence"></a>

## ADR 0002: Routing and Config Precedence

*Originally `docs/adr/0002-routing-config-precedence.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/adr/0002-routing-config-precedence.md`.*


Status: Accepted
Date: 2026-02-22
Last verified: 2026-07-16
Verification context: Plan 94 registers a provider-free route-certification
query command; it does not change call, environment, or default routing
precedence. Focused CLI and route-contract controls pass.

### Context

Routing behavior has been sensitive to environment defaults. This creates drift
between local runs, CI, and tests when policy is not explicitly set.

### Decision

1. Routing-sensitive tests must set routing policy explicitly.
2. Tests must not rely on ambient environment defaults.
3. Routing behavior contracts are validated under explicit policy fixtures.
4. Week 1 does not flip runtime routing defaults.

### Precedence Rule (target contract)

For any configurable routing option:
1. Explicit call/site config wins.
2. Explicit test fixture/env override is second.
3. Library defaults are last.

### Rationale

This prevents silent behavior drift and makes failures reproducible.

### Consequences

Positive:
1. Deterministic tests and clearer regression attribution.
2. Safer staged refactor to pure router extraction.

Negative:
1. More explicit setup in tests.

### Follow-up

Week 2+: extract pure routing resolver with typed output:
`resolve_call(request, config) -> ResolvedCallPlan`.

Verification context (2026-07-13): the resolved fallback order now determines
globally increasing structured-attempt ordinals. This adds observability of the
existing route; it does not change configuration precedence.

The runtime now treats a validated native-schema response as terminal for model
fallback; this is an execution-integrity boundary, not a new routing precedence.

Plan 354 changes only structured terminal-event ownership. Routing and config
precedence remain unchanged; composed sync/async structured controls pass.

---

<a id="0003-warning-taxonomy"></a>

## ADR 0003: Warning Taxonomy

*Originally `docs/adr/0003-warning-taxonomy.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/adr/0003-warning-taxonomy.md`.*


Status: Accepted
Date: 2026-02-22
Last verified: 2026-09-11
Verification context: External-observability content policy rejects unknown
values before callback registration; configuration errors remain errors rather
than warnings. No new warning code or advisory path is introduced.

Plan 94's OpenRouter generation enrichment emits a bounded warning for each
eventual-consistency 404 retry; exhaustion remains an error and never becomes a
silent model retry or provider fallback.

### Context

Current warnings include both model deprecation and model advisories
(outclassed-but-allowed). Warning category drift has caused test and contract
mismatch.

### Decision

1. `DeprecationWarning` is reserved for true deprecation/blocking paths.
2. `UserWarning` is used for outclassed-but-allowed advisories.
3. Week 1 locks category semantics; code identifiers can be added later.
4. Week 1 applies only drift fixes needed to align behavior/tests with this
   taxonomy.
5. Missing/disabled persistence for a caller that explicitly selects the strict
   tool-call API is an integrity error, not a warning or best-effort advisory.

### Rationale

Category consistency improves automation and human interpretation.

### Consequences

Positive:
1. Clear operational meaning of warnings.
2. Stable tests and less ambiguity in tool/agent behavior.

Negative:
1. Existing tests expecting different categories must be updated intentionally.

### Follow-up

Add stable warning codes (`LLMC_WARN_*`) with structured metadata once
router/kernel contracts are stabilized.

Verification context (2026-07-13): native-schema pre-response failures are
typed attempt events (`timeout`, `rate_limit`, or `provider_execution`), not
warnings. The retry kernel records the actual retry/fallback/exhaustion
disposition; persistence failure remains an integrity error.

Local failures after schema validation now propagate as terminal call errors
without another provider attempt or an advisory warning.

Plan 101 receipt contradictions remain fail-loud integrity errors, not warnings.

Plan 354 removes only a duplicate terminal lifecycle row. Warning categories,
fail-loud persistence, and retry diagnostics remain unchanged; affected
structured suites pass in fresh processes.

---

<a id="0004-result-model-semantics-migration"></a>

## ADR 0004: Fixed `result.model` Semantics

*Originally `docs/adr/0004-result-model-semantics-migration.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/adr/0004-result-model-semantics-migration.md`.*


Status: Accepted
Date: 2026-02-23
Last verified: 2026-07-15
Verification context: Plan 105 changes only Instructor construction serialization and cost/query internals; `model`, requested/resolved model semantics, and routing traces remain unchanged. Focused sync/async structured controls pass.

### Context

`LLMCallResult.model` had compatibility modes and migration toggles. This made
debugging harder and forced callers to know mode-specific behavior.

### Decision

1. Remove semantics-mode switching.
2. Remove semantics telemetry and related CLI reporting commands.
3. Use one identity contract everywhere:
   - `result.model`: terminal executed model.
   - `result.requested_model`: caller input model.
   - `result.resolved_model` / `result.execution_model`: terminal executed model.
   - `result.routing_trace`: routing/fallback explanation.

### Consequences

Positive:
1. No ambiguity in `result.model`.
2. No mode/env drift between environments.
3. Simpler client API and docs.

Negative:
1. Breaking change for clients that relied on legacy/model-mode behavior.
2. Removed mode-adoption telemetry and semantics report commands.

### Rollout

1. Version cut to `0.7.0`.
2. Keep additive identity fields and routing trace as the canonical debugging
   surface.

### Testing Contract

1. Identity tests assert `result.model == result.resolved_model` when resolved
   identity is known.
2. MCP/agent tests assert fallback cases still preserve:
   - `requested_model` as caller input.
   - `routing_trace` attempted model chain.

Verification context (2026-07-13): structured-attempt child events expose the
per-attempt model and global ordinal needed to diagnose fallback, without
changing `LLMCallResult.model`, `requested_model`, or `routing_trace`.

Post-validation finalization cannot switch models, preserving the executed
model identity attached to the already-validated result.

Plan 354 makes the public wrapper the sole structured terminal-lifecycle owner.
`LLMCallResult` model semantics and terminal call-row identity remain unchanged;
composed sync/async controls pass.

---

<a id="0005-reason-code-registry-governance"></a>

## ADR 0005: `reason_code` Registry Governance

*Originally `docs/adr/0005-reason-code-registry-governance.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/adr/0005-reason-code-registry-governance.md`.*


Status: Accepted  
Date: 2026-02-23
Last verified: 2026-04-05

Verification context: Codex agent parsing now canonicalizes exact gpt-5.4 requests before SDK dispatch
### Context

MCP submit-validation paths emit `reason_code` values that are counted in run
metadata and used for diagnostics (`submit_validation_reason_counts`).
Without registry governance, code names can drift, get reused with different
meaning, or fragment into one-off strings that break trend analysis.

### Decision

1. `reason_code` values are governed by an explicit registry in this ADR.
2. Registry changes are additive-only:
   - new codes may be added,
   - existing codes must not be removed or reassigned to new semantics.
3. Code format is lowercase `snake_case`.
4. Unknown/unregistered codes are still accepted at runtime but treated as
   unregistered telemetry until promoted through an ADR update.
5. Initial registry (version `2026-02-23`):
   - `unfinished_todos`: submit blocked because required TODO items are not complete.
   - `answer_not_grounded`: submit blocked because answer lacks required evidence grounding.

Current-code note (verified 2026-10-03): this repository only consumes
`reason_code` from submit-validator payloads (`llm_client/agent/mcp_turn_outcomes.py`);
it does not emit these codes, and `unfinished_todos` does not appear in this
repository's code. The runtime also keys behavior on `pending_atoms` (Plan #91),
which is not in the registry above and so is currently unregistered telemetry
under item 4; promoting it is a separate ADR update.

### Consequences

Positive:
1. Stable long-term metrics and reporting across releases.
2. Fewer ambiguous failure reasons in agent policy analysis.
3. Clear change-control path for adding new validation reasons.

Negative:
1. Slight process overhead for introducing new reason codes.
2. Temporary unregistered-code noise may appear before governance catches up.

### Testing Contract

1. Contract tests should assert known reason codes remain unchanged.
2. New reason codes require:
   - ADR update,
   - targeted test coverage,
   - changelog/release note entry.

---

<a id="0006-actor-id-issuance-policy"></a>

## ADR 0006: Foundation `actor_id` Issuance Policy

*Originally `docs/adr/0006-actor-id-issuance-policy.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/adr/0006-actor-id-issuance-policy.md`.*


Status: Accepted  
Date: 2026-02-23
Last verified: 2026-04-05

Verification context: Codex actor routing now canonicalizes exact gpt-5.4 requests before SDK dispatch
(historical 2026-04-05 note, unverified against current code: Plan #348 later
banned `gpt-5.4`, and no `gpt-5.4` canonicalization remains in the Codex adapter;
it has no bearing on the `actor_id` decision below).

### Context

Foundation events require `actor_id`, but issuance semantics were not formally
documented. This created ambiguity around trust boundaries and naming
consistency for decision/transition records.

### Decision

1. `actor_id` is required on all Foundation events and must identify the
   principal responsible for the recorded action.
2. Namespace prefixes are restricted to:
   - `user:`
   - `agent:`
   - `service:`
3. Canonical shape:
   - `<prefix><component>[:<scope>[:<version>]]`
   - example: `agent:mcp_loop:default:1`
4. Trust boundary:
   - server/runtime issuance is authoritative,
   - untrusted external values must not be passed through unchanged for
     privileged event classes.
5. Decision and transition-style events must always include a server-issued
   `actor_id` in one of the canonical namespaces.

### Consequences

Positive:
1. Clear accountability provenance in Foundation logs.
2. Consistent principal identity for policy analysis and auditing.
3. Reduced spoofing risk from pass-through actor labels.

Negative:
1. Additional implementation discipline is required when adding new emitters.
2. Legacy free-form actor identifiers should be migrated to canonical form.

### Testing Contract

1. Foundation event tests should assert non-empty canonical `actor_id` values.
2. New emitters must include coverage that verifies canonical namespace usage.

---

<a id="0007-observability-contract-boundary"></a>

## ADR 0007: Observability Contract Boundary

*Originally `docs/adr/0007-observability-contract-boundary.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/adr/0007-observability-contract-boundary.md`.*


Status: Accepted  
Last verified: 2026-09-11
Verification context: Optional Langfuse export remains complementary to the
authoritative local JSONL and SQLite sinks. Its default metadata-only policy
suppresses prompt and response export, while explicit `full` mode is required
to cross that external content boundary; no local persisted schema changes.
Date: 2026-02-23

### Context

Observability logic was historically mixed into core call paths, and `io_log.py`
served both as implementation and public API surface. As the codebase split into
`llm_client/observability/*` modules, we needed a stable contract for what is
persisted, how compatibility is preserved, and where behavior should evolve.

### Decision

1. Canonical observability implementation lives in `llm_client/observability/*`.
2. `llm_client/io_log.py` remains a compatibility facade for existing imports.
3. Default persistence behavior remains safe-by-default:
   - metadata-first logging,
   - no requirement to persist full raw content in default paths.
4. Warning and routing-related diagnostics emitted into observability surfaces
   must remain aligned with the warning taxonomy contract in ADR 0003.
5. Any breaking changes to observability payload shape or sink behavior require
   a dedicated ADR update.
6. The canonical tool-call surface exposes two explicit policies:
   - `log_tool_call` preserves compatibility best-effort behavior,
   - `log_tool_call_strict` is for pipeline-critical evidence and fails when
   logging is disabled, the trace id is blank, or either configured sink fails.
7. LLM usage accounting preserves bounded provider-reported numeric token
   details when available. Aggregate counts remain authoritative as reported;
   missing detail fields are not inferred, and reasoning content is not stored.

### Consequences

Positive:
1. Clear boundary between core execution and observability concerns.
2. Preserved compatibility for existing `io_log` consumers.
3. Better maintainability for query/experiment/reporting evolution.

Negative:
1. Transitional complexity while both compatibility facade and canonical modules exist.
2. Requires discipline to keep facade behavior aligned with canonical modules.

### Testing Contract

1. Compatibility tests must cover `io_log` delegated behavior.
2. Observability tests must verify default-safe persistence behavior.
3. Warning/diagnostic emission must remain category-consistent with ADR 0003.
4. Strict persistence tests must cover both sinks, disabled logging, and null or
   blank trace identifiers.
5. Native-schema attempt tests must cover `started` before provider invocation,
   typed pre-response failure, and retry-kernel recovery disposition. Attempt
   events exclude exception messages and provider bodies.
6. Usage-detail tests must cover Completion and Responses normalization, fresh
   and migrated SQLite schemas, JSONL import, query round-trip, and
   content-bearing negative controls.

Last verified: 2026-07-14 (Plan 97 Slice 3 transport-attempt lifecycle).

### 2026-07-25 Amendment: Privacy-Bounded Attempt Diagnostics

Plan 121 adds an additive `attempt_diagnostics` child ledger. It may retain
typed status/error identifiers, request-correlation identifiers, timeout kind,
exception class names/fingerprint, and a bounded `sanitized_summary` only after
deterministic redaction rejects credential, authorization, prompt, and raw-body
patterns. Raw exception messages, provider bodies, prompts, and headers remain
outside SQLite and require a separately authorized artifact reference. A
diagnostic records client-observed origin and attribution limits; it cannot
claim provider fault without typed provider/gateway response evidence.

Plan 101 adds trusted-process runtime receipts; it does not claim provider
attestation, source authentication, signatures, or hostile-process security.

### 2026-07-25 Amendment: Durable Budget Reservations

Plan 334 adds additive `budget_scopes` and `budget_reservations` metadata to
the SQLite observability store. They retain trace identifiers, normalized
micro-USD amounts, ownership IDs, and lifecycle timestamps only. They must not
retain prompts, responses, provider payloads, credentials, or exception text.
The canonical transaction logic lives in
`llm_client/observability/budget_reservations.py`; `io_log.py` owns only schema
creation and compatibility access to the shared SQLite connection.

### 2026-07-25 Amendment: Synchronized Sink Shutdown

The compatibility facade owns synchronized closure of its shared SQLite
connection. Shutdown waits behind the same write lock used by persistence and
then takes the connection lock in the normal write-path order. Tests and
maintenance commands must call `io_log.close()` rather than closing
`_db_conn` directly; this prevents lifecycle heartbeat writers from operating
on a connection closed concurrently by teardown.

### 2026-08-11 Amendment: Terminal Structured-Attempt Cost Evidence

Plan 353 makes cost and success independent observability facts. Native
structured execution may persist a failed logical-call row with numeric cost,
cost source, and marginal cost when one or more provider responses returned and
were priceable. The failed lifecycle classification and error record remain
unchanged; a synthetic accounting result must never imply valid structured
output.

The public `LLMError` boundary carries additive `cost`, `cost_source`, and
`cost_covers_all_attempts` fields. A reserved-concurrent lease settles from a
terminal error only when coverage is explicitly true and the cost is finite and
non-negative. Partial, pre-response, and cancelled paths release the lease, but
any numeric cost persisted on their failed call row remains included in future
budget-scope snapshots. No missing attempt cost is inferred, and no historical
row is backfilled.

### 2026-08-12 Amendment: Instructor Attempt Custody

Plan 356 extends the same append-only structured-attempt contract to the
Instructor execution path. Instructor receives `max_retries=1`; the shared
retry kernel owns every retry and fallback so provider generations cannot be
hidden inside the adapter. Successful attempts persist exact message content or
one tool call's function arguments as the received bytes, never a reserialized
parsed object. Metadata, raw-artifact, cost, and selected-attempt custody follow
the existing privacy and fail-loud rules.

---

<a id="0009-long-thinking-background-polling"></a>

## ADR 0009: Long-Thinking Responses Background Polling

*Originally `docs/adr/0009-long-thinking-background-polling.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/adr/0009-long-thinking-background-polling.md`.*


Status: Accepted
Date: 2026-02-23
Last verified: 2026-07-15
Verification context: Plan 105 aligns Responses cost-source precedence with Completions after a response is available; background enablement, retrieval, polling, endpoint validation, and timeout controls remain unchanged. Focused client tests pass.

### Context

`gpt-5.2-pro` can run long-thinking passes that exceed normal request timeouts
when `reasoning_effort` is high/xhigh. Without background execution + polling,
the client can fail or surface incomplete responses while work is still in
progress.

### Decision

1. `gpt-5.2-pro` is treated as a Responses-API model (currently `_RESPONSES_API_MODELS` in
   `llm_client/core/model_detection.py`; the former `llm_client/client.py` no
   longer exists).
2. For long-thinking effort levels (`high`, `xhigh`), Responses requests enable
   `background=true`.
3. When initial Responses status is non-terminal, the client polls by
   `response_id` until terminal completion/failure or timeout.
4. Polling controls are user-tunable via call kwargs:
   - `background_timeout` (default 900s),
   - `background_poll_interval` (default 15s).
5. Poll retrieval uses OpenAI SDK clients (`OpenAI` / `AsyncOpenAI`) because the
   current LiteLLM runtime exposes `responses()` as a function without a
   `.retrieve` method in this environment.
6. Background retrieval validates `api_base` and fails fast for non-OpenAI
   endpoints (for example OpenRouter), instead of retrying until timeout.
7. Routing traces expose `background_mode` to support lightweight adoption
   telemetry.
8. Configuration failures are machine-readable via `LLMConfigurationError`:
   - `LLMC_ERR_BACKGROUND_ENDPOINT_UNSUPPORTED`
   - `LLMC_ERR_BACKGROUND_OPENAI_KEY_REQUIRED`

### Consequences

Positive:
1. Long-thinking calls are resilient to normal request timeout windows.
2. Deterministic behavior for sync and async paths.
3. Operators can tune polling latency/timeout tradeoffs per call.

Negative:
1. Polling introduces longer wall-clock runtimes for deep-review calls.
2. Retrieval currently depends on OpenAI SDK client semantics for background
   lookup.

### Uncertainties

1. LiteLLM may expose first-class background retrieval in future versions; if
   that happens, retrieval strategy should be revisited to reduce duplicate
   client logic.
2. Background semantics for non-OpenAI providers are intentionally out-of-scope
   for this ADR.

### Testing Contract

1. Unit tests must cover:
   - `gpt-5.2-pro` Responses detection,
   - background/reasoning kwargs emission,
   - sync and async polling handoff on non-terminal initial statuses.
2. Retrieval helper tests must validate:
   - key-presence requirements,
   - OpenAI client invocation shape (api key/base URL/timeout).

Verification context (2026-07-13): Plan 97's native-schema attempt lifecycle is
limited to Completions native JSON-schema calls. Responses/background polling
semantics in this ADR remain unchanged.

Within that bounded native-schema path, local finalization after validation is
terminal and cannot re-enter provider retry or fallback; polling remains out of
scope and unchanged.

Plan 354 removes a duplicate private-runtime terminal lifecycle write without
changing Responses routing, background polling, or timeout behavior. Focused
structured runtime and lifecycle suites pass in fresh processes.

Current-code note (verified against `llm_client/execution/background_runtime.py`
on 2026-10-03; the decision above is unchanged): background retrieval now
accepts both OpenAI and OpenRouter endpoints (`_validate_background_retrieval_api_base`
returns `"openai"` or `"openrouter"`) and rejects any other `api_base`
with `LLMC_ERR_BACKGROUND_ENDPOINT_UNSUPPORTED`. Decision items 6 and 8 therefore
read as follows today: OpenRouter is no longer rejected, and the missing-key
errors are `LLMC_ERR_BACKGROUND_OPENAI_KEY_REQUIRED` and
`LLMC_ERR_BACKGROUND_OPENROUTER_KEY_REQUIRED`. Defaults of 900s/15s still hold.

---

<a id="0010-cross-project-runtime-substrate"></a>

## ADR 0010: Cross-Project Runtime and Observability Substrate

*Originally `docs/adr/0010-cross-project-runtime-substrate.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/adr/0010-cross-project-runtime-substrate.md`.*


Status: Accepted
Date: 2026-03-17
Last verified: 2026-09-11 (external observability privacy boundary)
Verification context: The shared substrate now applies one fail-loud,
metadata-only default when an optional Langfuse callback is enabled. Local
JSONL and SQLite evidence remains authoritative, and cross-project callers can
opt into full external content only through the explicit shared setting.

Plan 94 adds shared authenticated OpenRouter generation evidence, an immutable
exact route-certification registry, and a provider-free query CLI. Semantic
acceptance and project-specific promotion remain above this substrate.

### Context

The intended direction for the project is that any application, coding agent, or
research workflow can point at `llm_client` for LLM and embedding work and get
standardized execution, packaging, observability, and experiment recording by
default.

At the same time, adjacent repos such as `prompt_eval` already provide
higher-level capabilities like prompt comparison, evaluators, and optimization.
That created recurring confusion about which package owns:

1. the shared execution substrate,
2. the shared observability and experiment store,
3. prompt-specific evaluation semantics,
4. workflow orchestration.

We also want to avoid recreating commodity routing and workflow machinery that
existing libraries already solve well.

### Decision

1. `llm_client` is the mandatory cross-project substrate for LLM and embedding
   execution.
2. `llm_client` owns the generic runtime surfaces that many projects share:
   - provider and SDK dispatch,
   - structured output,
   - tool calling and agent runtime integration,
   - embeddings,
   - prompt rendering,
   - cost, latency, and trace capture,
   - shared run and event persistence.
3. `llm_client` owns the authoritative shared observability backend for
   cross-project work. JSONL and SQLite are the current sinks; the storage
   backend may evolve later without changing this ownership boundary.
4. The shared experiment envelope belongs to `llm_client`, including fields such
   as `project`, `dataset`, `condition_id`, `scenario_id`, `phase`, `seed`,
   `replicate`, `metrics_schema`, `config`, `provenance`, and per-item
   `metrics`/`extra`.
5. Higher-level packages such as `prompt_eval` consume this substrate rather
   than creating separate primary execution or observability stacks.
6. Commodity routing and normalization should be wrapped instead of recreated.
   Current preference:
   - use LiteLLM for provider normalization and routing where practical,
   - use LangGraph or an equivalent workflow runtime if durable orchestration
     requirements outgrow the simple local DAG layer.
7. Workflow orchestration is above the core client boundary. `task_graph` may
   remain as a simple orchestrator, but `llm_client` should not turn into a
   bespoke general-purpose workflow engine.
8. Cross-project callers that require tool execution to be auditable use the
   shared strict tool-call API rather than implementing project-local sinks.
9. LLM-capable application entry points use the shared `ObservedRun` contract
   when pre-client validation, policy, or workflow can fail. The application
   starts outer-run custody before fallible work, derives public-call trace IDs
   from the root, and records one controlled terminal state. Public call
   wrappers reject traces outside the active run lineage before dispatch. This
   is generic run persistence, not workflow orchestration; applications retain
   stage and success semantics. Migrated executables enable
   `LLM_CLIENT_REQUIRE_OBSERVED_RUN=1`; the opt-in remains a compatibility
   bridge until consumer entry points are audited.

### Consequences

Positive:
1. A single place to standardize execution, cost tracking, and run metadata
   across projects.
2. Cleaner separation between generic runtime infrastructure and prompt-specific
   evaluation logic.
3. Lower risk of duplicating provider routing, retry, and observability code in
   every project.
4. Clearer strategy for reusing existing libraries instead of rebuilding them.

Negative:
1. `llm_client` remains a broad dependency and needs tighter module boundaries.
2. Some current behavior is transitional, especially where other packages still
   keep their own local result stores.
3. Future contributors must distinguish shared substrate features from
   higher-level product features instead of adding everything into one layer.

### Testing Contract

1. Core execution tests must continue to prove that shared runtime surfaces work
   across multiple task types, not just prompt-eval use cases.
2. Observability tests must continue to prove that run/event storage remains a
   shared facility rather than a prompt-specific one.
3. Integration work in higher-level packages should verify that they can depend
   on `llm_client` without recreating primary execution or analytics backends.
4. Strict cross-project tool traces must prove sink failures propagate and the
   persisted event remains joinable to its parent trace.
5. Cross-project structured traces must prove every provider attempt begins at
   `started`, preserves pre-response failures, and records the retry kernel's
   actual disposition with logical-call-global ordinals.
6. Downstream observed-run adoption must include pre-call failure, linked-call
   success/failure, and cancellation controls plus one non-mocked root-to-child
   lifecycle receipt before advertising complete integration.

Last verified: 2026-07-28 (Plan 338 observed application-run lifecycle).

The shared runtime now distinguishes provider recovery from local finalization:
once native structured output validates, hook/cache/log failures fail loud
without repeating generation or switching models.

Plan 101 consumers pin the logical call identity returned by the same runtime
result; trace-only lookup is diagnostic.

Plan 354 reasserts public-wrapper ownership of the structured call's sole
terminal lifecycle. Private runtimes still persist one terminal call row and
structured-attempt events under the same logical call ID; composed sync/async
controls prove the joined boundary.

Plan 356 makes Instructor a first-class structured-attempt path without moving
evaluation semantics into this substrate. The shared retry kernel owns retry
count and disposition, and downstream evaluations may require the resulting
attempt receipt before treating a model result as execution evidence.

Current-code note (verified 2026-10-03): `llm_client/task_graph.py` named in
decision item 7 no longer exists in this repository (extracted to project-meta,
see ADR 0008); the workflow layer that remains here is `llm_client/workflow/`
and `llm_client/workflow_langgraph.py`. The decision itself is unchanged.

---

<a id="0011-prompt-assets-explicit-identity"></a>

## ADR 0011: Prompt Assets Use Explicit Identity and Lineage

*Originally `docs/adr/0011-prompt-assets-explicit-identity.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/adr/0011-prompt-assets-explicit-identity.md`.*


Status: Accepted  
Date: 2026-03-17  
Last verified: 2026-08-20
Verification context: `render_prompt()` now performs two read-only inspections
of caller-supplied context before rendering. It measures the context against an
optional sibling `<template>.contract.yaml`, and it reports content repeated
within the context. Both observe; neither resolves, substitutes, reorders, or
overrides prompt content, so deterministic resolution (decision 6) and prompt
asset identity (decision 3) are unchanged, and a rendered prompt is byte-for-byte
what it would have been without them. The contract file is discovered by an
explicit, documented naming convention rather than implicit override lookup, and
duplicate reporting needs no file at all, so decision 5 is intact either way.

### Context

The project direction is to treat prompts as data, not as ad hoc inline strings
inside application code. We also want prompts to be reusable across projects and
easy for coding agents to inspect, compare, and improve.

The main risk in a shared prompt system is ambiguity. Project-local overrides,
implicit resolution rules, and symlink-based indirection make it hard to answer
basic questions such as:

1. which prompt actually ran,
2. where the source of truth lives,
3. whether one prompt is a modified copy of another,
4. how an agent should compare prompt variants across projects.

### Decision

1. Prompts remain data assets and should be loaded through explicit prompt
   rendering APIs instead of inline Python f-strings.
2. Reusable prompts belong in a shared prompt asset layer rather than being
   owned by `prompt_eval`.
3. Each prompt asset must have explicit identity:
   - asset ID,
   - version,
   - namespace or owner,
   - metadata sufficient for provenance.
4. Customized prompts create new prompt assets with lineage metadata such as
   `derived_from`; they do not silently override an existing shared prompt.
5. Hidden runtime override resolution is not the default architecture. The
   system should prefer explicit prompt references over project-local shadowing.
6. `llm_client.render_prompt()` should resolve prompt inputs deterministically
   from explicit references or explicit file paths.
7. `prompt_eval` evaluates prompt assets and records their identity in run
   metadata; it does not become the canonical prompt registry.

### Consequences

Positive:
1. Deterministic provenance for prompt runs.
2. Better reuse and comparison across projects.
3. Lower ambiguity for coding agents inspecting or modifying prompt behavior.
4. Cleaner promotion path from local prompt experiments to shared prompt assets.

Negative:
1. A shared prompt asset layer needs its own metadata and versioning discipline.
2. Teams lose the convenience of implicit overrides and must create explicit new
   prompt assets for meaningful changes.
3. Existing project-local prompt layouts will need a gradual migration path.

### Testing Contract

1. Prompt rendering tests must prove deterministic resolution for explicit
   prompt references.
2. Observability and experiment logging should record prompt asset identity when
   the caller supplies it.
3. Prompt comparison workflows must treat prompt lineage as explicit metadata,
   not inferred from override order.

---

<a id="0012-shared-data-plane-boundary"></a>

## ADR 0012: Shared Data Plane Boundary

*Originally `docs/adr/0012-shared-data-plane-boundary.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/adr/0012-shared-data-plane-boundary.md`.*


Status: Accepted  
Last verified: 2026-09-11
Verification context: Optional Langfuse telemetry exports bounded metadata by
default and does not add raw prompts or responses to the shared data plane.
Explicit `full` mode is a separate external-content authorization; no dataset,
artifact, lineage, or local sink field changes.
Date: 2026-03-17

### Context

The broader ecosystem direction is to standardize reusable data across projects
so coding agents can rely on common datasets, artifacts, schemas, and
provenance instead of each repo inventing its own storage conventions.

The risk is that `llm_client` could grow from a shared runtime and observability
layer into an undifferentiated data platform that stores every raw payload,
corpus, and derived object itself.

We need a clear line between:

1. shared execution and experiment metadata,
2. shared datasets and artifacts,
3. project-specific derived stores and caches.

### Decision

1. Canonical reusable datasets, artifacts, schema definitions, and lineage
   metadata should be standardized across projects rather than being
   independently owned by each project repo.
2. `llm_client` remains the control plane, not the entire data plane. It owns:
   - execution events,
   - observability,
   - run metadata,
   - scoring records,
   - provenance links to datasets and artifacts.
3. The shared data plane should be a separate architectural layer that can host
   dataset registries, artifact registries, schema metadata, and storage
   adapters.
4. `llm_client` should persist stable references such as `dataset_id`,
   `artifact_id`, `uri`, `content_hash`, `schema_name`, `schema_version`, and
   lineage links instead of trying to inline every raw dataset or artifact.
5. Project-local stores are usually derived views, caches, or specialized
   runtimes. They are sources of truth only when they represent genuinely
   project-unique state that cannot reasonably live in the shared data plane.
6. Embedding work is split across the layers:
   - `llm_client` logs the embedding event and its provenance,
   - vectors, indexes, and large embedding artifacts live in the data plane or
     in project-specific derived stores that are linked back to that event.
7. Tool-call lifecycle rows may include bounded query metadata and result counts,
   but bulk tool results remain in project/data-plane artifacts referenced by
   the trace rather than being copied into the shared observability database.

### Consequences

Positive:
1. Cross-project reuse becomes an explicit architectural goal instead of an
   accident.
2. `llm_client` can stay focused on runtime and observability contracts.
3. Provenance becomes easier to query without forcing all payloads into one
   database schema.

Negative:
1. The ecosystem now needs a separate shared data layer with its own
   operational decisions.
2. Some current project-local data handling will need to be reclassified as
   either canonical shared data or derived local materialization.
3. Artifact and dataset identity must be designed carefully to avoid a weak
   registry that adds ceremony without enough value.

### Testing Contract

1. Observability tests should prove that run metadata can link cleanly to
   external dataset and artifact identifiers.
2. Provenance and lineage features must fail loudly when required references are
   missing or inconsistent.
3. New storage integrations must preserve the distinction between shared
   metadata in `llm_client` and bulk payloads in the data plane.
4. Strict tool-call tests must prove lifecycle metadata survives both sinks
   without introducing result-body persistence.
5. Structured execution-failure events retain only bounded failure class and
   exception type. Plan 121's additive attempt-diagnostic child ledger may
   retain a deterministically redacted, bounded operational summary plus typed
   status/correlation metadata; raw exception messages, provider bodies,
   prompts, credentials, and headers remain outside the shared metadata plane.

Last verified: 2026-07-14 (Plan 97 Slice 3 additive event migration).

Plan 101 receipts retain hashes and typed lifecycle metadata only; raw provider
content remains external behind the optional artifact reference.

---

<a id="0013-stream-lifecycle-heartbeat-observability"></a>

## ADR 0013: Stream Lifecycle Heartbeat and Stagnation Observability

*Originally `docs/adr/0013-stream-lifecycle-heartbeat-observability.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/adr/0013-stream-lifecycle-heartbeat-observability.md`.*


Status: Accepted  
Last verified: 2026-09-11
Verification context: The optional external callback policy changes only
content export. Stream start, progress, completion, failure, heartbeat, and
stagnation lifecycle semantics remain unchanged.
Date: 2026-03-22

### Context

`stream_llm` and `astream_llm` are visible entrypoints, but prior extraction
introduced regressions and missing terminal lifecycle rows:

1. Stream wrappers were not wrapped for lifecycle finalization when consumers
   stopped iterating at natural end or encountered an iterator exception.
2. Non-streaming `llm_client` monitor fields were emitted, while stream paths
   often stayed unobserved, producing blind spots in `get_active_llm_calls`.
3. The first implementation mixed model identifiers in stream adapters, including
   argument-level inconsistencies in async stream construction.
4. Stagnation is currently inference-based (time since last observed progress),
   not provider-progressive heartbeat proof because standard chat-stream providers
   do not emit reliable chunk-level progress metadata.

### Decision

1. Keep stream lifecycle observability in `llm_client`, with explicit terminal
   events emitted by stream adapters at iterator boundary:
   - `started` emitted before stream creation attempt
   - `progress` emitted from chunk iteration (`mark_progress` per chunk)
   - `completed` when `StopIteration` is reached
   - `failed` when iteration raises or stream setup fails
2. Use heartbeat/stall settings consistently across sync and async stream paths:
   - `lifecycle_heartbeat_interval_s`
   - `lifecycle_stall_after_s`
3. Drive monitor state from chunk callbacks only; heartbeat/stall markers remain
   inferred from elapsed time without assuming provider token-level progress.
4. Pass monitor objects only through private `_lifecycle_monitor` kwargs into provider
   payload builders, and never into public stream constructors.
5. Treat stream model constructor arguments as provider iterator + requested model
   (no duplicate positional overloads).
6. Programmatic tool calls use the separate typed tool-call lifecycle contract;
   they must not be projected as stream progress or heartbeat events.

### Consequences

Positive:
1. Live stream calls now appear in `get_active_llm_calls` with a truthful state
   transition from `started` to `completed`/`failed`.
2. Operators can diagnose stuck streams by combining heartbeat and stalled metadata
   without conflating provider-side heuristics with client truth.

Negative:
1. Long-running, non-progressing streams can still only be inferred as stale from
   inactivity (not provably "stuck").
2. Streams that are created and then never iterated remain in-progress until process
   end; this is a broader consumption contract issue and must be handled
   operationally.

### Testing Contract

1. Unit tests in `tests/test_client_lifecycle.py` must verify:
   - sync success emits `started -> progress -> completed`
   - sync iteration error emits `started -> progress -> failed` and captures error metadata
   - async success emits `started -> progress -> completed`
   - async iteration error emits `started -> progress -> failed` and captures error metadata
2. Existing stream fixtures should continue passing for non-streaming and streaming
   behavior after monitor extraction.

Verification context (2026-07-13): structured non-streaming attempt events now
also use `started`, but are stored in `structured_attempt_events`; they do not
change stream heartbeat or terminal lifecycle semantics in this ADR.

Plan 101 returns logical receipt identity only on non-streaming structured
results; stream heartbeat state remains separate and unchanged.

---

<a id="0014-call-replay-and-divergence-diagnosis-boundary"></a>

## ADR 0014: Call Replay And Divergence Diagnosis Boundary

*Originally `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md`.*


Status: Accepted
Date: 2026-03-22
Last verified: 2026-09-11
Verification context: Metadata-only external telemetry does not change call
snapshots, fingerprints, replay authority, selected-attempt receipts,
raw-artifact links, or historical replay. Explicit full-content export remains
outside the replay contract.

### Context

`llm_client` already owns the shared observability boundary for cross-project
LLM execution, but the current surface is stronger at proving that two
operational paths disagree than at explaining why they disagree.

Today we can inspect:

1. call rows and trace rollups,
2. lifecycle events such as `started`, `progress`, `stalled`, `completed`, and
   `failed`,
3. high-level result payloads and experiment aggregates.

That is enough to detect a mismatch between, for example, a proxy evaluation
lane and a live operational path. It is not yet enough to answer the higher
leverage questions cleanly:

1. Did both paths issue the same semantic request?
2. If not, which caller-visible inputs diverged?
3. Can we replay the exact captured call contract through the shared runtime?
4. Which parts of the problem belong in `llm_client`, and which remain
   workflow-specific project logic?

ADR 0007 keeps canonical observability in `llm_client/observability/*` and
requires ADR-level governance for payload-shape changes. ADR 0013 already makes
an important distinction between client-observed truth and provider-internal
inference; the same discipline is needed here.

### Decision

1. `llm_client` owns the shared call-level replay and divergence-diagnosis
   substrate.

2. The canonical shared unit is a **call snapshot**:
   - a normalized representation of one `llm_client` call contract at the
     boundary immediately before provider dispatch,
   - including caller-visible request inputs needed for comparison and replay,
   - excluding purely ephemeral observability metadata such as timestamps,
     call ids, latency, and cost.

3. `llm_client` must expose a stable **request fingerprint** derived from the
   normalized call snapshot:
   - identical semantic call contracts should produce the same fingerprint even
     across different traces or projects,
   - observability-only metadata must not perturb the fingerprint,
   - meaningful caller-visible request differences must appear either in the
     fingerprint or in the compact diff report.
   - version 2 and 3 exact-replay fingerprints additionally bind the public API,
     semantic call kind, and replay-support metadata; trace/project/timing/cost
     metadata remain excluded.
   - version 3 also binds the original call's checked effective `max_budget`.

4. `llm_client` must expose compact **call diff** surfaces that compare two
   captured call snapshots and report only the differences needed for the next
   operator decision:
   - rendered messages / content blocks,
   - structured-output schema or response-format identity,
   - model and routing inputs,
   - relevant transport-affecting kwargs,
   - observed result / error summaries.

5. `llm_client` must expose **call-level replay** over captured snapshots:
   - replay reissues the captured call through the shared `llm_client` runtime,
   - replay must run under an explicit new trace/project tag rather than
     mutating or overwriting the original record,
   - replay is about the call contract, not about reconstructing arbitrary
     workflow state.
   - a captured budget describes the original call but does not authorize new
     spend; version 3 replay requires a fresh explicit finite nonnegative
     budget and dispatches that new value.

6. Workflow-specific reconstruction remains project-local:
   - if reproducing a call requires rebuilding domain workflow state before the
     call boundary, that adapter belongs in the consuming project,
   - once the project can hand `llm_client` a prepared call snapshot or an
     equivalent call contract, comparison and replay belong in shared
     infrastructure.

7. Persistence remains safe-by-default and never truncates:
   - the database remains the primary query index,
   - replayable payloads may be stored directly or by artifact reference, but
     not truncated,
   - compact metadata and fingerprints must remain query-friendly even when the
     full snapshot lives out-of-row.

8. Programmatic tool-call lifecycles are diagnostic siblings of replayable LLM
   calls under a shared trace id. They are not call snapshots and cannot be
   replayed as LLM requests; projects own any operator-input replay adapter.

### Consequences

Positive:
1. Cross-project debugging stops reinventing request comparison logic.
2. Live-vs-proxy disagreements can be localized with shared tools instead of
   ad hoc repo-local scripts.
3. The observability layer becomes more operationally useful without turning
   `llm_client` into a workflow engine.
4. Shared fingerprints and diffs give prompt, schema, and routing work a more
   truthful operational-readiness signal.

Negative:
1. Observability payload shape grows and must be governed carefully.
2. Exact replay increases storage pressure if snapshots are large.
3. Call-level replay cannot prove equivalence of higher-level workflows that
   diverge before the `llm_client` call boundary.

### Testing Contract

1. Snapshot normalization tests must prove that ephemeral metadata does not
   perturb the fingerprint.
2. Diff tests must prove that meaningful caller-visible request changes are
   reported compactly and deterministically.
3. Replay tests must prove that a captured snapshot can be reissued under a new
   trace/project without mutating the original record.
4. Existing observability compatibility tests must continue passing.
5. Any artifact-backed snapshot persistence must prove "no truncation" and
   explicit lookup of the full replayable payload.
6. Tool-call observability changes must preserve the distinction between
   lifecycle diagnosis and replayable LLM call contracts.
7. Structured-attempt lifecycle events diagnose retries and fallback but are
   not replay envelopes. Replay continues to derive from the final call
   snapshot; attempt histories bind by `logical_call_id` and `trace_id`.
8. Budget-complete snapshot tests must cover all four public producer paths,
   budget-sensitive fingerprints, historical v1/v2 reads, malformed budgets,
   and rejection before dispatch when v3 fresh authority is absent.

Last verified: 2026-07-14 (Plan 97 Slice 3 lifecycle expansion).

Validated native-schema attempts are now terminal for retry/fallback even when
later local finalization fails, preventing replay diagnostics from observing a
fabricated second provider generation for a client-side failure.

Snapshot v3 adds the checked original-call budget to the closed replayable
envelope without changing historical v1/v2 interpretation. Snapshots already
marked replay-unsupported remain diagnostic captures and are refused before
reconstruction.

Plan 101 receipt lookup verifies the same v3 fingerprint but remains a
trusted-process provenance read, not replay authority or provider attestation.

Plan 354 removes a duplicate terminal lifecycle emitted by the private
structured runtime. Call snapshots, fingerprints, replay authority,
structured-attempt histories, and terminal call rows are unchanged; the
public wrapper retains one terminal event for the joined logical call.

Plan 356 adds `instructor` as an explicit selected-attempt execution path. Its
receipt is accepted only when the terminal row, call fingerprint, schema, model,
exact raw-content hash, and `started -> received -> validated` history agree.
This remains trusted-process evidence, not provider attestation.

---

<a id="0015-portfolio-runtime-substrate-scope"></a>

## ADR 0015: Present LLM Client As Runtime Substrate Evidence

*Originally `docs/adr/0015-portfolio-runtime-substrate-scope.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/adr/0015-portfolio-runtime-substrate-scope.md`.*


Wiki home: http://localhost:8088/index.php/Project_Wiki

### Status

Accepted.

### Context

`llm_client` is central shared infrastructure, but infrastructure alone is
often weak portfolio evidence. A reviewer may not care that many API surfaces
exist unless those surfaces make an applied system easier to inspect, govern,
or improve.

The repo already owns the cross-project runtime and observability substrate.
Adjacent projects own prompt evaluation, retrieval, qualitative analysis,
workflow orchestration, and applied analytic claims.

### Decision

Portfolio surfaces should present `llm_client` as supporting runtime evidence:

- lead with applied traces where observability changed an engineering decision;
- show cost, latency, route, error, structured-output, and trace data when
  making reliability claims;
- describe API breadth as enabling infrastructure, not as the main achievement;
- leave prompt-evaluation semantics to `prompt_eval`;
- leave project-specific analysis, retrieval, and coding logic to consuming
  projects;
- leave durable workflow orchestration above this runtime layer unless a
  separate ADR changes that boundary.

### Consequences

Benefits:

- makes the portfolio story understandable to non-infrastructure reviewers;
- prevents runtime work from being mistaken for analyst-facing product work;
- keeps ownership boundaries aligned with existing ADRs;
- creates a clear evidence path through downstream applied traces.

Costs:

- the repo's standalone page must be modest about claims;
- strongest evidence depends on downstream project traces;
- API breadth cannot be used as a substitute for applied outcomes.

### Controls

- [docs/APPLIED_OBSERVABILITY_CASE.md](../APPLIED_OBSERVABILITY_CASE.md)
  defines the applied portfolio case shape.
- [docs/REQUIREMENTS.md](../REQUIREMENTS.md) defines scope and non-goals.
- [docs/ops/CAPABILITY_DECOMPOSITION.md](../ops/CAPABILITY_DECOMPOSITION.md)
  defines ownership boundaries.
- [docs/VALIDATION.md](../VALIDATION.md) separates runtime evidence from
  downstream analytic validation.

---

<a id="0016-provider-capability-and-vendor-telemetry-boundary"></a>

## ADR 0016: Provider Capability and Vendor Telemetry Boundary

*Originally `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md`.*


Status: Accepted
Date: 2026-07-22
Applies to: Plan #110

### 2026-09-11 Amendment: External Callback Content Is Metadata-Only by Default

LiteLLM callbacks are an external data boundary, not merely another view over
the local observability store. Enabling Langfuse previously sent request
messages and generated content under LiteLLM's default callback behavior even
when `llm_client`'s local `ObservabilityContentPolicy` was metadata-only.

`llm_client` now defaults requested `langfuse_otel` and legacy `langfuse`
callbacks to `LLM_CLIENT_EXTERNAL_OBSERVABILITY_CONTENT=metadata_only`, which
sets LiteLLM's supported `turn_off_message_logging` switch before registering
the callback. Model, usage, cost, timing, task, and trace metadata remain
available. Prompt and response export requires the explicit value `full`;
unknown values fail before callback registration.

This is a global LiteLLM callback switch, so metadata-only is intentionally the
strongest active policy for the process. A full-content request does not turn
the switch back off if another component has already enabled it. Local
JSONL/SQLite evidence remains authoritative and retains its own independently
configured content policy.

### 2026-08-21 Amendment: A Schema Rejection Is Not a Route Denial at Runtime

The amendment below states the rule for how capability findings are *recorded*:
a schema-specific rejection belongs to that schema, not to the route. The
runtime violated the same rule in the opposite direction, and the 2026-08-20
capability restoration is what exposed it.

`_raise_if_unsupported_gpt5_structured_schema` ran from all four structured-call
exception handlers without consulting `StructuredOutputPolicy`. On the
native-schema path it fired immediately before the
`_is_schema_error(exc) -> _NativeSchemaFallback` hand-off, so a provider saying
"this schema is invalid" was converted into a terminal, route-level
`LLMCapabilityError` — exactly the schema-to-route generalization this ADR
forbids — and it preempted the machinery implementing the documented `auto`
contract, "preserves the historical native-schema-to-Instructor routing".

The failure only became reachable when Luna became native-schema capable.
Callers on the default `auto` policy were silently migrated onto the native path,
and any whose response model was not strict-safe went from working to terminal
failure. Inside Success's meeting-analysis stage did exactly that at
2026-08-20T23:58Z: ~770 failed calls per day against a schema Instructor had
been handling without complaint, reported as a transport incompatibility.

Standing rule: **a capability guard may only be terminal where no recovery
exists.** Where the caller's policy permits a downgrade and the path can perform
one, a schema rejection must remain recoverable. The guard now applies at the
native-schema sites only under a non-strict policy and only for errors the path
will genuinely convert into `_NativeSchemaFallback`; the responses-API sites keep
raising, because no Instructor downgrade exists there.

Corollary for capability changes generally: marking a route native-capable is not
an isolated registry edit. It re-routes every call site that relies on the
default policy. Enumerate those call sites and check each response model for
strict-mode safety before deploying — a green test on the call site that
motivated the change proves nothing about its siblings.

Verified 2026-08-21.

### 2026-08-20 Amendment: A Bounded Probe Result Is Not a Route Capability

`openrouter/openai/gpt-5.6-luna` returns to `native_structured_output: true`,
restoring the state Plan #339 delivered in `21735e0` and that `0a7c87c`
reverted for Luna alone on 2026-08-07 without recorded evidence.

The reverted setting is the failure mode this ADR exists to prevent, in the
opposite direction from Plan #110's ban work: a single large Process Tracing
schema found no accepting endpoint on 2026-07-29, and that bounded result was
generalized into a permanent route-level capability denial. Plan #339's Gap
section had already named this exact conversion as the defect.

Re-probed 2026-08-20 against the Inside Success bounded-extraction schema:
OpenRouter accepts Luna's native request and returns
`response_format.json_schema` with `strict=true`, `additionalProperties=false`,
`finish_reason=stop`, and valid JSON across five consecutive pipeline calls.

The denial was not conservative. Downgrading to Instructor sends the schema as a
non-enforced hint (`strict=None`, `response_format=null`), and an unenforced
schema let the model append array items until the 65,536-token output ceiling
truncated the JSON mid-string — output that can never validate, at ~14x the cost
of a healthy call. **A capability denial that silently selects an unenforced
transport is a correctness change, not a safe default**, and must carry evidence
of the same standard as a capability claim.

Standing rule: record capability findings at the granularity observed. A
schema-specific rejection belongs to that schema, not to the route. Where a
route's capability is genuinely uncertain, prefer failing loudly
(`StructuredOutputPolicy(mode="require_native_json_schema")`) over silently
routing to an unenforced transport.

Verified 2026-08-20.

### 2026-08-05 Amendment: Provider Exclusion and Malformed-JSON Recovery

Plan #349 adds `ignored_providers` to `OpenRouterRoutePolicyV1` and compiles it
to OpenRouter's native `provider.ignore` field. Exclusions are explicit
caller-owned routing intent, retained in call snapshots and replay identity;
they do not create a shared endpoint-health database. Allowed and ignored
provider sets must be non-empty, duplicate-free, and disjoint when supplied.

A syntactically malformed structured response remains retryable only within the
caller's existing retry, deadline, and budget bounds. The next attempt receives
a concise instruction to return only valid JSON matching the supplied schema.
This recovery does not retry a response that already satisfies the Pydantic
contract, and therefore does not move application semantic judgment into the
shared runtime.

### 2026-08-04 Amendment: GPT-5.4 Ban and Luna Default

Plan #348 hard-blocks every GPT-5.4-family route before dispatch, including
raw, OpenRouter, Mini/Nano, fallback, and Codex aliases. GPT-5.4 is removed
from the exact execution allowlist, capability table, packaged registry, and
maintained workflow defaults. GPT-5.6 Luna becomes the shared execution default
and replaces GPT-5.4 on maintained Codex workflow surfaces. When Luna cannot
satisfy a required execution contract, callers must select and justify an
explicit non-GPT-5.4 route; they may not silently revive GPT-5.4.

### 2026-08-17 Amendment: Compatibility-Aware Workload Routing

Plan #361 replaces the unsafe global Codex subscription default with an
explicit `WorkloadRouteContext` and `resolve_workload_route()` contract. Codex
subscription capacity is chosen only for a declared compatible interactive or
trusted-private workload with supported subscription authentication and known
available included capacity. Managed automation, service/API requirements, and
unsupported subscription authentication select the direct OpenAI API route.

OpenRouter remains an explicit edge route: a required router capability
(including non-OpenAI model access, multi-provider routing, or provider
controls) or a current recorded value comparison can select it. Subscription
exhaustion fails locally until the caller records whether paid Codex credits,
direct OpenAI API, or OpenRouter won the live comparison; it is never automatic
OpenRouter overflow. The legacy `DEFAULT_EXECUTION_MODEL` remains only for
unmigrated callers and does not express the new workload-routing policy.

### 2026-07-31 Amendment: OpenRouter Exact-Response Cache Policy

Plan #347 extends `OpenRouterRoutePolicyV1` with an explicit, default-off
exact-response cache mode and an optional TTL. `enabled` compiles to
`X-OpenRouter-Cache: true`; `refresh` additionally clears and replaces only the
matching entry; `disabled` sends the explicit provider opt-out when a typed
policy is present. TTLs fail locally outside OpenRouter's documented 1–86,400
second range.

Response caching retains generated content at OpenRouter's edge for the selected
TTL, so enabled and refresh modes conflict locally with
`zero_data_retention=True`. Raw response-cache headers also conflict with a
typed policy: callers may use the broad raw-header escape hatch only when they
do not claim typed cache governance.

OpenRouter hashes the complete provider request body. Therefore a cache-enabled
call retains `llm_client` task/trace custody locally but does not project its
unique per-call identity into OpenRouter's request-body Broadcast `trace` field.
An explicit caller-owned Broadcast trace is rejected for a cache-enabled call
rather than silently defeating reuse. Attribution and route-metadata headers do
not enter OpenRouter's cache key, although a cache hit does not return stale
router metadata.

This is distinct from provider prompt caching and from durable consumer stage
artifacts. OpenRouter does not coalesce concurrent misses and may evict entries;
consumers remain responsible for content-addressed resumability, single-flight,
schema and algorithm invalidation, and source-custody rules. Local/provider
usage telemetry remains evidence of billed versus cached tokens; one bounded
live repeated-call probe is required before a consumer advertises the route as
working.

### 2026-07-27 Amendment: Typed OpenRouter Route Policy

Plan #336 adds `OpenRouterRoutePolicyV1` as the supported named public
contract for stable OpenRouter provider-routing requirements: provider
allowlists, data-collection mode, zero-data-retention, same-model provider
fallback permission, sorting, and `require_parameters=true`. `llm_client`
compiles this object into OpenRouter's native `provider` payload, retains the
canonical policy in call snapshots, and rejects ambiguous raw `provider` kwargs
when the typed policy is present.

This amendment does not create a local endpoint inventory or preflight call.
OpenRouter remains the runtime authority on whether a current endpoint satisfies
the fixed model and requested constraints. An OpenRouter response that no
endpoint can satisfy those constraints is a non-retryable
`LLMNoCompatibleRouteError`, not evidence that the model is absent.

The policy constrains routing only. It does not authorize a provider to receive
private source fields; callers remain responsible for an authorization covering
every allowed upstream processor. Every resolved primary/fallback model leg
must be an OpenRouter route when this policy is used, and embeddings remain
outside the typed-policy surface.

### 2026-07-23 Amendment: Explicit Reasoning Policy

Plan #117 makes reasoning selection an explicit pre-dispatch policy for exact
allowlisted routes that expose configurable effort. Omission is no longer
interpreted as provider default. The caller must resolve an effort, including
`none` for explicit off where supported; unsupported values, forbidden off
states, and incompatible fallback chains fail locally.

Reviewed per-model capability metadata is enforcement authority. LiteLLM and
provider transports still own payload translation. `llm_client` does not fetch
mutable provider metadata during calls or implement provider-specific
application payloads. The resolved policy is bound into routing evidence,
replay identity, and cache identity.

Direct Gemini's prior automatic thinking default is superseded for governed
reasoning-policy calls. Codex receives the same normalized decision through its
SDK-specific `model_reasoning_effort` transport rather than choosing `high`
when omitted.

### 2026-07-23 Amendment: Exact Model Execution Allowlist

Plan #115 supersedes this ADR's ban-oriented model-selection policy while
preserving its provider-capability and telemetry decisions.

`llm_client` evaluates every canonical primary/fallback chain against one exact
shared allowlist before dispatch. DeepSeek V4 Flash is the sole
no-justification default. Every other allowed route requires a non-empty
`model_justification`, which is retained in the routing trace and replayable
call snapshot. A justification cannot authorize an unlisted model. The former
`compatibility` mode was removed by Plan #116 and is now rejected.

GPT-5 Mini and GPT-5.1 Mini are not allowlisted and are also hard-blocked,
together with Codex Mini routes.

The statement below that normalized public controls are forwarded “without a
model-family allowlist” refers only to capability-specific branching after
model authorization. It no longer means arbitrary models may execute.

### Context

`llm_client` exists so applications can use provider capabilities without
growing provider branches in every consumer. Two gaps made that boundary less
general than intended:

1. the public `reasoning_effort` option was forwarded only for hard-coded
   OpenAI and Anthropic families, even though OpenRouter and DeepSeek expose the
   same normalized control; and
2. required `task` and `trace_id` metadata reached local observability and
   LiteLLM callbacks, but not OpenRouter's native Broadcast trace envelope.

OpenRouter already normalizes reasoning controls and can broadcast request
traces to established observability backends. LiteLLM already owns commodity
transport normalization. Reimplementing either facility would add a second
capability matrix and a second telemetry exporter.

At the same time, vendor telemetry cannot replace local evidence. It does not
cover direct providers, workspace-agent SDKs, cache hits, pre-dispatch policy
failures, local schema validation, retry/fallback dispositions, or local budget
enforcement.

The user also requires Opus-family models to be unavailable through
`llm_client`, including workspace-agent aliases. A ban that applies only to raw
chat routes would be misleading. OpenRouter Auto Router, presets, and provider
fallback arrays can select a final model after the primary model string is
checked, so opaque model selection is also inside the ban's threat model.

### Decision

1. Normalized public controls are forwarded without a model-family allowlist.
   The selected provider/transport remains responsible for accepting or
   rejecting the control. `llm_client` must not silently discard it.
   When an installed LiteLLM capability table lags a documented OpenRouter
   normalized control, the OpenRouter transport declares that control through
   LiteLLM's `allowed_openai_params` compatibility seam and sets
   `provider.require_parameters=true`. A caller may still choose provider
   sorting and fallback policy, but may not opt into silently ignored controls.
2. The existing broad provider-kwargs surface remains the escape hatch for new
   provider features that do not yet have a normalized public option.
3. For OpenRouter calls, `llm_client` projects its required `task` and
   `trace_id` into OpenRouter's `trace` object without overwriting caller-owned
   trace fields. Account-side Broadcast configuration remains outside the
   library.
4. Local JSONL/SQLite evidence remains authoritative for `llm_client` execution
   semantics. OpenRouter logging/Broadcast and LiteLLM callbacks are optional,
   complementary projections.
5. Opus-family model IDs and aliases are hard-blocked before dispatch in every
   execution mode. The model registry, model-policy audit, public examples, and
   workflow defaults must not select Opus.
6. Every resolved fallback leg is checked. OpenRouter Auto Router, presets, and
   the auto-router plugin are rejected because their candidate sets are not
   locally inspectable; provider `models`/`fallbacks` arrays are accepted only
   when they contain no banned or opaque selector. Fixed-model provider sorting
   remains supported. Account Guardrails are recommended defense in depth, not
   a substitute for local enforcement.
7. Claude workspace-agent defaults that previously selected Opus move to
   Sonnet. The ordinary `max_intelligence` tier selects the best remaining
   non-banned registered candidate under its existing ordering; this decision
   does not create a special replacement route.

### Borrow Versus Build

- **Borrow:** OpenRouter reasoning parameters, OpenRouter Broadcast/OTLP
  exporters, and LiteLLM provider transport.
- **Build:** small normalization/projection seams, invariant enforcement, local
  evidence, and deterministic contract tests.
- **Do not build:** another provider capability database, another OTLP
  exporter, or an OpenRouter-specific application client.

### Consequences

Positive:

1. Newly standardized controls can work without adding model-family branches.
2. OpenRouter users can enable existing observability destinations without
   application instrumentation while retaining local forensic evidence.
3. Opus cannot be reached indirectly through agent aliases, defaults,
   fallbacks, Auto Router, or presets.

Negative:

1. An unsupported normalized control now fails at the provider instead of being
   silently ignored.
2. Local and vendor traces may both exist and need a shared trace identifier.
3. Existing workflows that depended on Opus change model behavior when their
   defaults move to Sonnet.
4. Callers cannot use account-side model selectors while the non-overridable
   local model ban is active; they must request an explicit model.

### Testing Contract

1. Sync and async call preparation must forward DeepSeek/OpenRouter
   `reasoning_effort`.
2. OpenRouter calls must merge `task` and `trace_id` into Broadcast metadata
   while preserving explicit caller fields; non-OpenRouter calls must not gain
   the vendor envelope.
3. Raw Opus IDs, OpenRouter Opus IDs, `claude-code/opus`, Opus fallback legs,
   Auto Router, and presets must all fail before provider or agent dispatch.
4. Opus must not appear as a selectable packaged-registry model or workflow
   default.
5. Local observability tests remain unchanged and green.
6. OpenRouter reasoning controls must set `provider.require_parameters=true`,
   preserve other provider-routing fields, and reject an explicit false value.

Plan 354 changes only local structured terminal-lifecycle ownership. Provider
selection, capability enforcement, OpenRouter policy, vendor telemetry, model
allowlisting, and explicit reasoning behavior remain unchanged; composed
sync/async structured controls pass.
