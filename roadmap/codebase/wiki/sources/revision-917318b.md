---
type: source
title: Revision 917318b Source Ingest
description: Current source binding for the complete Python/config surface and the exact Codex session-continuation seam.
created: 2026-08-22
updated: 2026-08-22
sources: [../../raw/source-manifest-917318b-company-f4a08fe.json, ../../../../llm_client/sdk/agents.py, ../../../../llm_client/sdk/agents_codex.py, ../../../../docs/guides/codex-integration.md]
confidence: high
---

# Exact session-capability source binding

The wiki describes personal upstream `BrianMills2718/llm_client` at source
commit `917318bf5d9087cff5148409a52a068103496c6f`, Git tree
`cfdb8d2260424f6a92fd844c7e046f4b5e2581bb`. The deterministic surface contains
165 tracked Python files plus `pyproject.toml`; its digest and current authority
hashes are bound by the immutable
[manifest](../../raw/source-manifest-917318b-company-f4a08fe.json).

This ingest advances the wiki's exact source binding without claiming that an
equally current repository capsule exists. The accepted `f194028` Project Meta
capsule, the verified-but-unpublished `c2f3693` personal capsule, and the
accepted `f4a08fe` Inside Success capsule remain distinct older evidence in the
manifest. Native source at `917318b` is authoritative for current code claims.

# Exact Codex session continuation

The public agent-kwarg boundary now carries `codex_session_mode` and
`codex_session_id`. Explicit `fresh`, `resume`, or `fork` calls use only the CLI
transport and require a stable caller-owned Codex home. The adapter renders the
exact subcommand, parses the returned session identity, rejects missing or
conflicting receipts, requires resume identity equality, and requires fork
identity inequality. The result includes an opaque home identity and its
persistence classification so an orchestrator can bind a continuation receipt
without logging the home path.

Ordinary one-shot calls retain temporary-home isolation. Explicit session
streaming fails visibly because the current streaming path uses the SDK and
cannot prove exact continuation; it never silently substitutes a fresh thread.

# Limits

This provider-free source ingest proves command construction, session-store
custody, receipt validation, and fail-loud routing. It does not claim that a
live model was invoked or that downstream AC16 has adopted the seam. Those are
separate runtime and consumer evidence boundaries.

Revision `657a98f` now owns the [current repository source binding](revision-657a98f.md)
after a packaging-only Python 3.10 compatibility correction.

# Citations

1. [Current source tree](https://github.com/BrianMills2718/llm_client/tree/917318bf5d9087cff5148409a52a068103496c6f)
2. [Public agent kwargs](https://github.com/BrianMills2718/llm_client/blob/917318bf5d9087cff5148409a52a068103496c6f/llm_client/sdk/agents.py#L200-L216)
3. [Persistent home and exact CLI receipt](https://github.com/BrianMills2718/llm_client/blob/917318bf5d9087cff5148409a52a068103496c6f/llm_client/sdk/agents_codex.py#L236-L282)
4. [Session command and validation](https://github.com/BrianMills2718/llm_client/blob/917318bf5d9087cff5148409a52a068103496c6f/llm_client/sdk/agents_codex.py#L650-L930)
5. [Streaming refusal](https://github.com/BrianMills2718/llm_client/blob/917318bf5d9087cff5148409a52a068103496c6f/llm_client/sdk/agents_codex.py#L1387-L1415)
