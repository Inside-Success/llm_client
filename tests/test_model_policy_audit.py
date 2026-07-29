from __future__ import annotations

from pathlib import Path

import pytest

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


def test_scan_paths_flags_banned_opus_even_with_override_acceptance(
    tmp_path: Path,
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    config = project / "config.yaml"
    config.write_text(
        'fallback_model: "claude-code/opus"\n'
        "model_override_acceptance:\n"
        "  accepted_by: brian\n"
        '  reason: "temporary review override"\n',
        encoding="utf-8",
    )

    violations = scan_paths([project])

    assert len(violations) == 1
    assert violations[0].kind == "banned_model_literal"
    assert violations[0].model == "claude-code/opus"


@pytest.mark.parametrize("model", ["gpt-5.5", "openrouter/openai/gpt-5.5"])
def test_scan_paths_flags_retired_gpt55_even_with_override_acceptance(
    tmp_path: Path, model: str
) -> None:
    """A retired family is a policy denial, not a temporary override."""
    project = tmp_path / "proj"
    project.mkdir()
    config = project / "config.yaml"
    config.write_text(
        f'fallback_model: "{model}"\n'
        "model_override_acceptance:\n"
        "  accepted_by: brian\n"
        '  reason: "historical default"\n',
        encoding="utf-8",
    )

    violations = scan_paths([project])

    assert len(violations) == 1
    assert violations[0].kind == "banned_model_literal"
    assert violations[0].model == model


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


def test_require_llm_client_flags_direct_provider_import(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = project / "service.py"
    source.write_text(
        'from openai import OpenAI\n'
        'client = OpenAI()\n',
        encoding="utf-8",
    )

    assert scan_paths([project]) == []

    violations = scan_paths([project], require_llm_client=True)

    assert len(violations) == 1
    assert violations[0].kind == "direct_provider_sdk"
    assert violations[0].model == "openai"


def test_require_llm_client_flags_direct_litellm_call(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = project / "service.py"
    source.write_text(
        'import litellm\n'
        'response = litellm.completion(model="gpt-5-mini", messages=[])\n',
        encoding="utf-8",
    )

    violations = scan_paths([project], require_llm_client=True)

    assert [violation.kind for violation in violations] == [
        "direct_provider_sdk",
        "direct_provider_sdk",
    ]
    assert [violation.model for violation in violations] == ["litellm", "litellm"]


def test_require_llm_client_allows_llm_client_usage(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = project / "service.py"
    source.write_text(
        'from llm_client import call_llm, get_model\n'
        'model = get_model("default_intelligent")\n'
        'call_llm(model, messages, task="demo", trace_id="t", max_budget=0)\n',
        encoding="utf-8",
    )

    violations = scan_paths([project], require_llm_client=True)

    assert violations == []


def test_require_llm_client_allows_registration_exception(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = project / "provider_demo.py"
    source.write_text(
        'llm_client_registration_exception = {\n'
        '    "accepted_by": "brian",\n'
        '    "reason": "provider SDK documentation sample",\n'
        '    "category": "provider_sdk_demo",\n'
        '}\n'
        'from openai import OpenAI\n',
        encoding="utf-8",
    )

    violations = scan_paths([project], require_llm_client=True)

    assert violations == []


def test_registration_only_flags_provider_but_not_raw_model_literal(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = project / "service.py"
    source.write_text(
        'from openai import OpenAI\n'
        'MODEL = "openrouter/openai/gpt-5-mini"\n',
        encoding="utf-8",
    )

    full_violations = scan_paths([project], require_llm_client=True)
    registration_violations = scan_paths([project], registration_only=True)

    assert [violation.kind for violation in full_violations] == [
        "direct_provider_sdk",
        "raw_model_literal",
    ]
    assert [violation.kind for violation in registration_violations] == [
        "direct_provider_sdk",
    ]
    assert registration_violations[0].model == "openai"


def test_registration_only_skips_non_python_config_files(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    config = project / "config.yaml"
    config.write_text(
        'fallback_model: "openrouter/openai/gpt-5-mini"\n',
        encoding="utf-8",
    )

    assert scan_paths([project], registration_only=True) == []
    assert scan_paths([project])[0].kind == "unaccepted_model_override"
