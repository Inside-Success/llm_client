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
