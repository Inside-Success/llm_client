"""Contract tests for exact plan-test discovery and execution."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/meta/check_plan_tests.py"


def _load_script() -> ModuleType:
    """Load the script as a module without depending on a package import seam."""

    spec = importlib.util.spec_from_file_location("check_plan_tests_under_test", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_find_test_class_uses_ast_scope_for_async_and_top_level_tests() -> None:
    """Class ownership must not leak past dedent or miss async methods."""

    module = _load_script()
    client_source = (ROOT / "tests/test_client.py").read_text(encoding="utf-8")
    replay_source = (ROOT / "tests/test_observability_replay.py").read_text(
        encoding="utf-8"
    )

    assert (
        module.find_test_class(
            client_source,
            "test_strict_native_schema_rejects_unsupported_model_before_instructor_async",
        )
        == "TestGPT5StructuredOutput"
    )
    assert (
        module.find_test_class(
            replay_source,
            "test_structured_output_mode_changes_snapshot_fingerprint",
        )
        is None
    )


def _completed_plan_file(anchor: str, tmp_path: Path) -> Path:
    """Rebuild one completed plan as its own file from docs/plans/COMPLETED_PLANS.md.

    Completed plans live as sections of COMPLETED_PLANS.md (headings demoted one
    level, section starts at ``<a id="<anchor>"></a>``); the plan tooling parses
    per-file plans, so restore the original heading levels into a temporary file.
    """

    text = (ROOT / "docs/plans/COMPLETED_PLANS.md").read_text(encoding="utf-8")
    start = text.index(f'<a id="{anchor}"></a>')
    end = text.find("\n<a id=", start + 1)
    section = text[start:] if end == -1 else text[start:end]
    lines = [line[1:] if line.startswith("##") else line for line in section.splitlines()[1:]]
    path = tmp_path / f"{anchor}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_plan99_required_tests_are_exact_and_executable(tmp_path: Path) -> None:
    """Plan 99 declarations resolve only to concrete pytest files or nodes."""

    module = _load_script()
    plan = module.parse_plan_file(
        _completed_plan_file("99_strict_native_json_schema_execution", tmp_path)
    )
    assert plan is not None
    requirements = plan.new_tests + plan.existing_tests
    assert requirements
    for requirement in requirements:
        assert not any(character.isspace() for character in requirement.file)
        if requirement.function is not None:
            assert " " not in requirement.function
        assert module.get_pytest_path(requirement, ROOT) is not None


def test_run_tests_uses_invoking_python_for_pytest(monkeypatch, tmp_path: Path) -> None:
    """The plan gate must not escape its selected virtualenv through PATH."""

    module = _load_script()
    test_file = tmp_path / "test_sample.py"
    test_file.write_text("def test_sample():\n    assert True\n", encoding="utf-8")
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    # mock-ok: observe command construction without recursively launching pytest.
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    exit_code, output = module.run_tests(
        [module.TestRequirement(file=test_file.name)],
        tmp_path,
    )

    assert exit_code == 0
    assert output == "ok"
    assert captured["args"][:4] == [sys.executable, "-m", "pytest", "-v"]
