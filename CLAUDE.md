# LLM Client

`CLAUDE.md` is the authored repository instruction authority. `AGENTS.md` is
its generated Codex-facing projection. Machine-readable ADR, coupling, and
required-reading edges are authored in `scripts/relationships.yaml`.

## Purpose

LLM Client uses `CLAUDE.md` as canonical repo governance and workflow policy.

## Commands

```bash
# Tests
make test                    # Full test suite
make test-quick              # Tests, minimal output
make check                   # Tests + type check + lint

# Observability
make cost                    # Total LLM spend (DAYS=7)
make cost-by-task            # Spend per task
make cost-by-model           # Spend per model
make errors                  # Error breakdown by model
make summary                 # Project stats

# Development
make status                  # git status --short --branch
make help                    # List all targets
make dead-code               # Run current dead-code scan
make dead-code-audit         # Refresh reviewed dead-code inventory
make dead-code-validate      # Validate reviewed dead-code dispositions

# API Reference
python scripts/meta/generate_api_reference.py --write  # Regenerate docs

# Plans
python scripts/meta/check_plan_tests.py --plan N       # Run tests for plan
python scripts/meta/complete_plan.py --plan N           # Mark plan complete

# Read-gating
python scripts/meta/check_required_reading.py <file>    # Check read-gate for a source file
python scripts/meta/validate_relationships.py --strict  # Validate coupling config
```

This file keeps the highest-signal repository rules in always-on agent context.
Use the linked project authorities and the nearest subtree `CLAUDE.md` for
details scoped below the repository root.

## Principles

1. **Runtime substrate, not thin wrapper** -- `llm_client` is a control plane providing routing, observability, retry/fallback, and structured output enforcement. It is not a convenience layer over LiteLLM.
2. **Required kwargs on every call** -- `task=`, `trace_id=`, `max_budget=`. No exceptions.
3. **Prompts as data** -- YAML/Jinja2 templates in `prompts/`, loaded via `render_prompt()`. No f-string prompts in calling code.
4. **Structured output via `json_schema`** -- Always use `json_schema` response_format, never `json_object`. Schema field descriptions are the primary mechanism for correct output.
5. **Observability first** -- All state changes logged with context. Query `~/projects/data/llm_observability.db` for real costs; never estimate.
6. **Fail loud** -- No silent fallbacks, no `except: pass`. Errors surface with context.
7. **Programs A-D complete** -- Do not invent new cleanup slices without fresh evidence. The roadmap tracks what remains.
8. **API reference is generated** -- Run `python scripts/meta/generate_api_reference.py --write` after changing the public surface or docstrings.

## Workflow

### Process Awareness
- All significant work follows meta-process plans in `docs/plans/`.
- Use `[Trivial]` only for <20 lines with no production code changes.
- Plan index: `docs/plans/CLAUDE.md`. Template: `docs/plans/TEMPLATE.md`.

### Read-Gating
- Source files coupled to ADRs in `scripts/relationships.yaml` require reading the linked docs before editing.
- `.claude/hooks/gate-edit.sh` enforces this at edit time.
- Override temporarily: `LLM_CLIENT_READ_GATE_MODE=warn`.

### Testing
- `make test` runs the full suite. `make check` adds type checking and lint.
- Plan-specific tests: `python scripts/meta/check_plan_tests.py --plan N`.

## Machine-Readable Governance

`scripts/relationships.yaml` is the source of truth for machine-readable governance in this repo: ADR coupling, required-reading edges, and doc-code linkage. This instruction file does not duplicate that graph. Prefer deterministic validators over prompt-only memory when those scripts are available.

## References

| Doc | Purpose |
|-----|---------|
| `docs/plans/01_master-roadmap.md` | Master roadmap (Programs A-E) |
| `docs/plans/CLAUDE.md` | Plan index |
| `docs/API_REFERENCE.md` | Generated API reference |
| `docs/adr/README.md` | Architecture decision records index |
| `scripts/relationships.yaml` | Source-doc coupling and read-gate config |
| `scripts/CLAUDE.md` | Scripts directory reference |
| `.openclaw/success-criteria.yaml` | OpenClaw success criteria contract |
