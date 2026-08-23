---
type: source
title: Revision 657a98f Source Ingest
description: Current source binding after preserving Python 3.10 dependency compatibility.
created: 2026-08-22
updated: 2026-08-22
sources: [../../raw/source-manifest-657a98f-company-f4a08fe.json, revision-917318b.md, ../../../../pyproject.toml]
confidence: high
---

# Current source binding

The current personal upstream source is commit
`657a98f135f6e0665cf34d81a8e8655c387dce69`, Git tree
`3d68f9a5d38915de654d182d477f26f8da95bb55`. Its deterministic code surface is
165 Python files plus `pyproject.toml`, bound by digest
`sha256:1498eadd...e7ab3b` in the immutable
[manifest](../../raw/source-manifest-657a98f-company-f4a08fe.json).

This revision retains the exact Codex-session capability implemented at
[revision `917318b`](revision-917318b.md) and adds one packaging correction.
LiteLLM 1.98.0 imports `typing.NotRequired`, which is unavailable on Python
3.10, even though the dependency publishes a compatible wheel. The project
advertises Python 3.10 support, so its dependency marker now constrains 3.10 to
LiteLLM below 1.98.0 while leaving Python 3.11 and newer on the existing open
upper range.

# Evidence and limits

The marker was evaluated provider-free for both Python 3.10 and 3.12 target
environments. GitHub's Python 3.10 import smoke exposed the incompatible 1.98.0
release; a subsequent CI run owns end-to-end installation evidence. No current
repository capsule was generated, so exact current claims still reopen native
source.

# Citations

1. [Current source tree](https://github.com/BrianMills2718/llm_client/tree/657a98f135f6e0665cf34d81a8e8655c387dce69)
2. [Python dependency markers](https://github.com/BrianMills2718/llm_client/blob/657a98f135f6e0665cf34d81a8e8655c387dce69/pyproject.toml#L9-L20)
3. [Exact Codex-session source ingest](revision-917318b.md)
