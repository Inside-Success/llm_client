# Plan 99 Current-Main Integration Acceptance

**Decision:** ACCEPT

**Review date:** 2026-07-13

**Accepted commit:** `c38aea4546b9a8318d233dd49b6fda7060d665c4`

**Accepted tree:** `d8ff2406611ea20434687274c7d71df0e409b7be`

**Pull request:** `#57`

**Reviewer:** independent read-only agent `/root/execution_plan_audit`

## Scope

This review accepts the exact Plan 99 replay repair integrated with `origin/main` at
`e30e088`. It supersedes the rejection of parent candidate `fb34d6c`, whose verification
could escape to ambient Python. It does not complete Plan 99, authorize a provider/model
call, or approve onto-canon6 Plan 0141 by itself.

The accepted history preserves implementation `5ed2a1e`, its earlier evidence commit
`340157f`, and `e30e088` as ancestors. Replay implementation and adversarial-test blobs
remain byte-identical to the already accepted repair boundary.

## Executed Evidence

| Gate | Result |
|---|---|
| Canonical-venv mandatory Plan 99 inventory | 320 passed |
| Wider Plan 97/99 overlap suite | 400 passed |
| Lifecycle/SQLite overlap subset | 99 passed |
| Plan-helper interpreter regression | 3 passed |
| Hook positive | canonical repository venv selected |
| Hook negatives | missing venv and failed fetch both blocked |
| Scoped Ruff, API reference, relationships, compile, diff | passed |
| GitHub `observability-switches` | passed on exact PR head |

Exact baseline comparisons also reproduced the documentation: repository Ruff reports
309 candidate findings versus 315 on clean `e30e088`; ambient mypy 1.19.1 reports
209 versus 210; canonical-venv mypy 1.20.0 reports 210 versus 211. These are inherited
red baselines with a one-finding candidate improvement, not green quality gates.

## Residual Risks

- A non-acceptance full-suite stress run reached 1,631 passed and 3 skipped with one
  Instructor lifecycle timeout failure; the same lifecycle surface passed in the isolated
  99-test overlap run.
- The previously documented SQLite background-writer race did not reproduce in this run.
  Relevant base/candidate files are identical, so `LLM-VERIFY-012` remains open.
- The AGENTS sync validator rejects the pre-existing `AGENTS.md -> CLAUDE.md` symlink on
  both base and candidate (`LLM-VERIFY-014`).

## Downstream Binding Rule

Merge only the reviewed commit lineage through the normal PR path. Plan 0141 must then
pin the resulting merge revision, verify the installed runtime source and replay behavior,
and obtain fresh downstream acceptance before any provider/model call.
