"""Account routing must bill the owning account without human intervention."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from llm_client.utils import openrouter_accounts as acct


@pytest.fixture(autouse=True)
def _clear_remote_cache():
    acct._git_remote_url.cache_clear()
    yield
    acct._git_remote_url.cache_clear()


@pytest.fixture()
def routing_file(tmp_path: Path) -> Path:
    payload = {
        "schema_version": "1.0",
        "default_account": "personal",
        "remote_owner_accounts": {"inside-success": "inside_success"},
        "repository_accounts": {"brianmills2718/onto-canon6": "inside_success"},
    }
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _git_repo(root: Path, remote: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=root, check=True)
    return root


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("https://github.com/Inside-Success/graph-retrieval.git", "inside_success"),
        ("git@github.com:Inside-Success/llm_client.git", "inside_success"),
        ("git@github.com-personal:BrianMills2718/llm_client.git", "personal"),
        ("https://github.com/BrianMills2718/agent_memory.git", "personal"),
    ],
)
def test_owner_decides_account(tmp_path, routing_file, remote, expected):
    repo = _git_repo(tmp_path / "repo", remote)
    assert acct.resolve_account(repo, routing_path=routing_file) == expected


def test_personally_owned_repo_can_be_declared_client_work(tmp_path, routing_file):
    """A personal remote doing client work routes by explicit declaration."""
    repo = _git_repo(tmp_path / "onto", "git@github.com-personal:BrianMills2718/onto-canon6.git")
    assert acct.resolve_account(repo, routing_path=routing_file) == "inside_success"


def test_symlinked_client_workspace_does_not_change_routing(tmp_path, routing_file):
    """Path is not a routing signal: client repos are symlinks into a personal tree."""
    repo = _git_repo(tmp_path / "personal-tree" / "onto-canon6",
                     "git@github.com-personal:BrianMills2718/onto-canon6.git")
    link = tmp_path / "inside-success" / "onto-canon6"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(repo)
    assert acct.resolve_account(link, routing_path=routing_file) == "inside_success"
    assert acct.resolve_account(repo, routing_path=routing_file) == "inside_success"


def test_undeclared_repository_falls_back_to_personal(tmp_path, routing_file):
    """Fail safe: never spend a client's money on an undeclared repository."""
    repo = _git_repo(tmp_path / "new", "https://github.com/BrianMills2718/brand-new.git")
    assert acct.resolve_account(repo, routing_path=routing_file) == "personal"


def test_non_repository_falls_back_to_personal(tmp_path, routing_file):
    assert acct.resolve_account(tmp_path, routing_path=routing_file) == "personal"


def test_explicit_override_wins(tmp_path, routing_file, monkeypatch):
    repo = _git_repo(tmp_path / "repo", "https://github.com/BrianMills2718/x.git")
    monkeypatch.setenv(acct.ACCOUNT_OVERRIDE_ENV, "inside_success")
    assert acct.resolve_account(repo, routing_path=routing_file) == "inside_success"


def test_unknown_override_is_rejected(tmp_path, routing_file, monkeypatch):
    monkeypatch.setenv(acct.ACCOUNT_OVERRIDE_ENV, "not-an-account")
    with pytest.raises(acct.AccountRoutingError):
        acct.resolve_account(tmp_path, routing_path=routing_file)


def test_broken_routing_table_raises_rather_than_guessing(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(acct.AccountRoutingError):
        acct.resolve_account(tmp_path, routing_path=bad)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git@github.com-personal:BrianMills2718/onto-canon6.git", ("brianmills2718", "onto-canon6")),
        ("https://github.com/Inside-Success/graph-retrieval.git", ("inside-success", "graph-retrieval")),
        ("ssh://git@github.com/Inside-Success/Team-Brains.git", ("inside-success", "team-brains")),
        ("https://github.com/Inside-Success/graph-retrieval", ("inside-success", "graph-retrieval")),
        ("not a remote url", None),
    ],
)
def test_remote_identity_parsing(url, expected):
    assert acct.parse_remote_identity(url) == expected


# ---------------------------------------------------------------------------
# Integration with key-ring resolution in llm_client.utils.openrouter
# ---------------------------------------------------------------------------

from llm_client.core.errors import LLMConfigurationError
from llm_client.utils import openrouter as _or

_ALL_KEY_ENV = (
    "OPENROUTER_API_KEY",
    "OPENROUTER_API_KEYS",
    "OPENROUTER_API_KEY_2",
    "OPENROUTER_API_KEY_PERSONAL",
    "OPENROUTER_API_KEY_INSIDE_SUCCESS",
    acct.ACCOUNT_OVERRIDE_ENV,
)


