# Prompt Rendering

This subtree contains the prompt rendering engine for `llm_client`.

## Purpose

Prompt rendering logic (`prompts.py`, `prompt_assets.py`) lives here. Canonical
prompt asset data files (YAML/Jinja2 templates) live externally at
`~/projects/prompts/` — configurable via `LLM_CLIENT_PROMPT_ASSET_ROOT`.
Package fallback copies for required built-ins live under
`llm_client/prompt_assets/` and must stay synced with the external canonical
asset when both exist.

## Local Rules

1. Keep prompt templates declarative and data-driven.
2. Update prompt-related docs or schemas when the prompt contract changes.
3. Do not move prompt text into Python source unless a test or loader requires
   it for a specific compatibility reason.
