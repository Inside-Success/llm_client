# LLM Client Session Handoff

## What this project is

`llm_client` is the shared runtime and control plane for model routing, structured output, retries, tool execution, and observability across the project ecosystem. It owns generic runtime evidence; project-specific policy remains in consumer projects.

## What was done this session

- Completed worktree lifecycle governance and historical branch disposition (Plan #92, merge `07d2b4a`).
- Added the privacy-preserving Codex/Claude tool-usage ledger (Plan #93, merge `67944d4`).
- Fixed provisional outcome maturation so later terminal transcript evidence replaces `missing` exactly once (`2f30f82`, merge `776f880`).
- Made generated API documentation use the invoking checkout and portable links (`48b6c9a`, merge `48e2c95`).
- Recorded the verification gaps and cleanup-tool dependency friction in `project-meta` PRs #11-#13.
- Removed all session-owned worktrees, claims, local branches, and feature-remote refs.

## Active source files

There are no uncommitted or ephemeral source files. Temporary real-import databases and summaries under `/tmp` were diagnostic-only and are not required for recovery.

## Build and verification commands

```bash
python -m pytest -q tests/test_agent_tool_usage.py tests/test_cli_smoke.py tests/test_api_reference_generation.py
python scripts/meta/generate_api_reference.py --check
ruff check scripts/meta/generate_api_reference.py tests/test_api_reference_generation.py llm_client/observability/agent_tool_usage.py llm_client/cli/tool_usage.py tests/test_agent_tool_usage.py
mypy --strict --follow-imports=silent llm_client/observability/agent_tool_usage.py llm_client/cli/tool_usage.py
```

The focused closeout gate passes: 12 tests, Ruff, mypy, and API-reference synchronization. `make check` remains red at the pre-existing 317-finding Ruff baseline tracked by `ISSUES.md` entry LLM-001; do not mistake that baseline for a Plan #93 regression.

## Uncertainties

None remain for the completed Plans #92 and #93 scope.

## Deferred work — not active session work

The reviewed forward-port queue is documented in `docs/ops/2026-07-09-worktree-disposition-report.md`. Recommended order:

1. `observability-config-truthfulness-v2` from `plan26-observability-config-truthfulness@86733ac`. Resolve import-time environment caching and test isolation; audit concurrent SQLite path switching before porting.
2. `secure-trace-browser-salvage` from `fix/instructor-retry-unwrapping@3def0e3`. Do not merge wholesale: require authentication, redaction, bounded previews, deterministic aggregation, and safe URL schemes.
3. `adversarial-review-prompt-asset-migration` from `codex/review-prompts-as-assets-20260624@1f5d6b7`. Port only the prompt-extraction intent into the current canonical prompt store; discard stale manifest and ignore-file changes.
4. `durable-run-progress-v2` from `plan-22-run-progress-observability@c3746d2`. Redesign around current schemas; prevent orphan rows and accidental stage erasure, and fail loudly on persistence errors.

Other known backlog:

- Twenty malformed historical Codex JSONL files require the explicit `--skip-malformed-files` coverage downgrade during full-history imports.
- Repository-wide Ruff/type baselines remain separate cleanup work; do not fold them into the four forward-port lanes without a dedicated plan and coverage report.

## Files that must not be edited directly

- `docs/API_REFERENCE.md` and `docs/API_REFERENCE.html` are generated. Change public code/docstrings or the generator, then run `python scripts/meta/generate_api_reference.py --write`.
- `AGENTS.md` is the generated Codex projection of canonical `CLAUDE.md` and relationship metadata.

## Quick sanity checks

```bash
git status --short --branch
git worktree list
python scripts/meta/generate_api_reference.py --check
python -m pytest -q tests/test_agent_tool_usage.py tests/test_cli_smoke.py tests/test_api_reference_generation.py
```

Expected repository state: clean `main`, synchronized with `origin/main`, with only the canonical checkout registered.
