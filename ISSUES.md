# `llm_client` issue tracker

## Open

### LLM-001: Repository-wide Ruff target has 317 baseline errors

| Field | Value |
|---|---|
| Status | Confirmed |
| Severity | Medium |
| Reported | 2026-07-09 during Plan #92 verification |

`make lint` reports 317 errors across `llm_client/` and `tests/`, including
unused imports/variables, import-order findings, and duplicate definitions.
The lifecycle-governance consumer test and the exact worktree-only installer
closure pass Ruff, so this is not a Plan #92 regression; it is a pre-existing
whole-repository gate failure.

**Next:** Create a bounded lint-baseline cleanup plan before treating
`make lint` as a required green gate.
