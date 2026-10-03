# CLI Commands

This subtree contains the `python -m llm_client` command modules.

## Purpose

Keep command entrypoints thin, deterministic, and easy to trace back to the
underlying package APIs. The command surface should expose the runtime substrate
without becoming a second implementation layer.

## What Lives Here

- `common.py` for shared CLI helpers
- Subcommand handlers: `adoption.py`, `backfill.py`, `cost.py`,
  `dashboard.py` (+ `dashboard_server.py`), `deliberate.py`, `duet.py`,
  `experiments.py` (+ `experiments_analytics.py`), `json_schema_call.py`,
  `models.py`, `prompt_drift.py`, `prompt_show.py`, `provider_limits.py`,
  `replay.py`, `review_artifact.py`, `review_cycle.py`,
  `route_certification.py`, `scores.py`, `tool_lint.py`, `tool_usage.py`,
  `tools.py`, and `traces.py`
- `__init__.py` for subcommand registration (the authoritative command list is
  `python -m llm_client --help`)

## Local Rules

1. Prefer calling package APIs over duplicating logic in the CLI layer.
2. Keep table/JSON formatting code local when it is purely presentation logic.
3. Keep read-only inspection commands separate from mutation or backfill
   commands.
4. Update the CLI help text when new subcommands or options are added.
