---
type: source
title: Inside Success Revision 5228ceb Source Ingest
description: Current source binding to the canonical Inside-Success/llm_client main, with the code changes since the former personal revision 4f7ecfa.
created: 2026-10-03
updated: 2026-10-03
sources: [../../raw/source-manifest-5228ceb-inside-success.json, ../../../../llm_client/inside_success_policy.py, ../../../../llm_client/execution/codex_identity.py, ../../../../llm_client/utils/litellm_log_filters.py]
confidence: high
---

# Current source binding

The current source is `Inside-Success/llm_client` commit
`5228ceb8b3e04750105b26292584aa9e7323d7a9`, Git tree
`1a0edc04d3ac04f87d429a75afdd685ad6903d0c`. Its deterministic code surface is
168 Python files plus `pyproject.toml` (169 files), bound by digest
`sha256:a29cd7f0...a662da` in the immutable
[manifest](../../raw/source-manifest-5228ceb-inside-success.json). The
manifest's authority hashes cover `AGENTS.md`, the ecosystem and capability
documents, Plan 105, and this wiki's schema.

This replaces the earlier binding to the former personal upstream at
[`4f7ecfa`](revision-4f7ecfa.md). That upstream is ancestry only; see
[lineage](../lineage/personal-and-inside-success.md).

# Source changes since `4f7ecfa` (package surface)

`git diff --name-status 4f7ecfa 5228ceb -- llm_client pyproject.toml` shows
three new Python modules and edits to existing ones; the rest of the
difference is the instruction files renamed from `CLAUDE.md` to `AGENTS.md`.

| Module | Status |
| --- | --- |
| `llm_client/inside_success_policy.py` | New: company model-policy overlay that allows reviewed Inside Success routes |
| `llm_client/execution/codex_identity.py` | New: privacy-bounded account identity evidence for ChatGPT-authenticated Codex calls |
| `llm_client/utils/litellm_log_filters.py` | New: targeted noise filter for LiteLLM's background logging worker |
| `core/client.py`, `core/errors.py`, `core/model_execution_policy.py`, `execution/*` (call contracts, lifecycle, wrappers, kernel, retry, structured runtime, timeout policy), `agent/mcp_turn_outcomes.py`, `codex_canary.py`, `langfuse_callbacks.py`, `utils/openrouter.py` | Modified |

This wiki's concept, workflow, and architecture pages were written against
`4f7ecfa` and cite that revision. They were not rewritten for these edits;
reopen native source at `5228ceb` for exact behavior of the modified modules.
Only the file counts and the lineage page were refreshed in this ingest.

# Limits

No repository capsule exists for `5228ceb`; the retained capsules describe
earlier revisions. The manifest's network pin records `5228ceb` as the observed
`main` head at ingest time and goes stale when `main` moves, which is expected
for `make codebase-wiki-check-full`. This is a source-only binding and proves
nothing about a deployed version.
