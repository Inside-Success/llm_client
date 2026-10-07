# `llm_client` issue tracker

Statuses re-checked against `main` (98c9333) on 2026-10-03 unless a row says otherwise.
Issues LLM-003/004/006/008/009 are cross-project policy frictions that are not
fully verifiable from this repository's code; they stay pending until transferred.

## Register

### LLM-014: Hash-pinned files still name consolidated Markdown paths

| Field | Value |
|---|---|
| Status | Open |
| Severity | Low |
| Reported | 2026-10-07 during the Markdown-cap consolidation |

On 2026-10-07 fifteen ADRs, seven completed plans and four run/ops records were
merged into `docs/adr/DECISIONS.md`, `docs/plans/COMPLETED_PLANS.md` and
`docs/runs/RUNS.md` (each old file is a section anchored by its old file name).
Files that the codebase-wiki freshness check hash-pins could not be repointed
without re-deriving the wiki manifest, so they still name old paths:
`llm_client/workflow/deliberate.py` and `llm_client/cli/deliberate.py`
(`docs/plans/33_deliberation_workflow.md`), `llm_client/workflow/deliberate_verifier.py`
(`docs/plans/34_deliberation_verifier_adjudicator.md`), and
`docs/plans/105_inside_success_fork_reconciliation.md` (ADR paths, as code
spans). `docs/ARCHIVED_DOCS_INDEX.md` maps each old path to its new anchor.
**Fix:** at the next codebase-wiki re-derive, change those mentions to
`docs/plans/COMPLETED_PLANS.md#<old-stem>` / `docs/adr/DECISIONS.md#<old-stem>`
in the same change that refreshes the manifest. Historical run ledgers under
`runs/`, `roadmap/codebase/raw/source-manifest-*.json` and the April
`scripts/inferred_deps.json` snapshot record paths as they were and are left as is.

### LLM-001: Repository-wide static-analysis targets are baseline-red

| Field | Value |
|---|---|
| Status | Confirmed |
| Severity | Medium |
| Reported | 2026-07-09 during Plan #92 verification |

Re-measured 2026-10-03 on main: `ruff check llm_client/ tests/` (ruff 0.16.3 from
`~/.local/bin`; the count depends on the ruff version) reports 1,098 errors, and
`mypy --strict llm_client/` reports 194 errors in 44 files (the 2026-07-14
figures were 309 and 210 across 40 files). Neither baseline is a regression of
any single plan. The Makefile defines `$(PYTHON)` (prefers `.venv`) but `test`,
`test-quick`, `lint`, and `typecheck` still invoke bare `python`/`ruff`/`mypy`,
so a new worktree can run system Python and miss the declared `langgraph` extra
(the `dev` extra includes it).

**Next:** Create a bounded static-analysis baseline cleanup plan and make every
quality target use `$(PYTHON)` before treating `make check` as a required green
gate.

### LLM-002: Canonical instruction source is self-contradictory (resolved)

| Field | Value |
|---|---|
| Status | Resolved 2026-08-03 |
| Severity | High |
| Reported | 2026-07-15 during Plan #104 orientation |

At resolution time `CLAUDE.md` was the authored repository authority and
`AGENTS.md` a separate deterministic generated projection. Historical note:
`CLAUDE.md` was later retired in #29; `AGENTS.md` is now the single authored
instruction source (`scripts/meta/check_agents_sync.py --check` reports
"AGENTS.md is the authored instruction source").

### LLM-013: Inside Success remote routes pushes through the personal credential

| Field | Value |
|---|---|
| Status | Closed (obsolete) 2026-10-03: this repository no longer receives pushes from the former personal checkout |
| Severity | Medium |
| Reported | 2026-07-15 during Plan #105 fork publication |

The configured `inside-success` remote uses HTTPS. Fetch succeeds anonymously,
but push selected the active personal GitHub CLI credential and failed with
HTTP 403 even though the machine has a working `github-insidesuccess` SSH
identity with write access to the same repository.

**Exact proposed policy-friction entry:**

- **Policy:** `multi-account-github-remote-routing`
- **Friction:** The `llm_client` `inside-success` HTTPS remote routes writes
  through the active personal credential rather than the configured
  organization SSH identity, so an authorized fork update fails until the
  agent replaces the remote URL at invocation time.
