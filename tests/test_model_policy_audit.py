from __future__ import annotations

from pathlib import Path

from llm_client.model_policy_audit import scan_paths


def test_scan_paths_flags_direct_literal_call(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = project / "service.py"
    source.write_text(
        'from llm_client import call_llm\n'
        'call_llm("openrouter/openai/gpt-5-mini", messages)\n',
        encoding="utf-8",
    )

    violations = scan_paths([project])

    assert len(violations) == 1
    assert violations[0].kind == "direct_call_literal"


def test_scan_paths_flags_unaccepted_override_fields(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    config = project / "config.yaml"
    config.write_text(
        'selection_task: graph_building\n'
        'fallback_model: "openrouter/openai/gpt-5-mini"\n',
        encoding="utf-8",
    )

    violations = scan_paths([project])

    assert len(violations) == 1
    assert violations[0].kind == "unaccepted_model_override"


def test_scan_paths_allows_human_accepted_override_fields(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    config = project / "config.yaml"
    config.write_text(
        'selection_task: graph_building\n'
        'fallback_model: "openrouter/openai/gpt-5-mini"\n'
        'model_override_acceptance:\n'
        '  accepted_by: brian\n'
        '  reason: "temporary fallback while MiniMax-M3 provider reliability is measured"\n',
        encoding="utf-8",
    )

    violations = scan_paths([project])

    assert violations == []


def test_scan_paths_flags_banned_fable_even_with_override_acceptance(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    config = project / "config.yaml"
    config.write_text(
        'fallback_model: "anthropic/claude-fable-5"\n'
        'model_override_acceptance:\n'
        '  accepted_by: brian\n'
        '  reason: "temporary benchmark override"\n',
        encoding="utf-8",
    )

    violations = scan_paths([project])

    assert len(violations) == 1
    assert violations[0].kind == "banned_model_literal"
    assert violations[0].model == "anthropic/claude-fable-5"


def test_scan_paths_allows_default_minimax_literal(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = project / "service.py"
    source.write_text(
        'from llm_client import call_llm\n'
        'call_llm("openrouter/minimax/minimax-m3", messages)\n',
        encoding="utf-8",
    )

    violations = scan_paths([project])

    assert violations == []


def test_scan_paths_flags_direct_minimax_override(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = project / "service.py"
    source.write_text(
        'MODEL = "minimax/MiniMax-M2.7"\n',
        encoding="utf-8",
    )

    violations = scan_paths([project])

    assert len(violations) == 1
    assert violations[0].model == "minimax/MiniMax-M2.7"
    assert violations[0].kind == "raw_model_literal"


def test_scan_paths_allows_inline_bypass_comment(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = project / "service.py"
    source.write_text(
        'MODEL = "openrouter/openai/gpt-5-mini"  # model-policy: allow-raw-model\n',
        encoding="utf-8",
    )

    violations = scan_paths([project])

    assert violations == []
