"""End-to-end CLI tests for the ``deliberate-task`` subcommand."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest


def test_parse_agents_two_agents() -> None:
    from llm_client.cli.deliberate import _parse_agents

    pairs = _parse_agents("a:codex/gpt-5.6-luna,b:claude-code/sonnet")
    assert pairs == [("a", "codex/gpt-5.6-luna"), ("b", "claude-code/sonnet")]


def test_parse_agents_strips_whitespace() -> None:
    from llm_client.cli.deliberate import _parse_agents

    pairs = _parse_agents("  a : codex/gpt-5.6-luna , b : claude-code/sonnet  ")
    assert pairs == [("a", "codex/gpt-5.6-luna"), ("b", "claude-code/sonnet")]


def test_parse_agents_rejects_malformed() -> None:
    from llm_client.cli.deliberate import _parse_agents

    with pytest.raises(ValueError, match="exactly 2 entries"):
        _parse_agents("only-one:codex/gpt-5.6-luna")
    with pytest.raises(ValueError, match="exactly 2 entries"):
        _parse_agents("a:m1,b:m2,c:m3")
    with pytest.raises(ValueError, match="expected 'name:model'"):
        _parse_agents("malformed,b:m2")


def test_load_task_file_json(tmp_path: Path) -> None:
    from llm_client.cli.deliberate import _load_task_file

    task_path = tmp_path / "task.json"
    task_path.write_text(json.dumps({
        "task_id": "t1",
        "title": "Q",
        "question": "Why?",
    }))
    data = _load_task_file(task_path)
    assert data["task_id"] == "t1"


def test_load_task_file_missing_exits(tmp_path: Path) -> None:
    from llm_client.cli.deliberate import _load_task_file

    with pytest.raises(SystemExit) as exc_info:
        _load_task_file(tmp_path / "nope.json")
    assert exc_info.value.code == 2


def test_load_task_file_rejects_non_object(tmp_path: Path) -> None:
    from llm_client.cli.deliberate import _load_task_file

    task_path = tmp_path / "task.json"
    task_path.write_text(json.dumps(["not", "an", "object"]))
    with pytest.raises(SystemExit) as exc_info:
        _load_task_file(task_path)
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# Full CLI invocation (langgraph required)
# ---------------------------------------------------------------------------

try:
    import langgraph  # noqa: F401

    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False


def _make_cli_args(
    task_file: Path,
    workspace: Path,
    out: Path,
    *,
    agents: str | None = None,
    max_rounds: int = 3,
) -> argparse.Namespace:
    return argparse.Namespace(
        task_file=str(task_file),
        workspace=str(workspace),
        out=str(out),
        agents=agents,
        max_rounds=max_rounds,
        synthesis_model=None,
        trace_id=None,
        max_budget=1.0,
    )


@pytest.mark.skipif(not HAS_LANGGRAPH, reason="langgraph not installed")
def test_cli_threads_max_rounds_into_builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--max-rounds N reaches build_deliberation_workflow."""
    from llm_client.cli import deliberate as cli_mod

    captured: dict[str, Any] = {}

    class _FakeApp:
        def invoke(self, state, config):
            return {"final_verdict": "stalled", "round": 1}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return _FakeApp(), {}

    monkeypatch.setattr("llm_client.workflow.deliberate.build_deliberation_workflow", fake_build)

    task_path = tmp_path / "task.json"
    task_path.write_text(json.dumps({"task_id": "t1", "title": "T", "question": "Q"}))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    out = tmp_path / "out"

    args = _make_cli_args(task_path, workspace, out, max_rounds=5)
    cli_mod.cmd_deliberate_task(args)

    assert captured["max_rounds"] == 5
    # workspace_path on the task should be overridden by --workspace.
    assert captured["task"]["workspace_path"] == str(workspace.resolve())


@pytest.mark.skipif(not HAS_LANGGRAPH, reason="langgraph not installed")
def test_cli_threads_explicit_agents_into_builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--agents 'a:m1,b:m2' must reach the builder as [(a,m1),(b,m2)]."""
    from llm_client.cli import deliberate as cli_mod

    captured: dict[str, Any] = {}

    class _FakeApp:
        def invoke(self, state, config):
            return {"final_verdict": "converged", "round": 2}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return _FakeApp(), {}

    monkeypatch.setattr("llm_client.workflow.deliberate.build_deliberation_workflow", fake_build)

    task_path = tmp_path / "task.json"
    task_path.write_text(json.dumps({"task_id": "t1", "title": "T", "question": "Q"}))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    out = tmp_path / "out"

    args = _make_cli_args(
        task_path, workspace, out,
        agents="myA:codex/gpt-5.6-luna,myB:claude-code/sonnet",
    )
    cli_mod.cmd_deliberate_task(args)

    assert captured["agents"] == [
        ("myA", "codex/gpt-5.6-luna"),
        ("myB", "claude-code/sonnet"),
    ]


def test_cli_bad_agents_string_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed --agents value exits with code 2 before any builder call."""
    from llm_client.cli import deliberate as cli_mod

    def fake_build(**kwargs):
        raise AssertionError("builder must not be called when --agents is bad")

    monkeypatch.setattr("llm_client.workflow.deliberate.build_deliberation_workflow", fake_build)

    task_path = tmp_path / "task.json"
    task_path.write_text(json.dumps({"task_id": "t1", "title": "T", "question": "Q"}))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    out = tmp_path / "out"

    args = _make_cli_args(task_path, workspace, out, agents="malformed")
    with pytest.raises(SystemExit) as exc_info:
        cli_mod.cmd_deliberate_task(args)
    assert exc_info.value.code == 2