- **Recommendation:** Configure the organization remote with the existing
  `github-insidesuccess` SSH host alias and add a credential-routing check that
  verifies fetch and dry-run push identity for each multi-account remote.

Transfer target is the external `project-meta/policy_friction.md` (not in this repo;
the 2026-07 claim that blocked transfer is unverified as still active).

### LLM-012: Failed pre-commit validation leaves generated docs staged

| Field | Value |
|---|---|
| Status | Partially addressed: `hooks/pre-commit` now runs doc-coupling (line 72) before API-reference generation and staging (lines 91-97); it still `git add`s `docs/plans/AGENTS.md` (line 68) first. Policy-friction handoff pending |
| Severity | Medium |
| Reported | 2026-07-15 during Plan #105 implementation commit |

The pre-commit hook regenerated and staged both API-reference outputs before
running doc-code coupling. Coupling then failed, so an unsuccessful commit
attempt left additional generated mutations in the index and expanded the
review scope before the agent could satisfy the reported requirement.

**Exact proposed policy-friction entry:**

- **Policy:** `pre-commit-validation-ordering`
- **Friction:** The `llm_client` pre-commit hook mutates and stages generated API
  documentation before later doc-code coupling validation can reject the
  commit, so a failed validation attempt changes the index and obscures the
  intended commit boundary.
- **Recommendation:** Run non-mutating validation before generation, or generate
  into a temporary location, compare, and only update/stage outputs after all
  blocking checks pass; add a negative control proving failed hooks leave the
  index unchanged.

Transfer target is the external `project-meta/policy_friction.md` (not in this repo;
the 2026-07 claim that blocked transfer is unverified as still active).

### LLM-011: Push rejection prescribes an unscoped claim

| Field | Value |
|---|---|
| Status | Pending policy-friction handoff (re-checked 2026-10-03: `scripts/meta/worktree-coordination/check_claims.py:1208` still prints an unscoped `--claim --task`; line 1255 suggests `--feature`) |
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

Transfer target is the external `project-meta/policy_friction.md` (not in this repo;
the 2026-07 claim that blocked transfer is unverified as still active).

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

Transfer target is the external `project-meta/policy_friction.md` (not in this repo;
the 2026-07 claim that blocked transfer is unverified as still active).

### LLM-007: Declared development install cannot collect the full test suite

| Field | Value |
|---|---|
| Status | Confirmed (re-checked 2026-10-03: `data_contracts` and `prompt_eval` are still undeclared in `pyproject.toml`; tests still import them) |
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

Transfer target is the external `project-meta/policy_friction.md` (not in this repo;
the 2026-07 claim that blocked transfer is unverified as still active).

### LLM-005: Declared development install cannot run the declared lint target (resolved)

| Field | Value |
|---|---|
| Status | Resolved: `pyproject.toml` `dev` extra now declares `ruff>=0.12,<1.0` (verified 2026-10-03) |
| Severity | Medium |
| Reported | 2026-07-15 during Plan #104 environment verification |

At report time `make install` installed `.[dev]` without Ruff while the `lint`
target invokes `ruff check`. The `dev` extra now includes Ruff; a clean-environment
check that every declared quality command executes remains unwritten.

### LLM-006: Capability-certification skill references a missing authority

| Field | Value |
|---|---|
| Status | Pending policy-friction handoff (references external `project-meta`/`ecosystem-ops` paths; not checkable from this repo) |
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

Transfer target is the external `project-meta/policy_friction.md` (not in this repo;
the 2026-07 claim that blocked transfer is unverified as still active).

### LLM-003: Required-reading gate cannot observe Codex repository reads

| Field | Value |
|---|---|
| Status | Pending policy-friction handoff (re-checked 2026-10-03: `.claude/hooks/track-reads.sh` is still the only recorder of `/tmp/.claude_session_reads`) |
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

Transfer target is the external `project-meta/policy_friction.md` (not in this repo;
the 2026-07 claim that blocked transfer is unverified as still active).

### LLM-010: Repository lacks the required coordination claim entrypoint

| Field | Value |
|---|---|
| Status | Confirmed (re-checked 2026-10-03: the Makefile has no `claim` or `release-claim` target; claiming goes through `make worktree`/`make session-start` and `scripts/meta/worktree-coordination/check_claims.py --claim`) |
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

Transfer target is the external `project-meta/policy_friction.md` (not in this repo;
the 2026-07 claim that blocked transfer is unverified as still active).
