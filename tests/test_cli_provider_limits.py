"""Subprocess tests for the agent-drivable provider-limit CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


SECRET = "sk-or-v1-cli-super-secret"


def _cli_env(tmp_path: Path) -> dict[str, str]:
    """Return one explicit provider-free inspection environment."""
    empty = tmp_path / "empty.env"
    empty.write_bytes(b"")
    env = os.environ.copy()
    env["LLM_CLIENT_KEYS_FILE"] = str(empty)
    env["OPENROUTER_API_KEY"] = SECRET
    env.pop("OPENROUTER_API_KEYS", None)
    for name in tuple(env):
        if name.startswith("OPENROUTER_API_KEY_"):
            env.pop(name)
    return env


def test_provider_limit_inspect_cli_is_provider_free_and_secret_free(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "llm_client", "provider-limit", "openrouter", "--inspect-only"],
        env=_cli_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "openrouter-key-environment-v1"
    assert payload["key_count"] == 1
    assert SECRET not in proc.stdout
    assert SECRET[-4:] not in proc.stdout


def test_provider_limit_cli_requires_one_explicit_action(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "llm_client", "provider-limit", "openrouter"],
        env=_cli_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    assert "--inspect-only" in proc.stderr
    assert "--allow-provider-read" in proc.stderr
    assert SECRET not in proc.stderr


def test_provider_limit_cli_error_is_stable_json_and_secret_free(tmp_path: Path) -> None:
    env = _cli_env(tmp_path)
    env["OPENROUTER_API_KEYS"] = SECRET
    proc = subprocess.run(
        [sys.executable, "-m", "llm_client", "provider-limit", "openrouter", "--inspect-only"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    payload = json.loads(proc.stderr)
    assert payload["code"] == "OPENROUTER_ROTATION_SOURCE_PRESENT"
    assert SECRET not in proc.stderr
    assert SECRET[-4:] not in proc.stderr
