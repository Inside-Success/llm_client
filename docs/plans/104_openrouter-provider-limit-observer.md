# Plan #104: OpenRouter Provider-Limit Observer

**Status:** Complete
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** onto-canon6 Plan 0141 provider-capped semantic sentinel and Greer governed-mapping stress test

---

## Gap

**Current:** `llm_client` can discover and rotate OpenRouter credentials, but it
cannot prove which credential sources are active or read a key's provider-reported
limit state through a typed, secret-free public boundary. Import-time loading can
also silently repopulate a scrubbed process from the default key file.

**Target:** Provide one source-aware environment inventory plus one explicitly
authorized, canonical `GET /api/v1/key` observer. The shared output preserves exact
decimal lexemes, unlimited/reset/BYOK/management/provisioning/expiry state, and a
SHA-256 key join without exposing the key or claiming enforcement.

**Why:** Greer's hard OSINT corpus needs a real semantic-authoring sentinel. The
generic credential/limit observation belongs in shared infrastructure; onto-canon6
owns attempt eligibility, reservation, and semantic execution policy.

---

## References Reviewed

- `investigations/cross-project/2026-07-15-plan0141-llm-client-provider-observer-seam.md` — source/key/transport seam investigation and failure taxonomy.
- `onto-canon6/docs/plans/plan0141_provider_spend_cap_contract_mockup.md` at `4044cfe7` — accepted observation-versus-enforcement boundary.
- `llm_client/utils/openrouter.py` — current deduplicating key discovery and rotation owner.
- `llm_client/__init__.py` — import-time key-file loading order.
- `llm_client/__main__.py` and `llm_client/cli/adoption.py` — modular CLI registration pattern.
- `docs/adr/0002-routing-config-precedence.md` — explicit configuration precedence.
- `docs/adr/0003-warning-taxonomy.md` — fail-loud typed error boundary.
- `docs/adr/0010-cross-project-runtime-substrate.md` — generic provider/runtime ownership.
- OpenRouter `GET /api/v1/key` and per-key limit documentation — authoritative remote response contract.

---

## Files Affected

- `llm_client/utils/openrouter.py` (modify)
- `llm_client/provider_limits.py` (create)
- `llm_client/cli/provider_limits.py` (create)
- `llm_client/__main__.py` (modify)
- `llm_client/__init__.py` (modify)
- `tests/test_provider_limits.py` (create)
- `tests/test_cli_provider_limits.py` (create)
- `tests/test_cli_smoke.py` (modify)
- `pyproject.toml` (modify)
- `docs/API_REFERENCE.md` and `docs/API_REFERENCE.html` (regenerate)
- `docs/plans/104_openrouter-provider-limit-observer.md` (create/update)
- `docs/plans/CLAUDE.md` (modify)
- `scripts/relationships.yaml` (modify)
- `ISSUES.md` (record discovered instruction-authority friction)

---

## Boundaries and Contracts

1. Environment inspection runs after package import and accepts only one primary
   key plus an explicitly configured absolute, zero-byte, regular, non-symlink
   `LLM_CLIENT_KEYS_FILE`.
2. Multi-key and numbered sources reject even if they duplicate the primary key
   and deduplication would produce a one-key ring.
3. The public observer accepts configuration and explicit provider-read authority,
   never a key, URL, key list, or key-file path.
4. Transport is fixed to canonical OpenRouter HTTPS, with redirects and ambient
   proxy inheritance disabled and a finite configured timeout.
5. The permissive remote parser is separate from the strict public producer model.
   Monetary JSON lexemes become exact `Decimal` values before Pydantic validation.
6. Success and error representations exclude secrets, suffixes, labels, creator
   IDs, bearer headers, and raw provider bodies.
7. `provider_limit_state_observed=true` means only that the authenticated endpoint
   reported state for the fingerprinted key. It never means a request was rejected
   or an invoice ceiling was enforced.

---

## Plan

1. Add negative-first tests for source-aware inventory, key-file/origin controls,
   exact parsing, transport failures, environment substitution, and secret leaks.
2. Extract one private source-aware discovery primitive beside the current
   deduplicating OpenRouter ring.
3. Implement strict public models, typed secret-free errors, environment inspection,
   and the explicitly gated current-key observer.
4. Add a thin JSON CLI with distinct inspect-only and provider-read actions.
5. Regenerate API docs, update relationship/index authorities, run focused and
   repository gates, then perform one bounded authenticated read.
6. Obtain independent capability certification before onto-canon6 consumes the seam.

---

## Required Tests

