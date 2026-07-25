# Plan #117: Explicit Reasoning Policy

**Status:** ✅ Complete

**Verified:** 2026-07-24T03:50:46Z
**Verification Evidence:**
```yaml
completed_by: scripts/complete_plan.py
timestamp: 2026-07-24T03:50:46Z
tests:
  unit: 1870 passed, 3 skipped, 12 deselected, 17 warnings in 201.88s (0:03:21)
  e2e_smoke: skipped (no e2e directory)
  e2e_real: skipped (--skip-real-e2e)
  doc_coupling: passed
commit: de0d2ad
```
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** cost- and latency-controlled reasoning-model execution

---

## Gap

**Current:** Reasoning-capable routes may execute with an omitted
`reasoning_effort`. Providers then choose their own defaults; Codex silently
defaults to `high`; direct Gemini may receive a client-default thinking budget;
and text/structured cache keys omit the normalized effort.

**Target:** Every exact allowlisted route with configurable reasoning requires a
validated explicit effort before cache lookup or provider/agent dispatch.
`reasoning_effort="none"` is the explicit off state where supported. Missing,
unsupported, and forbidden-off policies fail locally. The resolved policy is
preserved in routing evidence, replay identity, and cache identity.

**Why:** Provider-default reasoning can add substantial latency and output-token
cost without a caller decision. The shared runtime must make that decision
explicit once instead of relying on project-local provider payloads.

---

## References Reviewed

- `llm_client/core/model_execution_policy.py` — exact execution allowlist and
  pre-dispatch policy boundary.
- `llm_client/core/client_dispatch.py` — canonical route resolution.
- `llm_client/execution/{text,structured,stream,completion}_runtime.py` —
  dispatch, cache, and normalized-control paths.
- `llm_client/sdk/agents.py` — current Codex default/coercion behavior.
- `llm_client/observability/replay.py` — call snapshot and replay identity.
- `docs/adr/0002-routing-config-precedence.md` — explicit-call precedence.
- `docs/adr/0009-long-thinking-background-polling.md` — effort-dependent runtime
  behavior.
- `docs/adr/0014-call-replay-and-divergence-diagnosis-boundary.md` — meaningful
  controls must affect fingerprints and replay.
- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md` and Plan
  110 — normalized controls and fail-loud provider support.
- `docs/plans/27_direct-gemini-thinking-budget-policy.md` — superseded automatic
  direct-Gemini thinking default.
- OpenRouter reasoning documentation and `GET /api/v1/models`, observed
  2026-07-23 — per-model mandatory/default/supported-effort metadata.
- Official OpenAI model documentation, observed 2026-07-23 — direct GPT-5.5
  and GPT-5.6 effort sets and defaults.
- Installed LiteLLM provider-free normalization probe — direct Gemini 2.5/3
  normalized effort translation.

---

## Files Affected

- `llm_client/core/model_execution_policy.py`
- `llm_client/core/client_dispatch.py`
- `llm_client/execution/text_runtime.py`
- `llm_client/execution/structured_runtime.py`
- `llm_client/execution/stream_runtime.py`
- `llm_client/execution/completion_runtime.py`
- `llm_client/sdk/agents.py`
- focused model-policy, provider-kwargs, cache, streaming, and agent tests
- generated API reference and public reasoning documentation
- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md`
- `docs/plans/CLAUDE.md`
- `scripts/relationships.yaml`

---

## Boundaries And Rules

1. Exact canonical model identity owns reasoning capability policy; name-family
   inference is not enforcement authority.
2. Configurable reasoning requires a non-empty normalized effort on every model
   in the resolved primary/fallback chain.
3. `none` is explicit off, never omission. It is rejected for
   reasoning-mandatory models.
4. Unsupported efforts fail locally rather than relying on OpenRouter's nearest
   supported-effort remapping.
5. Models without a configurable effort surface remain unaffected.
6. The same resolved effort is applied to every fallback leg. A mixed chain is
   rejected if that effort is invalid for any configurable leg.
7. Direct Gemini no longer receives an automatic thinking budget when an
   explicit normalized reasoning policy is required.
8. Codex receives the normalized policy as `model_reasoning_effort`; silent
   defaulting and effort coercion are removed from the governed path.
9. Cache keys, call snapshots, replay, routing evidence, sync/async, structured,
   stream, and batch delegation preserve the same effort.

---

## Required Tests

| Test family | What it proves |
|---|---|
| model execution policy | missing, unsupported, forbidden-off, fallback mismatch, and valid explicit policies |
| public text/structured sync+async | rejection occurs before cache/provider dispatch |
| cache identity | otherwise-identical `none`, `high`, and `xhigh` calls cannot collide |
| provider kwargs | valid effort reaches OpenRouter, Responses, and direct Gemini without an automatic thinking default |
| streaming sync+async | policy validation precedes provider stream creation |
| Codex adapter | explicit normalized effort reaches the SDK/CLI; omission and unsupported coercions fail |
| replay/fingerprint | effort differences remain replayable and change request identity |

---

## Acceptance Criteria

- [x] Every configurable allowlisted route has reviewed exact capability data.
- [x] Omitted effort fails before cache lookup or provider/agent dispatch.
- [x] `none` works only where off is supported.
- [x] Unsupported effort and incompatible fallback chains fail locally.
- [x] Effort is part of text and structured sync/async cache identity.
- [x] Direct Gemini and Codex no longer choose an implicit reasoning level.
- [x] Snapshot/replay/routing evidence preserve the resolved effort.
- [x] Focused tests, the full feasible suite, changed-file lint, generated API
      drift, relationship validation, and required-reading gates pass.
- [x] Changes are committed and pushed on the Plan 117 branch.

## Verification Notes

- Full suite: 1,870 passed, 3 skipped, 12 deselected.
- The changed policy/runtime files pass Ruff; the repository-wide lint and
  strict mypy commands still report pre-existing facade and typing debt outside
  this plan.
- `check_agents_sync.py --check` remains blocked by the committed
  `AGENTS.md -> CLAUDE.md` symlink, which the validator refuses to overwrite.
  Plan 117 does not change either governance file.

---

## Non-Claims

- This does not select the best effort for any workload.
- This does not guarantee a provider uses the requested number of hidden tokens.
- This does not add a runtime fetch of mutable provider capability metadata.
- Models that expose reasoning but no configurable effort remain outside this
  effort-specific enforcement until a normalized explicit control exists.
