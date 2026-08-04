"""Render a deterministic whole-repository wiki from source-local summaries.

The generated Markdown is a searchable compression layer, never a competing
authority. Every tracked artifact is listed, while Python symbol prose comes
from actual docstrings and document prose comes from actual source sections.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

from enforced_planning.relationship_context import ArtifactRecord
from enforced_planning.relationship_context import ArtifactClassification
from enforced_planning.relationship_context import inventory_repository


DEFAULT_OUTPUT = Path("generated/docstring_wiki.md")
CLASSIFICATION_ORDER: tuple[ArtifactClassification, ...] = (
    "source",
    "test",
    "documentation",
    "fixture",
    "generated",
    "vendored",
    "archive",
    "other",
)


def _first_paragraph(text: str | None) -> str | None:
    """Compress one real docstring paragraph for the generated navigation view."""

    if not text:
        return None
    paragraphs = [part.strip() for part in text.strip().split("\n\n") if part.strip()]
    if not paragraphs:
        return None
    return " ".join(line.strip() for line in paragraphs[0].splitlines()).strip() or None


def _inline_code(value: str) -> str:
    """Render stable Markdown code even when a source name contains backticks."""

    fence = "``" if "`" in value else "`"
    return f"{fence}{value}{fence}"


def _artifact_lines(artifact: ArtifactRecord, *, self_path: str | None) -> list[str]:
    """Render one tracked artifact and its documented Python symbols."""

    lines = [f"### {_inline_code(artifact.path)}", ""]
    if artifact.path == self_path:
        lines.extend(["_Generated wiki projection; self-content intentionally omitted._", ""])
        return lines
    summary = artifact.summary or "_No source-local artifact summary._"
    lines.extend([summary, ""])
    documented_symbols = [
        symbol for symbol in artifact.symbols if symbol.qualified_name != "<module>" and symbol.docstring
    ]
    if documented_symbols:
        lines.append("**Symbols**")
        lines.append("")
        for symbol in documented_symbols:
            signature = symbol.signature or symbol.qualified_name
            prose = _first_paragraph(symbol.docstring) or "_No source docstring._"
            lines.append(
                f"- {_inline_code(symbol.qualified_name)} · {_inline_code(signature)} · line {symbol.line}: {prose}"
            )
        lines.append("")
    if artifact.diagnostics:
        codes = ", ".join(sorted({item.code for item in artifact.diagnostics}))
        lines.extend([f"_Coverage findings: {codes}._", ""])
    return lines


def render_docstring_wiki(repo_root: Path, *, output_path: Path = DEFAULT_OUTPUT) -> str:
    """Render every tracked artifact into a deterministic Markdown projection."""

    root = repo_root.resolve()
    report = inventory_repository(root)
    resolved_output = output_path if output_path.is_absolute() else root / output_path
    try:
        self_path = resolved_output.resolve().relative_to(root).as_posix()
    except ValueError:
        self_path = None
    classifications = Counter(artifact.classification for artifact in report.artifacts)
    diagnostic_codes = Counter(item.code for artifact in report.artifacts for item in artifact.diagnostics)
    lines = [
        "# Docstring Wiki",
        "",
        "<!-- GENERATED FILE: DO NOT EDIT -->",
        "<!-- source: git ls-files + actual source docstrings/document summaries -->",
        "<!-- regenerate: python scripts/docstring_wiki.py --write -->",
        "",
        "Searchable, non-authoritative compression of the repository's tracked",
        "artifacts. Open the cited source for full context and current truth.",
        "",
        "## Coverage",
        "",
        f"- Tracked artifacts: {report.tracked_count}",
        f"- Artifacts with source summaries: {report.summarized_count}",
        f"- Coverage findings: {report.diagnostic_count}",
    ]
    if diagnostic_codes:
        lines.append("- Finding types: " + ", ".join(f"{code}={count}" for code, count in sorted(diagnostic_codes.items())))
    lines.append("")
    for classification in CLASSIFICATION_ORDER:
        artifacts = [artifact for artifact in report.artifacts if artifact.classification == classification]
        if not artifacts:
            continue
        lines.extend([f"## {classification.replace('_', ' ').title()} ({classifications[classification]})", ""])
        for artifact in artifacts:
            lines.extend(_artifact_lines(artifact, self_path=self_path))
    return "\n".join(lines).rstrip() + "\n"


def check_docstring_wiki(repo_root: Path, *, output_path: Path = DEFAULT_OUTPUT) -> tuple[bool, str]:
    """Compare generated output byte-for-byte without rewriting the worktree."""

    root = repo_root.resolve()
    path = output_path if output_path.is_absolute() else root / output_path
    expected = render_docstring_wiki(root, output_path=output_path)
    if not path.exists():
        return False, f"docstring wiki missing: {path}"
    actual = path.read_text(encoding="utf-8")
    if actual != expected:
        return False, f"docstring wiki stale or hand-edited: {path}"
    return True, f"docstring wiki current: {path}"


def main(argv: list[str] | None = None) -> int:
    """Generate, check, or print the deterministic docstring wiki."""

    parser = argparse.ArgumentParser(description="Generate a searchable wiki from actual source docstrings")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="Write the generated wiki")
    mode.add_argument("--check", action="store_true", help="Fail if the generated wiki is missing or stale")
    args = parser.parse_args(argv)
    if args.check:
        ok, message = check_docstring_wiki(args.repo_root, output_path=args.output)
        print(message, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    rendered = render_docstring_wiki(args.repo_root, output_path=args.output)
    if args.write:
        path = args.output if args.output.is_absolute() else args.repo_root / args.output
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        print(f"wrote docstring wiki: {path}")
    else:
        print(rendered, end="")
    return 0


__all__ = ["DEFAULT_OUTPUT", "check_docstring_wiki", "main", "render_docstring_wiki"]
