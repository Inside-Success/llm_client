"""Shared test fixtures for llm_client test suite.

Disables observability logging during tests and points observability env vars at
temporary paths so even accidental re-enable paths cannot contend with the
shared global JSONL + SQLite observability state.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_observability_logging(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
    """Prevent tests from writing to the shared observability DB/JSONL."""

    monkeypatch.setenv("LLM_CLIENT_LOG_ENABLED", "0")
    monkeypatch.setenv("LLM_CLIENT_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("LLM_CLIENT_DB_PATH", str(tmp_path / "test-suite-observability.db"))
    monkeypatch.setenv("LLM_CLIENT_PROJECT", "pytest-suite")
