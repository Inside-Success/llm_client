# Run and Operational Evidence Records

Dated probe, certification and operational-inventory records.

Each section below was a separate file until 2026-10-07. Its anchor is the old file name without `.md`, so an old path such as `docs/ops/2026-07-09-worktree-disposition-report.md` maps to `docs/runs/RUNS.md#2026-07-09-worktree-disposition-report`. Section bodies are the original text with headings demoted one level and links to other consolidated records repointed.

## Contents

- [`llm_client` worktree disposition report — 2026-07-09](#2026-07-09-worktree-disposition-report)
- [OpenRouter GPT-5.6 planner-schema compatibility — 2026-07-21](#2026-07-21_openrouter_gpt56_planner_schema_compatibility)
- [OpenRouter GPT-5.6 Sol authoring-schema certification](#2026-07-25_openrouter_gpt56_sol_authoring_schema_certification)
- [Typed OpenRouter Route Policy Probe — 2026-07-27](#2026-07-27_typed_openrouter_route_policy_probe)

---

<a id="2026-07-09-worktree-disposition-report"></a>

## `llm_client` worktree disposition report — 2026-07-09

*Originally `docs/ops/2026-07-09-worktree-disposition-report.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/ops/2026-07-09-worktree-disposition-report.md`.*


### Method

The inventory uses local `git worktree list --porcelain`, checkout status,
`git merge-base --is-ancestor <tip> main`, `git cherry main <tip>`, and branch
upstream refs. No historical branch is merged or deleted merely because its
checkout is clean. `unique patches` is the `+` count from `git cherry`; zero
means patch-equivalent or already represented, not necessarily ancestor-equal.

At baseline, the canonical root reported one untracked entry only because the
first sanctioned in-repo lane preceded the `worktrees/` ignore rule. The final
canonical root is clean on `main`.

### Recorded disposition

| Checkout | Branch/ref | Main evidence | Unique patches | Recovery evidence | Action |
|---|---|---:|---:|---|---|
| `llm_client` | `fix/instructor-retry-unwrapping` | not ancestor | 4 | `origin/fix/instructor-retry-unwrapping` | Root restored to `main`; branch retained |
| `_worktrees/llm_client-gemini-merge` | detached `e9a0cbf` | ancestor | 0 | `main` | Checkout removed |
| `_worktrees/llm_client-gemini-schema-study` | `gemini-schema-study` | not ancestor | 0 | `origin/gemini-schema-study` | Checkout removed; branch retained |
| `_worktrees/llm_client-gemini31-parity` | detached `37623ec` | ancestor | 0 | `main` | Checkout removed |
| `llm_client-reviewmain` | `main` | exact `main` | 0 | `origin/main` | Checkout removed; canonical root now `main` |
| `llm_client-reviewmain/worktrees/codex-review-prompts-as-assets-20260624` | `codex/review-prompts-as-assets-20260624` | not ancestor | 4 | matching `origin/*` branch | Checkout and stale gitlink removed; branch retained |
| `llm_client/worktrees/worktree-lifecycle-governance-20260709` | Plan #92 | merged | 0 before work | completed claim and merged `main` | Closed through merge gate |
| `llm_client_worktrees/agent-collab-package` | `brian/agent-collab-package` | ancestor | 0 | `main` and matching `origin/*` | Checkout and merged local branch removed |
| `llm_client_worktrees/codex/recovered-control-churn-outcomes-20260622` | same | not ancestor | 1 | matching `origin/*` branch | Checkout removed; branch retained |
| `llm_client_worktrees/codex/submit-retry-state-progress-20260622` | same | not ancestor | 1 | matching `origin/*` branch | Checkout removed; branch retained |
| `llm_client_worktrees/merge-plan-91-into-main-20260405` | same | not ancestor | 3 | matching `origin/*` branch | Checkout removed; branch retained |
| `llm_client_worktrees/plan-22-run-progress-observability` | same | not ancestor | 2 | matching `origin/*` branch | Checkout removed; branch retained |
| `llm_client_worktrees/plan-52-llm-client-dead-code` | same | not ancestor | 5 | matching `origin/*` branch | Checkout removed; branch retained |
| `llm_client_worktrees/reconcile-main-with-origin-20260405` | same | ancestor | 0 | `main` and matching `origin/*` | Checkout and merged local branch removed |
| `~/worktrees/llm-client-anomaly-phase18` | `anomaly-phase18-worktree-projects` | not ancestor | 4 | local branch only | Checkout removed; local branch retained |
| `~/worktrees/llm-client-anomaly-phase18-merge` | `merge-anomaly-phase18-20260405` | ancestor | 0 | `main` | Checkout and merged local branch removed |
| `~/worktrees/llm-client-anomaly-phase19` | `anomaly-phase19-gpt54-codex` | not ancestor | 0 | local branch; patch represented on `main` | Checkout removed; branch retained |
| `~/worktrees/llm-client-anomaly-phase19-merge` | `merge-anomaly-phase19-20260405` | not ancestor | 0 | matching `origin/*` branch | Checkout removed; branch retained |
| `~/worktrees/llm-client-anomaly-phase20-merge` | `merge-anomaly-phase20-20260405` | ancestor | 0 | `main` and matching `origin/*` | Checkout and merged local branch removed |
| `~/worktrees/llm-client-gemini-shared-cap` | `anomaly-phase20-gemini-shared-cap` | not ancestor | 0 | matching `origin/*` branch | Checkout removed; branch retained |
| `~/worktrees/llm-client-observability-config-truthfulness` | `plan26-observability-config-truthfulness` | not ancestor | 1 | local branch; upstream configured as `origin/main` | Checkout removed; local branch retained |
| `/tmp/.../scratchpad/llmclient-main` | detached `c8ec030` | registration missing | 0 | patch represented on `main` | Missing registration pruned |
| `llm_client/worktrees/codebase-memory-usage-ledger-20260709` | same | ancestor | 0 | `main` | Late-discovered clean checkout and merged local branch removed |

### Decision queue after checkout cleanup

Nine retained branches have patches unique relative to `main` and require
intent/code review before merge or abandonment. Four additional retained
branches have no unique patch but are not ancestors and should be explicitly
closed only after confirming their historical purpose. This plan removes their
idle checkouts but deliberately does not guess those branch decisions.

### Cleanup discovery

The nested review checkout was not merely an ignored directory: commit
`87ff8a3` had added it to `main` as a mode-`160000` gitlink at tip `1f5d6b7`.
Removing the registered checkout correctly made its parent checkout show a
tracked deletion. The parent was restored instead of force-removed; Plan #92's
claimed follow-up removes the dead gitlink while the named local and remote
branch continue to retain the unique commits.

### Reconciliation result

Before the final evidence lane was created, `git worktree list` contained only
the canonical `/home/brian/projects/llm_client` checkout. It was clean on
`main`, with local and remote default branches both at `617d0fc`. All 13
non-ancestor branches in the decision queue still resolved. The final evidence
lane is temporary and is removed through the same merge gate after this report
lands.

### Branch review decisions

The 13 retained non-ancestor branches were reviewed read-only against
`main@a73031f`. The user approved execution of all high-confidence decisions.
No stale branch is merged wholesale.

| Branch | Decision | Confidence | Execution |
|---|---|---:|---|
| `fix/instructor-retry-unwrapping` | Retain for `secure-trace-browser-salvage` | High | Retained |
| `gemini-schema-study` | Superseded; delete local and feature-remote refs | Very high | Executed |
| `codex/review-prompts-as-assets-20260624` | Retain for `adversarial-review-prompt-asset-migration` | High | Retained |
| `codex/recovered-control-churn-outcomes-20260622` | Rejected by current failure-taxonomy contract; delete | High | Executed |
| `codex/submit-retry-state-progress-20260622` | Rejected by Plan #91 evidence contract; delete | High | Executed |
| `merge-plan-91-into-main-20260405` | Superseded; delete local and feature-remote refs | Very high | Executed |
| `plan-22-run-progress-observability` | Retain for `durable-run-progress-v2` | High | Retained |
| `plan-52-llm-client-dead-code` | Archive immutable tip; delete branch refs | High | Executed |
| `anomaly-phase18-worktree-projects` | Runtime behavior superseded; delete feature refs | High | Executed |
| `anomaly-phase19-gpt54-codex` | Exact patch on `main`; delete feature refs | High | Executed |
| `merge-anomaly-phase19-20260405` | Duplicate integration copy; delete branch refs | High | Executed |
| `anomaly-phase20-gemini-shared-cap` | Exact patches on `main`; delete branch refs | High | Executed |
| `plan26-observability-config-truthfulness` | Retain for `observability-config-truthfulness-v2` | High | Retained |

#### Review findings that constrain salvage

- The trace-browser branch exposes raw trace content through an unauthenticated
  `0.0.0.0`/CORS-`*` backend and accepts result URLs without a safe-scheme
  allowlist. Its useful UI/schema work requires redaction, bounded previews,
  deterministic aggregation, access controls, and tests before porting.
- The prompt-assets branch targets package fallback while the current resolver
  prefers the external canonical prompts store. Only the prompt-extraction
  intent should be ported; its wiki-manifest and ignore commits are stale.
- Durable run-progress remains a real missing generic capability, but the old
  implementation permits orphan progress rows, can erase a stage with
  `stage=None`, and conflicts with current observability schemas.
- The observability-config backup addresses real import-time configuration and
  test-isolation gaps. Its documentation is stale and dynamic SQLite path
  switching requires a concurrency audit before porting.
- Focused current-main verification executed 73 tests across Gemini schema,
  provider routing/cooldowns, adversarial review, failure taxonomy, Plan #91,
  and progress observability; all passed.

#### Execution evidence

- Nine reviewed local branches and their nine same-named feature-remote refs
  were deleted. No target tip changed between review and deletion.
- Plan #52 tip `94b59d7` is retained by the pushed annotated tag
  `archive/plan-52-llm-client-dead-code-20260709` before its branch refs were
  deleted.
- The separately named, unreviewed remote backup refs for anomaly phases 18
  and 19 remain untouched.
- Seven stale legacy coordination claims associated with deleted or retained
  reviewed branches were released after their owner sessions were confirmed
  stale.
- The four forward-port branches still resolve at their reviewed tips:
  `fix/instructor-retry-unwrapping@3def0e3`,
  `codex/review-prompts-as-assets-20260624@1f5d6b7`,
  `plan-22-run-progress-observability@c3746d2`, and
  `plan26-observability-config-truthfulness@86733ac`.

---

<a id="2026-07-21_openrouter_gpt56_planner_schema_compatibility"></a>

## OpenRouter GPT-5.6 planner-schema compatibility — 2026-07-21

*Originally `docs/runs/2026-07-21_openrouter_gpt56_planner_schema_compatibility.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/runs/2026-07-21_openrouter_gpt56_planner_schema_compatibility.md`.*


### Decision

GPT-5.6 Terra and Luna are registered as explicit OpenRouter planner
candidates. Terra is the preferred DIGIMON graph-planner candidate; Luna is a
lower-latency candidate for simpler bounded decisions. Neither becomes a
shared tier default from this evidence alone.

### Real contract exercised

The retained input was DIGIMON call `13449946` from trace
`digimon.query.394c4e7c1dc044f88dcedd32e6b965ab`, task
`digimon.query.dynamic_plan`. It contained the real planner system prompt,
89,623-character user context, and the captured
`PlannerRuntimeEnvelope_1457d37e879b_stop` schema.

The unmodified Pydantic provider schema failed on both OpenRouter routes before
generation because the endpoint rejected `oneOf` under `decision`. The planner
union is discriminated by required, mutually exclusive `action` constants.
Projecting that one union to `anyOf` preserves its accepted values while local
Pydantic validation continues to use the original contract.

### Results

| Route | Trace | Wall time | Tokens | Cost | Result |
|---|---|---:|---:|---:|---|
| `openrouter/openai/gpt-5.6-terra` (medium) | `digimon.model_compatibility.terra-medium.anyof.20260721` | 9.439 s | 34,849 in / 198 out | $0.11187125 | Provider JSON and original local schema valid; selected `relationship.vdb` with a relevant Shipping query. |
| `openrouter/openai/gpt-5.6-luna` (medium) | `digimon.model_compatibility.luna-medium.anyof.20260721` | 4.321 s | 34,849 in / 467 out | $0.0463625 | Provider JSON and original local schema valid; selected `structured.cypher` with a relevant roster-evidence rationale. |
| `openrouter/openai/gpt-5.6-terra` (medium), normal `acall_llm_structured` path | `llm_client.gpt56_terra.discriminated_union.runtime.20260721` | 4.696 s | retained in observability | $0.0011675 | Runtime projected the provider schema, returned `search`, and validated the unchanged local discriminated union. |

The runtime repair rewrites only a `oneOf` whose branches provably require one
common property with unique literal values. Overlapping or unproven unions are
left unchanged and therefore still fail visibly if a provider cannot accept
them.

### Current external metadata

- [OpenRouter Terra](https://openrouter.ai/openai/gpt-5.6-terra): 1M context,
  $2.50/M input and $15/M output.
- [OpenRouter Luna](https://openrouter.ai/openai/gpt-5.6-luna-20260709): 1M
  context, $1/M input and $6/M output.
- Artificial Analysis snapshot reviewed 2026-07-21: Terra medium intelligence
  46, 121 output tokens/s, 1.35 s time to first token; Luna medium intelligence
  38, 192 output tokens/s, 1.75 s time to first token. These are selection
  inputs, not local route certification.

### Scope of evidence

This proves transport and local structural compatibility for one retained,
large DIGIMON planner contract, plus the ordinary `acall_llm_structured`
execution path on a small discriminated union. It does not prove general
semantic superiority, all JSON Schema shapes, every OpenRouter upstream
provider, or full-query latency. A normal full DIGIMON planner trace is still
required before DIGIMON calls the selected route deployment-verified.

---

<a id="2026-07-25_openrouter_gpt56_sol_authoring_schema_certification"></a>

## OpenRouter GPT-5.6 Sol authoring-schema certification

*Originally `docs/runs/2026-07-25_openrouter_gpt56_sol_authoring_schema_certification.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/runs/2026-07-25_openrouter_gpt56_sol_authoring_schema_certification.md`.*


Date: 2026-07-25

### Claim

`openrouter/openai/gpt-5.6-sol` is an explicitly selectable OpenRouter route
for the Cybernetic Influence typed scenario-authoring contract. This evidence
licenses transport and schema compatibility only; it does not assert scenario
quality or make the route an automatic default.

### Environment and invalidation inputs

- Source branch: `feature/openrouter-sol-route`.
- Shared client revision: `0a6d0268d62443499e9ef8cc5208a00ef4573a90`.
- Provider catalog: authenticated `GET https://openrouter.ai/api/v1/models`,
  observed 2026-07-25; the returned model supports `structured_outputs` and
  `reasoning_effort`.
- Contract: Cybernetic Influence `_ProposalConsumer` JSON schema
  `526b57cae5d9108c`.
- Target: local shared-client runtime with the caller's OpenRouter credential.

### Direct contract evidence

| Requested and executed route | Trace | Result | Observed cost |
|---|---|---|---:|
| `openrouter/openai/gpt-5.6-sol` | `cybernetic_influence_v3/authoring/openrouter-sol-certification/20260725` | Native `json_schema` response validated as `resource_request_v1`; no unresolved question | `$0.046620` |

The retained `llm_calls` row records `execution_path=native_schema`, one
successful terminal lifecycle, 1,911 prompt tokens, 1,156 completion tokens,
and 395 reasoning tokens. The returned draft was compiled by the downstream
authoring consumer.

### Negative controls

- Before this route was registered, the exact requested identity failed closed
  at the execution allowlist; it could not silently fall back to direct OpenAI.
- The policy tests reject unlisted models, omitted reasoning for governed
  routes, and unsupported reasoning before provider dispatch.

### Scope

The current evidence is valid only while the exact route, schema, client
source, and OpenRouter credentials remain usable. Any change to those inputs
requires a fresh direct contract probe before advertising the route as usable.

---

<a id="2026-07-27_typed_openrouter_route_policy_probe"></a>

## Typed OpenRouter Route Policy Probe — 2026-07-27

*Originally `docs/runs/2026-07-27_typed_openrouter_route_policy_probe.md`; consolidated 2026-10-07. Full history: `git log --follow -- docs/runs/2026-07-27_typed_openrouter_route_policy_probe.md`.*


**Purpose:** Non-private acceptance evidence for Plan #336's shared-client
route-policy slice. This is not private-data authorization evidence.

### Frozen public input

- Requested model: `openrouter/deepseek/deepseek-v4-flash`
- Prompt: `Return the integer value 1.`
- Response schema: `RoutePolicyProbeV1(value: int)`
- Structured-output policy: `require_native_json_schema`
- Route policy: `data_collection="deny"`, `zero_data_retention=true`,
  provider fallback permitted, and no provider allowlist.
- Retry count: `0`

### Observed result

The call returned `{"value": 1}` and local Pydantic validation succeeded.
The authenticated OpenRouter generation-evidence reader was then allowed to
observe the selected upstream route after the call; it did not select or alter
that route.

| Field | Observed value |
| --- | --- |
| Requested model | `openrouter/deepseek/deepseek-v4-flash` |
| Resolved model | `openrouter/deepseek/deepseek-v4-flash-20260423` |
| Upstream provider | `Fireworks` |
| Upstream endpoint | `955a2bd9-841c-4cec-a92e-dbfd93111b24` |
| Outcome | `parseable` |
| Failure stage | `none` |
| Route observation | `routeobs1_c66946ec710611805c9d8489` |
| Trace | `llm-client/plan-336/nonprivate-probe-v2` |

The generation metadata became available after four bounded 404 retries. Those
were metadata-read retries only; the model call itself ran once.

### Scope boundary

This observation establishes that the new typed policy reaches a compatible
OpenRouter upstream for this fixed model and public input. It does not
authorize Fireworks, or any other provider, to process private Slack content.
The Inside Success consumer must supply an explicit authorization-compatible
allowlist before it transmits private source fields.
