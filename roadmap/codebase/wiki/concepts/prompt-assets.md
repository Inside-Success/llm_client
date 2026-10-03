---
type: concept
title: Prompt Assets
description: Versioned YAML/Jinja prompt identity, rendering, and observability boundaries.
created: 2026-08-16
updated: 2026-10-03
sources: [../../../../llm_client/prompts.py, ../../../../llm_client/prompt_assets.py, ../../../../llm_client/prompt_assets]
confidence: high
---

# Prompts as data

The repository treats reusable prompts as versioned assets rather than inline
f-strings in application code. `render_prompt` accepts either a YAML template
path or a `prompt_ref`, renders Jinja placeholders with strict missing-variable
behavior, validates role/content structure, and returns OpenAI-format message
dictionaries. The two source mechanisms are mutually exclusive.

`prompt_assets.py` gives shared assets explicit identity. A reference such as
`shared.summarize.concise@1` is parsed and resolved through a manifest to a
pinned asset file. Callers may pass the normalized prompt reference into the
public LLM call so observability can associate execution with the asset without
confusing the reference with the rendered prompt bytes.

Before rendering, `render_prompt` enforces a sibling `<template>.contract.yaml`
context budget (strict mode is configurable) and reports large content repeated
inside the context; setting `LLM_CLIENT_PROMPT_DUPLICATE_STRICT` makes
duplication an error.

# Ownership

This package owns prompt loading, rendering, identity, and propagation into
runtime evidence. It does not own prompt-evaluation rubrics or optimization
loops; those remain outside `llm_client` under the repository’s
[capability boundary](../overview.md). The
[public API](public-api-and-contracts.md) owns how `prompt_ref` travels into a
call envelope.

# Citations

All links pin Inside-Success/llm_client at `fe581ed`.

1. [`render_prompt`, lines 62-149](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/prompts.py#L62-L149)
2. [`resolve_prompt_asset`, lines 160-217](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/prompt_assets.py#L160-L217)
3. [Prompt-assets directory](https://github.com/Inside-Success/llm_client/blob/fe581ed19486f26dd06e8d08366ebe2bda21f8d1/llm_client/prompt_assets)
