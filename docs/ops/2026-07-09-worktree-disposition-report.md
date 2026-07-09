# `llm_client` worktree disposition report — 2026-07-09

## Method

The inventory uses local `git worktree list --porcelain`, checkout status,
`git merge-base --is-ancestor <tip> main`, `git cherry main <tip>`, and branch
upstream refs. No historical branch is merged or deleted merely because its
checkout is clean. `unique patches` is the `+` count from `git cherry`; zero
means patch-equivalent or already represented, not necessarily ancestor-equal.

At baseline, the canonical root reported one untracked entry only because the
first sanctioned in-repo lane preceded the `worktrees/` ignore rule. The final
canonical root is clean on `main`.

## Recorded disposition

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

## Decision queue after checkout cleanup

Nine retained branches have patches unique relative to `main` and require
intent/code review before merge or abandonment. Four additional retained
branches have no unique patch but are not ancestors and should be explicitly
closed only after confirming their historical purpose. This plan removes their
idle checkouts but deliberately does not guess those branch decisions.

## Cleanup discovery

The nested review checkout was not merely an ignored directory: commit
`87ff8a3` had added it to `main` as a mode-`160000` gitlink at tip `1f5d6b7`.
Removing the registered checkout correctly made its parent checkout show a
tracked deletion. The parent was restored instead of force-removed; Plan #92's
claimed follow-up removes the dead gitlink while the named local and remote
branch continue to retain the unique commits.

## Reconciliation result

Before the final evidence lane was created, `git worktree list` contained only
the canonical `/home/brian/projects/llm_client` checkout. It was clean on
`main`, with local and remote default branches both at `617d0fc`. All 13
non-ancestor branches in the decision queue still resolved. The final evidence
lane is temporary and is removed through the same merge gate after this report
lands.