@pytest.fixture()
def clean_key_env(monkeypatch):
    for name in _ALL_KEY_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_legacy_single_key_behaviour_is_untouched(clean_key_env):
    """Without per-account credentials, nothing about key resolution changes."""
    clean_key_env.setenv("OPENROUTER_API_KEY", "sk-legacy")
    clean_key_env.setenv("OPENROUTER_API_KEY_2", "sk-legacy-fallback")
    assert _or._openrouter_key_candidates_from_env() == ("sk-legacy", "sk-legacy-fallback")


def test_routed_account_key_is_used(clean_key_env, monkeypatch, routing_file):
    clean_key_env.setenv("OPENROUTER_API_KEY_INSIDE_SUCCESS", "sk-company")
    clean_key_env.setenv("OPENROUTER_API_KEY_PERSONAL", "sk-personal")
    clean_key_env.setenv(acct.ACCOUNT_OVERRIDE_ENV, "inside_success")
    monkeypatch.setenv(acct.ROUTING_PATH_ENV, str(routing_file))
    assert _or._openrouter_key_candidates_from_env() == ("sk-company",)


def test_routing_drops_the_other_accounts_key_from_the_ring(clean_key_env, monkeypatch, routing_file):
    """The ring must never fail over from one billing account onto another."""
    clean_key_env.setenv("OPENROUTER_API_KEY_INSIDE_SUCCESS", "sk-company")
    clean_key_env.setenv("OPENROUTER_API_KEY_PERSONAL", "sk-personal")
    clean_key_env.setenv("OPENROUTER_API_KEY", "sk-personal")
    clean_key_env.setenv(acct.ACCOUNT_OVERRIDE_ENV, "inside_success")
    monkeypatch.setenv(acct.ROUTING_PATH_ENV, str(routing_file))

    candidates = _or._openrouter_key_candidates_from_env()
    assert candidates == ("sk-company",)
    assert "sk-personal" not in candidates


def test_within_account_rotation_is_preserved(clean_key_env, monkeypatch, routing_file):
    """Account routing constrains which account may be billed, not rotation itself."""
    clean_key_env.setenv("OPENROUTER_API_KEY_INSIDE_SUCCESS", "sk-company")
    clean_key_env.setenv("OPENROUTER_API_KEY_PERSONAL", "sk-personal")
    clean_key_env.setenv("OPENROUTER_API_KEY", "sk-personal")
    clean_key_env.setenv("OPENROUTER_API_KEY_2", "sk-personal-spare")
    clean_key_env.setenv(acct.ACCOUNT_OVERRIDE_ENV, "personal")
    monkeypatch.setenv(acct.ROUTING_PATH_ENV, str(routing_file))

    candidates = _or._openrouter_key_candidates_from_env()
    assert candidates == ("sk-personal", "sk-personal-spare")
    assert "sk-company" not in candidates


def test_unrelated_keys_are_left_alone_but_warned_about(clean_key_env, monkeypatch, routing_file, caplog):
    """A key matching no configured account cannot be proven safe, so it is flagged."""
    clean_key_env.setenv("OPENROUTER_API_KEY_INSIDE_SUCCESS", "sk-company")
    clean_key_env.setenv("OPENROUTER_API_KEY", "sk-unrelated")
    clean_key_env.setenv(acct.ACCOUNT_OVERRIDE_ENV, "personal")
    monkeypatch.setenv(acct.ROUTING_PATH_ENV, str(routing_file))

    with caplog.at_level("WARNING"):
        candidates = _or._openrouter_key_candidates_from_env()
    assert candidates == ("sk-unrelated",)
    assert "sk-company" not in candidates
    assert any("no key matching" in r.message for r in caplog.records)


def test_missing_credential_for_owning_account_fails_loud(clean_key_env, monkeypatch, routing_file):
    """Never silently fall through to another account's key."""
    clean_key_env.setenv("OPENROUTER_API_KEY_PERSONAL", "sk-personal")
    clean_key_env.setenv("OPENROUTER_API_KEY", "sk-personal")
    clean_key_env.setenv(acct.ACCOUNT_OVERRIDE_ENV, "inside_success")
    monkeypatch.setenv(acct.ROUTING_PATH_ENV, str(routing_file))
    with pytest.raises(LLMConfigurationError, match="OPENROUTER_API_KEY_INSIDE_SUCCESS"):
        _or._openrouter_key_candidates_from_env()
