"""Explicit HTML anchors count as link targets for the Markdown link checker."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "llm_client_check_markdown_links", REPO_ROOT / "scripts" / "check_markdown_links.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_explicit_anchor_resolves_and_unknown_anchor_fails(tmp_path: Path) -> None:
    """A link to an <a id> anchor passes; a link to an absent anchor is reported."""

    (tmp_path / "DECISIONS.md").write_text(
        '# Decisions\n\n<a id="0001-model-identity-v0"></a>\n\n## ADR 0001: Model Identity\n',
        encoding="utf-8",
    )
    (tmp_path / "index.md").write_text(
        "[ok](DECISIONS.md#0001-model-identity-v0)\n"
        "[heading](DECISIONS.md#adr-0001-model-identity)\n"
        "[bad](DECISIONS.md#0002-missing)\n",
        encoding="utf-8",
    )

    violations = MODULE.check_markdown_links(["index.md"], tmp_path)

    assert [v.target for v in violations] == ["DECISIONS.md#0002-missing"]
