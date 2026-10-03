# Tests Directory

Pytest suite for `llm_client`.

## Running Tests

```bash
# Full suite. pyproject.toml addopts is "-m 'not integration'", so integration
# tests are already excluded by default (same as `make test`).
pytest tests/

# Integration tests explicitly (real network; see Makefile `test-integration`)
LLM_CLIENT_INTEGRATION=1 pytest -m integration

# Long-thinking smoke only (extra opt-in)
LLM_CLIENT_INTEGRATION=1 LLM_CLIENT_LONG_THINKING_SMOKE=1 pytest -m integration tests/integration_long_thinking_smoke_test.py

# Single test
pytest tests/test_client.py::TestRequiredTags::test_calls_experiment_enforcement_hook
```

## Conventions

1. Keep tests deterministic and offline-safe by default.
2. Mark real network tests with `@pytest.mark.integration`.
3. Prefer focused unit/contract assertions; avoid brittle snapshot-style checks.
4. When behavior contracts change, update both tests and relevant ADR/docs together.
