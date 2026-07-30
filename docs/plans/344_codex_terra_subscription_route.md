# Plan #344: Codex GPT-5.6 Terra Subscription Route

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Cybernetic Influence Packet 21B2 pressure and stabilization canaries

---

## Gap

**Current:** ChatGPT-authenticated Codex execution is certified only for
`codex/gpt-5.6-luna`; Terra identifiers currently select OpenRouter or direct
OpenAI API routes.

**Target:** Admit the exact `codex/gpt-5.6-terra` identity at medium reasoning,
prove it through the existing isolated CLI structured-output path, and let the
consumer separately certify its exact schemas before advertisement.

**Why:** Luna repeatedly returned an explicit capacity rejection during an
authorized long-running Cybernetic Influence canary. The operator approved a
Terra switch when it shortens the path to valid results.

## References Reviewed

- `CLAUDE.md` and `docs/plans/340_codex_luna_subscription_route.md`
- ADRs 0001, 0002, 0003, 0004, 0009, 0010, 0014, and 0016
- `docs/plans/117_explicit_reasoning_policy.md`
- `llm_client/core/model_execution_policy.py`
- `llm_client/sdk/agents.py`

## Files Affected

- `llm_client/core/model_execution_policy.py`
- `tests/test_codex_terra_subscription.py`
- `docs/guides/codex-integration.md`
- `docs/plans/CLAUDE.md`
- `docs/plans/344_codex_terra_subscription_route.md`

## Plan

1. Add only the exact subscription identity and medium reasoning contract.
2. Prove allowlist rejection/acceptance and exact CLI model projection.
3. Run one real structured call with ChatGPT authentication and no fallback.
4. Publish the candidate for the downstream simulator's schema certification.

## Required Tests

| Test | What it proves |
|---|---|
| Terra policy control | only explicit medium reasoning is admitted |
| CLI command control | the route executes `gpt-5.6-terra`, not OpenRouter |
| real structured probe | ChatGPT-authenticated Terra validates and records subscription billing |

## Acceptance Criteria

- [x] Exact Terra identity reaches the existing Codex CLI adapter.
- [x] Unsupported effort and missing justification fail before dispatch.
- [x] No fallback or OpenRouter route is introduced.
- [x] One real structured result validates with subscription-included billing.
- [x] Focused tests and changed-file checks pass.

## Observed Evidence

- Candidate `7501811bee49fe4c20af2d2a50e4040a596b328b` passes 34 focused
  model-policy, Luna-regression, and Terra-route tests after rebasing onto the
  current strict-schema mainline.
- A direct `CoderOutput` probe completed through ChatGPT-authenticated
  `codex/gpt-5.6-terra` at medium reasoning with subscription-included billing,
  no fallback, and zero metered cost.
- Cybernetic Influence deployed the exact client revision and certified its
  generic participant, narrator, five Coordination-person, and evidence-coder
  schemas. Same-route live runs `run_994222dd246f` and `run_e2c6181e721f`
  completed 158 aggregate calls with no error, retry, fallback, or metered
  cost.

## Non-Claims

- This does not make Terra a shared task-tier default.
- This does not establish Terra as generally better than Luna.
- This does not advertise Terra in any consumer before consumer-schema
  certification.
