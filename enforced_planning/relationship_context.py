"""Compile source-local summaries for every Git-tracked repository artifact.

This module is the visibility-first foundation for relationship-aware edit
context. It inventories with Git, parses Python with :mod:`ast`, and reads
Markdown source directly so target code is never imported and registry prose
never becomes a competing semantic authority.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
import json
from pathlib import Path, PurePosixPath
import subprocess
from typing import Literal, TypeAlias


ArtifactFormat: TypeAlias = Literal["python", "markdown", "text", "data", "binary", "other"]
ArtifactClassification: TypeAlias = Literal[
    "source",
    "test",
    "documentation",
    "generated",
    "vendored",
    "fixture",
    "archive",
    "other",
]
SymbolKind: TypeAlias = Literal["module", "class", "function", "method"]
WorkingTreeState: TypeAlias = Literal["present", "missing", "symlink"]

SCHEMA_VERSION = 1
SEMANTIC_MARKDOWN_HEADINGS = (
    "purpose",
    "decision",
    "status",
    "outcome",
    "goal",
    "gap",
    "summary",
)

_BINARY_SUFFIXES = {
    ".7z",
    ".bz2",
    ".db",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pyc",
    ".sqlite",
    ".sqlite3",
    ".tar",
    ".webp",
    ".woff",
    ".woff2",
    ".xz",
    ".zip",
}
_DATA_SUFFIXES = {".csv", ".json", ".jsonl", ".toml", ".tsv", ".xml", ".yaml", ".yml"}
_TEXT_SUFFIXES = {".cfg", ".ini", ".jinja", ".j2", ".rst", ".sh", ".sql", ".txt"}


class RelationshipContextError(RuntimeError):
    """Report an inventory failure that prevents truthful repository coverage."""


@dataclass(frozen=True)
class Diagnostic:
    """Describe one stable, actionable source-summary coverage finding."""

    code: str
    message: str
    line: int | None = None
    symbol: str | None = None


@dataclass(frozen=True)
class SymbolRecord:
    """Represent one statically discovered Python symbol and its real docstring."""

    symbol_id: str
    qualified_name: str
    kind: SymbolKind
    line: int
    signature: str | None
    docstring: str | None


@dataclass(frozen=True)
class ArtifactRecord:
    """Represent one tracked artifact without duplicating source-local meaning."""

    path: str
    format: ArtifactFormat
    classification: ArtifactClassification
    working_tree_state: WorkingTreeState
    summary: str | None
    summary_source: str | None
    symbols: tuple[SymbolRecord, ...]
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class InventoryReport:
    """Provide deterministic aggregate coverage over all tracked artifacts."""

    schema_version: int
    tracked_count: int
    summarized_count: int
    diagnostic_count: int
    artifacts: tuple[ArtifactRecord, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation with stable field names."""

        return asdict(self)

    def to_json(self, *, pretty: bool = False) -> str:
        """Serialize deterministically without timestamps or absolute paths."""

        separators = None if pretty else (",", ":")
        return json.dumps(
            self.to_dict(),
            indent=2 if pretty else None,
            separators=separators,
            sort_keys=True,
            ensure_ascii=True,
        ) + "\n"


def tracked_paths(repo_root: Path) -> tuple[str, ...]:
    """Return every Git-tracked path, preserving unusual names via NUL output."""

    root = repo_root.resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", b"")
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace").strip()
        raise RelationshipContextError(f"cannot inventory Git repository {root}: {detail or exc}") from exc

    paths = [raw.decode("utf-8", errors="surrogateescape") for raw in result.stdout.split(b"\0") if raw]
    return tuple(sorted(paths))


def classify_format(path: str) -> ArtifactFormat:
    """Classify artifact syntax independently from governance classification."""

    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".md", ".mdx"}:
        return "markdown"
    if suffix in _BINARY_SUFFIXES:
        return "binary"
    if suffix in _DATA_SUFFIXES:
        return "data"
    if suffix in _TEXT_SUFFIXES or not suffix:
        return "text"
    return "other"


