"""Contract tests for exact plan-test discovery and execution."""

from __future__ import annotations

import importlib.util
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


def test_plan99_required_tests_are_exact_and_executable() -> None:
    """Plan 99 declarations resolve only to concrete pytest files or nodes."""

    module = _load_script()
    plan = module.parse_plan_file(
        ROOT / "docs/plans/99_strict_native_json_schema_execution.md"
    )
    assert plan is not None
    requirements = plan.new_tests + plan.existing_tests
    assert requirements
    for requirement in requirements:
        assert not any(character.isspace() for character in requirement.file)
        if requirement.function is not None:
            assert " " not in requirement.function
        assert module.get_pytest_path(requirement, ROOT) is not None
