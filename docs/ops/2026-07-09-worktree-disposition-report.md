# `llm_client` worktree disposition report — 2026-07-09

## Method

The inventory uses local `git worktree list --porcelain`, checkout status,
`git merge-base --is-ancestor <tip> main`, `git cherry main <tip>`, and branch
upstream refs. No historical branch is merged or deleted merely because its
checkout is clean. `unique patches` is the `+` count from `git cherry`; zero
means patch-equivalent or already represented, not necessarily ancestor-equal.

The canonical root reports one untracked entry only because this sanctioned
in-repo lane was created before `worktrees/` was added to `.gitignore`; it had
no pre-existing file change.

## Recorded disposition

| Checkout | Branch/ref | Main evidence | Unique patches | Recovery evidence | Action |
|---|---|---:|---:|---|---|
| `llm_client` | `fix/instructor-retry-unwrapping` | not ancestor | 4 | `origin/fix/instructor-retry-unwrapping` | Restore root to `main`; retain branch for review |
| `_worktrees/llm_client-gemini-merge` | detached `e9a0cbf` | ancestor | 0 | `main` | Remove checkout |
| `_worktrees/llm_client-gemini-schema-study` | `gemini-schema-study` | not ancestor | 0 | `origin/gemini-schema-study` | Remove checkout; retain branch |
| `_worktrees/llm_client-gemini31-parity` | detached `37623ec` | ancestor | 0 | `main` | Remove checkout |
| `llm_client-reviewmain` | `main` | exact `main` | 0 | `origin/main` | Remove after nested checkout; switch canonical root to `main` |
| `llm_client-reviewmain/worktrees/codex-review-prompts-as-assets-20260624` | `codex/review-prompts-as-assets-20260624` | not ancestor | 4 | matching `origin/*` branch | Remove checkout; retain branch |
| `llm_client/worktrees/worktree-lifecycle-governance-20260709` | active Plan #92 | based on `main` | 0 before work | pushed topic branch, then merged `main` | Keep until merged/pushed; close through gate |
| `llm_client_worktrees/agent-collab-package` | `brian/agent-collab-package` | ancestor | 0 | `main` and matching `origin/*` | Remove checkout; delete merged local branch |
| `llm_client_worktrees/codex/recovered-control-churn-outcomes-20260622` | same | not ancestor | 1 | matching `origin/*` branch | Remove checkout; retain branch |
| `llm_client_worktrees/codex/submit-retry-state-progress-20260622` | same | not ancestor | 1 | matching `origin/*` branch | Remove checkout; retain branch |
| `llm_client_worktrees/merge-plan-91-into-main-20260405` | same | not ancestor | 3 | matching `origin/*` branch | Remove checkout; retain branch |
| `llm_client_worktrees/plan-22-run-progress-observability` | same | not ancestor | 2 | matching `origin/*` branch | Remove checkout; retain branch |
| `llm_client_worktrees/plan-52-llm-client-dead-code` | same | not ancestor | 5 | matching `origin/*` branch | Remove checkout; retain branch |
| `llm_client_worktrees/reconcile-main-with-origin-20260405` | same | ancestor | 0 | `main` and matching `origin/*` | Remove checkout; delete merged local branch |
| `~/worktrees/llm-client-anomaly-phase18` | `anomaly-phase18-worktree-projects` | not ancestor | 4 | local branch only | Remove checkout; retain local branch |
| `~/worktrees/llm-client-anomaly-phase18-merge` | `merge-anomaly-phase18-20260405` | ancestor | 0 | `main` | Remove checkout; delete merged local branch |
| `~/worktrees/llm-client-anomaly-phase19` | `anomaly-phase19-gpt54-codex` | not ancestor | 0 | local branch; patch represented on `main` | Remove checkout; retain branch |
| `~/worktrees/llm-client-anomaly-phase19-merge` | `merge-anomaly-phase19-20260405` | not ancestor | 0 | matching `origin/*` branch | Remove checkout; retain branch |
| `~/worktrees/llm-client-anomaly-phase20-merge` | `merge-anomaly-phase20-20260405` | ancestor | 0 | `main` and matching `origin/*` | Remove checkout; delete merged local branch |
| `~/worktrees/llm-client-gemini-shared-cap` | `anomaly-phase20-gemini-shared-cap` | not ancestor | 0 | matching `origin/*` branch | Remove checkout; retain branch |
| `~/worktrees/llm-client-observability-config-truthfulness` | `plan26-observability-config-truthfulness` | not ancestor | 1 | local branch; upstream configured as `origin/main` | Remove checkout; retain local branch |
| `/tmp/.../scratchpad/llmclient-main` | detached `c8ec030` | registration missing | 0 | patch represented on `main` | Prune missing registration |

## Decision queue after checkout cleanup

Nine retained branches have patches unique relative to `main` and require
intent/code review before merge or abandonment. Four additional retained
branches have no unique patch but are not ancestors and should be explicitly
closed only after confirming their historical purpose. This plan removes their
idle checkouts but deliberately does not guess those branch decisions.
