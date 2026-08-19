"""llm_calls must record which account paid, so the split can be audited."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from llm_client import io_log
from llm_client.utils import openrouter_accounts as acct


@pytest.fixture(autouse=True)
def _clear_caches():
    acct._git_remote_url.cache_clear()
    yield
    acct._git_remote_url.cache_clear()


def _git_repo(root: Path, remote: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=root, check=True)
    return root


def _fresh_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "obs.db")
    conn.executescript(io_log._TABLES_SQL)
    io_log._migrate_db(conn)
    return conn


def test_schema_has_billing_columns(tmp_path):
    conn = _fresh_db(tmp_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(llm_calls)")}
    assert "billing_account" in cols
    assert "openrouter_key_fingerprint" in cols


def test_migration_is_additive_on_an_existing_db(tmp_path):
    """An older database gains the columns without losing rows."""
    conn = _fresh_db(tmp_path)
    conn.execute("ALTER TABLE llm_calls DROP COLUMN billing_account")
    conn.execute("ALTER TABLE llm_calls DROP COLUMN openrouter_key_fingerprint")
    conn.execute("INSERT INTO llm_calls (timestamp, project, model) VALUES ('2026-01-01T00:00:00', 'p', 'm')")
    conn.commit()

    io_log._migrate_db(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(llm_calls)")}
    assert {"billing_account", "openrouter_key_fingerprint"} <= cols
    rows = conn.execute("SELECT project, billing_account FROM llm_calls").fetchall()
    assert rows == [("p", None)], "pre-existing rows must survive, unattributed"


def test_billing_account_is_not_indexed(tmp_path):
    """llm_calls is ~25M rows in practice; an index build here would stall startup."""
    conn = _fresh_db(tmp_path)
    indexes = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='llm_calls'")}
    assert "idx_calls_billing_account" not in indexes


def test_migration_is_idempotent(tmp_path):
    conn = _fresh_db(tmp_path)
    io_log._migrate_db(conn)
    io_log._migrate_db(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(llm_calls)")]
    assert cols.count("billing_account") == 1


def test_attribution_resolves_account_from_repository(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "client", "https://github.com/Inside-Success/graph-retrieval.git")
    monkeypatch.chdir(repo)
    account, _ = io_log._billing_attribution("openrouter/openai/gpt-5")
    assert account == "inside_success"


def test_attribution_defaults_to_personal_for_unowned_repository(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "mine", "https://github.com/BrianMills2718/whatever.git")
    monkeypatch.chdir(repo)
    account, _ = io_log._billing_attribution("openrouter/openai/gpt-5")
    assert account == "personal"


def test_fingerprint_only_for_openrouter_models(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "mine", "https://github.com/BrianMills2718/whatever.git")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-abcdefghijklmnop")
    monkeypatch.delenv("OPENROUTER_API_KEY_PERSONAL", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY_INSIDE_SUCCESS", raising=False)

    _, fp_router = io_log._billing_attribution("openrouter/openai/gpt-5")
    _, fp_direct = io_log._billing_attribution("claude-sonnet-4")
    assert fp_router is not None
    assert fp_direct is None, "a non-OpenRouter model has no OpenRouter key to attribute"


def test_fingerprint_never_contains_the_raw_secret(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "mine", "https://github.com/BrianMills2718/whatever.git")
    monkeypatch.chdir(repo)
    secret = "sk-or-v1-supersecretvalue0123456789"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    monkeypatch.delenv("OPENROUTER_API_KEY_PERSONAL", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY_INSIDE_SUCCESS", raising=False)

    _, fingerprint = io_log._billing_attribution("openrouter/openai/gpt-5")
    assert fingerprint is not None
    assert secret not in fingerprint
    assert "supersecret" not in fingerprint


def test_attribution_never_raises_into_the_call_path(monkeypatch):
    """Telemetry failure must not break an LLM call; key selection is the real gate."""
    def _boom(*_a, **_k):
        raise RuntimeError("git exploded")

    monkeypatch.setattr(acct, "resolve_account", _boom)
    account, _ = io_log._billing_attribution("openrouter/openai/gpt-5")
    assert account is None
