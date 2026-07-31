"""Focused policy and transport controls for subscription-backed Codex Terra."""

from pathlib import Path

from llm_client.core.model_execution_policy import (
    ALLOWED_EXECUTION_MODELS,
    REASONING_CAPABILITIES,
    evaluate_model_execution_policy,
)
from llm_client.sdk.agents import _build_codex_cli_command

MODEL = "codex/gpt-5.6-terra"


def test_codex_terra_admits_explicit_low_medium_and_high_reasoning() -> None:
    for effort in ("low", "medium", "high"):
        decision = evaluate_model_execution_policy(
            [MODEL],
            justification="Use the operator-selected subscription-backed Terra route.",
            reasoning_effort=effort,
        )

        assert MODEL in ALLOWED_EXECUTION_MODELS
        assert decision.uses_only_default is False
        assert decision.reasoning_policy.effort == effort
    assert REASONING_CAPABILITIES[MODEL].supported_efforts == frozenset(
        {"low", "medium", "high"}
    )


def test_codex_cli_command_selects_terra_at_low_effort(tmp_path: Path) -> None:
    command, _env, _stdin_payload = _build_codex_cli_command(
        MODEL,
        "Return the requested structured result.",
        output_schema={"type": "object", "properties": {}},
        kwargs={
            "working_directory": str(tmp_path),
            "approval_policy": "never",
            "sandbox_mode": "read-only",
            "skip_git_repo_check": True,
            "model_reasoning_effort": "low",
        },
        output_path=str(tmp_path / "last.txt"),
        schema_path=str(tmp_path / "schema.json"),
    )

    assert command[command.index("--model") + 1] == "gpt-5.6-terra"
    assert 'model_reasoning_effort="low"' in command
    assert command[command.index("-s") + 1] == "read-only"
