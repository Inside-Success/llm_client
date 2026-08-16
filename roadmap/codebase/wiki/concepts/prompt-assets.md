---
type: concept
title: Prompt Assets
description: Versioned YAML/Jinja prompt identity, rendering, and observability boundaries.
created: 2026-08-16
updated: 2026-08-16
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

# Ownership

This package owns prompt loading, rendering, identity, and propagation into
runtime evidence. It does not own prompt-evaluation rubrics or optimization
loops; those remain outside `llm_client` under the repository’s
[capability boundary](../overview.md). The
[public API](public-api-and-contracts.md) owns how `prompt_ref` travels into a
call envelope.

# Citations

1. [`render_prompt`, lines 57–128](https://github.com/BrianMills2718/llm_client/blob/f194028cec906fac8f3e3eef48ad30d84e8cf5bb/llm_client/prompts.py#L57-L128)
2. [`resolve_prompt_asset`, lines 160–217](https://github.com/BrianMills2718/llm_client/blob/f194028cec906fac8f3e3eef48ad30d84e8cf5bb/llm_client/prompt_assets.py#L160-L217)
3. [Prompt-assets directory at the pinned revision](https://github.com/BrianMills2718/llm_client/tree/f194028cec906fac8f3e3eef48ad30d84e8cf5bb/llm_client/prompt_assets)