| Test File | Test / family | What It Verifies |
|---|---|---|
| `tests/test_provider_limits.py` | valid source-aware inventory | one primary key and explicit empty file produce a stable secret-free fingerprint |
| `tests/test_provider_limits.py` | environment negatives | zero/multiple/rotation/duplicate-source/default/nonempty/symlink/relative file and alternate origin fail before HTTP |
| `tests/test_provider_limits.py` | exact response parsing | decimals, unlimited state, reset, BYOK, management/provisioning, and expiry survive exactly |
| `tests/test_provider_limits.py` | transport and substitution negatives | auth/status/redirect/content-type/malformed/non-finite/negative and post-read environment drift fail loud |
| `tests/test_provider_limits.py` | leak scan | no secret or provider-private field appears in models, errors, or dumps |
| `tests/test_cli_provider_limits.py` | inspect/read CLI | help and inspect are provider-free; a live read requires explicit authority; JSON/error envelopes are stable |
| `tests/test_cli_smoke.py` | provider-limit help | new command remains agent-discoverable without provider access |
| gated integration | one real current-key read | exact dedicated key returns a schema-valid envelope without inference |

---

## Acceptance Criteria

- [x] **AC1 (test, grade A):** exactly one primary key plus a verified explicit
  empty key file produces a source-aware, secret-free environment record.
- [x] **AC2 (negative tests, grade A):** every named ambiguous environment and
  credential-source case blocks before network access.
- [x] **AC3 (test, grade A):** provider numeric lexemes parse to exact `Decimal`;
  null unlimited state is preserved.
- [x] **AC4 (negative tests, grade A):** transport, payload, environment-drift,
  and secret-leak attacks fail without exposing raw external data.
- [x] **AC5 (subprocess test, grade A):** an explicit empty key file prevents a
  poisoned default file from repopulating the child.
- [x] **AC6 (observed, grade B):** one authenticated read returns a strict envelope
  for the exact key and performs no inference/model request.
- [x] **AC7 (test, grade A):** focused tests, generated API drift, relationship
  validation, CLI smoke, Ruff, strict mypy for changed modules, and relevant
  repository checks pass.
- [x] **AC8 (independent execution review):** a fresh verifier accepts the exact
  commit and confirms the licensed claim is provider-reported state only.

## Verification Evidence

- Focused contract/CLI/smoke suite: `31 passed, 1 deselected`.
- Gated real-provider integration: `1 passed`; the strict envelope reported an
  unlimited, non-resetting standard key and retained
  `strict_invoice_ceiling_supported=false`.
- Full repository suite after installing the two locally available but undeclared
  shared test dependencies: `1728 passed, 3 skipped, 12 deselected`.
- Ruff passed for every changed Python file; strict mypy with silent imported
  baseline diagnostics passed for the two new modules.
- API generation/check and strict relationship validation passed.
- Pre-landing review fixed post-buffer response-size enforcement by streaming
  under the configured cap; no unresolved critical or informational finding
  remains.
- Exact-revision provider observation: commit
  `00a90e5d73412c8346924f519abf1855289a12dc`, observed
  `2026-07-15T19:32:45.794300Z`, schema-valid unlimited/non-resetting standard
  key, with `strict_invoice_ceiling_supported=false` and no inference request.
- Independent fresh verifier: **ACCEPT** exact commit `00a90e5d73412c8346924f519abf1855289a12dc`
  (tree `f11292e8ff2a42303414156b6f4810b7c7f539fa`) for the observation-only
  library/direct-tool claim. It reran 31 focused tests, Ruff, strict changed-module
  mypy, API drift, and relationship validation. It performed no second provider
  read and found no blocking issue.

The provider-facing parser is intentionally permissive and may coerce compatible
wire values such as numeric strings before producing the strict public model.
Observation persistence remains a caller responsibility. Neither point upgrades
provider-reported state into enforcement evidence.

---

## Failure Modes and Next Actions

| Failure | Required action |
|---|---|
| ambiguous key sources or key file | reject before HTTP; repair environment |
| canonical origin mismatch | reject; do not follow or normalize arbitrary URLs |
| transport/auth/status/content failure | return stable typed code without raw body |
| malformed or impossible provider values | reject observation; preserve no partial output |
| environment changes across read | reject substitution; start a fresh child |
| live read reports unlimited/reset/management/provisioning/expiry | preserve observation; onto-canon6 decides eligibility |
| provider read works but enforcement remains untested | retain `strict_invoice_ceiling_supported=false` |

---

## Authorization

Brian authorized all work needed to reach the Greer stress-test end state on
2026-07-15, including reasonable provider spend and real LLM calls when they are
the faster valid path. This plan still keeps provider reads, reservation, and model
dispatch visible as distinct traceable actions; authorization does not weaken the
typed boundary or licensed claim.
