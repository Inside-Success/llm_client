# `llm_client` issue tracker

## Open

### LLM-001: Repository-wide static-analysis targets are baseline-red

| Field | Value |
|---|---|
| Status | Confirmed |
| Severity | Medium |
| Reported | 2026-07-09 during Plan #92 verification |

`make lint` reported 309 errors on 2026-07-14 across `llm_client/` and `tests/`, including
unused imports/variables, import-order findings, and duplicate definitions.
`make typecheck` reported 210 errors across 40 pre-existing files. Plan 101's
changed canonical modules and tests pass focused Ruff, and its new module
passes strict mypy with imported-module diagnostics silenced, so neither
baseline is a Plan 101 regression. The full 1,667-test suite passes when the
repo-local virtual environment is put on `PATH`; plain `make test` from a new
worktree instead uses system Python and misses the declared `langgraph` extra.

**Next:** Create a bounded static-analysis baseline cleanup plan and make the
Makefile select the repo-local environment before treating `make check` as a
required green gate.

### LLM-002: Canonical instruction source is self-contradictory

| Field | Value |
|---|---|
| Status | Pending policy-friction handoff |
| Severity | High |
| Reported | 2026-07-15 during Plan #104 orientation |

`AGENTS.md` is a symlink to `CLAUDE.md`, while `CLAUDE.md` says it is a generated
file that must not be edited and simultaneously names `CLAUDE.md` as its own
canonical source. Agents therefore cannot follow both the repository rule that
`CLAUDE.md` is canonical and the file-local instruction not to edit it.

**Exact proposed policy-friction entry:**

- **Policy:** `canonical-project-instructions`
- **Friction:** In `llm_client`, `AGENTS.md` symlinks to `CLAUDE.md`, but
  `CLAUDE.md` is a generated Codex projection that says not to edit it and names
  itself as the canonical source. The declared canonical/editable instruction
  authority is therefore circular and unavailable.
- **Recommendation:** Restore a human-authored canonical `CLAUDE.md` and generate
  a separate `AGENTS.md`, or declare a different editable canonical source and
  make both projections point to it; add a negative control rejecting a generated
  file whose `canonical_claude` resolves to itself.

The shared `project-meta/policy_friction.md` is actively claimed by
`plan0137-report-vgap-20260712`; transfer this entry after that claim closes.

### LLM-011: Push rejection prescribes an unscoped claim

| Field | Value |
|---|---|
| Status | Pending policy-friction handoff |
| Severity | Low |
| Reported | 2026-07-15 during Plan #105 branch publication |

The push hook correctly rejected a branch without a repository-local claim,
but its exact remediation command omitted `--plan` and `--feature`. Running the
prescribed command created an unscoped claim and immediately warned that the
claim should have been scoped, requiring release and recreation.

**Exact proposed policy-friction entry:**

- **Policy:** `repository-push-claim-guidance`
- **Friction:** The `llm_client` push hook's remediation command creates an
  unscoped claim even when the current branch and plan document identify a plan;
  the claim tool then warns that the prescribed claim is insufficiently scoped.
- **Recommendation:** Make the hook infer a unique plan from the branch or
  tracked plan document and print `--plan N`; when inference is unavailable,
  explain the required scope choice instead of prescribing an unscoped command.

The shared `project-meta/policy_friction.md` is actively claimed by
`plan0137-report-vgap-20260712`; transfer this entry after that claim closes.

### LLM-009: Parallel yielded commands lose first-class wait handles

| Field | Value |
|---|---|
| Status | Pending policy-friction handoff |
| Severity | Medium |
| Reported | 2026-07-15 during independent Plan #104 review |

Parallel `exec_command` calls that yielded sessions were wrapped by
`functions.exec` as completed values with nested session IDs. The independent
reviewer lost direct wait handles and unintentionally started a duplicate focused
pytest run. Both duplicate processes were terminated and no Plan 104 test process
remained.

