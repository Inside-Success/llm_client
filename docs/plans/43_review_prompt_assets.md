# Plan #43: Version Adversarial Review Prompts as Assets

**Status:** Complete
**Type:** implementation
**Priority:** Medium
**Blocked By:** None
**Blocks:** None

## Gap

The retained adversarial-review workflow embedded its generic and
quality-optimal behavioral prompts in Python even though the package already
has a versioned prompt-asset loader. The workflow should load those prompts
from named assets while preserving its public behavior.

## Research

- `llm_client/workflow/adversarial_review.py` — retained workflow and profiles.
- `llm_client/prompt_assets/` and `llm_client/prompts/` — existing asset parsing
  and rendering boundaries.
- Stale PR #32 — original implementation and regression tests.
- Current `main` — target for conflict resolution and compatibility testing.

## Boundary

- Preserve the public review profiles, response schemas, and rendered message
  contract.
- Validate prompt references when profiles are registered.
- Do not add model calls, change routing, or alter review-result semantics.

## Files Affected

- `llm_client/workflow/adversarial_review.py`
- `llm_client/prompt_assets/shared/review/`
- `tests/test_workflow_adversarial_review.py`
- `docs/plans/CLAUDE.md`

## Acceptance Criteria

- Generic and quality-optimal profiles resolve versioned prompt assets.
- Existing prompt content and schema-version behavior remain covered.
- A regression test prevents the quality-optimal policy text from returning to
  Python source.
- The focused adversarial-review and prompt-asset tests pass.

## Evidence

- Reconciled from stale PR #32 onto current `main`.
- `pytest -q tests/test_workflow_adversarial_review.py tests/test_prompts.py`
  records the current focused result in the landing commit.
