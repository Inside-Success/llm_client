"""Focused transport controls for subscription-backed Codex Luna."""

from pathlib import Path

from llm_client.sdk.agents import _build_codex_cli_command


def test_build_codex_cli_command_selects_luna_at_medium_effort(
    tmp_path: Path,
) -> None:
    command, _env, _stdin_payload = _build_codex_cli_command(
        "codex/gpt-5.6-luna",
        "Return the requested structured result.",
        output_schema={"type": "object", "properties": {}},
        kwargs={
            "working_directory": str(tmp_path),
            "approval_policy": "never",
            "sandbox_mode": "read-only",
            "skip_git_repo_check": True,
            "model_reasoning_effort": "medium",
        },
        output_path=str(tmp_path / "last.txt"),
        schema_path=str(tmp_path / "schema.json"),
    )

    assert command[command.index("--model") + 1] == "gpt-5.6-luna"
    assert 'model_reasoning_effort="medium"' in command
    assert command[command.index("-s") + 1] == "read-only"
    assert command[command.index("--output-schema") + 1] == str(
        tmp_path / "schema.json"
    )