**Exact proposed policy-friction entry:**

- **Policy:** `unified-exec-orchestration`
- **Friction:** Parallel `exec_command` calls that yielded sessions were wrapped
  by `functions.exec` as completed values with nested session IDs, so the caller
  lost direct wait handles and unintentionally started a duplicate focused
  pytest run.
- **Recommendation:** Surface yielded session IDs as first-class waitable results
  from orchestrated calls or reject parallel orchestration of yielding commands.

The shared `project-meta/policy_friction.md` is actively claimed by
`plan0137-report-vgap-20260712`; transfer this entry after that claim closes.

### LLM-007: Declared development install cannot collect the full test suite

| Field | Value |
|---|---|
| Status | Confirmed |
| Severity | Medium |
| Reported | 2026-07-15 during Plan #104 full-suite verification |

After a successful `make install`, full pytest collection fails because
`tests/test_boundary_schemas.py` imports the cross-project `data_contracts`
package, which is not declared in any project or development dependency. The
package exists in shared infrastructure but a clean `llm_client` environment
does not know to install it. After installing `data_contracts`, the suite ran
1,725 tests successfully but two CLI experiment tests failed because the
similarly extracted `prompt_eval` package is also undeclared.

**Next:** Declare these shared dependencies through a reproducible
workspace/development bootstrap, or make dependent tests explicitly gated with
fail-loud setup checks; add a clean-environment full-suite control.

### LLM-008: Push claim gate ignores the ecosystem session claim

| Field | Value |
|---|---|
| Status | Pending policy-friction handoff |
| Severity | High |
| Reported | 2026-07-15 during Plan #104 push |

The active ecosystem claim
`codex_llm-client_plan104-openrouter-provider-limit-observer-20260715.yaml`
names the exact repository, worktree, and branch and remains unexpired, but the
`llm_client` pre-push hook reported that the branch had no active claim. The hook
requires a second repository-specific claim, so the two coordination authorities
disagree about ownership of the same work.

**Exact proposed policy-friction entry:**

- **Policy:** `cross-client-worktree-claims`
- **Friction:** An active ecosystem session claim naming the exact `llm_client`
  repo, worktree, and branch was not recognized by the repository pre-push claim
  gate, which blocked a normal push and demanded a duplicate local claim.
- **Recommendation:** Make repository claim verification consume the canonical
  ecosystem claim schema, or have session start create the one claim authority
  the hook consumes; add a positive control covering Codex session claim through
  normal push.

The shared `project-meta/policy_friction.md` is actively claimed by
`plan0137-report-vgap-20260712`; transfer this entry after that claim closes.

### LLM-005: Declared development install cannot run the declared lint target

| Field | Value |
|---|---|
| Status | Confirmed |
| Severity | Medium |
| Reported | 2026-07-15 during Plan #104 environment verification |

`make install` installs `.[dev]`, and that extra does not declare Ruff. The same
Makefile's `lint` target invokes `ruff check`, so a clean repository-local setup
cannot execute its declared quality target without an undeclared global tool.

**Next:** Add a bounded Ruff dependency to the `dev` extra and cover a clean
environment's ability to execute every declared quality command.

### LLM-006: Capability-certification skill references a missing authority

| Field | Value |
|---|---|
| Status | Pending policy-friction handoff |
| Severity | High |
| Reported | 2026-07-15 during Plan #104 certification |

The mandatory `capability-certification` skill names
`project-meta/docs/ops/ADVERTISED_CAPABILITY_CERTIFICATION.md` as its canonical
standard, but that file does not exist and no matching certification authority
is discoverable in `project-meta`. Its named validator pilot,
`ecosystem-ops/capability_certification.py`, is also absent. The skill procedure
is readable, but neither its declared governing source nor its required evidence
consumer can be executed.

**Exact proposed policy-friction entry:**

