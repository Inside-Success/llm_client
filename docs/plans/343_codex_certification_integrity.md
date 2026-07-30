# Plan #343: Codex Certification Integrity

**Status:** In Progress
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** Trustworthy downstream advertisement of subscription-backed Codex routes

---

## Gap

**Current:** A caller can label route evidence with an arbitrary
`LLM_CLIENT_REVISION`, and `compile_codex_structured_success()` accepts any
nonempty content as parseable without validating it against the certified
schema.

**Target:** Derive and validate the installed shared-client revision, reject a
configured revision that does not match it, and compile Codex success evidence
only after the exact returned content validates against the supplied Pydantic
response model.

**Why:** Route certification is an evidence boundary. It must not certify a
different code revision or malformed output as a successful exact-schema route.

---

## References Reviewed

- `CLAUDE.md` — shared-client workflow and fail-loud requirements.
- `llm_client/route_certification_runtime.py` — current public certification compiler.
- `llm_client/route_certification.py` — retained observation integrity model.
- `llm_client/sdk/agents_codex.py` — exact Codex provider-schema projection.
- Cybernetic Influence `run_configuration.py` and
  `scripts/certify_codex_luna.py` — current downstream revision and compiler use.

---

## Files Affected

- `llm_client/revision.py` (create)
- `llm_client/route_certification_runtime.py` (modify)
- `llm_client/__init__.py` (modify)
- `tests/test_revision.py` (create)
- `tests/test_codex_luna_subscription.py` (modify)
- `docs/API_REFERENCE.md` and `docs/API_REFERENCE.html` (regenerate)
- `docs/plans/CLAUDE.md` (modify)

---

## Plan

1. Add a shared installed-revision resolver that recognizes a source checkout
   only when the imported package is the checkout's top-level `llm_client`
   package, otherwise falls back to distribution-version identity.
2. Reject a nonempty configured revision that differs from the installed
   revision.
3. Make the Codex success compiler accept the Pydantic response model, validate
   `result.content`, and derive both schema class and provider-schema digest
   internally.
4. Update the simulator consumer, tests, generated API reference, and deployment
   configuration to use the verified revision contract.

---

## Required Tests

| Test | What it verifies |
|---|---|
| source checkout resolution | The imported checkout's exact HEAD is returned |
| package fallback | A non-checkout install uses distribution-version identity |
| configured mismatch | A typo or stale configured revision fails loudly |
| malformed Codex content | Invalid JSON cannot produce certifying evidence |
| schema-invalid Codex content | Valid JSON violating the response model cannot certify |
| exact valid content | A validated Luna result retains the exact provider-schema digest |
| downstream simulator checks | Advertisement and live-run configuration use the verified revision |

---

## Acceptance Criteria

- [ ] Incorrect configured revisions fail before route advertisement or certification.
- [ ] Malformed or schema-invalid content cannot produce a certifying observation.
- [ ] Valid exact-schema Codex evidence remains certifiable.
- [ ] Focused shared-client and simulator tests pass.
- [ ] Generated API documentation is current.

