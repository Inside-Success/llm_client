---
type: source
title: Revision 4f7ecfa Source Ingest
description: Current source binding with exact Codex CLI JSONL custody at the public result boundary.
created: 2026-08-23
updated: 2026-08-23
sources: [../../raw/source-manifest-4f7ecfa-company-f4a08fe.json, ../../../../llm_client/core/data_types.py, ../../../../llm_client/sdk/agents_codex.py]
confidence: high
---

# Current source binding

The current personal upstream source is commit
`4f7ecfa9527bb68dd5a9bda81abd384612c0d9cd`, Git tree
`e9dfd48904b4efc3c8bc8ab330b2455a611c689f`. Its deterministic code surface is
165 Python files plus `pyproject.toml`, bound by digest
`sha256:c4a6aecf...f19a9475` in the immutable
[manifest](../../raw/source-manifest-4f7ecfa-company-f4a08fe.json).

# Exact Codex stream custody

Direct Codex CLI results now carry two intentionally different evidence
surfaces. `codex_events` is the normalized ordered projection of completed
items. `codex_jsonl` retains every nonblank decoded stdout line without parsing
or normalization, including malformed and unknown envelopes. The public
dataclass, Pydantic boundary schema, structured-call path, and process-safe
serializer all preserve the exact-line field.

This split lets experiment controllers parse and hash the real observed stream
without treating the shared client's completed-item filter as an exhaustive
event ledger. It remains transport output, not provider attestation or durable
replay storage.

# Evidence and limits

Provider-free tests exercise valid, future, and malformed lines; exact ordering;
structured public-call propagation; process serialization; and schema parity.
The current source has no newly generated repository capsule, so exact claims
reopen native source at this revision.

# Citations

1. [`LLMCallResult` evidence fields](https://github.com/BrianMills2718/llm_client/blob/4f7ecfa9527bb68dd5a9bda81abd384612c0d9cd/llm_client/core/data_types.py#L29-L92)
2. [CLI attachment and public result construction](https://github.com/BrianMills2718/llm_client/blob/4f7ecfa9527bb68dd5a9bda81abd384612c0d9cd/llm_client/sdk/agents_codex.py#L762-L924)
3. [Exact-line extraction](https://github.com/BrianMills2718/llm_client/blob/4f7ecfa9527bb68dd5a9bda81abd384612c0d9cd/llm_client/sdk/agents_codex.py#L1604-L1624)
4. [Process-safe field preservation](https://github.com/BrianMills2718/llm_client/blob/4f7ecfa9527bb68dd5a9bda81abd384612c0d9cd/llm_client/sdk/agents_codex.py#L590-L647)