- **Policy:** `capability-certification-skill`
- **Friction:** The required capability-certification skill references
  `project-meta/docs/ops/ADVERTISED_CAPABILITY_CERTIFICATION.md` as canonical,
  but the file is absent and no matching authority is discoverable; the skill's
  named `ecosystem-ops/capability_certification.py` validator is absent too,
  preventing agents from reading the governing standard or consuming the
  prescribed evidence record.
- **Recommendation:** Restore the canonical standard and validator or update the
  skill to their current authoritative paths; add a skill-integrity check that
  fails when a required local reference is missing.

The shared `project-meta/policy_friction.md` is actively claimed by
`plan0137-report-vgap-20260712`; transfer this entry after that claim closes.

### LLM-003: Required-reading gate cannot observe Codex repository reads

| Field | Value |
|---|---|
| Status | Pending policy-friction handoff |
| Severity | High |
| Reported | 2026-07-15 during Plan #104 read-gate verification |

The strict read gate consumes `/tmp/.claude_session_reads`, populated only by a
Claude `PostToolUse/Read` hook. Codex read every required document completely
through the repository shell, but `check_required_reading.py` reported all of
them unread. Its failure message instructs the agent to read the documents but
does not expose a supported cross-client recording command.

**Exact proposed policy-friction entry:**

- **Policy:** `required-reading-gate`
- **Friction:** `llm_client` required-reading enforcement observes Claude Read
  hooks but not Codex shell/file reads, so compliant Codex work is falsely
  blocked after the required documents were read.
- **Recommendation:** Provide a client-neutral `record-required-reading` command
  or integrate Codex read telemetry into the same session ledger; make the gate
  error name that supported path and add a cross-client positive control.

Plan #104 explicitly invokes the existing tracker for each fully read document
instead of disabling or weakening the gate. Transfer this entry centrally after
the active shared claim closes.

### LLM-004: Background execution handles do not survive context compaction

| Field | Value |
|---|---|
| Status | Pending policy-friction handoff |
| Severity | Medium |
| Reported | 2026-07-15 during Plan #104 environment setup |

The repo-local virtual-environment installation was running under execution
session `88993` when the agent context compacted. After compaction, polling the
documented session identifier returned `Unknown process id`, with no terminal
result available. The environment must therefore be inspected to distinguish a
completed command from an interrupted one.

**Exact proposed policy-friction entry:**

- **Policy:** `long-running-exec-session-continuity`
- **Friction:** A background `exec_command` session became unqueryable after
  agent context compaction, so a long-running required command lost its terminal
  result and completion status even though its session identifier was preserved.
- **Recommendation:** Preserve execution-session handles across compaction, or
  persist an explicit terminal result that a resumed agent can query; document
  the supported recovery command and add a compaction-resume positive control.

The shared `project-meta/policy_friction.md` is actively claimed by
`plan0137-report-vgap-20260712`; transfer this entry after that claim closes.

### LLM-010: Repository lacks the required coordination claim entrypoint

| Field | Value |
|---|---|
| Status | Pending policy-friction handoff |
| Severity | Medium |
| Reported | 2026-07-15 during Plan #105 coordination setup |

The ecosystem execution policy requires agents to establish a repository claim
before modifying shared projects, but the expected repository command,
`make claim`, is not implemented by `llm_client`. The attempt failed with
`No rule to make target 'claim'`, requiring a manually authored claim file.

**Exact proposed policy-friction entry:**

- **Policy:** `coordination-claim-entrypoint`
- **Friction:** Ecosystem policy requires a repository-local `make claim`
  entrypoint before shared-project writes, but `llm_client` has no `claim`
  target, so the prescribed coordination workflow fails before source work.
- **Recommendation:** Add standard `claim` and `release-claim` Make targets, or
  document and expose a supported client-neutral claim command through the
  Make target glossary with a positive integration check.

The shared `project-meta/policy_friction.md` is actively claimed by
`plan0137-report-vgap-20260712`; transfer this entry after that claim closes.
