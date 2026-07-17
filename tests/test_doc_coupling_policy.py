"""Regression tests for stage-aware documentation-coupling enforcement."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_doc_coupling.py"
SPEC = importlib.util.spec_from_file_location("llm_client_check_doc_coupling", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _coupling(coupling_type: str, *, soft: bool | None = None) -> dict[str, object]:
    """Build one source-to-doc relationship with an optional legacy override."""

    result: dict[str, object] = {
        "sources": ["llm_client/core/client.py"],
        "docs": ["docs/adr/0001-model-identity-v0.md"],
        "description": "Test relationship.",
        "type": coupling_type,
    }
    if soft is not None:
        result["soft"] = soft
    return result


def test_validated_relationship_requests_review_without_blocking() -> None:
    """Agent-validated relationships must not require content-free co-modification."""

    strict, warnings = MODULE.check_couplings(
        {"llm_client/core/client.py"},
        [_coupling("validated")],
    )

    assert strict == []
    assert len(warnings) == 1
    assert warnings[0]["type"] == "validated"


def test_locked_relationship_remains_blocking() -> None:
    """Explicitly locked contracts retain a hard failure when their doc is absent."""

    strict, warnings = MODULE.check_couplings(
        {"llm_client/core/client.py"},
        [_coupling("locked")],
    )

    assert len(strict) == 1
    assert warnings == []
    assert strict[0]["type"] == "locked"


def test_explicit_soft_override_preserves_legacy_configuration() -> None:
    """A legacy explicit soft flag takes precedence during config migration."""

    strict, warnings = MODULE.check_couplings(
        {"llm_client/core/client.py"},
        [_coupling("validated", soft=False)],
    )

    assert len(strict) == 1
    assert warnings == []


def test_broad_architecture_relationships_are_agent_validated() -> None:
    """Broad file globs should nominate review rather than force unrelated ADR edits."""

    config = yaml.safe_load((REPO_ROOT / "scripts" / "relationships.yaml").read_text())
    couplings = config["couplings"]

    assert couplings
    assert {coupling["type"] for coupling in couplings} == {"validated"}


def test_hook_validates_before_generating_and_wires_acknowledgements() -> None:
    """A rejected commit must not first acquire generated-file dirt."""

    hook = (REPO_ROOT / "hooks" / "pre-commit").read_text()

    assert hook.index('DOC_COUPLING=$(find_script "check_doc_coupling.py")') < hook.index(
        'API_REFERENCE_GEN=$(find_script "generate_api_reference.py")'
    )
    assert "--ack-file" in hook
    assert "Do not touch unrelated docs solely to satisfy co-modification." in hook


def test_installed_and_root_checkers_remain_identical() -> None:
    """The installed compatibility copy must not drift from the root checker."""

    root_checker = (REPO_ROOT / "scripts" / "check_doc_coupling.py").read_bytes()
    installed_checker = (REPO_ROOT / "scripts" / "meta" / "check_doc_coupling.py").read_bytes()

    assert root_checker == installed_checker
