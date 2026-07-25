# Plan #116: Ecosystem Allowlist Cutover

**Status:** Complete
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** Unconditional allowed-model enforcement

---

## Gap

**Current:** Plan #115 added exact allowlist enforcement, made DeepSeek V4
Flash the justification-free default, and hard-blocked GPT-5 Mini-family
routes. Twin opted in, but the shared client still defaults other consumers to
temporary compatibility mode.

**Target:** Migrate executable first-party consumers to the shared contract,
then remove compatibility mode. Every call chain must either use DeepSeek V4
Flash or record a task-specific reason for every allowed alternative. Unknown
and unapproved models must fail before dispatch everywhere.

**Why:** A policy that callers may silently decline is not an ecosystem
allowlist. The cutover must preserve intentional calibrated/evaluation routes
without converting stale model selections into implicit exceptions.

---

## References Reviewed

- `docs/plans/115_allowed-model-execution-policy.md` — implemented boundary,
  temporary compatibility contract, and required next slice.
- `llm_client/core/model_execution_policy.py` — exact allowed set and
  justification rule.
- `llm_client/execution/call_contracts.py` and the text, structured, and stream
  runtimes — public-call policy defaults and pre-dispatch boundary.
- Active first-party `llm_client` call sites under `/home/brian/code` and
  `/home/brian/projects/prompt_eval`, inventoried 2026-07-23.
- Each affected repository's applicable `CLAUDE.md`/`AGENTS.md` governance
  before modification.

---

## Scope and Boundaries

In scope:

1. executable source and operational scripts in active first-party repos;
2. task-specific recorded justification for retained non-default models;
3. replacement of active GPT-5 Mini defaults with DeepSeek V4 Flash;
4. unconditional shared enforcement and removal of the compatibility option;
5. a deterministic repository audit for disallowed active selections and
   missing exception evidence.

Excluded:

- archived repositories and generated build copies;
- frozen fixtures, recorded outputs, and historical experiment artifacts;
- dependencies and virtual environments;
- rewriting dirty overlapping user work merely to make the inventory green.

An excluded historical artifact may name an old model but cannot authorize or
dispatch it. A dirty executable caller that cannot be safely reconciled remains
fail-closed under the shared boundary and is reported explicitly.

---

## Delivery Packets

1. Migrate clean, bounded consumers and verify their focused tests.
2. Migrate governed large consumers in sanctioned worktrees where required.
3. Reconcile or explicitly quarantine dirty overlapping executable callers.
4. Remove compatibility mode, update public docs/tests, and regenerate the API
   reference if the public surface changes.
5. Run cross-repository static audit plus representative pre-dispatch and live
   route checks.

---

## Required Tests

| Test | What it proves |
|---|---|
| omitted policy still rejects unknown/disallowed model | enforcement is unconditional |
| compatibility value is rejected | callers cannot opt out |
| default route needs no justification | DeepSeek V4 Flash remains the normal path |
| alternate route without justification fails | exceptions cannot be silent |
| alternate route with justification records it | exception evidence is durable |
| full active-consumer audit | no known executable route relies on compatibility |
| focused consumer suites | added metadata and default changes preserve behavior |

---

## Acceptance Criteria

- [x] Active first-party executable callers are migrated or named as a
      fail-closed dirty-worktree exception.
- [x] GPT-5 Mini and GPT-5.1 Mini cannot execute through any shared-client mode.
- [x] DeepSeek V4 Flash is the sole justification-free model.
- [x] Every retained allowed alternative records a task-specific reason.
- [x] Compatibility mode no longer exists as an executable policy.
- [x] Focused shared and consumer tests pass.
- [x] Cross-repository audit and documentation reflect the actual cutover.

---

## Risks and Controls

- **Configured model expressions:** call sites often receive models from CLI,
  environment, or task routing. Their justification must describe why that
  configured route is intentionally preserved; the shared client still
  validates the resolved model exactly.
- **Dirty repositories:** never overwrite or accidentally commit unrelated user
  changes. Use non-overlapping edits, sanctioned worktrees, or report the
  unresolved caller.
- **Historical reproducibility:** old snapshots may contain the removed
  compatibility value. Replay must fail closed rather than silently weakening
  current execution policy; the snapshot remains inspectable as evidence.
- **False completeness:** static string scans complement but do not replace
  pre-dispatch runtime tests and representative live calls.

---

## Completion Evidence

### Shared boundary

- `model_policy` has one accepted value: `enforce_allowlist`; omitting the
  argument enforces the exact allowlist and the removed `compatibility` value
  fails before dispatch.
- GPT-5 Mini, GPT-5.1 Mini, and Codex Mini remain explicitly prohibited.
- DeepSeek V4 Flash is the only route that does not require
  `model_justification`.
- Policy and identity tests: `31 passed`.
- Broad suite, excluding two unavailable optional-dependency modules:
  `1845 passed, 4 skipped, 12 deselected`.

### Migrated consumers

- Twin, `claude-team-infra`, `enforced-planning`, `godel-concept-ladder`,
  `ladder-prototype`, `learning_map`, `project-meta`, `trace_eval`,
  `prompt_eval`, and both cybernetic-influence active lines record configured
  alternate-model reasons.
- Qualitative Coding defaults, operator scripts, report/evaluation helpers,
  docs, and Make targets now use DeepSeek V4 Flash by default; retained
  experimental routes record their reason. The final secondary-script slice
  passed `30` focused tests.
- DIGIMON Plan #159 merged in PR #139 after all reported CI checks passed.
- onto-canon6 Plan #0169 merged in PR #252. Its alias-aware inventory found
  zero maintained calls missing a reason; focused caller tests passed. Its
  inherited full-repository environment/artifact failures are documented in
  that plan and are not represented as a green full suite.

### Explicit fail-closed exception

`ats_handle_prediction` remains a protected dirty worktree with overlapping
user changes. Its tracked and untracked candidate-validation configurations
currently name GPT-5 Mini and Grok 4.3, and its modified caller does not record
a reason. Those routes are not allowlisted and therefore fail before provider
dispatch. They were not rewritten or committed under this plan.

### Audit boundary

The closing audit covered maintained executable Python, YAML, TOML, shell, and
Makefile surfaces in active first-party repositories. Tests, frozen fixtures,
run records, generated outputs, old worktrees, archives, and data logs may
retain historical model identifiers but cannot authorize current dispatch.
