# Plan #347: OpenRouter Response Cache Controls

**Status:** In Progress
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** cost-bounded Inside Success corpus preprocessing

---

## Gap

**Current:** OpenRouter can reuse an exact prior response when a caller sends
its response-cache headers, but `llm_client` has no typed public control for
that behavior. Callers can only inject raw headers, which neither expresses the
retention decision beside route policy nor rejects a conflict with
zero-data-retention. Inside Success therefore cannot safely enable exact-call
reuse through its shared runtime.

**Target:** Add explicit, default-off response-cache controls to
`OpenRouterRoutePolicyV1`. Compile them to OpenRouter headers, retain them in
call/replay identity, reject ambiguous raw cache headers and ZDR conflicts, and
prove identical behavior for completion and Responses request preparation.

**Why:** Before corpus-wide processing, exact repeated calls must be eligible
for provider reuse without weakening privacy policy or letting cache behavior
drift outside the durable call contract.

---

## References Reviewed

- `CLAUDE.md` — repository workflow and shared-runtime ownership.
- `llm_client/execution/call_contracts.py` — current typed OpenRouter policy.
- `llm_client/utils/openrouter.py` — policy compilation and header projection.
- `llm_client/observability/replay.py` — typed-policy serialization and request
  fingerprinting.
- `tests/test_openrouter_route_policy.py` and `tests/test_provider_kwargs.py` —
  current route-policy and request-preparation controls.
- `docs/adr/0002-routing-config-precedence.md` — explicit caller policy wins.
- `docs/adr/0003-warning-taxonomy.md` — policy conflicts fail loud.
- `docs/adr/0010-cross-project-runtime-substrate.md` — generic provider controls
  belong in `llm_client`.
- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md` and Plans
  110/117 — normalized provider controls remain durable execution identity.
- OpenRouter response-caching documentation, reviewed 2026-07-31 — exact
  response reuse uses `X-OpenRouter-Cache`, optional TTL uses
  `X-OpenRouter-Cache-TTL`, and concurrent misses are not coalesced.

---

## Boundaries

1. Response caching is disabled by default and requires explicit caller intent.
2. Enabling or refreshing response caching conflicts with
   `zero_data_retention=True` and
   fails locally before dispatch.
3. A TTL is valid only when response caching is enabled or refreshed and must
   be within OpenRouter's documented 1–86,400 second range.
4. When the typed route policy is present, raw response-cache headers are
   rejected rather than merged or silently overridden.
5. Cache-enabled requests retain local task/trace custody but omit OpenRouter's
   request-body Broadcast trace because that per-call value would change the
   exact-response cache key. An explicit caller trace conflicts and fails.
6. Provider prompt-cache token accounting remains unchanged; this plan controls
   only OpenRouter's exact-response cache.
7. Persistent stage artifacts, cross-process single-flight, and resumable corpus
   batches remain consumer responsibilities because their identities include
   preprocessing prompts, schemas, algorithms, and source custody.
8. A discounted asynchronous provider Batch API is not claimed for OpenRouter.

---

## Thin Slice

1. Add failing policy-validation and request-preparation tests.
2. Extend `OpenRouterRoutePolicyV1` with an explicit cache mode and optional TTL.
3. Compile the policy into canonical OpenRouter headers after conflict checks.
4. Prove the policy is present in snapshots and changes request identity.
5. Document the privacy and consumer-ownership boundary and regenerate the
   public API reference.
6. Run focused tests, strict relationship validation, generated-doc checks, and
   the feasible repository suite.

---

## Files Affected

- `llm_client/execution/call_contracts.py`
- `llm_client/utils/openrouter.py`
- `tests/test_openrouter_route_policy.py`
- `tests/test_provider_kwargs.py`
- `docs/adr/0016-provider-capability-and-vendor-telemetry-boundary.md`
- `docs/API_REFERENCE.md` and `docs/API_REFERENCE.html` (generated)
- `docs/plans/347_openrouter_response_cache_controls.md`
- `docs/plans/CLAUDE.md`

---

## Required Tests

| Test family | What it proves |
|---|---|
| policy validation | default-off behavior; enabled/TTL validation; ZDR conflict |
| typed-header compilation | exact cache and TTL headers appear only when authorized |
| raw-header negatives | typed policy cannot be bypassed or contradicted by raw headers |
| completion and Responses preparation | both OpenRouter transports receive the same cache policy |
| non-OpenRouter negative | typed OpenRouter policy remains invalid on direct routes |
| replay/fingerprint | cache mode and TTL are durable request identity |

---

## Acceptance Criteria

- [ ] Response caching remains off when not explicitly requested, and a typed
      disabled policy sends the provider's explicit opt-out header.
- [ ] Enabled caching produces `X-OpenRouter-Cache: true`; an explicit TTL also
      produces `X-OpenRouter-Cache-TTL`.
- [ ] Refresh mode clears and replaces only the exact matching cache entry.
- [ ] ZDR/cache, disabled/TTL, non-positive TTL, and typed/raw-header conflicts
      fail before provider dispatch.
- [ ] Completion and Responses request preparation preserve the same behavior.
- [ ] Cache-enabled requests do not receive a per-call Broadcast trace in the
      provider request body, while local trace custody remains intact.
- [ ] Cache policy serializes into call snapshots and changes fingerprints.
- [ ] Public documentation identifies response caching as provider-side exact
      reuse, distinct from prompt caching and consumer artifact caching.
- [ ] Focused tests, generated API checks, relationship validation, changed-file
      lint/type checks, and the feasible full suite pass.

---

## Downstream Handoff

Inside Success may consume the completed contract only through a separately
reviewed corpus-artifact slice. That slice must key artifacts by source content,
prompt identity, response schema, model, reasoning effort, route/cache policy,
and algorithm version; coalesce concurrent producers; fail on corrupt entries;
and prove hit, invalidation, concurrency, and resumability before full ingestion.