def classify_artifact(path: str) -> ArtifactClassification:
    """Classify maintenance ownership from conventional repository path segments."""

    parts = tuple(part.lower() for part in PurePosixPath(path).parts)
    if any(part in {"archive", "archived"} for part in parts):
        return "archive"
    if any(part in {"vendor", "vendored", "third_party", "node_modules"} for part in parts):
        return "vendored"
    if any(part in {"generated", "dist", "build"} for part in parts):
        return "generated"
    if "fixtures" in parts or "fixture" in parts:
        return "fixture"
    if parts and (parts[0] == "tests" or PurePosixPath(path).name.startswith("test_")):
        return "test"
    if parts and (parts[0] == "docs" or PurePosixPath(path).suffix.lower() in {".md", ".mdx", ".rst"}):
        return "documentation"
    if PurePosixPath(path).suffix.lower() in {".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".java"}:
        return "source"
    return "other"


def _first_paragraph(text: str | None) -> str | None:
    """Collapse the first non-empty source paragraph into compact context."""

    if not text:
        return None
    paragraphs = [paragraph.strip() for paragraph in text.strip().split("\n\n") if paragraph.strip()]
    if not paragraphs:
        return None
    return " ".join(line.strip() for line in paragraphs[0].splitlines()).strip() or None


def _annotation(node: ast.expr | None) -> str | None:
    """Render one AST annotation for descriptive signature context."""

    return ast.unparse(node) if node is not None else None


def _render_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Render a compact, non-executable signature from function AST fields."""

    args = node.args
    positional = [*args.posonlyargs, *args.args]
    defaults_offset = len(positional) - len(args.defaults)
    rendered: list[str] = []
    for index, argument in enumerate(positional):
        value = argument.arg
        annotation = _annotation(argument.annotation)
        if annotation:
            value += f": {annotation}"
        if index >= defaults_offset:
            value += f" = {ast.unparse(args.defaults[index - defaults_offset])}"
        rendered.append(value)
        if args.posonlyargs and index + 1 == len(args.posonlyargs):
            rendered.append("/")
    if args.vararg is not None:
        value = f"*{args.vararg.arg}"
        annotation = _annotation(args.vararg.annotation)
        if annotation:
            value += f": {annotation}"
        rendered.append(value)
    elif args.kwonlyargs:
        rendered.append("*")
    for argument, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        value = argument.arg
        annotation = _annotation(argument.annotation)
        if annotation:
            value += f": {annotation}"
        if default is not None:
            value += f" = {ast.unparse(default)}"
        rendered.append(value)
    if args.kwarg is not None:
        value = f"**{args.kwarg.arg}"
        annotation = _annotation(args.kwarg.annotation)
        if annotation:
            value += f": {annotation}"
        rendered.append(value)
    returns = _annotation(node.returns)
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    suffix = f" -> {returns}" if returns else ""
    return f"{prefix}{node.name}({', '.join(rendered)}){suffix}"


def _python_symbols(path: str, tree: ast.Module) -> tuple[SymbolRecord, ...]:
    """Extract module, class, and callable records in source order.

    Private callables remain part of the source-derived navigation surface when
    they have docstrings. Coverage policy is separate: undocumented private
    helpers are represented but do not create mandatory-docstring findings.
    """

    module_line = 1
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        module_line = tree.body[0].lineno
    records: list[SymbolRecord] = [
        SymbolRecord(
            symbol_id=f"{path}::<module>",
            qualified_name="<module>",
            kind="module",
            line=module_line,
            signature=None,
            docstring=ast.get_docstring(tree, clean=True),
        )
    ]

    def visit(body: list[ast.stmt], parents: tuple[str, ...] = ()) -> None:
        """Walk nested classes and their direct methods without executing source."""

        for node in body:
            if isinstance(node, ast.ClassDef):
                qualified = ".".join((*parents, node.name))
                records.append(
                    SymbolRecord(
                        symbol_id=f"{path}::{qualified}",
                        qualified_name=qualified,
                        kind="class",
                        line=node.lineno,
                        signature=node.name,
                        docstring=ast.get_docstring(node, clean=True),
                    )
                )
                visit(node.body, (*parents, node.name))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = ".".join((*parents, node.name))
                records.append(
                    SymbolRecord(
                        symbol_id=f"{path}::{qualified}",
                        qualified_name=qualified,
                        kind="method" if parents else "function",
                        line=node.lineno,
                        signature=_render_signature(node),
                        docstring=ast.get_docstring(node, clean=True),
                    )
                )

    visit(tree.body)
    return tuple(records)


def _python_record(repo_root: Path, path: str, classification: ArtifactClassification) -> ArtifactRecord:
    """Build a Python artifact record with explicit parse and docstring diagnostics."""

    source_path = repo_root / path
    try:
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=path)
    except UnicodeDecodeError as exc:
        diagnostic = Diagnostic("python-decode-error", str(exc))
        return ArtifactRecord(path, "python", classification, "present", None, None, (), (diagnostic,))
    except SyntaxError as exc:
        diagnostic = Diagnostic("python-parse-error", exc.msg, line=exc.lineno)
        return ArtifactRecord(path, "python", classification, "present", None, None, (), (diagnostic,))

    symbols = _python_symbols(path, tree)
    diagnostics: list[Diagnostic] = []
    for symbol in symbols:
        callable_is_private = symbol.kind in {"function", "method"} and symbol.qualified_name.rsplit(".", 1)[
            -1
        ].startswith("_")
        if symbol.docstring is None and not callable_is_private:
            diagnostics.append(
                Diagnostic(
                    "python-docstring-missing",
                    f"{symbol.kind} has no source docstring",
                    line=symbol.line,
                    symbol=symbol.qualified_name,
                )
            )
    module_docstring = symbols[0].docstring
    return ArtifactRecord(
        path=path,
        format="python",
        classification=classification,
        working_tree_state="present",
        summary=_first_paragraph(module_docstring),
        summary_source="python:module-docstring" if module_docstring else None,
        symbols=symbols,
        diagnostics=tuple(diagnostics),
    )


def _markdown_sections(text: str) -> tuple[str | None, list[tuple[str, str, int]]]:
    """Return the H1 title and level-2 sections with source line provenance."""

    title: str | None = None
    sections: list[tuple[str, str, int]] = []
    current_heading: str | None = None
    current_line = 0
    current_body: list[str] = []

    def flush() -> None:
        """Persist the current semantic section before moving to the next heading."""

        if current_heading is not None:
            sections.append((current_heading, "\n".join(current_body).strip(), current_line))

    in_fence = False
    fence_marker = ""
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            if current_heading is not None:
                current_body.append(line)
            continue
        if in_fence:
            if current_heading is not None:
                current_body.append(line)
            continue
        if stripped.startswith("# ") and title is None:
            title = stripped[2:].strip()
            continue
        if stripped.startswith("## "):
            flush()
            current_heading = stripped[3:].strip()
            current_line = line_number
            current_body = []
            continue
        if current_heading is not None:
            current_body.append(line)
    flush()
    return title, sections


def _markdown_first_paragraph(text: str) -> str | None:
    """Find initial prose while skipping headings, comments, and metadata lines."""

    paragraph: list[str] = []
    in_comment = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("<!--"):
            in_comment = not stripped.endswith("-->")
            continue
        if in_comment:
            if stripped.endswith("-->"):
                in_comment = False
            continue
        if not stripped:
            if paragraph:
                break
            continue
        if stripped.startswith("#") or (stripped.startswith("**") and ":**" in stripped):
            continue
        if stripped in {"---", "***"}:
            continue
        paragraph.append(stripped)
    return " ".join(paragraph) if paragraph else None


def _markdown_record(repo_root: Path, path: str, classification: ArtifactClassification) -> ArtifactRecord:
    """Build a Markdown record from actual title and semantic section prose."""

    source_path = repo_root / path
    try:
        text = source_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        diagnostic = Diagnostic("markdown-decode-error", str(exc))
        return ArtifactRecord(path, "markdown", classification, "present", None, None, (), (diagnostic,))

    title, sections = _markdown_sections(text)
    summary: str | None = None
    summary_source: str | None = None
    for desired in SEMANTIC_MARKDOWN_HEADINGS:
        for heading, body, _line in sections:
            if heading.casefold() == desired:
                summary = _first_paragraph(body)
                if summary:
                    summary_source = f"markdown:section:{heading}"
                    break
        if summary:
            break
    if summary is None:
        summary = _markdown_first_paragraph(text)
        if summary:
            summary_source = "markdown:first-paragraph"

    diagnostics: list[Diagnostic] = []
    if title is None:
        diagnostics.append(Diagnostic("markdown-title-missing", "document has no level-1 title"))
    if summary is None:
        diagnostics.append(Diagnostic("markdown-summary-missing", "document has no extractable semantic summary"))
    return ArtifactRecord(path, "markdown", classification, "present", summary, summary_source, (), tuple(diagnostics))


def _unavailable_record(
    path: str,
    artifact_format: ArtifactFormat,
    classification: ArtifactClassification,
    state: Literal["missing", "symlink"],
) -> ArtifactRecord:
    """Represent a tracked artifact whose working-tree source is not readable."""

    code = "tracked-file-missing" if state == "missing" else "tracked-symlink-not-read"
    message = (
        "tracked artifact is deleted from the working tree"
        if state == "missing"
        else "tracked symbolic link is represented but not followed for summary extraction"
    )
    return ArtifactRecord(
        path=path,
        format=artifact_format,
        classification=classification,
        working_tree_state=state,
        summary=None,
        summary_source=None,
        symbols=(),
        diagnostics=(Diagnostic(code, message),),
    )


def inventory_repository(repo_root: Path) -> InventoryReport:
    """Compile deterministic source-summary records for every tracked artifact."""

    root = repo_root.resolve()
    artifacts: list[ArtifactRecord] = []
    for path in tracked_paths(root):
        artifact_format = classify_format(path)
        classification = classify_artifact(path)
        source_path = root / path
        if source_path.is_symlink():
            record = _unavailable_record(path, artifact_format, classification, "symlink")
        elif not source_path.exists():
            record = _unavailable_record(path, artifact_format, classification, "missing")
        elif artifact_format == "python":
            record = _python_record(root, path, classification)
        elif artifact_format == "markdown":
            record = _markdown_record(root, path, classification)
        else:
            record = ArtifactRecord(path, artifact_format, classification, "present", None, None, (), ())
        artifacts.append(record)

    return InventoryReport(
        schema_version=SCHEMA_VERSION,
        tracked_count=len(artifacts),
        summarized_count=sum(artifact.summary is not None for artifact in artifacts),
        diagnostic_count=sum(len(artifact.diagnostics) for artifact in artifacts),
        artifacts=tuple(artifacts),
    )


def main(argv: list[str] | None = None) -> int:
    """Run the read-only relationship-context inventory CLI."""

    parser = argparse.ArgumentParser(description="Inventory tracked artifacts and extract source-local summaries")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Git repository root to inventory")
    parser.add_argument("--output", type=Path, help="Write JSON to this path instead of stdout")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print deterministic JSON")
    args = parser.parse_args(argv)

    try:
        report = inventory_repository(args.repo_root)
    except RelationshipContextError as exc:
        parser.exit(2, f"relationship-context: {exc}\n")
    payload = report.to_json(pretty=args.pretty)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


__all__ = [
    "ArtifactRecord",
    "Diagnostic",
    "InventoryReport",
    "RelationshipContextError",
    "SymbolRecord",
    "classify_artifact",
    "classify_format",
    "inventory_repository",
    "main",
    "tracked_paths",
]
